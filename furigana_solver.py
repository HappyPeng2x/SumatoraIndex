"""Shared informed furigana solver for JMdict and JMnedict git-repo generators.

Extracted from jmdict-to-git.py so jmnedict-to-git.py can produce the same
per-reading, kanjidic2-informed furigana for proper names that jmdict-to-git.py
already produces for words, instead of duplicating the solver.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

import json
import os


def _is_kanji(c):
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF or  # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or  # CJK Extension A
        0xF900 <= cp <= 0xFAFF or  # CJK Compatibility Ideographs
        0x20000 <= cp <= 0x2A6DF or  # CJK Extension B
        cp == 0x3005                # Kanji iteration mark (々) - not a real
                                     # character with its own kanjidic entry,
                                     # but it stands in for one (時々, 我々,
                                     # 苦々しい...) and must join the kanji run
                                     # it repeats, not the following kana run -
                                     # see _split_kanji_run's 々 special case.
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

def _split_kanji_run(run, reading, knowledge):
    """Try to assign one reading per character in run using knowledge.

    Returns a tuple of per-character readings when exactly one valid assignment
    exists; returns None when the split is impossible or ambiguous.
    Only called for multi-character runs (len(run) >= 2).

    Uses constrained backtracking: at each position only the known readings for
    that character are tried, so the search prunes aggressively compared to
    enumerating all C(len(reading)-1, len(run)-1) partitions.
    """
    n = len(run)
    found = []

    def search(char_idx, pos, current):
        if char_idx == n:
            if pos == len(reading):
                found.append(tuple(current))
            return len(found) < 2          # stop once ambiguous
        # 々 has no kanjidic entry of its own - it borrows whatever reading
        # was just assigned to the character it repeats, either as-is (我々
        # -> われ+われ) or rendaku-voiced, which is the more common case for
        # this exact repetition pattern (時々 -> とき+どき, 人々 -> ひと+びと).
        if run[char_idx] == '々' and char_idx > 0:
            prev = current[char_idx - 1]
            rend = _rendaku(prev)
            candidates = (prev, rend) if rend else (prev,)
        else:
            candidates = knowledge.get(run[char_idx], ())
        for stem in candidates:
            if reading.startswith(stem, pos):
                current.append(stem)
                if not search(char_idx + 1, pos + len(stem), current):
                    return False
                current.pop()
        return True

    search(0, 0, [])
    return found[0] if len(found) == 1 else None


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
                # Search from index 1, not 0: the kanji run must consume at
                # least one character of reading, so a match at position 0
                # (the kanji's own reading happens to start with the same
                # kana the following segment starts with, e.g. 砕く's くだ
                # followed by く) can never be the right anchor - matching
                # there anyway used to yield an empty, always-invalid
                # kanji_reading and made compute_furigana fail outright.
                anchor = remaining.find(next_kana_norm, 1)
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
    """Return bracket-notation furigana string, or None for pure-kana forms
    (or when no reliable furigana can be produced at all - see below).

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
        # A whole-word bracket fallback is only structurally valid when
        # kanji_form is pure kanji: parse_bracket_furigana (sumatora_common.py)
        # requires a bracket to immediately follow the kanji run it applies
        # to, and f'{kanji_form}[{reading_hira}]' places it at the very end
        # of the *entire* string - correct when there's no trailing/embedded
        # kana to place it after, but a structural violation otherwise (the
        # kana and the bracket itself leak through as literal characters).
        # _solve_ignorant already failing means there's no literal
        # correspondence between reading_hira and kanji_form's kana either
        # (a contracted/colloquial alternate reading, e.g. 駄々をこねる's
        # 「だだこねる」 eliding を) - there's no reliable partial split to
        # fall back to, so no furigana is the honest answer, not a broken one.
        if all(_is_kanji(c) for c in kanji_form):
            return f'{kanji_form}[{reading_hira}]'
        return None
    return ''.join(
        base if ruby is None else f'{base}[{ruby}]'
        for base, ruby in parts
    )


def applicable_readings(kanji_text, kana_list):
    """Return every kana reading (in kana_list order) that applies to kanji_text.

    kana_list entries are dicts with 'text' and an optional 'appliesToKanji'
    list (JMdict/JMnedict re_restr); '*' or a missing key means "applies to
    every kanji form".
    """
    return [
        k['text'] for k in kana_list
        if '*' in k.get('appliesToKanji', ['*']) or kanji_text in k.get('appliesToKanji', ['*'])
    ]
