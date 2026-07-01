#!/usr/bin/env python3
"""Build per-language Tatoeba SQLite databases from a gitoeba JSON repository.

Stage 2 of the Tatoeba pipeline. Reads sentence JSON files written by
tatoeba-to-git.py, resolves JMdict seq numbers via jmdict.db (FTS5 index),
and writes one {lang}.db per language with an ExamplesSummary view compatible
with SumatoraDictionary.

Database schema per language:

    ExamplePairs(seq, sentence_id, sentence, translation)
      seq          — JMdict sequence number (from DictionaryEntry)
      sentence_id  — Tatoeba Japanese sentence ID
      sentence     — Japanese sentence text
      translation  — Translation text in this language

    ExamplesSummary (VIEW)
      seq          — JMdict sequence number
      sentences    — JSON array of Japanese sentence texts
      translations — JSON array of translations (parallel to sentences)

The ExamplesSummary view is what SumatoraDictionary joins against:
    LEFT JOIN examples_{lang}.ExamplesSummary ON DictionaryEntry.seq = ExamplesSummary.seq

Note on language codes: gitoeba uses ISO 639-3 codes as provided by Tatoeba
(e.g. deu, fra, nld) which differ from the JMdict codes used in the translation
databases (ger, fre, dut). Map these as needed when registering the dictionary
in the app.

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
# Kana normalisation (hiragana → katakana for FTS5 kana column lookups)
# ---------------------------------------------------------------------------

def hira_to_kata(s):
    return ''.join(
        chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# JMdict seq resolver
# ---------------------------------------------------------------------------

class TokenResolver:
    """Resolves (writing, reading) B-line tokens to JMdict seq numbers via FTS5.

    Results are cached to avoid redundant queries — jpn_indices reuses the
    same vocabulary across many sentences.
    """

    def __init__(self, jmdict_path):
        self._conn = sqlite3.connect(f'file:{jmdict_path}?mode=ro', uri=True)
        self._cur = self._conn.cursor()
        self._cache = {}

    def resolve(self, writing, reading):
        """Return list of JMdict seq numbers for (writing, reading)."""
        key = (writing, reading)
        if key in self._cache:
            return self._cache[key]
        try:
            if reading is None:
                self._cur.execute(
                    'SELECT rowid FROM DictionaryIndex WHERE writingsPrio MATCH ? '
                    'UNION '
                    'SELECT rowid FROM DictionaryIndex WHERE writings MATCH ?',
                    (writing, writing),
                )
            else:
                kata = hira_to_kata(reading)
                self._cur.execute(
                    'SELECT rowid FROM ('
                    '    SELECT rowid FROM DictionaryIndex WHERE writingsPrio MATCH ?'
                    '    UNION'
                    '    SELECT rowid FROM DictionaryIndex WHERE writings MATCH ?'
                    ') INTERSECT SELECT rowid FROM ('
                    '    SELECT rowid FROM DictionaryIndex WHERE readingsPrioKana MATCH ?'
                    '    UNION'
                    '    SELECT rowid FROM DictionaryIndex WHERE readingsKana MATCH ?'
                    ')',
                    (writing, writing, kata, kata),
                )
            seqs = [row[0] for row in self._cur.fetchall()]
        except Exception:
            seqs = []
        self._cache[key] = seqs
        return seqs

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Per-language database builder
# ---------------------------------------------------------------------------

_CREATE_TABLE = '''\
CREATE TABLE ExamplePairs (
    seq         INTEGER,
    sentence_id INTEGER,
    sentence    TEXT,
    translation TEXT,
    PRIMARY KEY (seq, sentence_id)
)'''

_CREATE_VIEW = '''\
CREATE VIEW ExamplesSummary AS
    SELECT seq,
           json_group_array(sentence)    AS sentences,
           json_group_array(translation) AS translations
    FROM ExamplePairs
    GROUP BY seq'''


def _open_lang_db(lang, output_dir):
    path = os.path.join(output_dir, f'{lang}.db')
    conn = sqlite3.connect(path, isolation_level=None)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=DELETE')
    c.execute('DROP VIEW IF EXISTS ExamplesSummary')
    c.execute('DROP TABLE IF EXISTS ExamplePairs')
    c.execute(_CREATE_TABLE)
    c.execute(_CREATE_VIEW)
    c.execute('BEGIN TRANSACTION')
    return conn, c


def _finish_lang_db(conn, cur):
    cur.execute('COMMIT')
    conn.execute('VACUUM')
    conn.close()


# ---------------------------------------------------------------------------
# JSON file iteration
# ---------------------------------------------------------------------------

def iter_json_files(directory):
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            if name.endswith('.json'):
                yield os.path.join(root, name)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def process(gitoeba_dir, jmdict_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    resolver = TokenResolver(jmdict_path)

    # lang → (conn, cur, row_count)
    lang_dbs = {}

    sentences_dir = os.path.join(gitoeba_dir, 'sentences')
    sent_count = 0
    ambiguous = 0

    for path in iter_json_files(sentences_dir):
        with open(path, encoding='utf-8') as f:
            sent = json.load(f)

        translations = sent.get('translations', {})
        if not translations:
            continue

        # Resolve all verified tokens → JMdict seq numbers
        seqs = set()
        for tok in sent.get('indices', []):
            resolved = resolver.resolve(tok['writing'], tok.get('reading'))
            if len(resolved) > 1:
                ambiguous += 1
            seqs.update(resolved)

        if not seqs:
            continue

        sentence_id = sent['id']
        jpn_text = sent['text']

        for lang, translation in translations.items():
            if lang not in lang_dbs:
                conn, cur = _open_lang_db(lang, output_dir)
                lang_dbs[lang] = (conn, cur, 0)
            conn, cur, n = lang_dbs[lang]
            for seq in seqs:
                cur.execute(
                    'INSERT OR IGNORE INTO ExamplePairs '
                    '(seq, sentence_id, sentence, translation) VALUES (?, ?, ?, ?)',
                    (seq, sentence_id, jpn_text, translation),
                )
            lang_dbs[lang] = (conn, cur, n + 1)

        sent_count += 1
        if sent_count % 10000 == 0:
            print(f'  {sent_count} sentences processed…', flush=True)

    resolver.close()

    print(f'Processed {sent_count} sentences → {len(lang_dbs)} language databases')
    if ambiguous:
        print(
            f'  Warning: {ambiguous} token resolutions were ambiguous '
            f'(more than one JMdict entry matched)',
            file=sys.stderr,
        )

    for lang, (conn, cur, n) in sorted(lang_dbs.items()):
        _finish_lang_db(conn, cur)
        print(f'  {lang}.db  ({n} sentences)', flush=True)

    print('Done.', flush=True)


HELP = (
    'usage: gitoeba-to-sqlite.py '
    '-i <gitoeba directory> -j <jmdict.db> -o <output directory>'
)


def main(argv):
    gitoeba_dir = ''
    jmdict_path = ''
    output_dir = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:j:o:', ['idir=', 'jmdict=', 'odir='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            gitoeba_dir = arg
        elif opt in ('-j', '--jmdict'):
            jmdict_path = arg
        elif opt in ('-o', '--odir'):
            output_dir = arg
    if not gitoeba_dir or not jmdict_path or not output_dir:
        print(HELP)
        sys.exit(2)
    process(gitoeba_dir, jmdict_path, output_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
