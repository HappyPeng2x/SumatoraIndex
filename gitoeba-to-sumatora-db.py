#!/usr/bin/env python3
"""Build schema-v2 Tatoeba example rows in sumatora.db from a gitoeba JSON repo."""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import json
import os
import sys
from collections import defaultdict

import sumatora_schema
from sumatora_common import iter_json_files

_KANA_COL = 20

# Cap on how many example sentences one entry keeps per language pack, after
# ranking by _sentence_quality. Shorter, simpler sentences make better
# dictionary examples than long ones; this is a deterministic stand-in for
# Jitendex's curated per-sense cap of 3 (Sumatora links examples at the entry
# level, which can span several senses, hence the more generous default).
_MAX_EXAMPLES_PER_ENTRY = 8


def _sentence_quality(sentence_text):
    """Lower is better: shorter Japanese sentences read as simpler, more
    legible dictionary examples than long ones."""
    return len(sentence_text)


def _kata_to_hira(s):
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c for c in s)


def _has_kanji(s):
    return any('一' <= c <= '鿿' or '㐀' <= c <= '䶿' for c in s)


def _reading_of(word):
    feature = word.feature
    if len(feature) <= _KANA_COL:
        return None
    kana = feature[_KANA_COL]
    if not kana or kana == '*':
        return None
    return _kata_to_hira(kana)


class MecabTokenizer:
    def __init__(self, dicdir):
        import fugashi
        self._tagger = fugashi.GenericTagger(f'-d {dicdir} -r /dev/null')

    def tokenize(self, text):
        tokens = []
        for word in self._tagger(text):
            token = {'writing': word.surface}
            reading = _reading_of(word)
            if reading:
                token['reading'] = reading
            tokens.append(token)
        return tokens


def _sentence_segments(text, tokens):
    remaining = text
    segments = []
    for token in tokens:
        reading = token.get('reading')
        expression = token.get('expression') or token['writing']
        if not reading or not _has_kanji(expression):
            continue
        idx = remaining.find(expression)
        if idx == -1:
            continue
        if idx:
            segments.append((remaining[:idx], None))
        segments.append((expression, reading))
        remaining = remaining[idx + len(expression):]
    if remaining:
        segments.append((remaining, None))
    if not segments:
        return [(text, None)]
    return segments


class TokenResolver:
    def __init__(self, conn):
        self._conn = conn
        self._cache = {}
        self._jmdict_source_id = sumatora_schema.source_id(conn, 'jmdict')

    def resolve(self, writing, reading, source_entry_id=None):
        key = (writing, reading, source_entry_id)
        if key in self._cache:
            return self._cache[key]

        if source_entry_id is not None:
            rows = self._conn.execute(
                "SELECT e.entry_id, f.form_id FROM Entry e "
                "LEFT JOIN EntryForm f ON f.entry_id = e.entry_id AND f.text = ? "
                "WHERE e.source_id = ? AND e.source_key = ? AND e.entry_type = 'word'",
                (writing, self._jmdict_source_id, str(source_entry_id)),
            ).fetchall()
        elif reading:
            rows = self._conn.execute(
                "SELECT f.entry_id, f.form_id FROM EntryForm f "
                "JOIN Entry e ON e.entry_id = f.entry_id "
                "WHERE e.entry_type = 'word' AND f.form_type = 'writing' "
                "AND f.text = ? AND f.reading = ?",
                (writing, reading),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT f.entry_id, f.form_id FROM EntryForm f "
                "JOIN Entry e ON e.entry_id = f.entry_id "
                "WHERE e.entry_type = 'word' AND f.text = ?",
                (writing,),
            ).fetchall()

        self._cache[key] = rows
        return rows


def _sense_id(conn, entry_id, sense_number):
    if sense_number is None:
        return None
    row = conn.execute(
        'SELECT sense_id FROM Sense WHERE entry_id = ? AND display_number = ?',
        (entry_id, sense_number),
    ).fetchone()
    return row[0] if row else None


def _insert_example(conn, source_id, sentence_id, lang, translation, segments):
    conn.execute(
        'INSERT OR IGNORE INTO Example (source_id, source_key, lang, translation) '
        'VALUES (?, ?, ?, ?)',
        (source_id, str(sentence_id), lang, translation),
    )
    example_id = conn.execute(
        'SELECT example_id FROM Example WHERE source_id = ? AND source_key = ? AND lang = ?',
        (source_id, str(sentence_id), lang),
    ).fetchone()[0]
    if not conn.execute(
        'SELECT 1 FROM ExampleSegment WHERE example_id = ? LIMIT 1',
        (example_id,),
    ).fetchone():
        conn.executemany(
            'INSERT INTO ExampleSegment (example_id, ord, base, ruby) VALUES (?, ?, ?, ?)',
            [(example_id, i, base, ruby) for i, (base, ruby) in enumerate(segments)],
        )
    return example_id


