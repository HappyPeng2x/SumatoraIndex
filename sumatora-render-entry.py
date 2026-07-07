#!/usr/bin/env python3
"""Render one JMdict word entry from sumatora.db as terminal text, following
the Jitendex card layout: headword + furigana, numbered senses grouped by
part-of-speech with restriction notes and an example sentence, and an
alternate-forms table (kanji columns x reading rows) with cell badges.

This is a demonstration of the recipes documented in Database.md ("Building
an Alternate-Forms Table") and schema-v2.md (SenseAppliesToForm) — it reads
only EntryForm/FormTag/FormFuriganaSegment/Sense*/SenseAppliesToForm/Example*,
the same tables a client app would use, no extra derived storage.

Two deliberate departures from a literal Jitendex reproduction:

  - Jitendex merges adjacent senses that share identical tags/restrictions
    under one bullet. SenseGroup is currently 1:1 with Sense (see
    jmdict-to-sumatora-db.py's module docstring), so this script prints one
    bullet per sense instead — senses 2/3 of a "spring" entry each get their
    own repeated tag line rather than sharing one.
  - The 優/可/稀 forms-table badges are this script's own mapping onto
    EntryForm.is_primary/score (see build_forms_table()), not a stored
    Jitendex field: JMdict has no per-(kanji,reading)-pair priority, only
    independent per-kanji/per-reading tags, so Jitendex's own algorithm for
    picking these three tiers cannot be reproduced exactly from the source
    data either.

Usage:
    sumatora-render-entry.py -d sumatora.db <headword> [--seq N] [--lang eng]
"""

import argparse
import sqlite3
import sys
import unicodedata

_BADGE_PRIMARY = '優'  # 優 preferred
_BADGE_COMMON = '可'   # 可 valid/common
_BADGE_RARE = '稀'     # 稀 rare/irregular
_NOKANJI_COL = '∅'    # ∅


def _dwidth(s):
    """Display width counting wide (CJK) characters as 2 columns."""
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in s)


def _pad(s, width):
    return s + ' ' * max(0, width - _dwidth(s))


def resolve_entries(conn, headword, seq):
    if seq is not None:
        rows = conn.execute(
            "SELECT entry_id FROM Entry WHERE entry_type = 'word' AND source_key = ?",
            (str(seq),),
        ).fetchall()
        return [r[0] for r in rows]
    rows = conn.execute(
        "SELECT DISTINCT e.entry_id FROM EntryForm f JOIN Entry e ON e.entry_id = f.entry_id "
        "WHERE e.entry_type = 'word' AND f.text = ? AND f.is_search_only = 0",
        (headword,),
    ).fetchall()
    return [r[0] for r in rows]


def describe_entry(conn, entry_id, lang):
    """First-gloss summary line used for disambiguation between homographs."""
    row = conn.execute(
        "SELECT g.text FROM Sense s JOIN SenseGloss g ON g.sense_id = s.sense_id "
        "WHERE s.entry_id = ? AND g.lang = ? ORDER BY s.ord, g.ord LIMIT 1",
        (entry_id, lang),
    ).fetchone()
    seq = conn.execute("SELECT source_key FROM Entry WHERE entry_id = ?", (entry_id,)).fetchone()[0]
    forms = conn.execute(
        "SELECT text FROM EntryForm WHERE entry_id = ? AND is_search_only = 0 ORDER BY ord LIMIT 3",
        (entry_id,),
    ).fetchall()
    forms_str = '・'.join(f[0] for f in forms)
    return f'seq {seq}: {forms_str} — {row[0] if row else "(no gloss)"}'


def _visible_forms(conn, entry_id):
    cols = ('form_id', 'ord', 'form_type', 'text', 'reading', 'is_primary', 'is_common', 'score')
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM EntryForm WHERE entry_id = ? AND is_search_only = 0 ORDER BY ord",
        (entry_id,),
    ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def headline_form(forms):
    """Pick the form to headline the entry with.

    EntryForm.is_primary is chosen once across writing *and* reading forms
    together (see Database.md), so it can land on a kana-only reading row
    even when kanji forms exist, if that reading outscores every available
    kanji pairing (e.g. an entry where every kanji form is tagged rK). A
    dictionary card should still headline with a kanji form whenever one
    exists, so pick separately within the writing pool and only fall back to
    the reading pool for genuinely kana-only entries.
    """
    writing = [f for f in forms if f['form_type'] == 'writing']
    if writing:
        return max(writing, key=lambda f: (f['score'], f['is_common'], -f['ord']))
    primary = [f for f in forms if f['form_type'] == 'reading' and f['is_primary']]
    return primary[0] if primary else forms[0]


