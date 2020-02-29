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

__author__ = "Nicolas Centa"
__authors__ = ["Nicolas Centa"]
__contact__ = "nicolas.centa@happypeng.org"
__copyright__ = "Copyright 2020, Nicolas Centa"
__credits__ = ["Nicolas Centa"]
__date__ = "2020/02/15"
__deprecated__ = False
__email__ = "nicolas.centa@happypeng.org"
__license__ = "GPLv3"
__maintainer__ = "developer"
__status__ = "Production"
__version__ = "0.4.0"

import sqlite3
import sys
import getopt
import re


def parse_examples(a_file, a_db, a_output_db):
    cur = a_db.cursor()
    entry_cur = a_db.cursor()
    output_cur = a_output_db.cursor()

    output_cur.execute('PRAGMA journal_mode=WAL')

    output_cur.execute('DROP TABLE IF EXISTS Examples')
    output_cur.execute('DROP TABLE IF EXISTS ExamplesIndex')

    output_cur.execute('CREATE TABLE Examples (id INTEGER, sentence TEXT, PRIMARY KEY (id))')
    output_cur.execute('CREATE TABLE ExamplesIndex (id INTEGER, seq INTEGER, PRIMARY KEY (id, seq))')
    
    aline = re.compile(r'A: (?P<japanese>[^\t\n]*)\t(?P<english>[^\n]*)(#ID=(?P<id>[^\s]*))$')
    bline = re.compile(r'B: (?P<contents>.*)$')
    cont = re.compile(r'(?P<writing>[^\(\)\[\]\{\}\s]+)(\((?P<reading>[^\(\)\[\]\{\}\s]*)\))?(\[(?P<index>[^\(\)\[\]\{\}\s]*)\])?(\{(?P<expression>[^\(\)\[\]\{\}\s]*)\})?(?P<verified>~)?\s?')

    with open(a_file, 'r') as f:
        while True:
            line = f.readline()

            if not line:
                break

            match = aline.match(line)

            if match is None:
                raise BaseException("Could not parse A line: '" + line + "'")
            
            d = match.groupdict()

            line = f.readline()

            if not line:
                raise BaseException("No B line following A line at end of file.")

            match = bline.match(line)

            if match is None:
                raise BaseException("Could not parse B line: '" + line + "'")

            contents = match.group('contents')

            for m in cont.finditer(contents):
                if m['verified'] == '~':
                    exemple_id = int(''.join(d['id'].split('_')))

                    if m['reading'] is None:
                        cur.execute('SELECT DictionaryIndex.`rowid` AS seq FROM DictionaryIndex WHERE writingsPrio MATCH ? OR writings MATCH ?',
                            (m['writing'], m['writing']))
                    else:
                        cur.execute('SELECT DictionaryIndex.`rowid` AS seq FROM DictionaryIndex WHERE writingsPrio MATCH ? OR writings MATCH ? INTERSECT ' + \
                                'SELECT DictionaryIndex.`rowid` AS seq FROM DictionaryIndex WHERE readingsPrio MATCH ? OR readings MATCH ?',
                            (m['writing'], m['writing'], m['reading'], m['reading']))
                
                    r = cur.fetchall()

                    if len(r) > 0:
                        output_cur.execute('INSERT OR IGNORE INTO Examples (id, sentence) VALUES (?, ?)', (exemple_id, line[:-1]))

                    if len(r) > 1:
                        print("Ambiguous: " + m['writing'] + " in " + contents, file=sys.stderr)
                    
                    for s in r:
                        output_cur.execute('INSERT OR IGNORE INTO ExamplesIndex (id, seq) VALUES (?, ?)', (exemple_id, s[0]))

    output_cur.execute('COMMIT')


HELP_STRING = "usage: sumatora-index-tatoeba.py -i " \
    + "<example file> -o <output file> -j <jmdict db file>"


def main(argv):
    inputfile = ""
    outputfile = ""
    jmdict = ""
    
    try:
        opts, args = getopt.getopt(argv, "i:o:j:",
                                   ["ifile=", "ofile=", "jmdict="])
    except getopt.GetoptError:
        print(HELP_STRING)
        sys.exit(2)

    for opt, arg in opts:
        if opt == "-h":
            print(HELP_STRING)
            sys.exit()
        elif opt in ("-i", "--ifile"):
            inputfile = arg
        elif opt in ("-o", "--ofile"):
            outputfile = arg
        elif opt in ("-j", "--jmdict"):
            jmdict = arg

    if inputfile == "" or outputfile == "" or jmdict == "":
        print(HELP_STRING)
        sys.exit(2)
    
    db = sqlite3.connect(jmdict)
    output_db = sqlite3.connect(outputfile)

    parse_examples(inputfile, db, output_db)

    db.close()
    output_db.close()


if __name__ == "__main__":
    main(sys.argv[1:])