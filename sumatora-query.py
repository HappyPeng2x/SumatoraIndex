#!/usr/bin/env python3
""" Database generator for Sumatora Dictionary.

This program generates the database for use with the Android application
Sumatora Dictionary.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import json
import sqlite3
import os

# ---------------------------------------------------------------------------
# FTS search tiers — tried in priority order.
# Each tuple is (fts5_column, form_type) where form_type is 'kanji' or 'kana'.
# The DictionaryEntry columns that carry the same-tier tokens are used by
# matched_form() to identify which specific surface form the FTS hit.
# ---------------------------------------------------------------------------

_TIERS = [
    # (fts5 column to MATCH,  DictionaryEntry column with same tokens, form_type)
    ('writingsPrio',     'writingsPrio',  'kanji'),
    ('writings',         'writings',      'kanji'),
    ('readingsPrioKana', 'readingsPrio',  'kana'),
    ('readingsKana',     'readings',      'kana'),
]

_SQL_TEMPLATE = """SELECT
        DictionaryEntry.seq,
        DictionaryEntry.readingsPrio,
        DictionaryEntry.readings,
        DictionaryEntry.writingsPrio,
        DictionaryEntry.writings,
        DictionaryEntry.pos,
        DictionaryEntry.xref,
        DictionaryEntry.ant,
        DictionaryEntry.misc,
        DictionaryEntry.lsource,
        DictionaryEntry.dial,
        DictionaryEntry.s_inf,
        DictionaryEntry.field,
        DictionaryEntry.stagk,
        DictionaryEntry.stagr,
        DictionaryEntry.score,
        json_group_array(DictionaryTranslation.gloss)
    FROM DictionaryEntry, DictionaryTranslation
    WHERE
        DictionaryTranslation.seq = DictionaryEntry.seq AND
        DictionaryEntry.seq IN
            (SELECT DictionaryIndex.`rowid` AS seq
                FROM DictionaryIndex
                WHERE {fts_col} MATCH ?)
    GROUP BY DictionaryEntry.seq
    ORDER BY DictionaryEntry.score DESC"""


# ---------------------------------------------------------------------------
# stagk / stagr sense filtering
# ---------------------------------------------------------------------------

def matched_form(expr, row):
    """Return (kanji_form, kana_form) identifying which surface form matched expr.

    Walks the tier columns in priority order and returns the form type as soon
    as expr appears as a token in the corresponding DictionaryEntry column.
    Returns (None, None) when no column contains expr (should not happen for a
    valid FTS hit, but handled gracefully).
    """
    _seq, rp, r, wp, w = row[:5]
    for entry_col_value, form_type in [
        (wp, 'kanji'),
        (w,  'kanji'),
        (rp, 'kana'),
        (r,  'kana'),
    ]:
        if entry_col_value and expr in entry_col_value.split():
            return (expr, None) if form_type == 'kanji' else (None, expr)
    return (None, None)


def applicable_senses(stagk_json, stagr_json, kanji_form, kana_form):
    """Return the set of sense indices that apply to the matched form.

    A sense at index i is applicable when ALL of the following hold:
      - stagk[i] is empty, OR kanji_form is None, OR kanji_form is in stagk[i]
      - stagr[i] is empty, OR kana_form is None,  OR kana_form  is in stagr[i]

    Returns None when neither stagk nor stagr carry any restrictions (all
    senses apply unconditionally).
    """
    stagk = json.loads(stagk_json) if stagk_json else []
    stagr = json.loads(stagr_json) if stagr_json else []
    n = max(len(stagk), len(stagr))
    if n == 0:
        return None  # no per-sense restrictions

    result = set()
    for i in range(n):
        sk = stagk[i] if i < len(stagk) else []
        sr = stagr[i] if i < len(stagr) else []
        kanji_ok = not sk or kanji_form is None or kanji_form in sk
        kana_ok  = not sr or kana_form  is None or kana_form  in sr
        if kanji_ok and kana_ok:
            result.add(i)
    return result


# ---------------------------------------------------------------------------
# Query runner
# ---------------------------------------------------------------------------

def test_query(a_dir, a_lang, a_expr):
    conn = sqlite3.connect(os.path.join(a_dir, 'jmdict.db'))
    cur = conn.cursor()

    cur.execute(
        "ATTACH '" + os.path.join(a_dir, a_lang + '.db') + "' AS " + a_lang
    )

    seen_seqs = set()

    for fts_col, _entry_col, _form_type in _TIERS:
        sql = _SQL_TEMPLATE.format(fts_col=fts_col)
        cur.execute(sql, (a_expr,))
        rows = cur.fetchall()

        for row in rows:
            seq = row[0]
            if seq in seen_seqs:
                continue
            seen_seqs.add(seq)

            stagk_json, stagr_json = row[13], row[14]
            entry_score = row[15]
            kanji_form, kana_form = matched_form(a_expr, row)
            sense_filter = applicable_senses(stagk_json, stagr_json, kanji_form, kana_form)

            glosses_raw = json.loads(row[16])
            if sense_filter is not None:
                glosses_raw = [g for i, g in enumerate(glosses_raw) if i in sense_filter]

            print(f'seq={seq}  score={entry_score}  matched_kanji={kanji_form!r}  matched_kana={kana_form!r}')
            if sense_filter is not None:
                print(f'  sense filter applied: {sorted(sense_filter)}')
            for g in glosses_raw:
                print(f'  {g}')

        if seen_seqs:
            break  # stop at first tier that produced results

    cur.close()
    conn.close()


parser = argparse.ArgumentParser()

parser.add_argument('dir')
parser.add_argument('lang')
parser.add_argument('expr')

args = parser.parse_args()

test_query(args.dir, args.lang, args.expr)
