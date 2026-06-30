#!/usr/bin/env python3
"""Build Sumatora SQLite databases from a gitmdict JSON repository.

Reads JSON files produced by xml-to-git.py and writes the same SQLite
databases that sumatora-index.py used to produce in a single pass.

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
import sqlite3
import sys


# ---------------------------------------------------------------------------
# Kana normalisation (replaces romkan)
# Hiragana U+3041–U+3096 → Katakana U+30A1–U+30F6 via fixed offset +0x60
# ---------------------------------------------------------------------------

def hira_to_kata(s):
    return ''.join(
        chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c
        for c in s
    )


def calculate_parts_element(s, include_self=False):
    start = 0 if include_self else 1
    return {s[i:] for i in range(start, len(s))}


def calculate_parts(space_separated):
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(word)
    return ' '.join(parts)


def calculate_parts_kana(space_separated):
    kata = hira_to_kata(space_separated)
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(kata)
    return ' '.join(parts)


def to_kana(space_separated):
    return hira_to_kata(space_separated)


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

class SumatoraDB:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

        self._jmconn = sqlite3.connect(
            os.path.join(folder, 'jmdict.db'), isolation_level=None,
        )
        self._jmcur = self._jmconn.cursor()
        self._jmcur.execute('PRAGMA journal_mode=WAL')
        self._jmcur.execute('BEGIN TRANSACTION')

        self._trans = {}   # lang -> (conn, cur)

    # -- jmdict.db ----------------------------------------------------------

    def create_jmdict_tables(self):
        c = self._jmcur
        for t in ('DictionaryEntry', 'DictionaryControl',
                  'DictionaryIndex', 'DictionaryEntity'):
            c.execute(f'DROP TABLE IF EXISTS {t}')

        c.execute(
            'CREATE TABLE DictionaryEntry ('
            'seq INTEGER, readingsPrio TEXT, readings TEXT, '
            'writingsPrio TEXT, writings TEXT, pos TEXT, xref TEXT, '
            'ant TEXT, misc TEXT, lsource TEXT, dial TEXT, s_inf TEXT, '
            'field TEXT, PRIMARY KEY (seq))'
        )
        c.execute(
            'CREATE TABLE DictionaryControl '
            '(control TEXT NOT NULL, value INTEGER, PRIMARY KEY (control))'
        )
        c.execute(
            'CREATE VIRTUAL TABLE DictionaryIndex '
            'USING fts4(content="", '
            'readingsPrioKana, readingsPrioKanaParts, '
            'readingsKana, readingsKanaParts, '
            'writingsPrio, writingsPrioParts, '
            'writings, writingsParts)'
        )
        c.execute(
            'CREATE TABLE DictionaryEntity '
            '(name TEXT NOT NULL, content TEXT, PRIMARY KEY (name))'
        )

    def insert_entities(self, entities):
        self._jmcur.executemany(
            'INSERT INTO DictionaryEntity (name, content) VALUES (?, ?)',
            entities.items(),
        )

    def insert_entry(self, seq, readings_prio, readings, writings_prio,
                     writings, pos, xref, ant, misc, lsource, dial, s_inf,
                     field):
        rp_kata = to_kana(readings_prio)
        r_kata = to_kana(readings)
        self._jmcur.execute(
            'INSERT INTO DictionaryIndex '
            '(docid, readingsPrioKana, readingsPrioKanaParts, '
            'readingsKana, readingsKanaParts, '
            'writingsPrio, writingsPrioParts, writings, writingsParts) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (seq,
             rp_kata, calculate_parts_kana(readings_prio),
             r_kata, calculate_parts_kana(readings),
             writings_prio, calculate_parts(writings_prio),
             writings, calculate_parts(writings)),
        )
        self._jmcur.execute(
            'INSERT INTO DictionaryEntry '
            '(seq, readingsPrio, readings, writingsPrio, writings, '
            'pos, xref, ant, misc, lsource, dial, s_inf, field) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (seq, readings_prio, readings, writings_prio, writings,
             pos, xref, ant, misc, lsource, dial, s_inf, field),
        )

    # -- per-language translation DBs ----------------------------------------

    def _ensure_lang(self, lang):
        if lang in self._trans:
            return
        conn = sqlite3.connect(
            os.path.join(self.folder, f'{lang}.db'), isolation_level=None,
        )
        cur = conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('BEGIN TRANSACTION')
        cur.execute('DROP TABLE IF EXISTS DictionaryTranslation')
        cur.execute('DROP TABLE IF EXISTS DictionaryTranslationIndex')
        cur.execute(
            'CREATE TABLE DictionaryTranslation '
            '(seq INTEGER, gloss_id INTEGER, gloss_list_id INTEGER, '
            'gloss TEXT, PRIMARY KEY (seq, gloss_id))'
        )
        cur.execute(
            'CREATE VIRTUAL TABLE DictionaryTranslationIndex '
            'USING fts4(content="DictionaryTranslation", gloss)'
        )
        self._trans[lang] = (conn, cur)

    def insert_translation(self, lang, seq, glosses):
        self._ensure_lang(lang)
        _, cur = self._trans[lang]
        for i, sense_glosses in enumerate(glosses):
            cur.execute(
                'INSERT INTO DictionaryTranslation '
                '(seq, gloss_id, gloss) VALUES (?, ?, ?)',
                (seq, i, ', '.join(sense_glosses)),
            )

    # -- close ---------------------------------------------------------------

    def close(self):
        self._jmcur.execute('COMMIT')
        self._jmconn.close()

        for lang, (conn, cur) in self._trans.items():
            cur.execute(
                'INSERT INTO DictionaryTranslationIndex (docid, gloss) '
                'SELECT rowid, gloss FROM DictionaryTranslation'
            )
            cur.execute('COMMIT')
            conn.close()


# ---------------------------------------------------------------------------
# JSON field helpers
# ---------------------------------------------------------------------------

def _none_or_json(value):
    """Return JSON string only if value has at least one element, else None."""
    if not value:
        return None
    flat = value if not isinstance(value[0], list) else [x for sub in value for x in sub]
    if not flat:
        return None
    return json.dumps(value, ensure_ascii=False)


def _lsource_to_json(lsource_array):
    """Convert lsource sense arrays to the format used in the original DB.

    Original format: [[{"lang": "text"}, ...], ...]  (list of per-sense lists
    of single-key dicts, where key=lang and value=text).
    """
    if not lsource_array:
        return None
    converted = []
    for sense_sources in lsource_array:
        sense_list = [{ls['lang']: ls['text'] or ''} for ls in sense_sources]
        converted.append(sense_list)
    has_data = any(sl for sl in converted)
    if not has_data:
        return None
    return json.dumps(converted, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def build_readings_writings(entry):
    """Extract space-separated priority/non-priority reading and writing strings."""
    readings_prio_parts = []
    readings_parts = []
    for k in entry['kana']:
        if k['common']:
            readings_prio_parts.append(k['text'])
        else:
            readings_parts.append(k['text'])

    writings_prio_parts = []
    writings_parts = []
    for k in entry['kanji']:
        if k['common']:
            writings_prio_parts.append(k['text'])
        else:
            writings_parts.append(k['text'])

    return (
        ' '.join(readings_prio_parts),
        ' '.join(readings_parts),
        ' '.join(writings_prio_parts),
        ' '.join(writings_parts),
    )


def build_sense_fields(senses):
    """Aggregate per-sense structural fields into per-entry JSON arrays."""
    pos_arr, xref_arr, ant_arr, misc_arr = [], [], [], []
    lsrc_arr, dial_arr, sinf_arr, field_arr = [], [], [], []

    for s in senses:
        pos_arr.append(s.get('partOfSpeech', []))
        xref_arr.append(s.get('related', []))
        ant_arr.append(s.get('antonym', []))
        misc_arr.append(s.get('misc', []))
        lsrc_arr.append(s.get('languageSource', []))
        dial_arr.append(s.get('dialect', []))
        sinf_arr.append(s.get('info', []))
        field_arr.append(s.get('field', []))

    return (
        _none_or_json(pos_arr),
        _none_or_json(xref_arr),
        _none_or_json(ant_arr),
        _none_or_json(misc_arr),
        _lsource_to_json(lsrc_arr),
        _none_or_json(dial_arr),
        _none_or_json(sinf_arr),
        _none_or_json(field_arr),
    )


def iter_json_files(directory):
    """Yield (path,) for every .json file under directory, sorted."""
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            if name.endswith('.json'):
                yield os.path.join(root, name)


def process(git_dir, output_dir):
    metadata_path = os.path.join(git_dir, 'metadata.json')
    with open(metadata_path, encoding='utf-8') as f:
        metadata = json.load(f)

    db = SumatoraDB(output_dir)
    db.create_jmdict_tables()
    db.insert_entities(metadata.get('entities', {}))

    # -- entries -----------------------------------------------------------
    entries_dir = os.path.join(git_dir, 'entries')
    entry_count = 0
    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            entry = json.load(f)

        seq = entry['seq']
        rp, r, wp, w = build_readings_writings(entry)
        pos, xref, ant, misc, lsrc, dial, sinf, field = \
            build_sense_fields(entry.get('senses', []))

        db.insert_entry(seq, rp, r, wp, w, pos, xref, ant, misc,
                        lsrc, dial, sinf, field)
        entry_count += 1
        if entry_count % 10000 == 0:
            print(f'  {entry_count} entries inserted…', flush=True)

    print(f'Entries done: {entry_count}', flush=True)

    # -- translations -------------------------------------------------------
    trans_dir = os.path.join(git_dir, 'translations')
    trans_count = 0
    for path in iter_json_files(trans_dir):
        with open(path, encoding='utf-8') as f:
            t = json.load(f)
        db.insert_translation(t['lang'], t['seq'], t['glosses'])
        trans_count += 1
        if trans_count % 50000 == 0:
            print(f'  {trans_count} translation files inserted…', flush=True)

    print(f'Translations done: {trans_count}', flush=True)

    db.close()
    print(f'Databases written to {output_dir}', flush=True)


HELP = ('usage: git-to-sqlite.py '
        '-i <gitmdict directory> -o <output directory>')


def main(argv):
    git_dir = ''
    output_dir = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:o:', ['idir=', 'odir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            git_dir = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not git_dir or not output_dir:
        print(HELP)
        sys.exit(2)
    process(git_dir, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
