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
# Furigana computation (ignorant algorithm — no external dictionary)
# See Furigana.md for the algorithm description.
# ---------------------------------------------------------------------------

def _is_kanji(c):
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF or  # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or  # CJK Extension A
        0xF900 <= cp <= 0xFAFF or  # CJK Compatibility Ideographs
        0x20000 <= cp <= 0x2A6DF   # CJK Extension B
    )


def _kata_to_hira(s):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c
        for c in s
    )


# ---------------------------------------------------------------------------
# Kanjidic2 knowledge: reading variants for the informed furigana solver
# ---------------------------------------------------------------------------

# On'yomi endings that produce a sokuon (geminate っ) prefix form in compounds.
_SOKUON_FINALS = frozenset('くきちつ')

# Rendaku: initial mora voicing table (hiragana).
_RENDAKU = {
    'か': 'が', 'き': 'ぎ', 'く': 'ぐ', 'け': 'げ', 'こ': 'ご',
    'さ': 'ざ', 'し': 'じ', 'す': 'ず', 'せ': 'ぜ', 'そ': 'ぞ',
    'た': 'だ', 'ち': 'ぢ', 'つ': 'づ', 'て': 'で', 'と': 'ど',
    'は': 'ば', 'ひ': 'び', 'ふ': 'ぶ', 'へ': 'べ', 'ほ': 'ぼ',
}
# Small kana that can follow a mora (digraphs: しゃ, ちょ, etc.)
_SMALL_KANA = frozenset('ぁぃぅぇぉゃゅょ')


def _sokuon(hira):
    """Return sokuon prefix form (final mora → っ), or None if not applicable."""
    if hira and hira[-1] in _SOKUON_FINALS:
        return hira[:-1] + 'っ'
    return None


def _rendaku(hira):
    """Return rendaku (initial voicing) form, or None if not applicable."""
    if not hira:
        return None
    voiced = _RENDAKU.get(hira[0])
    if voiced is None:
        return None
    # Preserve a small-kana second character (digraph: しゃ → じゃ)
    if len(hira) >= 2 and hira[1] in _SMALL_KANA:
        return voiced + hira[1:]
    return voiced + hira[1:]


def _on_variants(hira):
    """Yield all valid surface forms for one on'yomi in hiragana."""
    yield hira
    sok = _sokuon(hira)
    if sok:
        yield sok
    rend = _rendaku(hira)
    if rend:
        yield rend
        sok_rend = _sokuon(rend)
        if sok_rend:
            yield sok_rend


def build_knowledge(gitjidic2_dir):
    """Build {char → frozenset of hiragana reading stems} from a gitjidic2 repo.

    For each character the set contains:
    - All on'yomi variants: base hiragana, sokuon form, rendaku form,
      rendaku-sokuon form.
    - Kun'yomi stem (text before the '.' okurigana separator), plus its
      rendaku variant.
    """
    knowledge = {}
    chars_dir = os.path.join(gitjidic2_dir, 'characters')
    if not os.path.isdir(chars_dir):
        raise FileNotFoundError(
            f'gitjidic2 characters directory not found: {chars_dir}\n'
            'Run kanjidic2-to-git.py first.'
        )
    for root, dirs, files in os.walk(chars_dir):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith('.json'):
                continue
            with open(os.path.join(root, name), encoding='utf-8') as fh:
                data = json.load(fh)
            char = data.get('char')
            if not char:
                continue
            variants = set()
            for on in data.get('on', []):
                for v in _on_variants(_kata_to_hira(on)):
                    variants.add(v)
            for kun in data.get('kun', []):
                stem = kun.split('.')[0]
                if stem:
                    variants.add(stem)
                    rend = _rendaku(stem)
                    if rend:
                        variants.add(rend)
            knowledge[char] = frozenset(variants)
    print(f'  Kanjidic2 knowledge loaded: {len(knowledge)} characters', flush=True)
    return knowledge


