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
__email__ = "nicolas.centa@happypeng.org"
__license__ = "GPLv3"
__maintainer__ = "developer"
__status__ = "Production"
__version__ = "0.2.0"

import sqlite3
import sys
import getopt
import libxml2
import json

from xml.sax import xmlreader, saxutils, SAXParseException, SAXException


class Locator(xmlreader.Locator):
    """SAX Locator adapter for libxml2.xmlTextReaderLocator"""

    def __init__(self, locator):
        self.__locator = locator

    def getColumnNumber(self):
        "Return the column number where the current event ends."
        return -1

    def getLineNumber(self):
        "Return the line number where the current event ends."
        return self.__locator.LineNumber()

    def getPublicId(self):
        "Return the public identifier for the current event."
        return None

    def getSystemId(self):
        "Return the system identifier for the current event."
        return self.__locator.BaseURI()


class LibXml2Reader(xmlreader.XMLReader):
    def __init__(self):
        xmlreader.XMLReader.__init__(self)
        self.__errors = None
        self.__parsing = 0

    def _errorHandler(self, arg, msg, severity, locator):
        if self.__errors is None:
            self.__errors = []
        self.__errors.append((severity,
                              SAXParseException(msg, None,
                                                Locator(locator))))

    def _reportErrors(self, fatal):
        for severity, exception in self.__errors:
            if severity in (libxml2.PARSER_SEVERITY_VALIDITY_WARNING,
                            libxml2.PARSER_SEVERITY_WARNING):
                self._err_handler.warning(exception)
            else:
                # when fatal is set, the parse will stop;
                # we consider that the last error reported
                # is the fatal one.
                if fatal and exception is self.__errors[-1][1]:
                    self._err_handler.fatalError(exception)
                else:
                    self._err_handler.error(exception)
        self.__errors = None

    def parse(self, source):
        self.__parsing = 1
        try:
            # prepare source and create reader
            source = saxutils.prepare_input_source(source)
            input = libxml2.inputBuffer(source.getByteStream())
            reader = input.newTextReader(source.getSystemId())

            reader.SetErrorHandler(self._errorHandler, None)
            # configure reader
            reader.SetParserProp(libxml2.PARSER_LOADDTD, 1)
            reader.SetParserProp(libxml2.PARSER_DEFAULTATTRS, 1)
            reader.SetParserProp(libxml2.PARSER_SUBST_ENTITIES, 0)
            reader.SetParserProp(libxml2.PARSER_VALIDATE, 0)
            # we reuse attribute maps (for a slight performance gain)
            attributesImpl = xmlreader.AttributesImpl({})
            # start loop
            self._cont_handler.startDocument()

            while 1:
                r = reader.Read()
                # check for errors
                if r == 1:
                    pass
                    if self.__errors is not None:
                        self._reportErrors(0)
                elif r == 0:
                    if self.__errors is not None:
                        self._reportErrors(0)
                    break  # end of parse
                else:
                    if self.__errors is not None:
                        self._reportErrors(1)
                    else:
                        self._err_handler.fatalError(
                            SAXException("Read failed (no details available)"))
                    break  # fatal parse error
                # get node type
                nodeType = reader.NodeType()
                # Element
                if nodeType == 1:
                    eltName = reader.Name()
                    attributesImpl._attrs = attrs = {}
                    while reader.MoveToNextAttribute():
                        attName = reader.Name()
                        attrs[attName] = reader.Value()
                    reader.MoveToElement()
                    self._cont_handler.startElement(eltName, attributesImpl)
                    if reader.IsEmptyElement():
                        self._cont_handler.endElement(eltName)
                # EndElement
                elif nodeType == 15:
                    self._cont_handler.endElement(reader.Name())
                # Text
                elif nodeType == 3:
                    self._cont_handler.characters(reader.Value())
                # SignificantWhitespace
                elif nodeType == 14:
                    self._cont_handler.characters(reader.Value())
                # EntityReference
                elif nodeType == 5:
                    # Treating entity as such
                    self._cont_handler.entity(reader.Name())
                elif nodeType == 10:
                    # We parse the doctype with a SAX parser
                    nodeText = str(reader.CurrentNode())
                    entityDeclParser = libxml2.createPushParser(
                        self._cont_handler,
                        nodeText, len(nodeText),
                        "doctype")
                    entityDeclParser.parseChunk("", 0, 1)
                    pass
                # Ignore all other node types
            if r == 0:
                self._cont_handler.endDocument()
            reader.Close()
        finally:
            self.__parsing = 0


def listElementCount(aTable):
    count = 0
    if type(aTable) is list:
        for ele in aTable:
            count = count + listElementCount(ele)
    else:
        count = count + 1
    return count


def noneOrJsonDumps(aTable):
    if (listElementCount(aTable)) > 0:
        return json.dumps(aTable, ensure_ascii=False)
    else:
        return None


