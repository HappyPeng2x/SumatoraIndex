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
        self.mCurrentLang = "eng"
        self.mSenseId = 0
        self.mSeq = 0
        self.mText = ""
        self.mKeb = ""
        self.mKeInf = ""
        self.mKebId = 0
        self.mReb = ""
        self.mReInf = ""
        self.mRebId = 0
        self.mGlossId = 0
        self.mPosId = 0

    def endElement(self, aName):
        if aName == "ent_seq":
            self.mSeq = int(self.mText)
            self.mCur.execute("INSERT INTO seqs (seq) VALUES (?)", [(self.mSeq)])
        elif aName == "k_ele":                
            self.mKeb = ""
            self.mKeInf = ""            
            self.mKebId = self.mKebId + 1
        elif aName == "keb":
            self.mKeb = self.mText
            self.mCur.execute("INSERT INTO writings (seq, keb_id, keb) VALUES (?, ?, ?)",
                              (self.mSeq, self.mKebId, self.mKeb))
        elif aName == "ke_inf":
            self.mKeInf = self.mText
            self.mCur.execute("INSERT INTO writings_inf (seq, keb_id, ke_inf) VALUES (?, ?, ?)",
                              (self.mSeq, self.mKebId, self.mKeInf))
        elif aName == "ke_pri":
            self.mCur.execute("INSERT INTO writings_prio (seq, keb_id, ke_pri) VALUES (?, ?, ?)",
                              (self.mSeq, self.mKebId, self.mText))
        elif aName == "re_pri":
            self.mCur.execute("INSERT INTO readings_prio (seq, reb_id, re_pri) VALUES (?, ?, ?)",
                              (self.mSeq, self.mRebId, self.mText))
        elif aName == "r_ele":            
            self.mReb = ""
            self.mReInf = ""
            self.mRebId = self.mRebId + 1
        elif aName == "reb":
            self.mReb = self.mText
            self.mCur.execute("INSERT INTO readings (seq, reb_id, reb) VALUES (?, ?, ?)",
                              (self.mSeq, self.mRebId, self.mReb))
        elif aName == "re_inf":
            self.mReInf = self.mText
            self.mCur.execute("INSERT INTO readings_inf (seq, reb_id, re_inf) VALUES (?, ?, ?)",
                              (self.mSeq, self.mRebId, self.mReInf))

        elif aName == "gloss":
            self.mCur.execute("INSERT INTO gloss (seq, sense_id, lang, gloss_id, gloss) VALUES (?, ?, ?, ?, ?)",
                              (self.mSeq, self.mSenseId, self.mLang, self.mGlossId, self.mText))
            self.mGlossId = self.mGlossId + 1
        elif aName == "pos":
            self.mCur.execute("INSERT INTO pos (seq, sense_id, pos_id, pos) VALUES (?, ?, ?, ?)",
                              (self.mSeq, self.mSenseId, self.mPosId, self.mText))
            self.mPosId = self.mPosId + 1
        elif aName == "entry":
            self.mSenseId = 0
            self.mPosId = 0
            self.mGlossId = 0
            self.mKebId = 0
            self.mRebId = 0
            self.mCurrentLang = "eng"

        self.mText = ""
        
    def startElement(self, aName, aAttrs):
        if "xml:lang" in aAttrs:
            self.mLang = aAttrs["xml:lang"]
        else:
            self.mLang = "eng"

        if aName == "sense":
            self.mStartSense = True
            self.mPosId = 0
            self.mGlossId = 0
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
        if len(aContent.strip()) > 0:
            self.mText = self.mText + aContent

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

    cur.execute("PRAGMA foreign_keys = ON")
    
    cur.execute("DROP TABLE IF EXISTS seqs")
    cur.execute("DROP TABLE IF EXISTS writings")
    cur.execute("DROP TABLE IF EXISTS readings")
    cur.execute("DROP TABLE IF EXISTS writings_inf")
    cur.execute("DROP TABLE IF EXISTS readings_inf")
    cur.execute("DROP TABLE IF EXISTS pos")
    cur.execute("DROP TABLE IF EXISTS gloss")
    cur.execute("DROP TABLE IF EXISTS writings_prio")
    cur.execute("DROP TABLE IF EXISTS readings_prio")

    cur.execute("CREATE TABLE seqs (seq INTEGER PRIMARY KEY)")
    cur.execute("CREATE TABLE writings (seq INTEGER, keb_id INTEGER, keb TEXT, " \
                + "PRIMARY KEY (seq, keb_id), " \
                + "FOREIGN KEY (seq) REFERENCES seqs (seq))")
    cur.execute("CREATE TABLE writings_inf (seq INTEGER, keb_id INTEGER, ke_inf TEXT, " \
                + "FOREIGN KEY (seq, keb_id) REFERENCES writings (seq, keb_id))")
    cur.execute("CREATE TABLE writings_prio (seq INTEGER, keb_id INTEGER, ke_pri TEXT, " \
                + "FOREIGN KEY (seq, keb_id) REFERENCES writings (seq, keb_id))")
    cur.execute("CREATE TABLE readings (seq INTEGER, reb_id INTEGER, reb TEXT, " \
                + "PRIMARY KEY (seq, reb_id), " \
                + "FOREIGN KEY (seq) REFERENCES seqs (seq))")
    cur.execute("CREATE TABLE readings_inf (seq INTEGER, reb_id INTEGER, re_inf TEXT, " \
                + "FOREIGN KEY (seq, reb_id) REFERENCES readings (seq, reb_id))")
    cur.execute("CREATE TABLE readings_prio (seq INTEGER, reb_id INTEGER, re_pri TEXT, " \
                + "FOREIGN KEY (seq, reb_id) REFERENCES readings (seq, reb_id))")
    cur.execute("CREATE TABLE pos (seq INTEGER, sense_id INTEGER, pos_id INTEGER, pos TEXT, " \
                + "PRIMARY KEY (seq, sense_id, pos_id), " \
                + "FOREIGN KEY (seq) REFERENCES seqs (seq))")
    cur.execute("CREATE TABLE gloss (seq INTEGER, sense_id INTEGER, lang TEXT, gloss_id INTEGER, gloss TEXT, " \
                + "PRIMARY KEY (seq, sense_id, lang, gloss_id), " \
                + "FOREIGN KEY (seq) REFERENCES seqs (seq))")
    
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
