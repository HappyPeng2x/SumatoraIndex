#!/usr/bin/env python3
"""Download JMdict and write a gitmdict JSON git repository.

Downloads JMdict.gz from the EDRDG server, caches it locally, then parses
the XML into one JSON file per entry and per language, mirroring the layout
of the gitmdict repository.

Downloaded files are cached in the cache directory; delete the cache to
force a re-download.

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
import urllib.request

from lxml import etree

JMDICT_URL = 'http://ftp.edrdg.org/pub/Nihongo/JMdict.gz'
NS_XML = '{http://www.w3.org/XML/1998/namespace}'
ENTITY_RE = re.compile(r'<!ENTITY\s+([\w\-\.]+)\s+"([^"]+)"')
SHARD_SIZE = 10000


# ---------------------------------------------------------------------------
# Download helpers
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
# Gzip-transparent helpers
# ---------------------------------------------------------------------------

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


def get_entity_names(parent, tag):
    result = []
    for el in parent.findall(tag):
        for child in el:
            if isinstance(child, etree._Entity):
                result.append(child.name)
    return result


def get_texts(parent, tag):
    return [el.text for el in parent.findall(tag) if el.text]


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
        pris = [p.text for p in r.findall('re_pri') if p.text]
        infs = [c.name for e in r.findall('re_inf') for c in e
                if isinstance(c, etree._Entity)]
        restr = [e.text for e in r.findall('re_restr') if e.text]
        kana.append({
            'text': reb,
            'common': bool(pris),
            'tags': pris + infs,
            'appliesToKanji': restr if restr else ['*'],
        })

    lang_glosses = {}
    lang_order = []
    eng_senses = []

    for s in elem.findall('sense'):
        sense_lang = 'eng'
        for child in s:
            if child.tag in ('pos', 'gloss'):
                lang = child.get(f'{NS_XML}lang', 'eng')
                if lang:
                    sense_lang = lang
                break

        sense_glosses = [g.text for g in s.findall('gloss') if g.text]

        if sense_lang not in lang_glosses:
            lang_glosses[sense_lang] = []
            lang_order.append(sense_lang)
        lang_glosses[sense_lang].append(sense_glosses)

        if sense_lang == 'eng':
            lsources = []
            for ls in s.findall('lsource'):
                lsources.append({
                    'lang': ls.get(f'{NS_XML}lang', ''),
                    'text': ls.text,
                    'full': ls.get('ls_type', '') != 'part',
                    'wasei': ls.get('ls_wasei', 'n') == 'y',
                })
            eng_senses.append({
                'partOfSpeech': get_entity_names(s, 'pos'),
                'related': get_texts(s, 'xref'),
                'antonym': get_texts(s, 'ant'),
                'field': get_entity_names(s, 'field'),
                'dialect': get_entity_names(s, 'dial'),
                'misc': get_entity_names(s, 'misc'),
                'info': get_texts(s, 's_inf'),
                'languageSource': lsources,
            })

    return seq, kanji, kana, eng_senses, lang_glosses


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
    jmdict_path = ensure_cached(JMDICT_URL, cache_dir)
    print(f'  Using {jmdict_path}', flush=True)

    entities = extract_entities(jmdict_path)
    print(f'  {len(entities)} entity declarations extracted', flush=True)

    os.makedirs(output_dir, exist_ok=True)
    entry_count = 0

    with _open_binary(jmdict_path) as f:
        for event, elem in etree.iterparse(
            f, tag='entry',
            load_dtd=True, resolve_entities=False, no_network=True,
        ):
            seq, kanji, kana, eng_senses, lang_glosses = parse_entry(elem)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            sh = seq // SHARD_SIZE
            write_json(
                os.path.join(output_dir, 'entries', str(sh), f'{seq}.json'),
                {'seq': seq, 'kanji': kanji, 'kana': kana, 'senses': eng_senses},
            )
            for lang, glosses in lang_glosses.items():
                write_json(
                    os.path.join(output_dir, 'translations', lang,
                                 str(sh), f'{seq}.json'),
                    {'seq': seq, 'lang': lang, 'glosses': glosses},
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
    'usage: jmdict-to-git.py '
    '-o <gitmdict directory> [--cache <cache directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/jmdict')
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
