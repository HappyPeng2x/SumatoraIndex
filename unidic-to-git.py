#!/usr/bin/env python3
"""Download the UniDic source archive and write pitch accent data to a gitch JSON repository.

UniDic (国語研短単位自動解析用辞書) is the official Japanese morphological
dictionary maintained by NINJAL (the National Institute for Japanese Language
and Linguistics).  Its lex.csv contains an aType column with hand-annotated
pitch accent positions for a large portion of its vocabulary.

License: GPL v2.0 / LGPL v2.1 / BSD New (triple licence) — all compatible
with GPLv3 and AGPLv3.  See the 'licenses' directory inside the archive.

Column indices in UniDic lex.csv (confirmed by tdmelodic/dic_index_map.py):
    0  surface   written form as it appears in text (kanji or kana)
    13 pron      pronunciation in katakana (ー marks long vowels)
    27 aType     comma-separated pitch drop positions; empty if unknown

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
    unidic-to-git.py -o <gitch directory> [--cache <cache directory>]
                     [--url <zip URL>]

The default download URL points to the February 2023 release of UniDic for
Contemporary Written Japanese (ver. 3.1.0, 576 MB).  Update --url when NINJAL
publishes a new release; check https://clrd.ninjal.ac.jp/unidic/en/ for the
latest archive path.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import csv
import getopt
import io
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import zipfile

_NINJAL_BASE         = 'https://clrd.ninjal.ac.jp'
_DOWNLOAD_PAGE       = _NINJAL_BASE + '/unidic/download.html'
_FALLBACK_UNIDIC_URL = (_NINJAL_BASE + '/unidic_archive/2512/unidic-cwj-202512.zip')
_CWJ_RE              = re.compile(r'/unidic_archive/\d+/unidic-cwj-\d+\.zip')

# Column indices in the raw lex.csv (confirmed by tdmelodic/dic_index_map.py)
_COL_SURFACE = 0
_COL_PRON    = 13   # katakana; ー marks long vowels
_COL_ATYPE   = 27   # comma-separated drop positions, '' if unlisted


# ---------------------------------------------------------------------------
# Version discovery
# ---------------------------------------------------------------------------

def discover_url():
    """Return the download URL of the latest UniDic-cwj zip from the NINJAL page.

    Falls back to _FALLBACK_UNIDIC_URL if the page cannot be fetched or parsed.
    """
    try:
        with urllib.request.urlopen(_DOWNLOAD_PAGE, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
        m = _CWJ_RE.search(html)
        if m:
            url = _NINJAL_BASE + m.group(0)
            print(f'  Latest UniDic-cwj: {url}', flush=True)
            return url
        print('  Warning: could not find cwj link on download page; using fallback URL',
              flush=True)
    except Exception as exc:
        print(f'  Warning: could not fetch download page ({exc}); using fallback URL',
              flush=True)
    return _FALLBACK_UNIDIC_URL


# ---------------------------------------------------------------------------
# Download / cache helpers  (same pattern as kanjidic2-to-git.py)
# ---------------------------------------------------------------------------

def _download(url, dest):
    """Download url to dest atomically via a temp file, saving validation headers."""
    print(f'  Downloading {url} …', flush=True)
    tmp = dest + '.tmp'
    try:
        with urllib.request.urlopen(url) as resp:
            total = resp.headers.get('Content-Length')
            done = 0
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // int(total)
                        print(f'\r  {done // (1024*1024)} / '
                              f'{int(total) // (1024*1024)} MB ({pct}%)',
                              end='', flush=True)
            print(flush=True)
            saved = {}
            if resp.headers.get('ETag'):
                saved['etag'] = resp.headers['ETag']
            if resp.headers.get('Last-Modified'):
                saved['last-modified'] = resp.headers['Last-Modified']
        os.replace(tmp, dest)
        with open(dest + '.headers', 'w') as f:
            json.dump(saved, f)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def ensure_cached(url, cache_dir):
    """Return local path to cached file, re-downloading when the server has a newer version.

    On first download, ETag / Last-Modified headers are stored alongside the
    file.  On subsequent calls a conditional GET is sent; a 304 response leaves
    the cache untouched.  If no validators are stored the cached file is used
    as-is (avoids re-downloading the 576 MB archive on every run).
    """
    os.makedirs(cache_dir, exist_ok=True)
    name = url.split('/')[-1]
    path = os.path.join(cache_dir, name)

    if not os.path.exists(path):
        _download(url, path)
        return path

    headers_path = path + '.headers'
    saved = {}
    if os.path.exists(headers_path):
        with open(headers_path) as f:
            saved = json.load(f)

    if not saved:
        print(f'  Using cached {name} (no validators stored; delete to force refresh)',
              flush=True)
        return path

    req = urllib.request.Request(url)
    if saved.get('etag'):
        req.add_header('If-None-Match', saved['etag'])
    if saved.get('last-modified'):
        req.add_header('If-Modified-Since', saved['last-modified'])

    tmp = path + '.tmp'
    try:
        with urllib.request.urlopen(req) as resp:
            print(f'  Remote file changed, re-downloading {url} …', flush=True)
            total = resp.headers.get('Content-Length')
            done = 0
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // int(total)
                        print(f'\r  {done // (1024*1024)} / '
                              f'{int(total) // (1024*1024)} MB ({pct}%)',
                              end='', flush=True)
            print(flush=True)
            new_saved = {}
            if resp.headers.get('ETag'):
                new_saved['etag'] = resp.headers['ETag']
            if resp.headers.get('Last-Modified'):
                new_saved['last-modified'] = resp.headers['Last-Modified']
        os.replace(tmp, path)
        with open(headers_path, 'w') as f:
            json.dump(new_saved, f)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            print(f'  {name} is up to date', flush=True)
        else:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    return path


# ---------------------------------------------------------------------------
# Kana helpers
# ---------------------------------------------------------------------------

def _kata_to_hira(s):
    """Convert full-width katakana to hiragana; leave other characters unchanged."""
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _parse_atype(s):
    """Return sorted list of non-negative integer pitch positions from an aType cell."""
    positions = []
    for tok in s.split(','):
        tok = tok.strip()
        if tok.isdigit():
            positions.append(int(tok))
    return sorted(set(positions))


def parse_entries(zip_path):
    """Yield (word, reading, [pitch_positions]) from the UniDic lex.csv inside the zip."""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        csv_name = next(
            (n for n in zf.namelist()
             if os.path.basename(n).startswith('lex') and n.endswith('.csv')),
            None,
        )
        if csv_name is None:
            print('Error: no lex*.csv found in archive', file=sys.stderr)
            sys.exit(1)
        print(f'  Parsing {csv_name} …', flush=True)
        with zf.open(csv_name) as raw_f:
            reader = csv.reader(io.TextIOWrapper(raw_f, encoding='utf-8'))
            count = 0
            for row in reader:
                if len(row) <= _COL_ATYPE:
                    continue
                atype_str = row[_COL_ATYPE].strip()
                if not atype_str:
                    continue
                positions = _parse_atype(atype_str)
                if not positions:
                    continue
                surface = unicodedata.normalize('NFC', row[_COL_SURFACE].strip())
                pron    = _kata_to_hira(row[_COL_PRON].strip())
                if not surface or not pron:
                    continue
                count += 1
                if count % 10000 == 0:
                    print(f'  {count} entries parsed…', flush=True)
                yield surface, pron, positions


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

def process(output_dir, cache_dir, url=''):
    if not url:
        url = discover_url()
    zip_path = ensure_cached(url, cache_dir)
    print(f'  Using {zip_path}', flush=True)

    merged = {}  # word → {reading → set of pitch positions}

    for word, reading, positions in parse_entries(zip_path):
        if word not in merged:
            merged[word] = {}
        if reading not in merged[word]:
            merged[word][reading] = set()
        merged[word][reading].update(positions)

    total_entries = sum(len(v) for v in merged.values())
    print(f'  {total_entries} (word, reading) pairs → {len(merged)} unique words',
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
    '    [--url   <url>]   pin a specific zip URL (default: auto-discover latest from NINJAL)'
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
    process(output_dir, cache_dir, url)


if __name__ == '__main__':
    main(sys.argv[1:])
