"""Shared helpers for the SumatoraIndex v2 (schema-v2.md) stage-2 generators."""

import os


def iter_json_files(directory):
    """Yield every .json file under directory, in sorted (deterministic) order."""
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            if name.endswith('.json'):
                yield os.path.join(root, name)


def hira_to_kata(s):
    return ''.join(
        chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c
        for c in s
    )


def kata_to_hira(s):
    return ''.join(
        chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c
        for c in s
    )


_KANJI_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF), (0x20000, 0x2A6DF))


def _is_kanji(c):
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi in _KANJI_RANGES)


def parse_bracket_furigana(text):
    """Parse jmdict-to-git.py's bracket-notation furigana into (base, ruby) segments.

    '食[た]べ物[もの]' -> [('食', 'た'), ('べ', None), ('物', 'もの')]
    Plain text with no brackets at all -> [(text, None)].

    A bracket always immediately follows the maximal kanji run it applies to, so
    runs are split on kanji/non-kanji boundaries, not on brackets alone — a bare
    regex over '[...]' would incorrectly swallow a preceding kana run into the
    next bracketed kanji run's base text.
    """
    segments = []
    i = 0
    n = len(text)
    while i < n:
        if _is_kanji(text[i]):
            j = i
            while j < n and _is_kanji(text[j]):
                j += 1
            base = text[i:j]
            ruby = None
            if j < n and text[j] == '[':
                close = text.find(']', j)
                if close != -1:
                    ruby = text[j + 1:close]
                    j = close + 1
            segments.append((base, ruby))
            i = j
        else:
            if text[i] in '[]':
                segments.append((text[i], None))
                i += 1
                continue
            j = i
            while j < n and not _is_kanji(text[j]) and text[j] not in '[]':
                j += 1
            segments.append((text[i:j], None))
            i = j
    return segments


def is_priority_code(code):
    """True for JMdict/JMnedict ke_pri/re_pri priority codes (news1, ichi2, nf12, ...).

    These drive EntryForm.is_common/score directly and must not become Tag/FormTag
    rows — only the remaining informational codes (iK, rK, ateji, gikun, ...) do.
    """
    return code in ('news1', 'news2', 'ichi1', 'ichi2', 'spec1', 'spec2',
                    'gai1', 'gai2') or (code.startswith('nf') and code[2:].isdigit())


class TagCache:
    """Get-or-create cache for the Tag table, keyed by (category, code)."""

    def __init__(self, conn):
        self._conn = conn
        self._cache = {}
        for tag_id, category, code in conn.execute('SELECT tag_id, category, code FROM Tag'):
            self._cache[(category, code)] = tag_id

    def get_or_create(self, category, code, label, description=None, sort_order=0):
        key = (category, code)
        tag_id = self._cache.get(key)
        if tag_id is not None:
            return tag_id
        cur = self._conn.execute(
            'INSERT INTO Tag (code, category, label, description, sort_order) '
            'VALUES (?, ?, ?, ?, ?)',
            (code, category, label, description, sort_order),
        )
        tag_id = cur.lastrowid
        self._cache[key] = tag_id
        return tag_id