# ---------------------------------------------------------------------------
# Informed partition solver for consecutive kanji runs
# ---------------------------------------------------------------------------

def _partitions(s, k):
    """Yield all tuples of k non-empty strings whose concatenation equals s."""
    if k == 1:
        if s:
            yield (s,)
        return
    for i in range(1, len(s) - k + 2):
        for rest in _partitions(s[i:], k - 1):
            yield (s[:i],) + rest


def _split_kanji_run(run, reading, knowledge):
    """Try to assign one reading per character in run using knowledge.

    Returns a tuple of per-character readings when exactly one valid partition
    exists; returns None when the split is impossible or ambiguous.
    Only called for multi-character runs (len(run) >= 2).
    """
    n = len(run)
    valid = set()
    for parts in _partitions(reading, n):
        if all(parts[i] in knowledge.get(run[i], frozenset()) for i in range(n)):
            valid.add(parts)
    return next(iter(valid)) if len(valid) == 1 else None


def _parse_segments(text):
    """Split text into alternating (is_kanji_run, raw, normalised) tuples."""
    segments = []
    norm = _kata_to_hira(text)
    i = 0
    while i < len(text):
        if _is_kanji(text[i]):
            j = i + 1
            while j < len(text) and _is_kanji(text[j]):
                j += 1
            segments.append((True, text[i:j], norm[i:j]))
            i = j
        else:
            j = i + 1
            while j < len(text) and not _is_kanji(text[j]):
                j += 1
            segments.append((False, text[i:j], norm[i:j]))
            i = j
    return segments


def _solve_ignorant(kanji_form, reading_hira, knowledge=None):
    """Return list of (base, ruby_or_None) pairs, or None on failure.

    When knowledge is provided, consecutive kanji runs of two or more
    characters are split per character using _split_kanji_run; a block bracket
    is kept only when the partition is ambiguous or impossible.
    """
    segs = _parse_segments(kanji_form)
    parts = []
    pos = 0
    for idx, (kanji_run, raw, norm) in enumerate(segs):
        if not kanji_run:
            end = pos + len(norm)
            if _kata_to_hira(reading_hira[pos:end]) != norm:
                return None
            parts.append((raw, None))
            pos = end
        else:
            next_kana_norm = None
            for k in range(idx + 1, len(segs)):
                if not segs[k][0]:
                    next_kana_norm = segs[k][2]
                    break
            remaining = reading_hira[pos:]
            if next_kana_norm is None:
                kanji_reading = remaining
            else:
                anchor = remaining.find(next_kana_norm)
                if anchor < 0:
                    return None
                kanji_reading = remaining[:anchor]
            if not kanji_reading:
                return None
            # For multi-char runs, try per-character split with knowledge.
            if knowledge and len(raw) > 1:
                split = _split_kanji_run(raw, kanji_reading, knowledge)
                if split:
                    for char, r in zip(raw, split):
                        parts.append((char, r))
                    pos += len(kanji_reading)
                    continue
            parts.append((raw, kanji_reading))
            pos += len(kanji_reading)
    if pos != len(reading_hira):
        return None
    return parts


def compute_furigana(kanji_form, reading, knowledge=None):
    """Return bracket-notation furigana string, or None for pure-kana forms.

    Example: compute_furigana("食べ物", "たべもの") → "食[た]べ物[もの]"
    Without knowledge, consecutive kanji blocks fall back to a single bracket:
    東京湾[とうきょうわん].  With knowledge (from build_knowledge), per-character
    splitting is attempted: 東[とう]京[きょう]湾[わん].
    """
    if not any(_is_kanji(c) for c in kanji_form):
        return None
    reading_hira = _kata_to_hira(reading)
    parts = _solve_ignorant(kanji_form, reading_hira, knowledge)
    if parts is None:
        return f'{kanji_form}[{reading_hira}]'
    return ''.join(
        base if ruby is None else f'{base}[{ruby}]'
        for base, ruby in parts
    )


