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
    def __init__(self, aOut):
        self.mOut = aOut

        self.mReadings = ""
        self.mWritings = ""
        
        self.mSense = ""
        self.mSenseId = 1

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

    def endElement(self, aName):
        if aName == "ent_seq":
            self.mSeq = int(self.mText)
        elif aName == "gloss":
            if self.mSense != "":
                self.mSense = self.mSense + "\n"
            self.mSense = self.mSense + str(self.mSenseId) + " - " + self.mText
        elif aName == "k_ele":
            if self.mWritings != "":
                self.mWritings = self.mWritings + " "
            if self.mKePri == True:
                self.mWritings = self.mWritings + "_" + self.mKeb
            else:
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
            if self.mReadings != "":
                self.mReadings = self.mReadings + " "
            if self.mRePri == True:
                self.mReadings = self.mReadings + "_" + self.mReb
            else:
                self.mReadings = self.mReadings + self.mReb                
            self.mReb = ""
            self.mRePri = False
        elif aName == "reb":
            self.mReb = self.mText
        elif aName == "entry":            
            if self.mSense != "":
                self.mOut.startElement("sense", {"lang" : self.mCurrentLang})
                self.mOut.characters(self.mSense)
                self.mOut.endElement("sense")
            self.mOut.endElement("entry")
            self.mCurrentLang = ""
            self.mWritings = ""
            self.mReadings = ""
            self.mGloss = ""
            self.mSense = ""
            self.mSenseId = 1
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
                self.mOut.startElement("entry", {"seq" : str(self.mSeq),
                                                 "writings" : self.mWritings,
                                                 "readings" : self.mReadings})
                self.mEntryOpened = True
        elif (aName == "pos" or aName == "gloss") and self.mStartSense:
            self.mStartSense = False
            
            if self.mLang == "":
                self.mLang = "eng"
        
            if not self.mCurrentLang == self.mLang:
                if self.mSense != "":
                    self.mOut.startElement("sense", {"lang" : self.mCurrentLang})
                    self.mOut.characters(self.mSense)
                    self.mOut.endElement("sense")
                self.mSense = ""
                self.mSenseId = 1
                self.mCurrentLang = self.mLang
            else:
                self.mSenseId = self.mSenseId + 1

    def characters(self, aContent):
        if len(aContent.strip()) > 0:
            self.mText = self.mText + aContent

HELP_STRING = """usage: sumatora-index.py -d <date> -i <JMdict input file> -o <JMdict.xml output file>"""

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

    of = open(outputfile, "w")
    gen = XMLGenerator(out=of, encoding="utf-8", short_empty_elements=True)
    gen.startDocument()
    gen.startElement("dict", {"version" : "1", "date" : date})

    handler = JMDictHandler(gen)
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)
    
    f = open(inputfile, "r")
    
    parser.parse(f)
    
    f.close()

    gen.endElement("dict")

    of.close()

if __name__ == "__main__":
   main(sys.argv[1:])
