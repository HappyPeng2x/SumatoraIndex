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
import sqlite3
import os

SQL_QUERY_EXACT_WRITING_PRIO = """SELECT DictionaryEntry.seq,
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
        json_group_array(DictionaryTranslation.gloss)
    FROM DictionaryEntry, DictionaryTranslation
    WHERE
        DictionaryTranslation.seq = DictionaryEntry.seq AND
        DictionaryEntry.seq IN 
            (SELECT DictionaryIndex.`rowid` AS seq
                FROM DictionaryIndex
                WHERE writingsPrio MATCH ?)
    GROUP BY DictionaryEntry.seq"""

def test_query(a_dir, a_lang, a_expr):
    conn = sqlite3.connect(os.path.join(a_dir, 'jmdict.db'))
    cur = conn.cursor()

    cur.execute("ATTACH '" + os.path.join(a_dir, a_lang + '.db') + "' AS " + a_lang)

    print("Query plan:")

    cur.execute("EXPLAIN QUERY PLAN " + SQL_QUERY_EXACT_WRITING_PRIO, (a_expr,))

    results = cur.fetchall()

    for result in results:
        print(result)

    print("Query results:")

    cur.execute(SQL_QUERY_EXACT_WRITING_PRIO, (a_expr,))

    results = cur.fetchall()

    for result in results:
        print(result)

    cur.close()
    conn.close()

parser = argparse.ArgumentParser()

parser.add_argument('dir')
parser.add_argument('lang')
parser.add_argument('expr')

args = parser.parse_args()

test_query(args.dir, args.lang, args.expr)