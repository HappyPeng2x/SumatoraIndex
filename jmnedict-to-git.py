#!/usr/bin/env python3
"""Download JMnedict and write a gitnedict JSON git repository.

Downloads JMnedict.xml.gz from the EDRDG server, caches it locally, then
parses the XML into one JSON file per entry, mirroring the layout of the
gitmdict repository used for JMdict.

Each entry JSON has the form:

    {
      "seq": 5000000,
      "kanji": [{"text": "東京", "common": true, "tags": ["news1"]}],
      "kana":  [{"text": "とうきょう", "appliesToKanji": ["*"]}],
      "types": ["place"],
      "translations": ["Tokyo"]
    }

`types` is the deduplicated list of JMnedict name_type entity codes across
all <trans> elements.  `translations` is the list of <trans_det> strings.

Furigana is not computed here — it is generated at DB-build time by
jmnedict-to-sumatora-db.py (kanjidic2-informed, via furigana_solver.py),
keyed by every reading that applies to a kanji form, since a name can have
more than one valid reading just like a JMdict word.

Downloaded files are cached; delete the cache to force a re-download.

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
import re
import sys
import urllib.error
import urllib.request

from lxml import etree

JMNEDICT_URL = 'http://ftp.edrdg.org/pub/Nihongo/JMnedict.xml.gz'
ENTITY_RE = re.compile(r'<!ENTITY\s+([\w\-\.]+)\s+"([^"]+)"')
SHARD_SIZE = 10000


# ---------------------------------------------------------------------------
# Download helpers
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

    # File exists — build a conditional GET using stored validators.
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


def _open_text(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', encoding='utf-8')
    return open(path, 'r', encoding='utf-8')


def _open_binary(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rb')
    return open(path, 'rb')


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def extract_entities(path):
    """Read the DOCTYPE block and extract entity name → description pairs."""
    with _open_text(path) as f:
        header = f.read(30000)
    end = header.find(']>')
    if end == -1:
        end = len(header)
    return {m.group(1): m.group(2) for m in ENTITY_RE.finditer(header[:end + 2])}


def parse_entry(elem):
    seq = int(elem.findtext('ent_seq'))

    kanji = []
    for k in elem.findall('k_ele'):
        keb = k.findtext('keb') or ''
        pris = [p.text for p in k.findall('ke_pri') if p.text]
        infs = [c.name for e in k.findall('ke_inf') for c in e
                if isinstance(c, etree._Entity)]
        kanji.append({'text': keb, 'common': bool(pris), 'tags': pris + infs})

    kana = []
    for r in elem.findall('r_ele'):
        reb = r.findtext('reb') or ''
        restr = [e.text for e in r.findall('re_restr') if e.text]
        kana.append({
            'text': reb,
            'appliesToKanji': restr if restr else ['*'],
        })

    types = []
    translations = []
    for t in elem.findall('trans'):
        for nt in t.findall('name_type'):
            for child in nt:
                if isinstance(child, etree._Entity) and child.name not in types:
                    types.append(child.name)
        td = t.findtext('trans_det')
        if td:
            translations.append(td)

    return seq, kanji, kana, types, translations


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
    jmnedict_path = ensure_cached(JMNEDICT_URL, cache_dir)
    print(f'  Using {jmnedict_path}', flush=True)

    entities = extract_entities(jmnedict_path)
    print(f'  {len(entities)} entity declarations extracted', flush=True)

    os.makedirs(output_dir, exist_ok=True)
    entry_count = 0

    with _open_binary(jmnedict_path) as f:
        for event, elem in etree.iterparse(
            f, tag='entry',
            load_dtd=True, resolve_entities=False, no_network=True,
        ):
            seq, kanji, kana, types, translations = parse_entry(elem)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            sh = seq // SHARD_SIZE
            write_json(
                os.path.join(output_dir, 'entries', str(sh), f'{seq}.json'),
                {
                    'seq': seq,
                    'kanji': kanji,
                    'kana': kana,
                    'types': types,
                    'translations': translations,
                },
            )

            entry_count += 1
            if entry_count % 10000 == 0:
                print(f'  {entry_count} entries processed…', flush=True)

    write_json(
        os.path.join(output_dir, 'metadata.json'),
        {'entities': entities},
    )
    print(f'Done: {entry_count} entries written to {output_dir}', flush=True)


HELP = (
    'usage: jmnedict-to-git.py '
    '-o <gitnedict directory> [--cache <cache directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/jmnedict')
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