# ---------------------------------------------------------------------------
# Patch system (RFC 7396 JSON Merge Patch)
# ---------------------------------------------------------------------------

# Default patches directory: SumatoraIndex/patches/ next to this script.
# load_patches() silently returns {} when the directory does not exist.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PATCHES_DIR = os.path.join(_SCRIPT_DIR, 'patches')


def load_patches(patches_dir):
    """Return {seq: patch_dict} for all JSON files under patches_dir/entries/.

    Directory structure mirrors gitmdict/entries/{shard}/{seq}.json.
    Returns an empty dict when patches_dir or its entries/ subdirectory is absent.
    """
    patches = {}
    entries_dir = os.path.join(patches_dir, 'entries')
    if not os.path.isdir(entries_dir):
        return patches
    for root, dirs, files in os.walk(entries_dir):
        dirs.sort()
        for name in sorted(files):
            if not name.endswith('.json'):
                continue
            try:
                seq = int(name[:-5])
            except ValueError:
                continue
            with open(os.path.join(root, name), encoding='utf-8') as f:
                patches[seq] = json.load(f)
    if patches:
        print(f'  {len(patches)} patches loaded from {patches_dir}', flush=True)
    return patches


def apply_patch(data, patch):
    """Apply an RFC 7396 JSON Merge Patch to data in-place.

    Each key in patch replaces the corresponding key in data.
    A null value removes the key from data. Keys absent from patch are kept.
    """
    for key, value in patch.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value


def _find_reading(kanji_text, kana_list):
    """Return the first kana reading that applies to kanji_text."""
    for k in kana_list:
        applies = k.get('appliesToKanji', ['*'])
        if '*' in applies or kanji_text in applies:
            return k['text']
    return None


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


def parse_entry(elem, knowledge=None):
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
        nokanji = r.find('re_nokanji') is not None
        kana.append({
            'text': reb,
            'common': bool(pris),
            'tags': pris + infs,
            'appliesToKanji': restr if restr else ['*'],
            'nokanji': nokanji,
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
                'stagk': get_texts(s, 'stagk'),
                'stagr': get_texts(s, 'stagr'),
            })

    for k in kanji:
        reading = _find_reading(k['text'], kana)
        k['furigana'] = compute_furigana(k['text'], reading, knowledge) if reading else None

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

def process(output_dir, cache_dir, kanjidic2_dir=None, patches_dir=None):
    knowledge = build_knowledge(kanjidic2_dir) if kanjidic2_dir else None
    patches = load_patches(patches_dir if patches_dir is not None else _DEFAULT_PATCHES_DIR)

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
            seq, kanji, kana, eng_senses, lang_glosses = parse_entry(elem, knowledge)
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            entry_data = {'seq': seq, 'kanji': kanji, 'kana': kana, 'senses': eng_senses}
            if seq in patches:
                apply_patch(entry_data, patches[seq])
                seq = entry_data['seq']

            sh = seq // SHARD_SIZE
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


HELP = (
    'usage: jmdict-to-git.py '
    '-o <gitmdict directory> [--cache <cache directory>] '
    '[--kanjidic2 <gitjidic2 directory>] [--patches <patches directory>]'
)


def main(argv):
    output_dir = ''
    cache_dir = os.path.expanduser('~/.cache/jmdict')
    kanjidic2_dir = None
    patches_dir = None
    try:
        opts, _ = getopt.getopt(argv, 'ho:', ['odir=', 'cache=', 'kanjidic2=', 'patches='])
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
        elif opt == '--kanjidic2':
            kanjidic2_dir = arg
        elif opt == '--patches':
            patches_dir = arg
    if not output_dir:
        print(HELP)
        sys.exit(2)
    process(output_dir, cache_dir, kanjidic2_dir, patches_dir)


if __name__ == '__main__':
    main(sys.argv[1:])
