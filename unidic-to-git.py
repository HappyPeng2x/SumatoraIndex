#!/usr/bin/env python3
"""Download the UniDic binary archive and extract pitch accent data.

Downloads the UniDic-cwj zip from NINJAL, extracts sys.dic from it (the
zip is discarded afterwards; only sys.dic is kept in the cache), reads the
feature section of sys.dic to extract pitch accent annotations, and writes
the data to a gitch JSON repository.

The regular (non-_full) zip is used (~570 MB download, ~243 MB cached sys.dic)
rather than the _full archive (2.8 GB), because the binary contains all the
pitch data we need and is far smaller than the source lex.csv distribution.

UniDic is distributed by NINJAL under a GPL v2.0 / LGPL v2.1 / BSD New
triple licence — compatible with GPLv3 and AGPLv3.

Feature field positions inside sys.dic (determined empirically):
    8  orth   written form (kanji or kana as it appears in running text)
    9  pron   pronunciation in katakana (ー marks long vowels)
    24 aType  pitch accent drop position(s); CSV-quoted when multi-valued

The aType field is stored with CSV quoting when it contains commas (e.g.
"0,2" for a word that has two possible pitch patterns).  Each feature string
is therefore parsed with csv.reader rather than a naïve split.

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
    unidic-to-git.py -o <gitch directory>
        [--cache <dir>]   download cache (default: ~/.cache/unidic)
        [--url   <url>]   pin a specific zip URL (default: auto-discover)

The default URL is auto-discovered from https://clrd.ninjal.ac.jp/unidic/download.html
so the latest release is always used.  Use --url to pin a specific version.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.3.0"

import csv
import getopt
import io
import json
import os
import re
import struct
import sys
import unicodedata
import urllib.error
import urllib.request
import zipfile

_NINJAL_BASE         = 'https://clrd.ninjal.ac.jp'
_DOWNLOAD_PAGE       = _NINJAL_BASE + '/unidic/download.html'
_FALLBACK_UNIDIC_URL = _NINJAL_BASE + '/unidic_archive/2512/unidic-cwj-202512.zip'
# Match the regular (non-_full) cwj zip to keep the download small.
_CWJ_RE = re.compile(r'/unidic_archive/\d+/unidic-cwj-\d+\.zip(?!\.)')

_COL_ORTH  = 8    # written form (kanji/kana)
_COL_PRON  = 9    # katakana pronunciation
_COL_ATYPE = 24   # pitch drop position(s); CSV-quoted when multi-valued


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def discover_url():
    """Return the latest UniDic-cwj (non-_full) zip URL from the NINJAL download page."""
    try:
        with urllib.request.urlopen(_DOWNLOAD_PAGE, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        m = _CWJ_RE.search(html)
        if m:
            url = _NINJAL_BASE + m.group(0)
            print(f'  Latest UniDic-cwj: {url}', flush=True)
            return url
        print('  Warning: cwj link not found on download page; using fallback URL',
              flush=True)
    except Exception as exc:
        print(f'  Warning: could not fetch download page ({exc}); using fallback URL',
              flush=True)
    return _FALLBACK_UNIDIC_URL


# ---------------------------------------------------------------------------
# Download / cache helpers
# ---------------------------------------------------------------------------

def _stream_zip_to_file(resp, dest):
    """Write the body of an open urllib response to dest, showing progress."""
    total = resp.headers.get('Content-Length')
    done = 0
    with open(dest, 'wb') as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // int(total)
                print(
                    f'\r  {done // (1024 * 1024)} / '
                    f'{int(total) // (1024 * 1024)} MB  ({pct}%)',
                    end='', flush=True,
                )
    print(flush=True)
    saved = {}
    if resp.headers.get('ETag'):
        saved['etag'] = resp.headers['ETag']
    if resp.headers.get('Last-Modified'):
        saved['last-modified'] = resp.headers['Last-Modified']
    return saved


def _extract_sysdic(zip_path, dest):
    """Extract sys.dic from zip_path and write it atomically to dest."""
    print('  Extracting sys.dic from zip…', flush=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        name = next(
            (n for n in zf.namelist() if os.path.basename(n) == 'sys.dic'),
            None,
        )
        if name is None:
            print('Error: sys.dic not found in archive', file=sys.stderr)
            sys.exit(1)
        tmp = dest + '.tmp'
        try:
            with zf.open(name) as src, open(tmp, 'wb') as out:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(tmp, dest)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def _download_and_extract(url, cache_dir, resp=None):
    """Download zip (or use open resp), extract sys.dic, discard zip, save headers."""
    sysdic_path  = os.path.join(cache_dir, 'sys.dic')
    headers_path = os.path.join(cache_dir, 'sys.dic.headers')
    tmp_zip      = os.path.join(cache_dir, '_download.zip.tmp')
    try:
        if resp is not None:
            saved = _stream_zip_to_file(resp, tmp_zip)
        else:
            print(f'  Downloading {url} …', flush=True)
            with urllib.request.urlopen(url) as r:
                saved = _stream_zip_to_file(r, tmp_zip)
        _extract_sysdic(tmp_zip, sysdic_path)
        with open(headers_path, 'w') as f:
            json.dump(saved, f)
    finally:
        if os.path.exists(tmp_zip):
            os.unlink(tmp_zip)


def ensure_sysdic(url, cache_dir):
    """Return path to a cached sys.dic, refreshing from NINJAL when the zip has changed.

    Cache layout (cache_dir/):
        sys.dic           — extracted binary dictionary
        sys.dic.headers   — ETag / Last-Modified from the last zip download

    The zip itself is never kept; it is downloaded to a temp file, sys.dic is
    extracted, and the zip is deleted.  This keeps the persistent cache at
    ~243 MB rather than ~813 MB.
    """
    os.makedirs(cache_dir, exist_ok=True)
    sysdic_path  = os.path.join(cache_dir, 'sys.dic')
    headers_path = os.path.join(cache_dir, 'sys.dic.headers')

    if not os.path.exists(sysdic_path):
        _download_and_extract(url, cache_dir)
        return sysdic_path

    saved = {}
    if os.path.exists(headers_path):
        with open(headers_path) as f:
            saved = json.load(f)

    if not saved:
        print('  Using cached sys.dic (no validators; delete to force refresh)',
              flush=True)
        return sysdic_path

    req = urllib.request.Request(url)
    if saved.get('etag'):
        req.add_header('If-None-Match', saved['etag'])
    if saved.get('last-modified'):
        req.add_header('If-Modified-Since', saved['last-modified'])

    try:
        with urllib.request.urlopen(req) as resp:
            print('  Remote zip changed, re-downloading…', flush=True)
            _download_and_extract(url, cache_dir, resp=resp)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            print('  UniDic is up to date', flush=True)
        else:
            raise

    return sysdic_path


# ---------------------------------------------------------------------------
# Binary parsing
# ---------------------------------------------------------------------------

def _read_feature_block(sysdic_path):
    """Return the raw feature-section bytes from sys.dic."""
    with open(sysdic_path, 'rb') as f:
        hdr = f.read(72)
    fields = struct.unpack_from('<IIIIIIIIII', hdr, 0)
    # dsize is in double-array units (8 bytes each)
    da_bytes    = fields[6] * 8
    tok_bytes   = fields[7]
    feat_bytes  = fields[8]
    feat_offset = 72 + da_bytes + tok_bytes
    with open(sysdic_path, 'rb') as f:
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


def parse_entries(sysdic_path):
    """Yield (word, reading_hiragana, [pitch_positions]) for every entry with pitch."""
    print(f'  Parsing feature section of {sysdic_path}', flush=True)
    block = _read_feature_block(sysdic_path)
    count = 0
    for raw in block.split(b'\x00'):
        if not raw:
            continue
        try:
            line = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        # csv.reader handles quoted fields like "0,2" correctly.
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

def process(output_dir, cache_dir, url):
    sysdic_path = ensure_sysdic(url, cache_dir)

    merged = {}  # word → {reading → set of pitch positions}

    for word, reading, positions in parse_entries(sysdic_path):
        if word not in merged:
            merged[word] = {}
        if reading not in merged[word]:
            merged[word][reading] = set()
        merged[word][reading].update(positions)

    total_pairs = sum(len(v) for v in merged.values())
    print(f'  {total_pairs} (word, reading) pairs → {len(merged)} unique words',
          flush=True)

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
    '    [--cache <dir>]   download cache (default: ~/.cache/unidic)\n'
    '    [--url   <url>]   pin a specific zip URL (default: auto-discover latest)'
)


def main(argv):
    output_dir = ''
    cache_dir  = os.path.expanduser('~/.cache/unidic')
    url        = ''
    try:
        opts, _ = getopt.getopt(argv, 'ho:', ['odir=', 'cache=', 'url='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-o', '--odir'):
            output_dir = arg
        elif opt == '--cache':
            cache_dir = arg
        elif opt == '--url':
            url = arg
    if not output_dir:
        print(HELP)
        sys.exit(2)
    if not url:
        url = discover_url()
    process(output_dir, cache_dir, url)


if __name__ == '__main__':
    main(sys.argv[1:])
