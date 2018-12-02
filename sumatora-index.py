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
__copyright__ = "Copyright 2018, Nicolas Centa"
__credits__ = ["Nicolas Centa"]
__date__ = "2018/12/02"
__deprecated__ = False
__email__ =  "nicolas.centa@happypeng.org"
__license__ = "GPLv3"
__maintainer__ = "developer"
__status__ = "Production"
__version__ = "0.1.0"

import xml.sax
import sqlite3
import sys
import getopt

class JMDictHandler(xml.sax.ContentHandler):
    def __init__(self, aCur):
        self.mCur = aCur
        self.mLang = ""
        self.mStartSense = False
        self.mCurrentLang = ""
        self.mSenseId = 0
        self.mSeq = 0
        self.mText = ""
        self.mKeb = ""
        self.mKeInf = ""
        self.mKebId = 0
        self.mReb = ""
        self.mReInf = ""
        self.mRebId = 0

    def endElement(self, aName):
        if aName == "ent_seq":
            self.mSeq = int(self.mText)
        elif aName == "k_ele":
            self.mCur.execute("INSERT INTO writings (seq, keb_id, keb, ke_inf) VALUES (?, ?, ?, ?)",
                              (self.mSeq, self.mKebId, self.mKeb, self.mKeInf))
            
            self.mKeb = ""
            self.mKeInf = ""            
            self.mKebId = self.mKebId + 1
        elif aName == "keb":
            self.mKeb = self.mText
        elif aName == "ke_inf":
            self.mKeInf = self.mText
        elif aName == "ke_pri":
            self.mCur.execute("INSERT INTO writings_prio (seq, keb_id, ke_pri) VALUES (?, ?, ?)",
                              (self.mSeq, self.mKebId, self.mText))
        elif aName == "re_pri":
            self.mCur.execute("INSERT INTO readings_prio (seq, reb_id, re_pri) VALUES (?, ?, ?)",
                              (self.mSeq, self.mRebId, self.mText))
        elif aName == "r_ele":
            self.mCur.execute("INSERT INTO readings (seq, reb_id, reb, re_inf) VALUES (?, ?, ?, ?)",
                              (self.mSeq, self.mRebId, self.mReb, self.mReInf))
            
            self.mReb = ""
            self.mReInf = ""
            self.mRebId = self.mRebId + 1
        elif aName == "reb":
            self.mReb = self.mText
        elif aName == "re_inf":
            self.mReInf = self.mText
        elif aName == "gloss":
            self.mCur.execute("INSERT INTO gloss (seq, sense_id, lang, gloss) VALUES (?, ?, ?, ?)",
                              (self.mSeq, self.mSenseId, self.mLang, self.mText))
        elif aName == "pos":
            self.mCur.execute("INSERT INTO pos (seq, sense_id, pos) VALUES (?, ?, ?)",
                              (self.mSeq, self.mSenseId, self.mText))
        elif aName == "entry":
            self.mSenseId = 0
            self.mKebId = 0
            self.mRebId = 0
            self.mCurrentLang = ""
        
    def startElement(self, aName, aAttrs):
        if "xml:lang" in aAttrs:
            self.mLang = aAttrs["xml:lang"]

        if aName == "sense":
            self.mStartSense = True
        elif (aName == "pos" or aName == "gloss") and self.mStartSense:
            self.mStartSense = False

            if self.mLang == "":
                self.mLang = "eng"

            if not self.mCurrentLang == self.mLang:
                self.mCurrentLang = self.mLang
                self.mSenseId = 0
            else:
                self.mSenseId = self.mSenseId + 1

    def characters(self, aContent):
        self.mText = aContent

HELP_STRING = """usage: sumatora-index.py -i <JMdict input file> -o <JMdict.db output file>"""

def main(argv):
    inputfile = ""
    outputfile = ""

    try:
        opts, args = getopt.getopt(argv, "hi:o:", ["ifile=", "ofile="])
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
    
    if inputfile == "" or outputfile == "":
        print(HELP_STRING)
        sys.exit(2)
            
    conn = sqlite3.connect(outputfile, isolation_level=None)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS writings")
    cur.execute("DROP TABLE IF EXISTS readings")
    cur.execute("DROP TABLE IF EXISTS pos")
    cur.execute("DROP TABLE IF EXISTS gloss")
    cur.execute("DROP TABLE IF EXISTS writings_prio")
    cur.execute("DROP TABLE IF EXISTS readings_prio")
    
    cur.execute("CREATE TABLE writings (seq INTEGER, keb_id INTEGER, keb TEXT, ke_inf TEXT)")
    cur.execute("CREATE TABLE writings_prio (seq INTEGER, keb_id INTEGER, ke_pri TEXT)")
    cur.execute("CREATE TABLE readings (seq INTEGER, reb_id INTEGER, reb TEXT, re_inf TEXT)")
    cur.execute("CREATE TABLE readings_prio (seq INTEGER, reb_id INTEGER, re_pri TEXT)")
    cur.execute("CREATE TABLE pos (seq INTEGER, sense_id INTEGER, pos TEXT)")
    cur.execute("CREATE TABLE gloss (seq INTEGER, sense_id INTEGER, lang TEXT, gloss TEXT)")
    
    cur.execute("BEGIN TRANSACTION")
    
    handler = JMDictHandler(cur)
    
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)
    
    f = open(inputfile, "r")
    
    parser.parse(f)
    
    f.close()
    
    cur.execute("END TRANSACTION")

if __name__ == "__main__":
   main(sys.argv[1:])