def furigana_display(conn, form_id):
    segs = conn.execute(
        "SELECT base, ruby FROM FormFuriganaSegment WHERE form_id = ? ORDER BY ord",
        (form_id,),
    ).fetchall()
    if not segs:
        return None
    return ''.join(base for base, _ in segs), ''.join(ruby or base for base, ruby in segs)


def sense_tags(conn, sense_group_id):
    rows = conn.execute(
        "SELECT t.category, t.code, t.label FROM SenseGroupTag sgt JOIN Tag t ON t.tag_id = sgt.tag_id "
        "WHERE sgt.sense_group_id = ? ORDER BY t.category, t.sort_order",
        (sense_group_id,),
    ).fetchall()
    chips = []
    has_kana_only = False
    for category, code, label in rows:
        if category == 'misc' and code == 'uk':
            has_kana_only = True
            continue
        chips.append(label.split(' (')[0])
    if has_kana_only:
        chips.append('kana')
    return chips


def restriction_label(conn, entry_id, sense_id, forms):
    restricted = conn.execute(
        "SELECT ef.form_type, ef.text, ef.reading FROM SenseAppliesToForm s "
        "JOIN EntryForm ef ON ef.form_id = s.form_id WHERE s.sense_id = ?",
        (sense_id,),
    ).fetchall()
    if not restricted:
        return None

    order = {}
    for f in forms:
        order.setdefault(f['text'], f['ord'])
        if f['form_type'] == 'writing' and f['reading']:
            order.setdefault(f['reading'], f['ord'])

    restricted_readings, restricted_kanji = set(), set()
    for form_type, text, reading in restricted:
        if form_type == 'reading':
            restricted_readings.add(text)
        else:
            restricted_kanji.add(text)
            if reading:
                restricted_readings.add(reading)

    all_readings = {f['reading'] for f in forms if f['form_type'] == 'writing' and f['reading']}
    all_readings |= {f['text'] for f in forms if f['form_type'] == 'reading'}
    all_kanji = {f['text'] for f in forms if f['form_type'] == 'writing'}

    # stagr (reading-restricted) and stagk (kanji-restricted) both collapse into
    # the same SenseAppliesToForm rows; tell them apart by which dimension the
    # restriction actually narrows, same idea Jitendex's own label follows.
    if restricted_readings and len(restricted_readings) < len(all_readings):
        label = '・'.join(sorted(restricted_readings, key=lambda r: order.get(r, 0)))
    elif restricted_kanji and len(restricted_kanji) < len(all_kanji):
        label = '・'.join(sorted(restricted_kanji, key=lambda r: order.get(r, 0)))
    else:
        return None
    return f'{label} only'


def example_for_sense(conn, entry_id, sense_id, first_sense_id, lang):
    """Tatoeba example linked to this sense, falling back onto the entry's
    first sense for examples with no senseNumber in the source corpus (see
    gitoeba-to-sumatora-db.py's _sense_id()) — purely a display choice, not a
    claim that the source data actually ties the sentence to that sense."""
    row = conn.execute(
        "SELECT ee.example_id, ee.matched_text FROM EntryExample ee "
        "WHERE ee.entry_id = ? AND (ee.sense_id = ? OR (ee.sense_id IS NULL AND ? = ?)) "
        "ORDER BY ee.sense_id IS NULL, ee.ord LIMIT 1",
        (entry_id, sense_id, sense_id, first_sense_id),
    ).fetchone()
    if not row:
        return None
    example_id, matched_text = row
    seg_rows = conn.execute(
        "SELECT base, ruby FROM ExampleSegment WHERE example_id = ? ORDER BY ord",
        (example_id,),
    ).fetchall()
    if not seg_rows:
        return None
    jp = ''.join(base for base, _ in seg_rows)
    translation = conn.execute(
        "SELECT translation FROM Example WHERE example_id = ? AND lang = ?",
        (example_id, lang),
    ).fetchone()
    return jp, translation[0] if translation else None


def build_forms_table(forms):
    writing = [f for f in forms if f['form_type'] == 'writing']
    reading_only = [f for f in forms if f['form_type'] == 'reading']

    columns, seen = [], set()
    for f in writing:
        if f['text'] not in seen:
            seen.add(f['text'])
            columns.append(f['text'])

    bridging_readings = {f['reading'] for f in writing if f['reading']}
    reading_ord = {}
    for f in writing:
        if f['reading']:
            reading_ord[f['reading']] = min(reading_ord.get(f['reading'], f['ord']), f['ord'])
    row_readings = sorted(bridging_readings, key=lambda r: reading_ord[r])

    nokanji = sorted(
        (f for f in reading_only if f['text'] not in bridging_readings),
        key=lambda f: f['ord'],
    )

    cell = {(f['reading'], f['text']): f for f in writing}
    return columns, row_readings, cell, nokanji


