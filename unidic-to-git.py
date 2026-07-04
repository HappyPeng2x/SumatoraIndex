#!/usr/bin/env python3
"""Extract pitch accent data from the installed UniDic binary dictionary.

Reads sys.dic from the `unidic` Python package, parses its feature section,
and writes pitch accent entries to a gitch JSON repository.

Prerequisites:
    pip install unidic
    python -m unidic download    # one-time ~526 MB download from NINJAL/AWS

UniDic is distributed by NINJAL under a GPL v2.0 / LGPL v2.1 / BSD New
triple licence — compatible with GPLv3 and AGPLv3.

Feature field positions inside sys.dic (determined empirically):
    8  orth   written form (kanji or kana as it appears in running text)
    9  pron   pronunciation in katakana (ー marks long vowels)
    24 aType  pitch accent drop position(s); may be multi-valued: "0,2"

The aType values in the raw binary use CSV quoting when they contain commas
(e.g.  "0,2"  for a word with two possible pitch patterns).  Each feature
string is therefore parsed with csv.reader rather than a naïve split.

Pitch position encoding (same as the rest of the pipeline):
    0  — heiban    (LH…H, no drop)
    1  — atamadaka (HL…L, drops after mora 1)
    N  — drops after mora N

Output follows the gitch directory layout consumed by gitch-to-sqlite.py:
    gitch/
        metadata.json
        entries/
            {shard}/
                {word}.json    shard = ord(word[0]) // 1000

Usage:
    unidic-to-git.py -o <gitch directory> [--dicdir <path to sys.dic dir>]

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.2.0"

import csv
import getopt
import io
import json
import os
import struct
import sys
import unicodedata

_COL_ORTH  = 8    # written form (kanji/kana)
_COL_PRON  = 9    # katakana pronunciation
_COL_ATYPE = 24   # pitch drop position(s); CSV-quoted when multi-valued


# ---------------------------------------------------------------------------
# UniDic location
# ---------------------------------------------------------------------------

def find_dicdir():
    """Return the sys.dic directory from the installed `unidic` package."""
    try:
        import unidic
        return unidic.DICDIR
    except ImportError:
        print(
            'Error: the `unidic` Python package is not installed.\n'
            '  pip install unidic\n'
            '  python -m unidic download',
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Binary parsing
# ---------------------------------------------------------------------------

def _read_feature_block(dicdir):
    """Return the raw feature bytes from sys.dic."""
    path = os.path.join(dicdir, 'sys.dic')
    if not os.path.exists(path):
        print(
            f'Error: sys.dic not found in {dicdir!r}.\n'
            '  Run: python -m unidic download',
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, 'rb') as f:
        hdr = f.read(72)
    fields = struct.unpack_from('<IIIIIIIIII', hdr, 0)
    # dsize is in double-array units (8 bytes each)
    da_bytes   = fields[6] * 8
    tok_bytes  = fields[7]
    feat_bytes = fields[8]
    feat_offset = 72 + da_bytes + tok_bytes
    with open(path, 'rb') as f:
        f.seek(feat_offset)
        return f.read(feat_bytes)


def _kata_to_hira(s):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in s
    )


def _parse_atype(s):
    """Return sorted list of non-negative integer pitch positions."""
    positions = []
    for tok in s.split(','):
        tok = tok.strip()
        if tok.isdigit():
            positions.append(int(tok))
    return sorted(set(positions))


def parse_entries(dicdir):
    """Yield (word, reading_hiragana, [pitch_positions]) for every entry with pitch."""
    print(f'  Reading sys.dic from {dicdir}', flush=True)
    block = _read_feature_block(dicdir)
    count = 0
    for raw in block.split(b'\x00'):
        if not raw:
            continue
        try:
            line = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        # Use csv.reader so that quoted fields like "0,2" parse as one token.
        try:
            row = next(csv.reader(io.StringIO(line)))
        except StopIteration:
            continue
        if len(row) <= _COL_ATYPE:
            continue
        atype_str = row[_COL_ATYPE].strip()
        if not atype_str or atype_str == '*':
            continue
        positions = _parse_atype(atype_str)
        if not positions:
            continue
        word = unicodedata.normalize('NFC', row[_COL_ORTH].strip())
        pron = _kata_to_hira(row[_COL_PRON].strip())
        if not word or not pron:
            continue
        count += 1
        if count % 50000 == 0:
            print(f'  {count} entries with pitch parsed…', flush=True)
        yield word, pron, positions


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

def process(output_dir, dicdir):
    merged = {}  # word → {reading → set of pitch positions}

    for word, reading, positions in parse_entries(dicdir):
        if word not in merged:
            merged[word] = {}
        if reading not in merged[word]:
            merged[word][reading] = set()
        merged[word][reading].update(positions)

    total_pairs = sum(len(v) for v in merged.values())
    print(f'  {total_pairs} (word, reading) pairs → {len(merged)} unique words', flush=True)

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
        {'source': 'unidic', 'word_count': len(merged), 'pair_count': pair_count},
    )

    print(
        f'Done: {len(merged)} words, {pair_count} (word, reading) pairs → {output_dir}',
        flush=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HELP = (
    'usage: unidic-to-git.py -o <gitch directory>\n'
    '    [--dicdir <dir>]   path to the UniDic sys.dic directory\n'
    '                       (default: auto-detect from installed `unidic` package)'
)


def main(argv):
    output_dir = ''
    dicdir     = ''
    try:
        opts, _ = getopt.getopt(argv, 'ho:', ['odir=', 'dicdir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-o', '--odir'):
            output_dir = arg
        elif opt == '--dicdir':
            dicdir = arg
    if not output_dir:
        print(HELP)
        sys.exit(2)
    if not dicdir:
        dicdir = find_dicdir()
    process(output_dir, dicdir)


if __name__ == '__main__':
    main(sys.argv[1:])
