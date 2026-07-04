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

# ISO 639-3 (Tatoeba) → ISO 639-2/B (JMdict bibliographic codes).
# Only languages where the two standards differ are listed; others pass through.
_LANG_MAP = {
    'sqi': 'alb',  # Albanian
    'hye': 'arm',  # Armenian
    'eus': 'baq',  # Basque
    'mya': 'bur',  # Burmese
    'zho': 'chi',  # Chinese
    'ces': 'cze',  # Czech
    'cym': 'wel',  # Welsh
    'deu': 'ger',  # German
    'ell': 'gre',  # Modern Greek
    'fas': 'per',  # Persian
    'fra': 'fre',  # French
    'isl': 'ice',  # Icelandic
    'kat': 'geo',  # Georgian
    'mkd': 'mac',  # Macedonian
    'msa': 'may',  # Malay
    'nld': 'dut',  # Dutch
    'ron': 'rum',  # Romanian
    'slk': 'slo',  # Slovak
    'bod': 'tib',  # Tibetan
}


# ---------------------------------------------------------------------------
# Kana normalisation (hiragana → katakana for FTS5 kana column lookups)
# ---------------------------------------------------------------------------

def hira_to_kata(s):
    return ''.join(
        chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# Furigana markup
# ---------------------------------------------------------------------------

def _has_kanji(s):
    return any('一' <= c <= '鿿' or '㐀' <= c <= '䶿' for c in s)


def markup_sentence(text, indices):
    """Return text with {expression;reading} furigana spans inserted.

    Only tokens whose expression contains at least one kanji are marked —
    pure-kana expressions need no furigana. Tokens are applied left-to-right;
    if an expression is not found in the remaining text it is silently skipped.
    """
    remaining = text
    parts = []
    for tok in indices:
        reading = tok.get('reading')
        if not reading:
            continue
        expression = tok.get('expression') or tok['writing']
        if not _has_kanji(expression):
            continue
        idx = remaining.find(expression)
        if idx == -1:
            continue
        parts.append(remaining[:idx])
        parts.append(f'{{{expression};{reading}}}')
        remaining = remaining[idx + len(expression):]
    parts.append(remaining)
    return ''.join(parts)


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
    seq           INTEGER,
    sentence_id   INTEGER,
    sentence      TEXT,
    translation   TEXT,
    matched_token TEXT,
    PRIMARY KEY (seq, sentence_id)
)'''

_CREATE_VIEW = '''\
CREATE VIEW ExamplesSummary AS
    SELECT seq,
           json_group_array(sentence)      AS sentences,
           json_group_array(translation)   AS translations,
           json_group_array(matched_token) AS matched_tokens
    FROM ExamplePairs
    GROUP BY seq'''


def _open_lang_db(lang, output_dir):
    path = os.path.join(output_dir, f'examples_{lang}.db')
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

    sentences_dir = os.path.join(gitoeba_dir, 'sentences')
    translations_dir = os.path.join(gitoeba_dir, 'translations')

    # Load all sentences into memory: id → (text, indices)
    print('Loading sentences…', flush=True)
    sentences = {}
    for path in iter_json_files(sentences_dir):
        with open(path, encoding='utf-8') as f:
            sent = json.load(f)
        sentences[sent['id']] = (sent['text'], sent.get('indices', []))
    print(f'  {len(sentences)} sentences loaded', flush=True)

    # Precompute seq→token maps and furigana-marked sentence text per sentence
    print('Resolving tokens…', flush=True)
    seq_cache = {}     # sentence_id → {seq: matched_token surface form}
    marked_cache = {}  # sentence_id → furigana-marked sentence text
    ambiguous = 0
    for sent_id, (text, indices) in sentences.items():
        seq_to_token = {}
        for tok in indices:
            resolved = resolver.resolve(tok['writing'], tok.get('reading'))
            if len(resolved) > 1:
                ambiguous += 1
            # Surface form as it appears in the sentence (inflected form when
            # expression is set; otherwise the dictionary writing form).
            surface = tok.get('expression') or tok['writing']
            for seq in resolved:
                if seq not in seq_to_token:  # first-match wins per sentence
                    seq_to_token[seq] = surface
        if seq_to_token:
            seq_cache[sent_id] = seq_to_token
            marked_cache[sent_id] = markup_sentence(text, indices)
    resolver.close()
    print(f'  {len(seq_cache)} sentences have at least one resolved token', flush=True)
    if ambiguous:
        print(
            f'  Warning: {ambiguous} token resolutions were ambiguous '
            f'(more than one JMdict entry matched)',
            file=sys.stderr,
        )

    # Process each language directory
    lang_dirs = sorted(
        d for d in os.listdir(translations_dir)
        if os.path.isdir(os.path.join(translations_dir, d))
    ) if os.path.isdir(translations_dir) else []

    total_langs = 0
    for lang in lang_dirs:
        lang_dir = os.path.join(translations_dir, lang)
        conn, cur = _open_lang_db(lang, output_dir)
        n = 0
        for path in iter_json_files(lang_dir):
            with open(path, encoding='utf-8') as f:
                t = json.load(f)
            sent_id = t['id']
            seq_to_token = seq_cache.get(sent_id)
            if not seq_to_token:
                continue
            jpn_text = marked_cache[sent_id]
            translation = t['translation']
            for seq, matched_token in seq_to_token.items():
                cur.execute(
                    'INSERT OR IGNORE INTO ExamplePairs '
                    '(seq, sentence_id, sentence, translation, matched_token) '
                    'VALUES (?, ?, ?, ?, ?)',
                    (seq, sent_id, jpn_text, translation, matched_token),
                )
            n += 1
        _finish_lang_db(conn, cur)
        print(f'  examples_{lang}.db  ({n} sentences)', flush=True)
        total_langs += 1

    print(f'Done: {total_langs} language databases.', flush=True)


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
