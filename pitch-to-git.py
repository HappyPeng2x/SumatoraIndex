#!/usr/bin/env python3
"""Read pitch accent TSV data files and write a gitch JSON repository.

Reads one or more TSV files, merges entries for the same (word, reading) pair,
and writes one JSON file per unique word form under the gitch directory.

Input TSV format (tab-separated, UTF-8, no header line):

    word<TAB>reading<TAB>pitches

  word    — dictionary headword (kanji or kana surface form)
  reading — kana reading in hiragana (katakana is normalised automatically)
  pitches — one or more pitch drop positions separated by commas or spaces:
              0 = heiban (flat)
              1 = atamadaka (drops after 1st mora)
              N = drops after N-th mora
            Multiple patterns for the same entry are merged automatically.

A two-column form is also accepted for pure-kana entries where word = reading:

    reading<TAB>pitches

Directory layout:
    gitch/
        metadata.json
        entries/
            {shard}/
                {word}.json    (shard = ord(word[0]) // 1000)

Each word JSON:
    {
      "word": "食べる",
      "readings": [
        {"reading": "たべる", "pitches": [2]}
      ]
    }

  word     — NFC-normalised headword
  readings — list of reading objects sorted by reading string;
             pitches is a sorted list of integer drop positions

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
import sys
import unicodedata


# ---------------------------------------------------------------------------
# Kana normalisation
# ---------------------------------------------------------------------------

def _kata_to_hira(s):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# TSV parsing
# ---------------------------------------------------------------------------

_PITCH_SEP = re.compile(r'[\s,]+')


def _parse_pitches(raw):
    pitches = []
    for tok in _PITCH_SEP.split(raw.strip()):
        tok = tok.strip()
        if tok.isdigit():
            pitches.append(int(tok))
    return sorted(set(pitches))


def parse_tsv(path):
    """Yield (word, reading, pitches_list) from a TSV file."""
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
                yield unicodedata.normalize('NFC', word), reading, pitches


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(input_paths, output_dir):
    # word → {reading → set of pitch positions}
    merged = {}

    for path in input_paths:
        file_rows = 0
        for word, reading, pitches in parse_tsv(path):
            if word not in merged:
                merged[word] = {}
            if reading not in merged[word]:
                merged[word][reading] = set()
            merged[word][reading].update(pitches)
            file_rows += 1
        print(f'  {path}: {file_rows} rows parsed', flush=True)

    os.makedirs(output_dir, exist_ok=True)
    pair_count = 0

    for word, readings_map in merged.items():
        shard = ord(word[0]) // 1000
        readings = [
            {'reading': r, 'pitches': sorted(ps)}
            for r, ps in sorted(readings_map.items())
        ]
        pair_count += len(readings)
        safe_name = word.replace('/', '_')
        write_json(
            os.path.join(output_dir, 'entries', str(shard), f'{safe_name}.json'),
            {'word': word, 'readings': readings},
        )

    write_json(
        os.path.join(output_dir, 'metadata.json'),
        {'word_count': len(merged), 'pair_count': pair_count},
    )
    print(f'Done: {len(merged)} words, {pair_count} (word, reading) pairs → {output_dir}',
          flush=True)


HELP = (
    'usage: pitch-to-git.py '
    '-i <tsv_file> [-i <tsv_file2> …] -o <gitch directory>'
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
