#!/usr/bin/env python3
"""Build the KanjiEntry/KanjiReading/KanjiMeaning tables of sumatora.db (schema-v2.md).

Reads character JSON files produced by kanjidic2-to-git.py and writes rows into
an existing (or newly created) sumatora.db, following schema-v2.md's "dedicated
tables are cleaner" recommendation for KANJIDIC2 data: kanji do not get Entry
rows, since nothing cross-references a kanji by entry_id.

    KanjiEntry(character PK, entry_id NULL, strokes, grade, jlpt, frequency, radical)
    KanjiReading(character, reading_type IN ('on','kun','nanori'), ord, text)
    KanjiMeaning(character, lang, ord, text)

kanjidic2-to-git.py does not currently extract nanori readings, so no 'nanori'
rows are produced yet; the reading_type CHECK constraint still allows for them.
Meanings have no per-entry language tag in the source JSON (kanjidic2's m_lang
default is English) so they are all written with lang='eng'.

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
from sumatora_common import iter_json_files


def process(gitjidic2_dir, db_path):
    conn = sumatora_schema.open_or_init_db(db_path)
    c = conn.cursor()
    src = sumatora_schema.source_id(conn, 'kanjidic2')

    chars_dir = f'{gitjidic2_dir}/characters'
    count = 0
    for path in iter_json_files(chars_dir):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        char = data.get('char')
        if not char:
            continue

        c.execute(
            "INSERT INTO Entry (source_id, source_key, entry_type, sort_key) "
            "VALUES (?, ?, 'kanji', ?)",
            (src, char, char),
        )
        entry_id = c.lastrowid
        c.execute(
            'INSERT INTO EntryForm '
            '(entry_id, ord, form_type, text, is_primary, is_common) '
            "VALUES (?, 0, 'writing', ?, 1, 0)",
            (entry_id, char),
        )
        form_id = c.lastrowid
        c.execute(
            "INSERT INTO SearchTerm (entry_id, form_id, term, normalized, script, priority) "
            "VALUES (?, ?, ?, ?, 'writing', 0)",
            (entry_id, form_id, char, char),
        )

        c.execute(
            'INSERT INTO KanjiEntry '
            '(character, entry_id, strokes, grade, jlpt, frequency, radical) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (char, entry_id, data.get('strokes'), data.get('grade'), data.get('jlpt'),
             data.get('freq'), data.get('radical')),
        )

        readings = [('on', r) for r in data.get('on', [])] + \
                   [('kun', r) for r in data.get('kun', [])]
        for ord_, (reading_type, text) in enumerate(readings):
            c.execute(
                'INSERT INTO KanjiReading (character, reading_type, ord, text) '
                'VALUES (?, ?, ?, ?)',
                (char, reading_type, ord_, text),
            )

        for ord_, text in enumerate(data.get('meanings', [])):
            c.execute(
                'INSERT INTO KanjiMeaning (character, lang, ord, text) VALUES (?, ?, ?, ?)',
                (char, 'eng', ord_, text),
            )
            c.execute(
                "INSERT INTO SearchTerm "
                "(entry_id, form_id, term, normalized, script, priority) "
                "VALUES (?, NULL, ?, ?, 'gloss', 0)",
                (entry_id, text, text.lower()),
            )

        count += 1
        if count % 2000 == 0:
            print(f'  {count} characters inserted…', flush=True)

    sumatora_schema.set_build_metadata(
        conn,
        kanjidic2_char_count=str(count),
    )
    c.execute("INSERT INTO SearchTermFts(SearchTermFts) VALUES ('rebuild')")
    conn.commit()
    conn.close()

    print(f'Done: {count} characters → {db_path}', flush=True)


HELP = (
    'usage: kanjidic2-to-sumatora-db.py '
    '-i <gitjidic2 directory> -d <sumatora.db path>'
)


def main(argv):
    gitjidic2_dir = ''
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
            gitjidic2_dir = arg
        elif opt in ('-d', '--db'):
            db_path = arg
    if not gitjidic2_dir or not db_path:
        print(HELP)
        sys.exit(2)
    process(gitjidic2_dir, db_path)


if __name__ == '__main__':
    main(sys.argv[1:])
