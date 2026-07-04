#!/usr/bin/env python3
"""Build Sumatora SQLite databases from a gitmdict JSON repository.

Reads JSON files produced by xml-to-git.py and writes the same SQLite
databases that sumatora-index.py used to produce in a single pass.

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
import sqlite3
import sys
import time


# ---------------------------------------------------------------------------
# Kana normalisation (replaces romkan)
# Hiragana U+3041–U+3096 → Katakana U+30A1–U+30F6 via fixed offset +0x60
# ---------------------------------------------------------------------------

def hira_to_kata(s):
    return ''.join(
        chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c
        for c in s
    )


def calculate_parts_element(s, include_self=False):
    start = 0 if include_self else 1
    return {s[i:] for i in range(start, len(s))}


def calculate_parts(space_separated):
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(word)
    return ' '.join(parts)


def calculate_parts_kana(space_separated):
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(hira_to_kata(word))
    return ' '.join(parts)


def to_kana(space_separated):
    return hira_to_kata(space_separated)


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

class SumatoraDB:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

        self._jmconn = sqlite3.connect(
            os.path.join(folder, 'jmdict.db'), isolation_level=None,
        )
        self._jmcur = self._jmconn.cursor()
        self._jmcur.execute('PRAGMA journal_mode=DELETE')
        self._jmcur.execute('BEGIN TRANSACTION')

        self._trans = {}   # lang -> (conn, cur)

    # -- jmdict.db ----------------------------------------------------------

    def create_jmdict_tables(self):
        c = self._jmcur
        for t in ('DictionaryEntry', 'DictionaryControl',
                  'DictionaryIndex', 'DictionaryEntity',
                  'ProperNounEntry', 'ProperNounIndex'):
            c.execute(f'DROP TABLE IF EXISTS {t}')

        c.execute(
            'CREATE TABLE DictionaryEntry ('
            'seq INTEGER, readingsPrio TEXT, readings TEXT, '
            'writingsPrio TEXT, writings TEXT, pos TEXT, xref TEXT, '
            'ant TEXT, misc TEXT, lsource TEXT, dial TEXT, s_inf TEXT, '
            'field TEXT, kanjiData TEXT, kanaData TEXT, '
            'stagk TEXT, stagr TEXT, furigana TEXT, rules TEXT, score INTEGER, PRIMARY KEY (seq))'
        )
        c.execute(
            'CREATE INDEX DictionaryEntryRules ON DictionaryEntry (rules)'
        )
        c.execute(
            'CREATE INDEX DictionaryEntryScore ON DictionaryEntry (score)'
        )
        c.execute(
            'CREATE TABLE DictionaryControl '
            '(control TEXT NOT NULL, value INTEGER, PRIMARY KEY (control))'
        )
        c.execute(
            'CREATE VIRTUAL TABLE DictionaryIndex '
            'USING fts5('
            'readingsPrioKana, readingsPrioKanaParts, '
            'readingsKana, readingsKanaParts, '
            'writingsPrio, writingsPrioParts, '
            'writings, writingsParts, '
            'content="")'
        )
        c.execute(
            'CREATE TABLE DictionaryEntity '
            '(name TEXT NOT NULL, content TEXT, PRIMARY KEY (name))'
        )
        c.execute(
            'CREATE TABLE ProperNounEntry ('
            'seq INTEGER, readings TEXT, writings TEXT, '
            'types TEXT, translations TEXT, PRIMARY KEY (seq))'
        )
        c.execute(
            'CREATE VIRTUAL TABLE ProperNounIndex '
            'USING fts5('
            'readingsKana, readingsKanaParts, '
            'writings, writingsParts, '
            'content="")'
        )

    def insert_entities(self, entities):
        self._jmcur.executemany(
            'INSERT INTO DictionaryEntity (name, content) VALUES (?, ?)',
            entities.items(),
        )

    def insert_proper_noun(self, seq, readings, writings, types_json,
                           translations_json):
        r_kata = to_kana(readings)
        self._jmcur.execute(
            'INSERT INTO ProperNounIndex '
            '(rowid, readingsKana, readingsKanaParts, writings, writingsParts) '
            'VALUES (?, ?, ?, ?, ?)',
            (seq,
             r_kata, calculate_parts_kana(readings),
             writings, calculate_parts(writings)),
        )
        self._jmcur.execute(
            'INSERT INTO ProperNounEntry '
            '(seq, readings, writings, types, translations) '
            'VALUES (?, ?, ?, ?, ?)',
            (seq, readings, writings, types_json, translations_json),
        )

    def insert_control(self, entry_count):
        rows = [
            ('build_timestamp', int(time.time())),
            ('format_version',  1),
            ('entry_count',     entry_count),
        ]
        self._jmcur.executemany(
            'INSERT INTO DictionaryControl (control, value) VALUES (?, ?)',
            rows,
        )

    def insert_entry(self, seq, readings_prio, readings, writings_prio,
                     writings, pos, xref, ant, misc, lsource, dial, s_inf,
                     field, kanji_data, kana_data, stagk, stagr, furigana,
                     rules, score):
        rp_kata = to_kana(readings_prio)
        r_kata = to_kana(readings)
        self._jmcur.execute(
            'INSERT INTO DictionaryIndex '
            '(rowid, readingsPrioKana, readingsPrioKanaParts, '
            'readingsKana, readingsKanaParts, '
            'writingsPrio, writingsPrioParts, writings, writingsParts) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (seq,
             rp_kata, calculate_parts_kana(readings_prio),
             r_kata, calculate_parts_kana(readings),
             writings_prio, calculate_parts(writings_prio),
             writings, calculate_parts(writings)),
        )
        self._jmcur.execute(
            'INSERT INTO DictionaryEntry '
            '(seq, readingsPrio, readings, writingsPrio, writings, '
            'pos, xref, ant, misc, lsource, dial, s_inf, field, '
            'kanjiData, kanaData, stagk, stagr, furigana, rules, score) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (seq, readings_prio, readings, writings_prio, writings,
             pos, xref, ant, misc, lsource, dial, s_inf, field,
             kanji_data, kana_data, stagk, stagr, furigana, rules, score),
        )

    # -- per-language translation DBs ----------------------------------------

    def _ensure_lang(self, lang):
        if lang in self._trans:
            return
        conn = sqlite3.connect(
            os.path.join(self.folder, f'{lang}.db'), isolation_level=None,
        )
        cur = conn.cursor()
        cur.execute('PRAGMA journal_mode=DELETE')
        cur.execute('BEGIN TRANSACTION')
        cur.execute('DROP TABLE IF EXISTS DictionaryTranslation')
        cur.execute('DROP TABLE IF EXISTS DictionaryTranslationIndex')
        cur.execute(
            'CREATE TABLE DictionaryTranslation '
            '(seq INTEGER, gloss_id INTEGER, '
            'gloss TEXT, PRIMARY KEY (seq, gloss_id))'
        )
        cur.execute(
            'CREATE VIRTUAL TABLE DictionaryTranslationIndex '
            'USING fts5(gloss, content="DictionaryTranslation")'
        )
        self._trans[lang] = (conn, cur)

    def insert_translation(self, lang, seq, glosses):
        self._ensure_lang(lang)
        _, cur = self._trans[lang]
        for i, sense_glosses in enumerate(glosses):
            cur.execute(
                'INSERT INTO DictionaryTranslation '
                '(seq, gloss_id, gloss) VALUES (?, ?, ?)',
                (seq, i, ', '.join(sense_glosses)),
            )

    # -- close ---------------------------------------------------------------

    def close(self):
        self._jmcur.execute('COMMIT')
        self._jmconn.execute('VACUUM')
        self._jmconn.close()

        for lang, (conn, cur) in self._trans.items():
            cur.execute(
                "INSERT INTO DictionaryTranslationIndex(DictionaryTranslationIndex) VALUES('rebuild')"
            )
            cur.execute('COMMIT')
            conn.execute('VACUUM')
            conn.close()


# ---------------------------------------------------------------------------
# JSON field helpers
# ---------------------------------------------------------------------------

def _none_or_json(value):
    """Return JSON string only if value has at least one element, else None."""
    if not value:
        return None
    flat = value if not isinstance(value[0], list) else [x for sub in value for x in sub]
    if not flat:
        return None
    return json.dumps(value, ensure_ascii=False)


def _lsource_to_json(lsource_array):
    """Serialize lsource sense arrays, preserving lang, text, full, wasei.

    Format: [[{"lang":"...", "text":"...", "full":bool, "wasei":bool}, ...], ...]
    """
    if not lsource_array:
        return None
    converted = []
    for sense_sources in lsource_array:
        sense_list = [
            {
                'lang': ls['lang'],
                'text': ls.get('text') or '',
                'full': ls.get('full', True),
                'wasei': ls.get('wasei', False),
            }
            for ls in sense_sources
        ]
        converted.append(sense_list)
    has_data = any(sl for sl in converted)
    if not has_data:
        return None
    return json.dumps(converted, ensure_ascii=False)


def _kanji_data_json(kanji_list):
    """Serialize kanji element array preserving text, common, tags."""
    if not kanji_list:
        return None
    return json.dumps(kanji_list, ensure_ascii=False)


def _kana_data_json(kana_list):
    """Serialize kana element array preserving text, common, tags, appliesToKanji, nokanji."""
    if not kana_list:
        return None
    return json.dumps(kana_list, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Cross-reference resolution
# ---------------------------------------------------------------------------

def build_xref_index(entries_dir):
    """Scan all entry JSON files and return (kanji_to_seqs, kana_to_seqs).

    Each dict maps a headword text to the sorted list of seq numbers that
    contain it as a kanji or kana element respectively.
    """
    kanji_to_seqs = {}
    kana_to_seqs = {}
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)
        seq = entry['seq']
        for k in entry.get('kanji', []):
            kanji_to_seqs.setdefault(k['text'], []).append(seq)
        for k in entry.get('kana', []):
            kana_to_seqs.setdefault(k['text'], []).append(seq)
    return kanji_to_seqs, kana_to_seqs


def _parse_xref_text(text):
    """Split a JMdict xref/ant string into (headword, reading, sense_num).

    Formats accepted:
      headword
      headword・reading
      headword・sense_num
      headword・reading・sense_num
    """
    parts = text.split('・')
    sense_num = None
    if parts and parts[-1].isdigit():
        sense_num = int(parts[-1])
        parts = parts[:-1]
    if len(parts) >= 2:
        return parts[0], parts[1], sense_num
    return parts[0] if parts else text, None, sense_num


def _resolve_one_xref(text, kanji_to_seqs, kana_to_seqs):
    """Resolve one xref/ant string to a {text, seq[, sense]} dict."""
    headword, reading, sense_num = _parse_xref_text(text)
    if reading:
        candidates = set(kanji_to_seqs.get(headword, [])) & set(kana_to_seqs.get(reading, []))
    else:
        candidates = set(kanji_to_seqs.get(headword, [])) | set(kana_to_seqs.get(headword, []))
    seq = min(candidates) if candidates else None
    result = {'text': text, 'seq': seq}
    if sense_num is not None:
        result['sense'] = sense_num
    return result


def _resolve_xref_array(xref_array, kanji_to_seqs, kana_to_seqs):
    """Transform a per-sense xref/ant array: replace strings with resolved dicts."""
    if not xref_array:
        return None
    resolved = [
        [_resolve_one_xref(t, kanji_to_seqs, kana_to_seqs) for t in sense_refs]
        for sense_refs in xref_array
    ]
    if not any(sense_refs for sense_refs in resolved):
        return None
    return json.dumps(resolved, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Deinflection rule derivation
# ---------------------------------------------------------------------------

# Maps JMdict POS entity codes to Yomitan-compatible deinflection rule codes.
_POS_TO_RULES = {
    'v1':    'v1',
    'v1-s':  'v1',
    'v5aru': 'v5',
    'v5b':   'v5',
    'v5g':   'v5',
    'v5k':   'v5',
    'v5k-s': 'v5',
    'v5m':   'v5',
    'v5n':   'v5',
    'v5r':   'v5',
    'v5r-i': 'v5',
    'v5s':   'v5',
    'v5t':   'v5',
    'v5u':   'v5',
    'v5u-s': 'v5',
    'v5uru': 'v5',
    'vk':    'vk',
    'vs-i':  'vs',
    'vs-s':  'vs',
    'vz':    'vz',
    'adj-i': 'adj-i',
    'adj-ix': 'adj-i',
}


def derive_rules(senses):
    """Return space-separated deinflection rule codes for an entry, or None.

    Collects all POS codes across every sense, maps each to a rule code via
    _POS_TO_RULES, and returns the sorted unique set joined by spaces.
    Returns None for entries with no inflectable POS (nouns, particles, etc.).
    """
    rules = set()
    for s in senses:
        for pos in s.get('partOfSpeech', []):
            rule = _POS_TO_RULES.get(pos)
            if rule:
                rules.add(rule)
    return ' '.join(sorted(rules)) if rules else None


# ---------------------------------------------------------------------------
# Headword scoring
# ---------------------------------------------------------------------------

# Kanji-element info tags that mark a form as irregular or rarely used.
_IRREGULAR_KANJI_TAGS = frozenset({'iK', 'rK', 'io'})


def compute_score(kanji_list, kana_list):
    """Return headword score: +1 priority, 0 standard, -1 irregular/rare.

    +1: at least one kanji or kana element is marked common (has priority tags).
    -1: there are kanji elements AND every one of them carries at least one
        irregular/rare tag (iK, rK, io) AND none are common.
     0: everything else (standard non-priority entries, kana-only entries).
    """
    if any(k['common'] for k in kanji_list) or any(k['common'] for k in kana_list):
        return 1
    if kanji_list and all(
        set(k.get('tags', [])) & _IRREGULAR_KANJI_TAGS for k in kanji_list
    ):
        return -1
    return 0


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def build_readings_writings(entry):
    """Extract space-separated priority/non-priority reading and writing strings."""
    readings_prio_parts = []
    readings_parts = []
    for k in entry['kana']:
        if k['common']:
            readings_prio_parts.append(k['text'])
        else:
            readings_parts.append(k['text'])

    writings_prio_parts = []
    writings_parts = []
    for k in entry['kanji']:
        if k['common']:
            writings_prio_parts.append(k['text'])
        else:
            writings_parts.append(k['text'])

    return (
        ' '.join(readings_prio_parts),
        ' '.join(readings_parts),
        ' '.join(writings_prio_parts),
        ' '.join(writings_parts),
    )


def build_sense_fields(senses, xref_index=None):
    """Aggregate per-sense structural fields into per-entry JSON arrays.

    When xref_index=(kanji_to_seqs, kana_to_seqs) is provided, xref and ant
    strings are resolved to {text, seq[, sense]} dicts; otherwise stored raw.
    """
    pos_arr, xref_arr, ant_arr, misc_arr = [], [], [], []
    lsrc_arr, dial_arr, sinf_arr, field_arr = [], [], [], []
    stagk_arr, stagr_arr = [], []

    for s in senses:
        pos_arr.append(s.get('partOfSpeech', []))
        xref_arr.append(s.get('related', []))
        ant_arr.append(s.get('antonym', []))
        misc_arr.append(s.get('misc', []))
        lsrc_arr.append(s.get('languageSource', []))
        dial_arr.append(s.get('dialect', []))
        sinf_arr.append(s.get('info', []))
        field_arr.append(s.get('field', []))
        stagk_arr.append(s.get('stagk', []))
        stagr_arr.append(s.get('stagr', []))

    if xref_index is not None:
        kanji_to_seqs, kana_to_seqs = xref_index
        xref_json = _resolve_xref_array(xref_arr, kanji_to_seqs, kana_to_seqs)
        ant_json = _resolve_xref_array(ant_arr, kanji_to_seqs, kana_to_seqs)
    else:
        xref_json = _none_or_json(xref_arr)
        ant_json = _none_or_json(ant_arr)

    return (
        _none_or_json(pos_arr),
        xref_json,
        ant_json,
        _none_or_json(misc_arr),
        _lsource_to_json(lsrc_arr),
        _none_or_json(dial_arr),
        _none_or_json(sinf_arr),
        _none_or_json(field_arr),
        _none_or_json(stagk_arr),
        _none_or_json(stagr_arr),
    )


def iter_json_files(directory):
    """Yield (path,) for every .json file under directory, sorted."""
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            if name.endswith('.json'):
                yield os.path.join(root, name)


def process(git_dir, output_dir, nedict_dir=None):
    metadata_path = os.path.join(git_dir, 'metadata.json')
    with open(metadata_path, encoding='utf-8') as f:
        metadata = json.load(f)

    db = SumatoraDB(output_dir)
    db.create_jmdict_tables()
    db.insert_entities(metadata.get('entities', {}))

    # -- entries -----------------------------------------------------------
    entries_dir = os.path.join(git_dir, 'entries')
    print('Building xref index…', flush=True)
    xref_index = build_xref_index(entries_dir)
    print(f'  {len(xref_index[0])} kanji forms, {len(xref_index[1])} kana forms indexed', flush=True)

    entry_count = 0
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)

        seq = entry['seq']
        senses = entry.get('senses', [])
        rp, r, wp, w = build_readings_writings(entry)
        pos, xref, ant, misc, lsrc, dial, sinf, field, stagk, stagr = \
            build_sense_fields(senses, xref_index)
        kanji_list = entry.get('kanji', [])
        furigana_map = {k['text']: k['furigana'] for k in kanji_list if k.get('furigana') is not None}
        furigana = json.dumps(furigana_map, ensure_ascii=False) if furigana_map else None
        kana_list = entry.get('kana', [])
        kanji_data = _kanji_data_json(kanji_list)
        kana_data = _kana_data_json(kana_list)
        rules = derive_rules(senses)
        score = compute_score(kanji_list, kana_list)

        db.insert_entry(seq, rp, r, wp, w, pos, xref, ant, misc,
                        lsrc, dial, sinf, field, kanji_data, kana_data,
                        stagk, stagr, furigana, rules, score)
        entry_count += 1
        if entry_count % 10000 == 0:
            print(f'  {entry_count} entries inserted…', flush=True)

    print(f'Entries done: {entry_count}', flush=True)

    # -- translations -------------------------------------------------------
    trans_dir = os.path.join(git_dir, 'translations')
    trans_count = 0
    for path in iter_json_files(trans_dir):
        with open(path, encoding='utf-8') as f:
            t = json.load(f)
        db.insert_translation(t['lang'], t['seq'], t['glosses'])
        trans_count += 1
        if trans_count % 50000 == 0:
            print(f'  {trans_count} translation files inserted…', flush=True)

    print(f'Translations done: {trans_count}', flush=True)

    # -- proper nouns (optional) --------------------------------------------
    if nedict_dir:
        nedict_entries_dir = os.path.join(nedict_dir, 'entries')
        noun_count = 0
        for path in iter_json_files(nedict_entries_dir):
            with open(path, encoding='utf-8') as f:
                entry = json.load(f)
            seq = entry['seq']
            readings = ' '.join(k['text'] for k in entry.get('kana', []))
            writings = ' '.join(k['text'] for k in entry.get('kanji', []))
            types = entry.get('types', [])
            translations = entry.get('translations', [])
            types_json = json.dumps(types, ensure_ascii=False) if types else None
            translations_json = (
                json.dumps(translations, ensure_ascii=False) if translations else None
            )
            db.insert_proper_noun(seq, readings, writings, types_json,
                                  translations_json)
            noun_count += 1
            if noun_count % 10000 == 0:
                print(f'  {noun_count} proper nouns inserted…', flush=True)
        print(f'Proper nouns done: {noun_count}', flush=True)

    db.insert_control(entry_count)
    db.close()
    print(f'Databases written to {output_dir}', flush=True)


HELP = ('usage: git-to-sqlite.py '
        '-i <gitmdict directory> -o <output directory> '
        '[--nedict <gitnedict directory>]')


def main(argv):
    git_dir = ''
    output_dir = ''
    nedict_dir = None
    try:
        opts, _ = getopt.getopt(argv, 'hi:o:', ['idir=', 'odir=', 'nedict='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            git_dir = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
        elif opt == '--nedict':
            nedict_dir = arg
    if not git_dir or not output_dir:
        print(HELP)
        sys.exit(2)
    process(git_dir, output_dir, nedict_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
