#!/usr/bin/env python3
"""Download the Wadoku XML export and write pitch accent data to a gitch JSON repository.

Wadoku (和独辞典) is a Japanese-German dictionary that includes pitch accent
data for roughly 95,000 entries, distributed under CC BY-SA (Ulrich Apel &
Wadoku e.V.).  See https://www.wadoku.de/wiki/display/WAD/Wörterbuch+Lizenz

The XML export is downloaded automatically and cached.  On subsequent runs a
conditional HTTP GET (If-None-Match / If-Modified-Since) is used so the
archive is only re-downloaded when Wadoku publishes a new release.

Output follows the gitch directory layout consumed by gitch-to-sqlite.py:

    gitch/
        metadata.json
        entries/
            {shard}/
                {word}.json    shard = ord(word[0]) // 1000

Pitch position encoding (same as the rest of the pipeline):
    0  — heiban   (LH…H, no drop)
    1  — atamadaka (HL…L, drops after mora 1)
    N  — drops after mora N

Usage:
    wadoku-to-git.py -o <gitch directory> [--cache <cache directory>]

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
import sys
import tarfile
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

WADOKU_URL = 'https://www.wadoku.de/downloads/xml-export/wadoku-xml-latest.tar.xz'
NS = '{http://www.wadoku.de/xml/entry}'


# ---------------------------------------------------------------------------
# Download / cache helpers  (same pattern as kanjidic2-to-git.py)
# ---------------------------------------------------------------------------

def _download(url, dest):
    """Download url to dest atomically via a temp file, saving validation headers."""
    print(f'  Downloading {url} …', flush=True)
    tmp = dest + '.tmp'
    try:
        with urllib.request.urlopen(url) as resp:
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
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

    On first download the file and its HTTP validation headers (ETag,
    Last-Modified) are saved to disk.  On subsequent calls a conditional GET
    is issued with If-None-Match / If-Modified-Since; a 304 Not Modified
    response leaves the cached file untouched.
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

    req = urllib.request.Request(url)
    if saved.get('etag'):
        req.add_header('If-None-Match', saved['etag'])
    if saved.get('last-modified'):
        req.add_header('If-Modified-Since', saved['last-modified'])

    tmp = path + '.tmp'
    try:
        with urllib.request.urlopen(req) as resp:
            print(f'  Remote file changed, re-downloading {url} …', flush=True)
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
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
# XML parsing
# ---------------------------------------------------------------------------

def _parse_accents(reading_el):
    """Return non-negative integer pitch positions from <accent> child elements."""
    positions = []
    for acc in reading_el.findall(f'{NS}accent'):
        text = (acc.text or '').strip()
        if text.isdigit():
            positions.append(int(text))
    return positions


def _get_orths(form_el):
    """Return NFC-normalised word forms from <orth> elements.

    Prefers non-midashigo variants (cleaner surface forms without dictionary
    formatting markup); falls back to all <orth> elements when none are
    non-midashigo.
    """
    orths = form_el.findall(f'{NS}orth')
    non_midashigo = [o for o in orths if o.get('midashigo') != 'true']
    chosen = non_midashigo if non_midashigo else orths
    return [unicodedata.normalize('NFC', o.text) for o in chosen if o.text]


def parse_entries(xml_file):
    """Yield (word, reading, [pitch_positions]) tuples from the Wadoku XML stream.

    Uses iterparse so the ~120 MB uncompressed XML is processed without loading
    it all into memory at once; each <entry> element is cleared after use.
    Only entries that have both a <hira> reading and at least one <accent> with
    a non-negative integer position are yielded.
    """
    for _event, elem in ET.iterparse(xml_file, events=['end']):
        if elem.tag != f'{NS}entry':
            continue

        form = elem.find(f'{NS}form')
        if form is None:
            elem.clear()
            continue

        reading_el = form.find(f'{NS}reading')
        if reading_el is None:
            elem.clear()
            continue

        positions = _parse_accents(reading_el)
        if not positions:
            elem.clear()
            continue

        hira_el = reading_el.find(f'{NS}hira')
        if hira_el is None or not hira_el.text:
            elem.clear()
            continue

        reading = hira_el.text.strip()
        words = _get_orths(form)
        elem.clear()

        for word in words:
            yield word, reading, positions


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

def process(output_dir, cache_dir):
    archive_path = ensure_cached(WADOKU_URL, cache_dir)
    print(f'  Using {archive_path}', flush=True)

    merged = {}  # word → {reading → set of pitch positions}

    with tarfile.open(archive_path, 'r:xz') as tf:
        xml_member = next(
            (m for m in tf.getmembers() if m.name.endswith('.xml')),
            None,
        )
        if xml_member is None:
            print('Error: no .xml file found inside archive', file=sys.stderr)
            sys.exit(1)
        print(f'  Parsing {xml_member.name} …', flush=True)
        with tf.extractfile(xml_member) as f:
            count = 0
            for word, reading, positions in parse_entries(f):
                if word not in merged:
                    merged[word] = {}
                if reading not in merged[word]:
                    merged[word][reading] = set()
                merged[word][reading].update(positions)
                count += 1
                if count % 10000 == 0:
                    print(f'  {count} entries parsed…', flush=True)

    print(f'  {count} raw entries → {len(merged)} unique words', flush=True)

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
        {'source': 'wadoku', 'word_count': len(merged), 'pair_count': pair_count},
    )

    print(
        f'Done: {len(merged)} words, {pair_count} (word, reading) pairs → {output_dir}',
        flush=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HELP = (
    'usage: wadoku-to-git.py -o <gitch directory> [--cache <cache directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/wadoku')
    try:
        opts, _ = getopt.getopt(argv, 'ho:', ['odir=', 'cache='])
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
    if not output_dir:
        print(HELP)
        sys.exit(2)
    process(output_dir, cache_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
