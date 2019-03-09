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
__version__ = "0.2.0"

import xml.sax
import sqlite3
import sys
import getopt

from xml.sax.saxutils import XMLGenerator

class JMDictHandler(xml.sax.ContentHandler):
    def __init__(self, aCur):
        self.mCur = aCur

        self.mReadings = ""
        self.mReadingsPrio = ""
        self.mWritings = ""
        self.mWritingsPrio = ""
        
        self.mSense = ""
        self.mSenseId = 1
        self.mCurrentSenseId = 0

        self.mSeq = 0
        self.mText = ""
        self.mCurrentLang = ""
        
        self.mLang = ""
        self.mStartSense = False

        self.mKeb = ""
        self.mKePri = False

        self.mReb = ""
        self.mRePri = False

        self.mEntryOpened = False

    def calculateParts(self, aString):
        result = ""

        for i in range(1, len(aString)):
            if result != "":
                result = result + " "
            result = result + aString[i:]

        return result

    def insertTranslation(self):
        self.mCur.execute("INSERT INTO DictionaryTranslation (seq, lang, gloss) " \
                                  + "VALUES (?, ?, ?)", \
                                  (self.mSeq, self.mCurrentLang, self.mSense))
        
    def insertEntry(self):
        self.mCur.execute("INSERT INTO DictionaryEntry (seq, readingsPrio, readingsPrioParts, " \
                          + "readings, readingsParts, writingsPrio, writingsPrioParts, " \
                          + "writings, writingsParts) " \
                          + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", \
                          (self.mSeq, self.mReadingsPrio, self.calculateParts(self.mReadingsPrio), \
                           self.mReadings, self.calculateParts(self.mReadings), \
                           self.mWritingsPrio, self.calculateParts(self.mWritingsPrio), \
                           self.mWritings, self.calculateParts(self.mWritings)))
        
    def endElement(self, aName):
        if aName == "ent_seq":
            self.mSeq = int(self.mText)
        elif aName == "gloss":
            if self.mSenseId == self.mCurrentSenseId:
                self.mSense = self.mSense + ", " + self.mText
            else:
                self.mSense = self.mSense + "\n" + str(self.mSenseId) + ". " + self.mText
                self.mCurrentSenseId = self.mSenseId
        elif aName == "k_ele":
            if self.mKePri == True:
                if self.mWritingsPrio != "":
                    self.mWritingsPrio = self.mWritingsPrio + " "
                self.mWritingsPrio = self.mWritingsPrio + self.mKeb
            else:
                if self.mWritings != "":
                    self.mWritings = self.mWritings + " "
                self.mWritings = self.mWritings + self.mKeb
            self.mKeb = ""
            self.mKePri = False
        elif aName == "keb":
            self.mKeb = self.mText
        elif aName == "ke_pri":
            self.mKePri = True
        elif aName == "re_pri":
            self.mRePri = True
        elif aName == "r_ele":
            if self.mRePri == True:
                if self.mReadingsPrio != "":
                    self.mReadingsPrio = self.mReadingsPrio + " "
                self.mReadingsPrio = self.mReadingsPrio + self.mReb
            else:
                if self.mReadings != "":
                    self.mReadings = self.mReadings + " "
                self.mReadings = self.mReadings + self.mReb
            self.mReb = ""
            self.mRePri = False
        elif aName == "reb":
            self.mReb = self.mText
        elif aName == "entry":
            self.insertEntry()
            
            if self.mSense != "":
                self.insertTranslation()
            self.mCurrentLang = ""
            self.mWritings = ""
            self.mWritingsPrio = ""
            self.mReadings = ""
            self.mReadingsPrio = ""
            self.mSense = ""
            self.mSenseId = 1
            self.mCurrentSenseId = 0
            self.mEntryOpened = False
        self.mText = ""
        
    def startElement(self, aName, aAttrs):
        if "xml:lang" in aAttrs:
            self.mLang = aAttrs["xml:lang"]
        else:
            self.mLang = "eng"

        if aName == "sense":
            self.mStartSense = True
            
            if self.mEntryOpened == False:
                self.mEntryOpened = True
        elif (aName == "pos" or aName == "gloss") and self.mStartSense:
            self.mStartSense = False
            
            if self.mLang == "":
                self.mLang = "eng"
        
            if not self.mCurrentLang == self.mLang:
                if self.mSense != "":
                    self.insertTranslation()
                self.mSense = ""
                self.mSenseId = 1
                self.mCurrentSenseId = 0
                self.mCurrentLang = self.mLang
            else:
                self.mSenseId = self.mSenseId + 1

    def characters(self, aContent):
        if len(aContent.strip()) > 0:
            self.mText = self.mText + aContent

HELP_STRING = """usage: sumatora-index.py -d <date> -i <JMdict input file> -o <JMdict.db output file>"""

def main(argv):
    inputfile = ""
    outputfile = ""
    date = ""

    try:
        opts, args = getopt.getopt(argv, "hi:o:d:", ["ifile=", "ofile=", "date="])
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
        elif opt in ("-d", "--date"):
            date = arg
            
    if inputfile == "" or outputfile == "" or date == "":
        print(HELP_STRING)
        sys.exit(2)

    conn = sqlite3.connect(outputfile, isolation_level=None)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS DictionaryEntry")
    cur.execute("DROP TABLE IF EXISTS DictionaryTranslation")
    cur.execute("DROP TABLE IF EXISTS DictionaryControl")
    cur.execute("DROP TABLE IF EXISTS DictionaryIndex")
    cur.execute("DROP TABLE IF EXISTS DictionaryBookmark")
    cur.execute("DROP TABLE IF EXISTS DictionarySearchResult")
    
    cur.execute("CREATE TABLE DictionaryEntry (seq INTEGER, readingsPrio TEXT, " \
                + "readingsPrioParts TEXT, readings TEXT, readingsParts TEXT, " \
                + "writingsPrio TEXT, writingsPrioParts TEXT, writings TEXT, " \
                + "writingsParts TEXT, PRIMARY KEY (seq))")
    cur.execute("CREATE TABLE DictionaryTranslation (seq INTEGER, lang TEXT NOT NULL, " \
                + "gloss TEXT, PRIMARY KEY (seq, lang))")
    cur.execute("CREATE TABLE DictionaryBookmark (seq INTEGER, bookmark INTEGER, " \
                + "PRIMARY KEY (seq))")
    cur.execute("CREATE TABLE DictionaryControl (control TEXT NOT NULL, value INTEGER, " \
                + "PRIMARY KEY (control))")
    cur.execute("CREATE VIRTUAL TABLE DictionaryIndex USING fts4(content=\"DictionaryEntry\", " \
                + "readingsPrio, readingsPrioParts, readings, readingsParts, " \
                + "writingsPrio, writingsPrioParts, writings, writingsParts)")
    cur.execute("CREATE TABLE DictionarySearchResult (entryOrder INTEGER, seq INTEGER, " \
                + "readingsPrio TEXT, " \
                + "readings TEXT, " \
                + "writingsPrio TEXT, writings TEXT, " \
                + "lang TEXT, gloss TEXT, PRIMARY KEY (seq))")

    cur.execute("BEGIN TRANSACTION")
    
    handler = JMDictHandler(cur)
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)
    
    f = open(inputfile, "r")
    
    parser.parse(f)
    
    f.close()

    cur.execute("INSERT INTO DictionaryControl (control, value) VALUES (?, ?)", \
                ("date", date))
    cur.execute("INSERT INTO DictionaryControl (control, value) VALUES (?, ?)", \
                ("version", 2))

    # Test bookmarks
    #cur.execute("INSERT INTO DictionaryBookmark (seq, bookmark) VALUES (?, ?)", \
    #            (1311110, 1))
    #cur.execute("INSERT INTO DictionaryBookmark (seq, bookmark) VALUES (?, ?)", \
    #            (1311125, 1))

                
    cur.execute("END TRANSACTION")

    cur.execute("INSERT INTO DictionaryIndex (DictionaryIndex) VALUES ('rebuild')")

if __name__ == "__main__":
    main(sys.argv[1:])
