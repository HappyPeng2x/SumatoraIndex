#!/usr/bin/env python3
"""Build the name (Entry/EntryForm/NameTranslation/...) rows of sumatora.db from gitnedict.

Reads entry JSON files produced by jmnedict-to-git.py and writes rows into an
existing (or newly created) sumatora.db, per schema-v2.md: proper names use the
same Entry/EntryForm tables as JMdict words (entry_type='name'), plus
NameTranslation for the flat translation list and EntryTag(category='name_type')
for JMnedict's name-type codes (place, person, surname, ...).

    Entry(entry_type='name')
    EntryForm(form_type='writing'|'reading')
    FormTag           — informational kanji tags only (priority codes drive is_common)
    NameTranslation
    EntryTag          — category='name_type'
    Tag               — category='name_type', label from gitnedict's metadata.json entities
    SearchTerm        — one row per writing/reading form

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
from sumatora_common import TagCache, hira_to_kata, is_priority_code, iter_json_files


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

        ord_ = 0
        for k in entry.get('kanji', []):
            is_common = bool([t for t in k.get('tags', []) if is_priority_code(t)])
            c.execute(
                'INSERT INTO EntryForm '
                '(entry_id, ord, form_type, text, is_primary, is_common) '
                "VALUES (?, ?, 'writing', ?, ?, ?)",
                (entry_id, ord_, k['text'], 1 if ord_ == 0 else 0, int(is_common)),
            )
            form_id = c.lastrowid
            for t in k.get('tags', []):
                if is_priority_code(t):
                    continue
                label = entities.get(t, t)
                tag_id = tags.get_or_create('form', t, label)
                c.execute(
                    'INSERT INTO FormTag (form_id, tag_id) VALUES (?, ?)',
                    (form_id, tag_id),
                )
            _insert_search_term(c, entry_id, form_id, k['text'], 'writing', is_common)
            ord_ += 1

        for r in entry.get('kana', []):
            c.execute(
                'INSERT INTO EntryForm '
                '(entry_id, ord, form_type, text, is_primary, is_common) '
                "VALUES (?, ?, 'reading', ?, ?, 0)",
                (entry_id, ord_, r['text'], 1 if ord_ == 0 else 0),
            )
            form_id = c.lastrowid
            _insert_search_term(c, entry_id, form_id, r['text'], 'kana', False)
            ord_ += 1

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
