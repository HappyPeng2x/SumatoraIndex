#!/usr/bin/env python3
"""Build the word (Entry/EntryForm/Sense/.../SearchTerm) rows of sumatora.db from gitmdict.

Reads entry + per-language translation JSON files produced by jmdict-to-git.py and
writes rows into an existing (or newly created) sumatora.db, per schema-v2.md.

Two full passes over gitmdict/entries/ are required:

  Pass 1 — Entry, EntryForm, FormTag, FormFuriganaSegment.
           Builds seq_to_entry_id plus kanji_index/kana_index (text -> [(seq,
           entry_id, form_id), ...]) used by pass 2 to resolve cross-references,
           since a xref can point at an entry processed either before or after
           the current one in file order.

  Pass 2 — SenseGroup, Sense, SenseGloss, SenseNote, SenseLanguageSource,
           SenseAppliesToForm, SenseReference, FormRule, SearchTerm,
           SearchSuffix.
           Per-language translation files are located directly by
           (lang, shard, seq) path rather than walking the whole translations/
           tree, since only entries actually present in gitmdict/entries/ matter.

Design choices carried over from schema-v2.md's own text (see schema-v2.md and
the SumatoraIndex build plan in ~/.claude/plans/):

  - SenseGroup is 1:1 with Sense (no adjacent-sense merging yet — JMdict senses
    already carry a full tag set each, unlike hand-authored dictionaries).
  - Tag.category is assigned by which JMdict field a code came from, not by
    inspecting the code string. Priority codes (news1, ichi1, nf12, ...) drive
    EntryForm.is_common/score directly and are never turned into FormTag rows.
  - target_sense_id in SenseReference is left NULL (only target_sense_number is
    resolved from the "headword・reading・N" xref suffix) — resolving the exact
    target Sense row would require a third full pass for a marginal benefit over
    target_sense_number, which is enough for "jump to sense N" navigation.
  - FormRule is computed per-form (not per-entry like v1's DictionaryEntry.rules):
    a sense's derived rule codes are attributed only to the forms it applies to
    (via SenseAppliesToForm when stagk/stagr restrict it, otherwise all forms of
    the entry), which is strictly more precise than v1 without extra source data.
  - This is the last stage-2 script in the build order that touches
    SearchTerm/SenseGloss (kanjidic2 and jmnedict run before it, pitch and
    gitoeba run after but don't touch these tables), so it rebuilds both FTS5
    indexes at the end.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import json
import os
import sys
from collections import defaultdict

import sumatora_schema
from sumatora_common import TagCache, hira_to_kata, is_priority_code, iter_json_files, parse_bracket_furigana

# Kanji-element info tags that mark a form as irregular or rarely used.
_IRREGULAR_TAGS = frozenset({'iK', 'rK', 'io'})

# Maps JMdict POS entity codes to Yomitan-compatible deinflection rule codes.
_POS_TO_RULES = {
    'v1': 'v1', 'v1-s': 'v1',
    'v5aru': 'v5', 'v5b': 'v5', 'v5g': 'v5', 'v5k': 'v5', 'v5k-s': 'v5',
    'v5m': 'v5', 'v5n': 'v5', 'v5r': 'v5', 'v5r-i': 'v5', 'v5s': 'v5',
    'v5t': 'v5', 'v5u': 'v5', 'v5u-s': 'v5', 'v5uru': 'v5',
    'vk': 'vk',
    'vs-i': 'vs', 'vs-s': 'vs',
    'vz': 'vz',
    'adj-i': 'adj-i', 'adj-ix': 'adj-i',
}

_RULE_LABELS = {
    'v1': 'Ichidan verb', 'v5': 'Godan verb', 'vk': 'Kuru verb',
    'vs': 'Suru verb', 'vz': 'Zuru verb', 'adj-i': 'I-adjective',
}


def compute_entry_score(kanji_list, kana_list):
    """+1 priority, 0 standard, -1 irregular/rare (same rule v1 used entry-wide)."""
    if any(k['common'] for k in kanji_list) or any(k['common'] for k in kana_list):
        return 1
    if kanji_list and all(set(k.get('tags', [])) & _IRREGULAR_TAGS for k in kanji_list):
        return -1
    return 0


def _form_score(common, tags):
    if common:
        return 1
    if set(tags) & _IRREGULAR_TAGS:
        return -1
    return 0


def _applicable_readings(kanji_text, kana_list):
    """Return every kana reading that applies to kanji_text."""
    readings = []
    for k in kana_list:
        applies = k.get('appliesToKanji', ['*'])
        if '*' in applies or kanji_text in applies:
            readings.append(k['text'])
    return readings


def _fallback_furigana_segments(text, reading):
    """Conservative furigana for alternate readings not precomputed in gitmdict."""
    return [(text, reading)]


def _parse_xref_text(text):
    """Split a JMdict xref/ant string into (headword, reading, sense_num)."""
    parts = text.split('・')
    sense_num = None
    if parts and parts[-1].isdigit():
        sense_num = int(parts[-1])
        parts = parts[:-1]
    if len(parts) >= 2:
        return parts[0], parts[1], sense_num
    return parts[0] if parts else text, None, sense_num


def _resolve_reference(text, kanji_index, kana_index):
    """Resolve one xref/ant string to (target_entry_id, target_form_id, sense_num).

    Mirrors gitmdict-to-sqlite.py's tie-break of picking the lowest JMdict seq
    among ambiguous candidates, but also recovers which specific form matched.
    """
    headword, reading, sense_num = _parse_xref_text(text)
    if reading:
        writing_by_seq = {seq: (eid, fid) for seq, eid, fid in kanji_index.get(headword, [])}
        reading_seqs = {seq for seq, eid, fid in kana_index.get(reading, [])}
        candidates = set(writing_by_seq) & reading_seqs
        if not candidates:
            return None, None, sense_num
        chosen = min(candidates)
        return writing_by_seq[chosen][0], writing_by_seq[chosen][1], sense_num
    combined = {}
    for seq, eid, fid in kanji_index.get(headword, []):
        combined.setdefault(seq, (eid, fid))
    for seq, eid, fid in kana_index.get(headword, []):
        combined.setdefault(seq, (eid, fid))
    if not combined:
        return None, None, sense_num
    chosen = min(combined)
    return combined[chosen][0], combined[chosen][1], sense_num


def _insert_search_term(c, entry_id, form_id, text, normalized, script, priority):
    c.execute(
        'INSERT INTO SearchTerm (entry_id, form_id, term, normalized, script, priority) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (entry_id, form_id, text, normalized, script, priority),
    )
    search_id = c.lastrowid
    suffixes = {normalized[i:] for i in range(1, len(normalized))}
    c.executemany(
        'INSERT INTO SearchSuffix (search_id, suffix) VALUES (?, ?)',
        [(search_id, suf) for suf in suffixes],
    )


def _pass1_forms(c, entries_dir, src, entities, tags):
    """Entry + EntryForm + FormTag + FormFuriganaSegment. Returns the indices pass 2 needs."""
    seq_to_entry_id = {}
    kanji_index = defaultdict(list)  # text -> [(seq, entry_id, form_id), ...]
    kana_index = defaultdict(list)

    count = 0
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)
        seq = entry['seq']
        kanji_list = entry.get('kanji', [])
        kana_list = entry.get('kana', [])

        c.execute(
            "INSERT INTO Entry (source_id, source_key, entry_type, score) VALUES (?, ?, 'word', ?)",
            (src, str(seq), compute_entry_score(kanji_list, kana_list)),
        )
        entry_id = c.lastrowid
        seq_to_entry_id[seq] = entry_id

        form_ord = 0
        for k in kanji_list:
            readings = _applicable_readings(k['text'], kana_list) or [None]
            for reading_idx, reading in enumerate(readings):
                c.execute(
                    'INSERT INTO EntryForm '
                    '(entry_id, ord, form_type, text, reading, is_primary, is_common, score) '
                    "VALUES (?, ?, 'writing', ?, ?, ?, ?, ?)",
                    (entry_id, form_ord, k['text'], reading, 1 if form_ord == 0 else 0,
                     int(k['common']), _form_score(k['common'], k.get('tags', []))),
                )
                form_id = c.lastrowid
                if k.get('furigana') and reading_idx == 0:
                    segments = parse_bracket_furigana(k['furigana'])
                elif reading:
                    segments = _fallback_furigana_segments(k['text'], reading)
                else:
                    segments = []
                for seg_ord, (base, ruby) in enumerate(segments):
                    c.execute(
                        'INSERT INTO FormFuriganaSegment (form_id, ord, base, ruby) '
                        'VALUES (?, ?, ?, ?)',
                        (form_id, seg_ord, base, ruby),
                    )
                for t in k.get('tags', []):
                    if is_priority_code(t):
                        continue
                    tag_id = tags.get_or_create('form', t, entities.get(t, t))
                    c.execute('INSERT INTO FormTag (form_id, tag_id) VALUES (?, ?)', (form_id, tag_id))
                kanji_index[k['text']].append((seq, entry_id, form_id))
                form_ord += 1

        for k in kana_list:
            c.execute(
                'INSERT INTO EntryForm '
                '(entry_id, ord, form_type, text, is_primary, is_common, score) '
                "VALUES (?, ?, 'reading', ?, ?, ?, ?)",
                (entry_id, form_ord, k['text'], 1 if form_ord == 0 else 0,
                 int(k['common']), _form_score(k['common'], k.get('tags', []))),
            )
            form_id = c.lastrowid
            for t in k.get('tags', []):
                if is_priority_code(t):
                    continue
                tag_id = tags.get_or_create('form', t, entities.get(t, t))
                c.execute('INSERT INTO FormTag (form_id, tag_id) VALUES (?, ?)', (form_id, tag_id))
            kana_index[k['text']].append((seq, entry_id, form_id))
            form_ord += 1

        count += 1
        if count % 10000 == 0:
            print(f'  pass 1: {count} entries processed…', flush=True)

    return seq_to_entry_id, kanji_index, kana_index


def _pass2_senses(c, entries_dir, translations_dir, entities, tags,
                   seq_to_entry_id, kanji_index, kana_index):
    langs = sorted(os.listdir(translations_dir)) if os.path.isdir(translations_dir) else []

    count = 0
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)
        seq = entry['seq']
        entry_id = seq_to_entry_id[seq]
        senses = entry.get('senses', [])
        shard = seq // 10000

        all_form_ids = [row[0] for row in
                        c.execute('SELECT form_id FROM EntryForm WHERE entry_id = ?', (entry_id,))]
        form_rules = defaultdict(set)
        sense_ids = []

        for i, s in enumerate(senses):
            c.execute(
                'INSERT INTO SenseGroup (entry_id, ord, display_number) VALUES (?, ?, ?)',
                (entry_id, i, i + 1),
            )
            sense_group_id = c.lastrowid
            c.execute(
                'INSERT INTO Sense (entry_id, sense_group_id, source_ord, ord, display_number) '
                'VALUES (?, ?, ?, ?, ?)',
                (entry_id, sense_group_id, i, i, i + 1),
            )
            sense_id = c.lastrowid
            sense_ids.append(sense_id)

            for category, field in (('pos', 'partOfSpeech'), ('misc', 'misc'),
                                     ('field', 'field'), ('dialect', 'dialect')):
                for code in s.get(field, []):
                    tag_id = tags.get_or_create(category, code, entities.get(code, code))
                    c.execute(
                        'INSERT OR IGNORE INTO SenseGroupTag (sense_group_id, tag_id) VALUES (?, ?)',
                        (sense_group_id, tag_id),
                    )

            for ord_n, note in enumerate(s.get('info', [])):
                c.execute(
                    'INSERT INTO SenseNote (sense_id, ord, text) VALUES (?, ?, ?)',
                    (sense_id, ord_n, note),
                )

            for ord_l, ls in enumerate(s.get('languageSource', [])):
                c.execute(
                    'INSERT INTO SenseLanguageSource (sense_id, ord, lang, text, is_full, is_wasei) '
                    'VALUES (?, ?, ?, ?, ?, ?)',
                    (sense_id, ord_l, ls['lang'], ls.get('text') or None,
                     int(ls.get('full', True)), int(ls.get('wasei', False))),
                )

            stagk, stagr = s.get('stagk', []), s.get('stagr', [])
            if stagk or stagr:
                restricted = set()
                for text in stagk:
                    for row in c.execute(
                        "SELECT form_id FROM EntryForm WHERE entry_id = ? AND form_type = 'writing' AND text = ?",
                        (entry_id, text),
                    ):
                        restricted.add(row[0])
                for text in stagr:
                    for row in c.execute(
                        "SELECT form_id FROM EntryForm WHERE entry_id = ? AND form_type = 'reading' AND text = ?",
                        (entry_id, text),
                    ):
                        restricted.add(row[0])
                for form_id in restricted:
                    c.execute(
                        'INSERT INTO SenseAppliesToForm (sense_id, form_id) VALUES (?, ?)',
                        (sense_id, form_id),
                    )
                applicable_forms = restricted
            else:
                applicable_forms = all_form_ids

            rule_codes = {_POS_TO_RULES[p] for p in s.get('partOfSpeech', []) if p in _POS_TO_RULES}
            if rule_codes:
                for form_id in applicable_forms:
                    form_rules[form_id] |= rule_codes

            for ref_type, field in (('xref', 'related'), ('antonym', 'antonym')):
                for ord_r, text in enumerate(s.get(field, [])):
                    tgt_entry_id, tgt_form_id, sense_num = _resolve_reference(
                        text, kanji_index, kana_index,
                    )
                    c.execute(
                        'INSERT INTO SenseReference '
                        '(sense_id, ord, reference_type, display_text, target_entry_id, '
                        'target_form_id, target_sense_number) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (sense_id, ord_r, ref_type, text, tgt_entry_id, tgt_form_id, sense_num),
                    )

        for lang in langs:
            tpath = os.path.join(translations_dir, lang, str(shard), f'{seq}.json')
            if not os.path.exists(tpath):
                continue
            with open(tpath, encoding='utf-8') as f:
                glosses = json.load(f)['glosses']
            for idx, gloss_list in enumerate(glosses):
                if idx < len(sense_ids):
                    sid = sense_ids[idx]
                else:
                    # More senses in this language than in the English structural
                    # data (rare) — hold the overflow gloss in its own bare Sense.
                    c.execute(
                        'INSERT INTO SenseGroup (entry_id, ord) VALUES (?, ?)',
                        (entry_id, idx),
                    )
                    sgid = c.lastrowid
                    c.execute(
                        'INSERT INTO Sense (entry_id, sense_group_id, source_ord, ord) VALUES (?, ?, ?, ?)',
                        (entry_id, sgid, idx, idx),
                    )
                    sid = c.lastrowid
                    sense_ids.append(sid)
                for gord, text in enumerate(gloss_list):
                    c.execute(
                        'INSERT INTO SenseGloss (sense_id, lang, ord, text) VALUES (?, ?, ?, ?)',
                        (sid, lang, gord, text),
                    )

        for form_id, rules in form_rules.items():
            for rule in rules:
                c.execute(
                    'INSERT OR IGNORE INTO FormRule (form_id, rule) VALUES (?, ?)',
                    (form_id, rule),
                )

        count += 1
        if count % 10000 == 0:
            print(f'  pass 2: {count} entries processed…', flush=True)


def _insert_search_terms(conn, c, entries_dir, seq_to_entry_id):
    """SearchTerm/SearchSuffix for every writing/reading form (needs form_ids from pass 1).

    Reads via a dedicated cursor: _insert_search_term() writes with `c` on every
    iteration, and reusing the same cursor for both would reset the read cursor's
    result set after the first row (a classic Python sqlite3 cursor pitfall).
    """
    read_cur = conn.cursor()
    for row in read_cur.execute(
        "SELECT f.form_id, f.entry_id, f.text, f.reading, f.form_type, f.is_common "
        "FROM EntryForm f JOIN Entry e ON e.entry_id = f.entry_id "
        "WHERE e.entry_type = 'word'"
    ):
        form_id, entry_id, text, reading, form_type, is_common = row
        if form_type == 'writing':
            _insert_search_term(c, entry_id, form_id, text, text, 'writing', is_common)
        else:
            _insert_search_term(c, entry_id, form_id, text, hira_to_kata(text), 'kana', is_common)


def process(gitmdict_dir, db_path):
    conn = sumatora_schema.open_or_init_db(db_path)
    c = conn.cursor()
    src = sumatora_schema.source_id(conn, 'jmdict')

    with open(f'{gitmdict_dir}/metadata.json', encoding='utf-8') as f:
        entities = json.load(f).get('entities', {})

    tags = TagCache(conn)
    entries_dir = f'{gitmdict_dir}/entries'
    translations_dir = f'{gitmdict_dir}/translations'

    print('Pass 1: Entry/EntryForm/FormTag/FormFuriganaSegment…', flush=True)
    seq_to_entry_id, kanji_index, kana_index = _pass1_forms(c, entries_dir, src, entities, tags)
    print(f'  {len(seq_to_entry_id)} entries, {len(kanji_index)} kanji forms, '
          f'{len(kana_index)} kana forms indexed', flush=True)

    print('Building SearchTerm/SearchSuffix…', flush=True)
    _insert_search_terms(conn, c, entries_dir, seq_to_entry_id)

    print('Pass 2: Sense/SenseGloss/SenseReference/FormRule…', flush=True)
    _pass2_senses(c, entries_dir, translations_dir, entities, tags,
                  seq_to_entry_id, kanji_index, kana_index)

    for rule, label in _RULE_LABELS.items():
        c.execute(
            'INSERT OR IGNORE INTO DeinflectionRule (rule, label) VALUES (?, ?)',
            (rule, label),
        )

    print('Rebuilding SearchTermFts/GlossSearchFts…', flush=True)
    c.execute("INSERT INTO SearchTermFts(SearchTermFts) VALUES ('rebuild')")
    c.execute("INSERT INTO GlossSearchFts(GlossSearchFts) VALUES ('rebuild')")

    sumatora_schema.set_build_metadata(conn, jmdict_entry_count=str(len(seq_to_entry_id)))
    conn.commit()
    conn.close()

    print(f'Done: {len(seq_to_entry_id)} words → {db_path}', flush=True)


HELP = (
    'usage: jmdict-to-sumatora-db.py '
    '-i <gitmdict directory> -d <sumatora.db path>'
)


def main(argv):
    gitmdict_dir = ''
    db_path = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:d:', ['idir=', 'db='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            gitmdict_dir = arg
        elif opt in ('-d', '--db'):
            db_path = arg
    if not gitmdict_dir or not db_path:
        print(HELP)
        sys.exit(2)
    process(gitmdict_dir, db_path)


if __name__ == '__main__':
    main(sys.argv[1:])
