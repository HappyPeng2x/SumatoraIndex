#!/usr/bin/env python3
"""Download Tatoeba exports and write a gitoeba JSON git repository.

Stage 1 of the Tatoeba pipeline. Downloads and processes:
  - per_language/jpn/jpn_sentences.tsv.bz2      (Japanese sentence texts)
  - jpn_indices.tar.bz2                           (B-line JMdict annotations)
  - per_language/jpn/jpn-{lang}_links.tsv.bz2    (links to translations per language)
  - per_language/{lang}/{lang}_sentences.tsv.bz2  (translation sentence texts)

Writes one JSON file per Japanese sentence with verified JMdict annotations
to <gitoeba>/sentences/{shard}/{id}.json. Only sentences with at least one
verified token AND at least one translation in any language are written.

Downloaded files are cached in the cache directory; delete the cache to
force a full re-download.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import bz2
import getopt
import json
import os
import re
import sys
import tarfile
import urllib.request

BASE_URL = 'https://downloads.tatoeba.org/exports'
SHARD_SIZE = 10000

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
# Skip per-language files smaller than this; they contain only a header or
# are effectively empty (the smallest real link file is ~47 bytes).
MIN_FILE_BYTES = 200

# B-line token regex — same semantics as sumatora-index-tatoeba.py.
# Each space-separated token in jpn_indices text has the form:
#   writing(reading)[index]{expression}~
# Only tokens with a trailing ~ are verified JMdict matches.
# The [index] field is a sequential counter, NOT a JMdict seq number.
TOKEN_RE = re.compile(
    r'(?P<writing>[^\(\)\[\]\{\}\s]+)'
    r'(\((?P<reading>[^\(\)\[\]\{\}\s]*)\))?'
    r'(\[[^\(\)\[\]\{\}\s]*\])?'
    r'(\{[^\(\)\[\]\{\}\s]*\})?'
    r'(?P<verified>~)?'
    r'\s?'
)


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download(url, dest):
    print(f'    Downloading {url} …', flush=True)
    urllib.request.urlretrieve(url, dest)


def ensure_cached(url, cache_dir):
    """Return local path to the cached file, downloading if absent."""
    name = url.split('/')[-1]
    path = os.path.join(cache_dir, name)
    if not os.path.exists(path):
        _download(url, path)
    return path


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_tsv_bz2(path, id_col=0, text_col=2):
    """Yield (int_id, text) from a bz2-compressed TSV file."""
    with bz2.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) > max(id_col, text_col):
                try:
                    yield int(parts[id_col]), parts[text_col]
                except ValueError:
                    pass


def load_sentences(path):
    """Load a bz2 TSV sentence file into {sentence_id: text}."""
    print(f'  Loading {os.path.basename(path)} …', flush=True)
    return {sid: text for sid, text in parse_tsv_bz2(path)}


def load_links(path, known_ids):
    """Load a bz2 TSV link file into {jpn_id: first_trans_id}.

    Rows where col[0] is not in known_ids are ignored (the file may contain
    links in both directions; we only want Japanese→target).
    Only the first translation ID seen for each Japanese sentence is kept.
    """
    result = {}
    with bz2.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2:
                continue
            try:
                src = int(parts[0])
                dst = int(parts[1])
            except ValueError:
                continue
            if src in known_ids and src not in result:
                result[src] = dst
    return result


def parse_jpn_indices(cache_dir):
    """Download and parse jpn_indices → {sentence_id: [(writing, reading)]}.

    Only verified (~) tokens are included. Duplicate tokens per sentence are
    removed. Returns only sentences that have at least one verified token.
    """
    url = f'{BASE_URL}/jpn_indices.tar.bz2'
    local = ensure_cached(url, cache_dir)
    print('  Parsing jpn_indices …', flush=True)

    result = {}
    with tarfile.open(local, 'r:bz2') as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith('.csv'))
        for raw in tf.extractfile(member):
            line = raw.decode('utf-8').rstrip('\n')
            parts = line.split('\t')
            if len(parts) < 3:
                continue
            try:
                sentence_id = int(parts[0])
            except ValueError:
                continue
            tokens = []
            seen = set()
            for m in TOKEN_RE.finditer(parts[2]):
                if m['verified'] == '~' and m['writing']:
                    tok = (m['writing'], m['reading'] or None)
                    if tok not in seen:
                        seen.add(tok)
                        tokens.append(tok)
            if tokens:
                if sentence_id not in result:
                    result[sentence_id] = tokens
                else:
                    # merge tokens from multiple B-lines for the same sentence
                    existing = set(result[sentence_id])
                    result[sentence_id].extend(
                        t for t in tokens if t not in existing
                    )
    return result


def list_available_langs(cache_dir):
    """Return sorted list of 3-letter lang codes from the jpn/ index page."""
    url = f'{BASE_URL}/per_language/jpn/'
    local = os.path.join(cache_dir, '_jpn_dir.html')
    if not os.path.exists(local):
        _download(url, local)
    with open(local, encoding='utf-8', errors='replace') as f:
        content = f.read()
    return sorted(set(re.findall(r'href="jpn-([a-z]{3})_links\.tsv\.bz2"', content)))


def process_lang(lang, cache_dir, indexed_ids):
    """Download links + translations for lang. Returns {jpn_id: trans_text}."""
    link_url = f'{BASE_URL}/per_language/jpn/jpn-{lang}_links.tsv.bz2'
    link_path = ensure_cached(link_url, cache_dir)
    if os.path.getsize(link_path) < MIN_FILE_BYTES:
        return {}

    sent_url = f'{BASE_URL}/per_language/{lang}/{lang}_sentences.tsv.bz2'
    try:
        sent_path = ensure_cached(sent_url, cache_dir)
    except Exception as e:
        print(f'    Warning: {lang} sentences unavailable: {e}', file=sys.stderr)
        return {}
    if os.path.getsize(sent_path) < MIN_FILE_BYTES:
        return {}

    links = load_links(link_path, indexed_ids)
    if not links:
        return {}

    needed = set(links.values())
    lang_sents = {
        sid: text
        for sid, text in parse_tsv_bz2(sent_path)
        if sid in needed
    }

    return {
        jpn_id: lang_sents[trans_id]
        for jpn_id, trans_id in links.items()
        if trans_id in lang_sents
    }


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
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Japanese sentences
    jpn_sent_path = ensure_cached(
        f'{BASE_URL}/per_language/jpn/jpn_sentences.tsv.bz2', cache_dir
    )
    jpn_sentences = load_sentences(jpn_sent_path)
    print(f'  {len(jpn_sentences)} Japanese sentences loaded', flush=True)

    # Step 2: B-line annotations (verified JMdict token links)
    jpn_indices = parse_jpn_indices(cache_dir)
    print(f'  {len(jpn_indices)} sentences with verified annotations', flush=True)
    indexed_ids = set(jpn_indices.keys())

    # Step 3: Per-language translations
    langs = list_available_langs(cache_dir)
    print(f'  {len(langs)} language link files found', flush=True)

    # translations[jpn_id][jm_lang] = translation_text (first found per lang)
    translations = {}
    for i, tatoeba_lang in enumerate(langs, 1):
        lang_trans = process_lang(tatoeba_lang, cache_dir, indexed_ids)
        n = len(lang_trans)
        jm_lang = _LANG_MAP.get(tatoeba_lang, tatoeba_lang)
        if n:
            for jpn_id, text in lang_trans.items():
                if jpn_id not in translations:
                    translations[jpn_id] = {}
                translations[jpn_id][jm_lang] = text
        label = f'{tatoeba_lang}→{jm_lang}' if jm_lang != tatoeba_lang else tatoeba_lang
        print(f'  [{i:3d}/{len(langs)}] {label}: {n} links', flush=True)

    # Step 4: Write sentence JSON files
    written = skipped = 0
    for jpn_id, tokens in jpn_indices.items():
        text = jpn_sentences.get(jpn_id)
        trans = translations.get(jpn_id)
        if not text or not trans:
            skipped += 1
            continue

        shard = jpn_id // SHARD_SIZE
        data = {
            'id': jpn_id,
            'text': text,
            'indices': [
                {'writing': w, 'reading': r} if r else {'writing': w}
                for w, r in tokens
            ],
            'translations': trans,
        }
        write_json(
            os.path.join(output_dir, 'sentences', str(shard), f'{jpn_id}.json'),
            data,
        )
        written += 1
        if written % 10000 == 0:
            print(f'  {written} sentences written…', flush=True)

    active_langs = sorted({
        lang
        for trans in translations.values()
        for lang in trans
    })
    write_json(
        os.path.join(output_dir, 'metadata.json'),
        {'langs': active_langs},
    )

    print(
        f'Done: {written} sentences written, {skipped} skipped '
        f'({len(active_langs)} languages)',
        flush=True,
    )


HELP = (
    'usage: tatoeba-to-git.py '
    '-o <gitoeba directory> [--cache <cache directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/tatoeba')
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