def process(gitoeba_dir, unidic_dir, db_path):
    conn = sumatora_schema.open_or_init_db(db_path)
    source_id = sumatora_schema.source_id(conn, 'tatoeba')
    resolver = TokenResolver(conn)
    tokenizer = MecabTokenizer(unidic_dir)

    sentences_dir = os.path.join(gitoeba_dir, 'sentences')
    translations_dir = os.path.join(gitoeba_dir, 'translations')

    print('Loading sentences...', flush=True)
    sentences = {}
    for path in iter_json_files(sentences_dir):
        with open(path, encoding='utf-8') as f:
            sentence = json.load(f)
        sentences[sentence['id']] = sentence
    print(f'  {len(sentences)} sentences loaded', flush=True)

    print('Resolving tokens and segmenting Japanese text...', flush=True)
    entry_cache = {}
    segment_cache = {}
    for sent_id, sentence in sentences.items():
        entry_links = {}
        for token in sentence.get('indices', []):
            matched_text = token.get('expression') or token['writing']
            for entry_id, form_id in resolver.resolve(
                token['writing'], token.get('reading'), token.get('entryId'),
            ):
                sense_id = _sense_id(conn, entry_id, token.get('senseNumber'))
                entry_links.setdefault(entry_id, (form_id, matched_text, sense_id))
        if entry_links:
            entry_cache[sent_id] = entry_links
            segment_cache[sent_id] = _sentence_segments(
                sentence['text'], tokenizer.tokenize(sentence['text']),
            )
    print(f'  {len(entry_cache)} sentences have v2 entry links', flush=True)

    lang_dirs = sorted(
        d for d in os.listdir(translations_dir)
        if os.path.isdir(os.path.join(translations_dir, d))
    ) if os.path.isdir(translations_dir) else []

    example_count = link_count = 0
    for lang in lang_dirs:
        lang_dir = os.path.join(translations_dir, lang)

        # Collect every candidate (sentence, translation) for this language
        # before writing anything, so examples can be ranked and capped per
        # entry — EntryExample.ord then means "best example first" instead of
        # arbitrary file-iteration order, and entries with many Tatoeba
        # matches don't get an unbounded example list.
        translation_by_sent = {}
        for path in iter_json_files(lang_dir):
            with open(path, encoding='utf-8') as f:
                translation = json.load(f)
            sent_id = translation['id']
            if sent_id not in entry_cache:
                continue
            translation_by_sent[sent_id] = translation['translation']

        by_entry = defaultdict(list)  # entry_id -> [(quality, sent_id, form_id, matched_text, sense_id), ...]
        for sent_id in translation_by_sent:
            quality = _sentence_quality(sentences[sent_id]['text'])
            for entry_id, (form_id, matched_text, sense_id) in entry_cache[sent_id].items():
                by_entry[entry_id].append((quality, sent_id, form_id, matched_text, sense_id))

        kept_sent_ids = set()
        ranked_by_entry = {}
        for entry_id, candidates in by_entry.items():
            candidates.sort(key=lambda c: c[0])
            top = candidates[:_MAX_EXAMPLES_PER_ENTRY]
            ranked_by_entry[entry_id] = top
            kept_sent_ids.update(sent_id for _quality, sent_id, *_rest in top)

        example_id_by_sent = {}
        lang_examples = 0
        for sent_id in kept_sent_ids:
            example_id_by_sent[sent_id] = _insert_example(
                conn,
                source_id,
                sent_id,
                lang,
                translation_by_sent[sent_id],
                segment_cache[sent_id],
            )
            lang_examples += 1
        example_count += lang_examples

        for entry_id, ranked in ranked_by_entry.items():
            for ord_, (_quality, sent_id, form_id, matched_text, sense_id) in enumerate(ranked):
                conn.execute(
                    'INSERT OR IGNORE INTO EntryExample '
                    '(entry_id, example_id, ord, matched_text, sense_id) VALUES (?, ?, ?, ?, ?)',
                    (entry_id, example_id_by_sent[sent_id], ord_, matched_text, sense_id),
                )
                link_count += 1
        print(f'  {lang}: {lang_examples} examples, <= {_MAX_EXAMPLES_PER_ENTRY} per entry', flush=True)

    sumatora_schema.set_build_metadata(
        conn,
        tatoeba_example_count=str(example_count),
        tatoeba_entry_link_count=str(link_count),
    )
    conn.commit()
    conn.close()
    print(f'Done: {example_count} examples, {link_count} entry links -> {db_path}', flush=True)


HELP = 'usage: gitoeba-to-sumatora-db.py -i <gitoeba directory> -u <unidic dicdir> -d <sumatora.db path>'


def main(argv):
    gitoeba_dir = ''
    unidic_dir = ''
    db_path = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:u:d:', ['idir=', 'unidic=', 'db='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            gitoeba_dir = arg
        elif opt in ('-u', '--unidic'):
            unidic_dir = arg
        elif opt in ('-d', '--db'):
            db_path = arg
    if not gitoeba_dir or not unidic_dir or not db_path:
        print(HELP)
        sys.exit(2)
    process(gitoeba_dir, unidic_dir, db_path)


if __name__ == '__main__':
    main(sys.argv[1:])