class JMDictHandler():
    def __init__(self, aCur):
        self.mCur = aCur

        self.mReadings = ""
        self.mReadingsPrio = ""
        self.mWritings = ""
        self.mWritingsPrio = ""

        self.mSenseId = 1
        self.mCurrentSenseId = 0

        self.mSeq = 0
        self.mText = ""
        self.mCurrentLang = ""
        self.mEntity = ""

        self.mLang = ""
        self.mStartSense = False

        self.mKeb = ""
        self.mKePri = False

        self.mReb = ""
        self.mRePri = False

        self.mEntryOpened = False

        self.mSense = []

        self.mPos = []
        self.mXref = []
        self.mAnt = []
        self.mMisc = []
        self.mLSource = []
        self.mDial = []
        self.mSInf = []
        self.mField = []

        self.mSenseArray = []

        self.mPosArray = []
        self.mXrefArray = []
        self.mAntArray = []
        self.mMiscArray = []
        self.mLSourceArray = []
        self.mDialArray = []
        self.mSInfArray = []
        self.mFieldArray = []

        self.mDeclaredEntities = {}

        self.mLSourceLang = ""

    def serializeSet(self, aSet):
        r = ""
        for s in aSet:
            if r != "":
                r = r + " " + s
            else:
                r = s
        return r

    def calculateParts(self, aString):
        s = set()
        for e in aString.split(" "):
            s |= self.calculatePartsElement(e)
        return self.serializeSet(s)

    def calculatePartsElement(self, aString):
        s = set()
        for i in range(1, len(aString)):
            s |= {aString[i:]}
        return s

    def insertTranslation(self):
        try:
            self.mCur.execute("INSERT INTO DictionaryTranslation "
                              + "(seq, lang, gloss) "
                              + "VALUES (?, ?, ?)",
                              (self.mSeq, self.mCurrentLang,
                               json.dumps(self.mSenseArray,
                                          ensure_ascii=False)))
        except Exception:
            print("DictionaryTranslation: ignoring seq " + str(self.mSeq) +
                  " lang " + self.mCurrentLang + " because of error")

    def insertEntry(self):
        try:
            self.mCur.execute("INSERT INTO DictionaryEntry "
                              + "(seq, readingsPrio, readingsPrioParts, "
                              + "readings, readingsParts, "
                              + "writingsPrio, writingsPrioParts, "
                              + "writings, writingsParts, pos, "
                              + "xref, ant, misc, lsource, "
                              + "dial, s_inf, field) "
                              + "VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
                              + "?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (self.mSeq, self.mReadingsPrio,
                               self.calculateParts(self.mReadingsPrio),
                               self.mReadings,
                               self.calculateParts(self.mReadings),
                               self.mWritingsPrio,
                               self.calculateParts(self.mWritingsPrio),
                               self.mWritings,
                               self.calculateParts(self.mWritings),
                               noneOrJsonDumps(self.mPosArray),
                               noneOrJsonDumps(self.mXrefArray),
                               noneOrJsonDumps(self.mAntArray),
                               noneOrJsonDumps(self.mMiscArray),
                               noneOrJsonDumps(self.mLSourceArray),
                               noneOrJsonDumps(self.mDialArray),
                               noneOrJsonDumps(self.mSInfArray),
                               noneOrJsonDumps(self.mFieldArray)))
        except sqlite3.Error:
            print("DictionaryEntry: ignoring seq " + str(self.mSeq) +
                  " because of error")

    def startDocument(self):
        pass

    def endElement(self, aName):
        if aName == "ent_seq":
            self.mSeq = int(self.mText)
        elif aName == "gloss":
            self.mSense = self.mSense + [self.mText]
        elif aName == "sense":
            self.mSenseArray = self.mSenseArray + [self.mSense]
            self.mSense = []

            if self.mCurrentLang == "eng":
                self.mPosArray = self.mPosArray + [self.mPos]
                self.mXrefArray = self.mXrefArray + [self.mXref]
                self.mAntArray = self.mAntArray + [self.mAnt]
                self.mMiscArray = self.mMiscArray + [self.mMisc]
                self.mLSourceArray = self.mLSourceArray + [self.mLSource]
                self.mDialArray = self.mDialArray + [self.mDial]
                self.mSInfArray = self.mSInfArray + [self.mSInf]
                self.mFieldArray = self.mFieldArray + [self.mField]

            self.mPos = []
            self.mXref = []
            self.mAnt = []
            self.mMisc = []
            self.mLSource = []
            self.mDial = []
            self.mSInf = []
            self.mField = []
        elif aName == "k_ele":
            if self.mKePri is True:
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
            if self.mRePri is True:
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

            if len(self.mSenseArray) != 0:
                self.insertTranslation()
                self.mSenseArray = []
            self.mCurrentLang = ""
            self.mWritings = ""
            self.mWritingsPrio = ""
            self.mReadings = ""
            self.mReadingsPrio = ""
            self.mSenseId = 1
            self.mCurrentSenseId = 0
            self.mEntryOpened = False

            self.mSense = []

            self.mPos = []
            self.mXref = []
            self.mAnt = []
            self.mMisc = []
            self.mLSource = []
            self.mDial = []
            self.mSInf = []
            self.mField = []

            self.mSenseArray = []

            self.mPosArray = []
            self.mXrefArray = []
            self.mAntArray = []
            self.mMiscArray = []
            self.mLSourceArray = []
            self.mDialArray = []
            self.mSInfArray = []
            self.mFieldArray = []
        elif aName == "pos":
            self.mPos = self.mPos + [self.mEntity]
        elif aName == "xref":
            self.mXref = self.mXref + [self.mText]
        elif aName == "ant":
            self.mAnt = self.mAnt + [self.mText]
        elif aName == "misc":
            self.mMisc = self.mMisc + [self.mEntity]
        elif aName == "lsource":
            self.mLSource = self.mLSource + [{self.mLSourceLang: self.mText}]
            self.mLSourceLang = ""
        elif aName == "dial":
            self.mDial = self.mDial + [self.mEntity]
        elif aName == "s_inf":
            self.mSInf = self.mSInf + [self.mText]
        elif aName == "field":
            self.mField = self.mField + [self.mEntity]

        self.mText = ""
        self.mEntity = ""

    def startElement(self, aName, aAttrs):
        if aAttrs is not None and "xml:lang" in aAttrs:
            self.mLang = aAttrs["xml:lang"]
        else:
            self.mLang = "eng"

        if aName == "sense":
            self.mStartSense = True

            if self.mEntryOpened is False:
                self.mEntryOpened = True
        elif (aName == "pos" or aName == "gloss") and self.mStartSense:
            self.mStartSense = False

            if self.mLang == "":
                self.mLang = "eng"

            if not self.mCurrentLang == self.mLang:
                if len(self.mSenseArray) != 0:
                    self.insertTranslation()
                    self.mSenseArray = []
                self.mSense = []
                self.mSenseId = 1
                self.mCurrentSenseId = 0
                self.mCurrentLang = self.mLang
            else:
                self.mSenseId = self.mSenseId + 1
        elif aName == "lsource":
            if aAttrs is not None and "xml:lang" in aAttrs:
                self.mLSourceLang = aAttrs["xml:lang"]

    def characters(self, aContent):
        if len(aContent.strip()) > 0:
            self.mText = self.mText + aContent

    def entity(self, aEntity):
        if len(self.mEntity.strip()) > 0:
            self.mEntity = self.mEntity + " " + aEntity
        else:
            self.mEntity = aEntity

    def endDocument(self):
        pass

    def entityDecl(self, name, type, externalID, systemID, content):
        self.mDeclaredEntities[name] = content


