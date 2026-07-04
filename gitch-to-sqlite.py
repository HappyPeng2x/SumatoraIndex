#!/usr/bin/env python3
"""Build pitch.db SQLite database from a gitch JSON repository.

Reads word JSON files produced by pitch-to-git.py and writes a single SQLite
database with a PitchAccent table for use in the Android app.

Database schema:

    PitchAccent
      word     TEXT       — kanji or kana headword (NFC-normalised)
      reading  TEXT       — hiragana reading
      pitches  TEXT       — JSON array of valid pitch position integers, e.g. [0] or [1,2]
      PRIMARY KEY (word, reading)

    PitchControl
      control  TEXT PK
      value    INTEGER    — build_timestamp (Unix epoch) or entry_count

Usage:
    gitch-to-sqlite.py -i <gitch directory> -o <output directory>

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
# JSON file iteration
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

def process(gitch_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    db_path = os.path.join(output_dir, 'pitch.db')

    conn = sqlite3.connect(db_path, isolation_level=None)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=DELETE')
    c.execute('BEGIN TRANSACTION')

    for table in ('PitchAccent', 'PitchControl'):
        c.execute(f'DROP TABLE IF EXISTS {table}')

    c.execute(
        'CREATE TABLE PitchAccent ('
        'word TEXT NOT NULL, reading TEXT NOT NULL, pitches TEXT NOT NULL, '
        'PRIMARY KEY (word, reading))'
    )
    c.execute('CREATE INDEX PitchAccentReading ON PitchAccent (reading)')
    c.execute(
        'CREATE TABLE PitchControl '
        '(control TEXT NOT NULL, value INTEGER, PRIMARY KEY (control))'
    )

    entries_dir = os.path.join(gitch_dir, 'entries')
    count = 0

    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        word = data.get('word')
        if not word:
            continue
        for entry in data.get('readings', []):
            reading = entry.get('reading')
            pitches = entry.get('pitches')
            if not reading or pitches is None:
                continue
            c.execute(
                'INSERT OR REPLACE INTO PitchAccent (word, reading, pitches) VALUES (?, ?, ?)',
                (word, reading, json.dumps(pitches, ensure_ascii=False)),
            )
            count += 1
            if count % 10000 == 0:
                print(f'  {count} entries inserted…', flush=True)

    c.executemany(
        'INSERT INTO PitchControl (control, value) VALUES (?, ?)',
        [('build_timestamp', int(time.time())), ('entry_count', count)],
    )

    c.execute('COMMIT')
    conn.execute('VACUUM')
    conn.close()

    print(f'Done: {count} entries → {db_path}', flush=True)


HELP = (
    'usage: gitch-to-sqlite.py '
    '-i <gitch directory> -o <output directory>'
)


def main(argv):
    gitch_dir = ''
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
            gitch_dir = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not gitch_dir or not output_dir:
        print(HELP)
        sys.exit(2)
    process(gitch_dir, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
