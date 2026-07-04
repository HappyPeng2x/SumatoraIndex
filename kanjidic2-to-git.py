#!/usr/bin/env python3
"""Download kanjidic2.xml.gz and write a gitjidic2 JSON repository.

Downloads kanjidic2.xml.gz from the EDRDG server, caches it locally, then
parses the XML into one JSON file per character entry.

Directory layout:
    gitjidic2/
        metadata.json
        characters/
            {shard}/
                {XXXX}.json   (filename = uppercase hex codepoint,
                               shard = codepoint // 1000)

Each character JSON:
    {"char": "食", "on": ["ショク", "ジキ"], "kun": ["く.う", "く.らう", "た.べる"]}

  on  — ja_on readings in katakana, as found in kanjidic2
  kun — ja_kun readings in hiragana, okurigana after "." as found in kanjidic2

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import gzip
import json
import os
import sys
import urllib.request

from lxml import etree

KANJIDIC2_URL = 'https://www.edrdg.org/kanjidic/kanjidic2.xml.gz'


# ---------------------------------------------------------------------------
# Download / cache helpers
# ---------------------------------------------------------------------------

def _download(url, dest):
    print(f'  Downloading {url} …', flush=True)
    urllib.request.urlretrieve(url, dest)


def ensure_cached(url, cache_dir):
    """Return local path to the cached file, downloading if absent."""
    os.makedirs(cache_dir, exist_ok=True)
    name = url.split('/')[-1]
    path = os.path.join(cache_dir, name)
    if not os.path.exists(path):
        _download(url, path)
    return path


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def parse_character(elem):
    """Return (char, data_dict) from a <character> element, or (None, None)."""
    char = elem.findtext('literal')
    if not char:
        return None, None

    on_readings = []
    kun_readings = []
    meanings = []

    for rmgroup in elem.findall('.//rmgroup'):
        for r in rmgroup.findall('reading'):
            r_type = r.get('r_type', '')
            text = (r.text or '').strip()
            if not text:
                continue
            if r_type == 'ja_on':
                on_readings.append(text)
            elif r_type == 'ja_kun':
                kun_readings.append(text)
        for m in rmgroup.findall('meaning'):
            # English meanings have no m_lang attribute (it is the default language)
            if m.get('m_lang') is None and m.text:
                meanings.append(m.text.strip())

    misc = elem.find('misc')
    strokes = grade = jlpt = freq = None
    if misc is not None:
        sc = misc.find('stroke_count')
        if sc is not None and sc.text:
            strokes = int(sc.text)
        g = misc.find('grade')
        if g is not None and g.text:
            grade = int(g.text)
        j = misc.find('jlpt')
        if j is not None and j.text:
            jlpt = int(j.text)
        f = misc.find('freq')
        if f is not None and f.text:
            freq = int(f.text)

    radical = None
    for rv in elem.findall('.//rad_value'):
        if rv.get('rad_type') == 'classical' and rv.text:
            radical = int(rv.text)
            break

    data = {'char': char, 'on': on_readings, 'kun': kun_readings}
    if meanings:
        data['meanings'] = meanings
    if strokes is not None:
        data['strokes'] = strokes
    if grade is not None:
        data['grade'] = grade
    if jlpt is not None:
        data['jlpt'] = jlpt
    if freq is not None:
        data['freq'] = freq
    if radical is not None:
        data['radical'] = radical

    return char, data


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(output_dir, cache_dir):
    path = ensure_cached(KANJIDIC2_URL, cache_dir)
    print(f'  Using {path}', flush=True)

    os.makedirs(output_dir, exist_ok=True)
    count = 0

    with gzip.open(path, 'rb') as f:
        for event, elem in etree.iterparse(f, tag='character'):
            char, data = parse_character(elem)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            if char is None:
                continue

            cp = ord(char)
            shard = cp // 1000
            hex_cp = f'{cp:04X}'
            write_json(
                os.path.join(output_dir, 'characters', str(shard), f'{hex_cp}.json'),
                data,
            )
            count += 1
            if count % 2000 == 0:
                print(f'  {count} characters processed…', flush=True)

    write_json(
        os.path.join(output_dir, 'metadata.json'),
        {'count': count},
    )
    print(f'Done: {count} characters written to {output_dir}', flush=True)


HELP = (
    'usage: kanjidic2-to-git.py '
    '-o <gitjidic2 directory> [--cache <cache directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/kanjidic2')
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