def badge(f):
    if f is None:
        return ''
    if f['is_primary']:
        return _BADGE_PRIMARY
    if f['score'] < 0:
        return _BADGE_RARE
    return _BADGE_COMMON


def print_forms_table(columns, row_readings, cell, nokanji):
    trivial = len(columns) <= 1 and len(row_readings) <= 1 and not nokanji
    if trivial:
        return  # Database.md: omit a one-cell matrix rather than render it
    print(f'Forms  ({_BADGE_PRIMARY} preferred · {_BADGE_COMMON} valid · {_BADGE_RARE} rare/irregular)')

    headers = [''] + columns + ([_NOKANJI_COL] if nokanji else [])
    row_labels = row_readings + [f['text'] for f in nokanji]
    label_width = max([_dwidth(r) for r in row_labels] + [6])
    col_widths = [max(_dwidth(h), 4) for h in columns] + ([4] if nokanji else [])

    print(_pad('', label_width) + '  ' + '  '.join(_pad(h, w) for h, w in zip(columns + ([_NOKANJI_COL] if nokanji else []), col_widths)))
    for reading in row_readings:
        cells = [badge(cell.get((reading, c))) for c in columns]
        if nokanji:
            cells.append('')
        print(_pad(reading, label_width) + '  ' + '  '.join(_pad(c, w) for c, w in zip(cells, col_widths)))
    for f in nokanji:
        cells = [''] * len(columns) + [badge(f)]
        print(_pad(f['text'], label_width) + '  ' + '  '.join(_pad(c, w) for c, w in zip(cells, col_widths)))


def render_entry(conn, entry_id, lang):
    forms = _visible_forms(conn, entry_id)
    head = headline_form(forms)

    if head['form_type'] == 'writing':
        _, ruby = furigana_display(conn, head['form_id']) or (head['text'], head['reading'])
        print(f"{head['text']} 【{ruby}】")
    else:
        print(head['text'])
    print()

    senses = conn.execute(
        "SELECT sense_id, sense_group_id, ord FROM Sense WHERE entry_id = ? ORDER BY ord",
        (entry_id,),
    ).fetchall()
    first_sense_id = senses[0][0] if senses else None

    for sense_id, sense_group_id, ord_ in senses:
        display_number = conn.execute(
            "SELECT display_number FROM Sense WHERE sense_id = ?", (sense_id,),
        ).fetchone()[0] or (ord_ + 1)

        chips = sense_tags(conn, sense_group_id)
        restriction = restriction_label(conn, entry_id, sense_id, forms)
        chip_line = '・'.join(chips)
        if restriction:
            chip_line += f'  [{restriction}]'
        print(f'* {chip_line}')

        glosses = conn.execute(
            "SELECT text FROM SenseGloss WHERE sense_id = ? AND lang = ? AND gloss_type = 'main' ORDER BY ord",
            (sense_id, lang),
        ).fetchall()
        gloss_text = '; '.join(g[0] for g in glosses)
        print(f'  {display_number}. {gloss_text}')

        example = example_for_sense(conn, entry_id, sense_id, first_sense_id, lang)
        if example:
            jp, translation = example
            print(f'     例: {jp}')
            if translation:
                print(f'        {translation}')
        print()

    columns, row_readings, cell, nokanji = build_forms_table(forms)
    print_forms_table(columns, row_readings, cell, nokanji)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('-d', '--db', required=True, help='path to sumatora.db')
    parser.add_argument('headword', nargs='?', help='writing or reading to look up')
    parser.add_argument('--seq', type=int, help='JMdict sequence number, bypasses headword lookup')
    parser.add_argument('--index', type=int, default=0, help='pick the Nth match when a headword is ambiguous')
    parser.add_argument('--lang', default='eng', help='gloss/example language (default: eng)')
    args = parser.parse_args(argv)

    if not args.headword and args.seq is None:
        parser.error('provide a headword or --seq')

    conn = sqlite3.connect(args.db)
    entry_ids = resolve_entries(conn, args.headword, args.seq)
    if not entry_ids:
        print('No matching entry found.', file=sys.stderr)
        return 1
    if len(entry_ids) > 1 and args.index == 0 and args.seq is None:
        print(f'{len(entry_ids)} entries match — showing the first; pick another with --index or --seq:',
              file=sys.stderr)
        for i, eid in enumerate(entry_ids):
            print(f'  [{i}] {describe_entry(conn, eid, args.lang)}', file=sys.stderr)
        print(file=sys.stderr)

    render_entry(conn, entry_ids[args.index], args.lang)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
