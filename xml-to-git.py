#!/usr/bin/env python3
"""Parse JMdict XML into a git repo with one JSON file per entry and language.

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

from lxml import etree

NS_XML = '{http://www.w3.org/XML/1998/namespace}'
ENTITY_RE = re.compile(r'<!ENTITY\s+([\w\-\.]+)\s+"([^"]+)"')
SHARD_SIZE = 10000


def extract_entities(path):
    """Read just the DOCTYPE block and extract entity name→description pairs."""
    with open(path, 'r', encoding='utf-8') as f:
        header = f.read(30000)
    end = header.find(']>')
    if end == -1:
        end = len(header)
    return {m.group(1): m.group(2) for m in ENTITY_RE.finditer(header[:end + 2])}


def shard(seq):
    return seq // SHARD_SIZE


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')


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

    # Group senses by language. Language is determined by the xml:lang
    # attribute on the first <pos> or <gloss> child of each <sense>.
    lang_glosses = {}   # lang -> [[gloss, ...], ...]  (list of senses)
    lang_order = []
    eng_senses = []     # structural metadata, English senses only

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


def process(input_file, output_dir):
    entities = extract_entities(input_file)
    print(f'Extracted {len(entities)} entity declarations', flush=True)

    entry_count = 0

    with open(input_file, 'rb') as f:
        for event, elem in etree.iterparse(
            f, tag='entry',
            load_dtd=True, resolve_entities=False, no_network=True,
        ):
            seq, kanji, kana, eng_senses, lang_glosses = parse_entry(elem)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            sh = shard(seq)

            entry_data = {
                'seq': seq,
                'kanji': kanji,
                'kana': kana,
                'senses': eng_senses,
            }
            write_json(
                os.path.join(output_dir, 'entries', str(sh), f'{seq}.json'),
                entry_data,
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


HELP = 'usage: xml-to-git.py -i <JMdict input file> -o <output git directory>'


def main(argv):
    input_file = ''
    output_dir = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:o:', ['ifile=', 'odir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--ifile'):
            input_file = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not input_file or not output_dir:
        print(HELP)
        sys.exit(2)
    process(input_file, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
