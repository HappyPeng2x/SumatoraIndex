#!/usr/bin/env python3
"""Build kanjidic2.db SQLite database from a gitjidic2 JSON repository.

Reads character JSON files produced by kanjidic2-to-git.py and writes a
single SQLite database with a KanjiEntry table suitable for character detail
views in the Android app.

Database schema:

    KanjiEntry
      char     TEXT PK  — the kanji character (single Unicode scalar)
      "on"     TEXT     — space-separated on readings (katakana)
      kun      TEXT     — space-separated kun readings (hiragana, okurigana after '.')
      meanings TEXT     — JSON array of English meanings
      strokes  INTEGER  — stroke count
      grade    INTEGER  — school grade (1-6 kyouiku, 8 jinmei; NULL otherwise)
      jlpt     INTEGER  — old JLPT level 1-4 (4=N5 … 1=N1); NULL if not listed
      freq     INTEGER  — newspaper frequency rank; NULL if not listed
      radical  INTEGER  — classical radical number

    KanjiControl
      control  TEXT PK
      value    INTEGER

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
# JSON file iteration (shared pattern with other pipeline scripts)
# ---------------------------------------------------------------------------

def iter_json_files(directory):
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            if name.endswith('.json'):
                yield os.path.join(root, name)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(gitjidic2_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    db_path = os.path.join(output_dir, 'kanjidic2.db')

    conn = sqlite3.connect(db_path, isolation_level=None)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=DELETE')
    c.execute('BEGIN TRANSACTION')

    for table in ('KanjiEntry', 'KanjiControl'):
        c.execute(f'DROP TABLE IF EXISTS {table}')

    c.execute(
        'CREATE TABLE KanjiEntry ('
        'char TEXT PRIMARY KEY, '
        '"on" TEXT, kun TEXT, meanings TEXT, '
        'strokes INTEGER, grade INTEGER, jlpt INTEGER, freq INTEGER, radical INTEGER)'
    )
    c.execute(
        'CREATE TABLE KanjiControl '
        '(control TEXT NOT NULL, value INTEGER, PRIMARY KEY (control))'
    )

    chars_dir = os.path.join(gitjidic2_dir, 'characters')
    count = 0
    for path in iter_json_files(chars_dir):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        char = data.get('char')
        if not char:
            continue

        on_str  = ' '.join(data.get('on',  [])) or None
        kun_str = ' '.join(data.get('kun', [])) or None
        meanings = data.get('meanings')

        c.execute(
            'INSERT INTO KanjiEntry '
            '(char, "on", kun, meanings, strokes, grade, jlpt, freq, radical) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (char,
             on_str,
             kun_str,
             json.dumps(meanings, ensure_ascii=False) if meanings else None,
             data.get('strokes'),
             data.get('grade'),
             data.get('jlpt'),
             data.get('freq'),
             data.get('radical')),
        )
        count += 1
        if count % 2000 == 0:
            print(f'  {count} characters inserted…', flush=True)

    c.executemany(
        'INSERT INTO KanjiControl (control, value) VALUES (?, ?)',
        [('build_timestamp', int(time.time())), ('char_count', count)],
    )

    c.execute('COMMIT')
    conn.execute('VACUUM')
    conn.close()

    print(f'Done: {count} characters → {db_path}', flush=True)


HELP = (
    'usage: gitjidic2-to-sqlite.py '
    '-i <gitjidic2 directory> -o <output directory>'
)


def main(argv):
    gitjidic2_dir = ''
    output_dir = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:o:', ['idir=', 'odir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            gitjidic2_dir = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not gitjidic2_dir or not output_dir:
        print(HELP)
        sys.exit(2)
    process(gitjidic2_dir, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
