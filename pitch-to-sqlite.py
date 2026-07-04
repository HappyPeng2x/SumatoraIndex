#!/usr/bin/env python3
"""Build pitch.db SQLite database from a pitch accent TSV data file.

Reads one or more TSV files containing word/reading/pitch data and writes a
single SQLite database with a PitchAccent table for use in the Android app's
character and entry detail views.

Input TSV format (tab-separated, UTF-8, no header line):

    word<TAB>reading<TAB>pitches

  word    — dictionary headword (kanji or kana surface form)
  reading — kana reading in hiragana (katakana is normalised automatically)
  pitches — one or more pitch drop positions separated by commas or spaces:
              0 = heiban (flat — rises and stays high throughout)
              1 = atamadaka (drops after the 1st mora)
              N = drops after the N-th mora; when N equals the mora count
                  of the reading the word is odaka (LH…HL)
            Multiple valid patterns for the same entry: list on one row,
            e.g. "0,2", or on separate rows — they are merged automatically.

A two-column form is also accepted for pure-kana entries where word = reading:

    reading<TAB>pitches

Compatible with kanjium-style TSV exports (github.com/mifunetoshiro/kanjium),
OJAD exports, and other common pitch accent data formats.  Feed data from
whichever source you have rights to; this script does not download anything.

Database schema:

    PitchAccent
      word     TEXT       — kanji or kana headword
      reading  TEXT       — hiragana reading
      pitches  TEXT       — JSON array of valid pitch position integers, e.g. [0] or [1,2]
      PRIMARY KEY (word, reading)

    PitchControl
      control  TEXT PK
      value    INTEGER    — build_timestamp (Unix epoch) or entry_count

Usage:
    pitch-to-sqlite.py -i <tsv_file> [-i <tsv_file2> …] -o <output directory>

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
import re
import sqlite3
import sys
import time


# ---------------------------------------------------------------------------
# Kana normalisation (katakana → hiragana for consistent storage)
# ---------------------------------------------------------------------------

def _kata_to_hira(s):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------

# Accepts pitch values separated by commas, spaces, or both.
_PITCH_SEP = re.compile(r'[\s,]+')


def _parse_pitches(raw):
    """Return sorted list of unique integer pitch positions from a raw string."""
    pitches = []
    for tok in _PITCH_SEP.split(raw.strip()):
        tok = tok.strip()
        if tok.isdigit():
            pitches.append(int(tok))
    return sorted(set(pitches))


def parse_tsv(path):
    """Yield (word, reading, pitches_list) tuples from a TSV file.

    Accepts both the three-column form  word<TAB>reading<TAB>pitches
    and the two-column form             reading<TAB>pitches  (word = reading).
    Lines starting with # and blank lines are ignored.
    """
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            cols = line.split('\t')
            if len(cols) >= 3:
                word    = cols[0].strip()
                reading = _kata_to_hira(cols[1].strip())
                pitches = _parse_pitches(cols[2])
            elif len(cols) == 2:
                reading = _kata_to_hira(cols[0].strip())
                word    = reading
                pitches = _parse_pitches(cols[1])
            else:
                continue
            if word and reading and pitches:
                yield word, reading, pitches


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(input_paths, output_dir):
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
    c.execute(
        'CREATE INDEX PitchAccentReading ON PitchAccent (reading)'
    )
    c.execute(
        'CREATE TABLE PitchControl '
        '(control TEXT NOT NULL, value INTEGER, PRIMARY KEY (control))'
    )

    # Accumulate all rows in memory so that duplicate (word, reading) pairs
    # from multiple input files are merged into a single pitches list.
    merged = {}  # (word, reading) → set of pitch positions

    for path in input_paths:
        file_rows = 0
        for word, reading, pitches in parse_tsv(path):
            key = (word, reading)
            if key not in merged:
                merged[key] = set()
            merged[key].update(pitches)
            file_rows += 1
        print(f'  {path}: {file_rows} rows parsed', flush=True)

    for (word, reading), pitch_set in merged.items():
        pitches_json = json.dumps(sorted(pitch_set), ensure_ascii=False)
        c.execute(
            'INSERT INTO PitchAccent (word, reading, pitches) VALUES (?, ?, ?)',
            (word, reading, pitches_json),
        )

    entry_count = len(merged)
    c.executemany(
        'INSERT INTO PitchControl (control, value) VALUES (?, ?)',
        [('build_timestamp', int(time.time())), ('entry_count', entry_count)],
    )

    c.execute('COMMIT')
    conn.execute('VACUUM')
    conn.close()

    print(f'Done: {entry_count} entries → {db_path}', flush=True)


HELP = (
    'usage: pitch-to-sqlite.py '
    '-i <tsv_file> [-i <tsv_file2> …] -o <output directory>'
)


def main(argv):
    input_paths = []
    output_dir = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:o:', ['input=', 'odir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--input'):
            input_paths.append(arg)
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not input_paths or not output_dir:
        print(HELP)
        sys.exit(2)
    process(input_paths, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