HELP_STRING = "usage: sumatora-index.py -d <date> -i " \
    + "<JMdict input file> -o <JMdict.db output file>"


def main(argv):
    inputfile = ""
    outputfile = ""
    date = ""

    try:
        opts, args = getopt.getopt(argv, "hi:o:d:",
                                   ["ifile=", "ofile=", "date="])
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
    cur.execute("DROP TABLE IF EXISTS DictionaryEntity")

    cur.execute("CREATE TABLE DictionaryEntry (seq INTEGER, "
                + "readingsPrio TEXT, "
                + "readingsPrioParts TEXT, readings TEXT, "
                + "readingsParts TEXT, "
                + "writingsPrio TEXT, writingsPrioParts TEXT, "
                + "writings TEXT, "
                + "writingsParts TEXT, pos TEXT, "
                + "xref TEXT, ant TEXT, misc TEXT, "
                + "lsource TEXT, dial TEXT, s_inf TEXT, "
                + "field TEXT, PRIMARY KEY (seq))")
    cur.execute("CREATE TABLE DictionaryTranslation (seq INTEGER, "
                + "lang TEXT NOT NULL, "
                + "gloss TEXT, PRIMARY KEY (seq, lang))")
    cur.execute("CREATE TABLE DictionaryControl "
                + "(control TEXT NOT NULL, value INTEGER, "
                + "PRIMARY KEY (control))")
    cur.execute("CREATE VIRTUAL TABLE DictionaryIndex "
                + "USING fts4(content=\"DictionaryEntry\", "
                + "readingsPrio, readingsPrioParts, readings, readingsParts, "
                + "writingsPrio, writingsPrioParts, writings, writingsParts)")
    cur.execute("CREATE TABLE DictionaryEntity "
                + "(name TEXT NOT NULL, content TEXT, PRIMARY KEY (name))")

    cur.execute("BEGIN TRANSACTION")

    handler = JMDictHandler(cur)

    f = open(inputfile, "rb")
    parser = LibXml2Reader()

    parser.setContentHandler(handler)
    parser.parse(f)

    f.close()

    cur.execute("INSERT INTO DictionaryControl (control, value) VALUES (?, ?)",
                ("date", date))
    cur.execute("INSERT INTO DictionaryControl (control, value) VALUES (?, ?)",
                ("version", 3))

    cur.execute("END TRANSACTION")

    for e in handler.mDeclaredEntities:
        cur.execute("INSERT INTO DictionaryEntity "
                    + "(name, content) VALUES (?, ?)",
                    (e, handler.mDeclaredEntities[e]))

    cur.execute("INSERT INTO DictionaryIndex "
                + "(DictionaryIndex) VALUES ('rebuild')")


if __name__ == "__main__":
    main(sys.argv[1:])
