#!/usr/bin/env python3
"""Build the name (Entry/EntryForm/NameTranslation/...) rows of sumatora.db from gitnedict.

Reads entry JSON files produced by jmnedict-to-git.py and writes rows into an
existing (or newly created) sumatora.db, per schema-v2.md: proper names use the
same Entry/EntryForm tables as JMdict words (entry_type='name'), plus
NameTranslation for the flat translation list and EntryTag(category='name_type')
for JMnedict's name-type codes (place, person, surname, ...).

    Entry(entry_type='name')
    EntryForm(form_type='writing'|'reading')  — one row per valid kanji/reading
                                                 pair, same expansion jmdict uses
    FormTag           — informational kanji tags only (priority codes drive is_common)
    FormFuriganaSegment — from jmnedict-to-git.py's furiganaByReading, when built with --kanjidic2
    NameTranslation
    EntryTag          — category='name_type'
    Tag               — category='name_type', label from gitnedict's metadata.json entities
    SearchTerm        — one row per writing/reading form

is_primary is chosen by is_common across all of an entry's candidate forms
(buffered before insertion), not by JMnedict source order — mirrors the same
fix in jmdict-to-sumatora-db.py, since a name entry can list an uncommon
kanji form before its common one.

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
import sys

import sumatora_schema
from furigana_solver import applicable_readings
from sumatora_common import TagCache, hira_to_kata, is_priority_code, iter_json_files, parse_bracket_furigana


def _select_primary(candidates):
    """Return the index of the candidate that should be is_primary.

    Chosen by is_common; ties keep the earliest candidate (same tie-break as
    jmdict-to-sumatora-db.py's _select_primary when it has nothing else to
    go on — JMnedict doesn't carry the finer-grained irregular-form tags
    JMdict does, so is_common is the only signal worth ranking on here).
    """
    return max(range(len(candidates)), key=lambda i: candidates[i]['is_common'])


def process(gitnedict_dir, db_path):
    conn = sumatora_schema.open_or_init_db(db_path)
    c = conn.cursor()
    src = sumatora_schema.source_id(conn, 'jmnedict')

    with open(f'{gitnedict_dir}/metadata.json', encoding='utf-8') as f:
        entities = json.load(f).get('entities', {})

    tags = TagCache(conn)

    entries_dir = f'{gitnedict_dir}/entries'
    count = 0
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)

        seq = entry['seq']
        c.execute(
            "INSERT INTO Entry (source_id, source_key, entry_type) VALUES (?, ?, 'name')",
            (src, str(seq)),
        )
        entry_id = c.lastrowid

        kana_list = entry.get('kana', [])

        # Buffer every candidate form first so is_primary can be chosen by
        # is_common across the whole entry instead of by JMnedict source order.
        pending = []
        for k in entry.get('kanji', []):
            is_common = bool([t for t in k.get('tags', []) if is_priority_code(t)])
            readings = applicable_readings(k['text'], kana_list) or [None]
            furigana_by_reading = k.get('furiganaByReading') or {}
            for reading in readings:
                pending.append({
                    'form_type': 'writing',
                    'text': k['text'],
                    'reading': reading,
                    'is_common': int(is_common),
                    'tags': k.get('tags', []),
                    'furigana': furigana_by_reading.get(reading) if reading else None,
                })
        for r in kana_list:
            pending.append({
                'form_type': 'reading',
                'text': r['text'],
                'reading': None,
                'is_common': 0,
                'tags': [],
                'furigana': None,
            })

        primary_idx = _select_primary(pending) if pending else None

        for ord_, f in enumerate(pending):
            c.execute(
                'INSERT INTO EntryForm '
                '(entry_id, ord, form_type, text, reading, is_primary, is_common) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (entry_id, ord_, f['form_type'], f['text'], f['reading'],
                 1 if ord_ == primary_idx else 0, f['is_common']),
            )
            form_id = c.lastrowid

            if f['furigana']:
                for seg_ord, (base, ruby) in enumerate(parse_bracket_furigana(f['furigana'])):
                    c.execute(
                        'INSERT INTO FormFuriganaSegment (form_id, ord, base, ruby) '
                        'VALUES (?, ?, ?, ?)',
                        (form_id, seg_ord, base, ruby),
                    )

            for t in f['tags']:
                if is_priority_code(t):
                    continue
                label = entities.get(t, t)
                tag_id = tags.get_or_create('form', t, label)
                c.execute(
                    'INSERT INTO FormTag (form_id, tag_id) VALUES (?, ?)',
                    (form_id, tag_id),
                )

            script = 'writing' if f['form_type'] == 'writing' else 'kana'
            _insert_search_term(c, entry_id, form_id, f['text'], script, bool(f['is_common']))

        for ord_t, text in enumerate(entry.get('translations', [])):
            c.execute(
                'INSERT INTO NameTranslation (entry_id, ord, text) VALUES (?, ?, ?)',
                (entry_id, ord_t, text),
            )

        for name_type in entry.get('types', []):
            label = entities.get(name_type, name_type)
            tag_id = tags.get_or_create('name_type', name_type, label)
            c.execute(
                'INSERT INTO EntryTag (entry_id, tag_id) VALUES (?, ?)',
                (entry_id, tag_id),
            )

        count += 1
        if count % 10000 == 0:
            print(f'  {count} names inserted…', flush=True)

    sumatora_schema.set_build_metadata(conn, jmnedict_entry_count=str(count))
    c.execute("INSERT INTO SearchTermFts(SearchTermFts) VALUES ('rebuild')")
    conn.commit()
    conn.close()

    print(f'Done: {count} names → {db_path}', flush=True)


def _insert_search_term(c, entry_id, form_id, text, script, is_common):
    normalized = hira_to_kata(text) if script == 'kana' else text
    c.execute(
        'INSERT INTO SearchTerm (entry_id, form_id, term, normalized, script, priority) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (entry_id, form_id, text, normalized, script, 1 if is_common else 0),
    )


HELP = (
    'usage: jmnedict-to-sumatora-db.py '
    '-i <gitnedict directory> -d <sumatora.db path>'
)


def main(argv):
    gitnedict_dir = ''
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
            gitnedict_dir = arg
        elif opt in ('-d', '--db'):
            db_path = arg
    if not gitnedict_dir or not db_path:
        print(HELP)
        sys.exit(2)
    process(gitnedict_dir, db_path)


if __name__ == '__main__':
    main(sys.argv[1:])
