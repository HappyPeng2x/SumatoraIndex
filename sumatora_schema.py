"""Single source of truth for the SumatoraIndex v2 (schema-v2.md) SQLite schema.

Every stage-2 (*-to-sumatora-db.py) generator imports init_db() from here instead
of redefining CREATE TABLE statements itself.
"""

import os
import sqlite3

SCHEMA_VERSION = 2

_DDL = """
CREATE TABLE BuildMetadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE DataSource (
    source_id   INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    url         TEXT,
    license     TEXT,
    attribution TEXT
);

CREATE TABLE Entry (
    entry_id    INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES DataSource(source_id),
    source_key  TEXT NOT NULL,
    entry_type  TEXT NOT NULL CHECK (entry_type IN ('word', 'name', 'kanji')),
    sort_key    TEXT,
    score       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, source_key)
);

CREATE TABLE EntrySource (
    entry_id  INTEGER NOT NULL REFERENCES Entry(entry_id),
    source_id INTEGER NOT NULL REFERENCES DataSource(source_id),
    note      TEXT,
    url       TEXT,
    PRIMARY KEY (entry_id, source_id)
);

CREATE TABLE EntryForm (
    form_id       INTEGER PRIMARY KEY,
    entry_id      INTEGER NOT NULL REFERENCES Entry(entry_id),
    ord           INTEGER NOT NULL,
    form_type     TEXT NOT NULL CHECK (form_type IN ('writing', 'reading')),
    text          TEXT NOT NULL,
    reading       TEXT,
    is_primary    INTEGER NOT NULL CHECK (is_primary IN (0, 1)),
    is_common     INTEGER NOT NULL CHECK (is_common IN (0, 1)),
    is_search_only INTEGER NOT NULL DEFAULT 0 CHECK (is_search_only IN (0, 1)),
    score         INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX EntryFormUnique
ON EntryForm(entry_id, form_type, text, IFNULL(reading, ''));

CREATE TABLE FormTag (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    tag_id  INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (form_id, tag_id)
);

CREATE TABLE FormFuriganaSegment (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    ord     INTEGER NOT NULL,
    base    TEXT NOT NULL,
    ruby    TEXT,
    PRIMARY KEY (form_id, ord)
);

CREATE TABLE Tag (
    tag_id      INTEGER PRIMARY KEY,
    code        TEXT NOT NULL,
    category    TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category, code)
);

CREATE TABLE SenseGroup (
    sense_group_id INTEGER PRIMARY KEY,
    entry_id       INTEGER NOT NULL REFERENCES Entry(entry_id),
    ord            INTEGER NOT NULL,
    display_number INTEGER
);

CREATE TABLE SenseGroupTag (
    sense_group_id INTEGER NOT NULL REFERENCES SenseGroup(sense_group_id),
    tag_id         INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (sense_group_id, tag_id)
);

CREATE TABLE Sense (
    sense_id       INTEGER PRIMARY KEY,
    entry_id       INTEGER NOT NULL REFERENCES Entry(entry_id),
    sense_group_id INTEGER NOT NULL REFERENCES SenseGroup(sense_group_id),
    source_ord     INTEGER NOT NULL,
    ord            INTEGER NOT NULL,
    display_number INTEGER
);

CREATE TABLE SenseGloss (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    lang     TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    gloss_type TEXT NOT NULL DEFAULT 'main'
        CHECK (gloss_type IN ('main', 'literal', 'figurative', 'explanation')),
    PRIMARY KEY (sense_id, lang, ord, gloss_type)
);

CREATE TABLE SenseNote (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (sense_id, ord)
);

CREATE TABLE SenseLanguageSource (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    ord      INTEGER NOT NULL,
    lang     TEXT NOT NULL,
    text     TEXT,
    is_full  INTEGER NOT NULL CHECK (is_full IN (0, 1)),
    is_wasei INTEGER NOT NULL CHECK (is_wasei IN (0, 1)),
    PRIMARY KEY (sense_id, ord)
);

CREATE TABLE SenseAppliesToForm (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    form_id  INTEGER NOT NULL REFERENCES EntryForm(form_id),
    PRIMARY KEY (sense_id, form_id)
);

CREATE TABLE SenseReference (
    reference_id       INTEGER PRIMARY KEY,
    sense_id           INTEGER NOT NULL REFERENCES Sense(sense_id),
    ord                INTEGER NOT NULL,
    reference_type     TEXT NOT NULL CHECK (reference_type IN ('xref', 'antonym')),
    display_text       TEXT NOT NULL,
    target_entry_id    INTEGER REFERENCES Entry(entry_id),
    target_form_id     INTEGER REFERENCES EntryForm(form_id),
    target_sense_id    INTEGER REFERENCES Sense(sense_id),
    target_sense_number INTEGER,
    preview_text       TEXT
);

CREATE TABLE Example (
    example_id INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES DataSource(source_id),
    source_key TEXT NOT NULL,
    lang       TEXT NOT NULL,
    translation TEXT NOT NULL,
    UNIQUE (source_id, source_key, lang)
);

CREATE TABLE ExampleSegment (
    example_id INTEGER NOT NULL REFERENCES Example(example_id),
    ord        INTEGER NOT NULL,
    base       TEXT NOT NULL,
    ruby       TEXT,
    PRIMARY KEY (example_id, ord)
);

CREATE TABLE EntryExample (
    entry_id      INTEGER NOT NULL REFERENCES Entry(entry_id),
    example_id    INTEGER NOT NULL REFERENCES Example(example_id),
    ord           INTEGER NOT NULL,
    matched_text  TEXT,
    sense_id      INTEGER REFERENCES Sense(sense_id),
    PRIMARY KEY (entry_id, example_id)
);

CREATE TABLE PitchAccent (
    pitch_id INTEGER PRIMARY KEY,
    word     TEXT,
    reading  TEXT NOT NULL,
    source_id INTEGER REFERENCES DataSource(source_id),
    UNIQUE (word, reading, source_id)
);

CREATE TABLE PitchPattern (
    pitch_id INTEGER NOT NULL REFERENCES PitchAccent(pitch_id),
    ord      INTEGER NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (pitch_id, ord)
);

CREATE TABLE FormPitch (
    form_id  INTEGER NOT NULL REFERENCES EntryForm(form_id),
    pitch_id INTEGER NOT NULL REFERENCES PitchAccent(pitch_id),
    confidence TEXT NOT NULL CHECK (confidence IN ('exact', 'reading_fallback')),
    PRIMARY KEY (form_id, pitch_id)
);

CREATE TABLE NameTranslation (
    entry_id INTEGER NOT NULL REFERENCES Entry(entry_id),
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (entry_id, ord)
);

CREATE TABLE EntryTag (
    entry_id INTEGER NOT NULL REFERENCES Entry(entry_id),
    tag_id   INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (entry_id, tag_id)
);

CREATE TABLE KanjiEntry (
    character TEXT PRIMARY KEY,
    entry_id  INTEGER UNIQUE REFERENCES Entry(entry_id),
    strokes   INTEGER,
    grade     INTEGER,
    jlpt      INTEGER,
    frequency INTEGER,
    radical   INTEGER
);

CREATE TABLE KanjiReading (
    character TEXT NOT NULL REFERENCES KanjiEntry(character),
    reading_type TEXT NOT NULL CHECK (reading_type IN ('on', 'kun', 'nanori')),
    ord       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (character, reading_type, ord)
);

CREATE TABLE KanjiMeaning (
    character TEXT NOT NULL REFERENCES KanjiEntry(character),
    lang      TEXT NOT NULL,
    ord       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (character, lang, ord)
);

CREATE TABLE SearchTerm (
    search_id   INTEGER PRIMARY KEY,
    entry_id    INTEGER NOT NULL REFERENCES Entry(entry_id),
    form_id     INTEGER REFERENCES EntryForm(form_id),
    term        TEXT NOT NULL,
    normalized  TEXT NOT NULL,
    script      TEXT NOT NULL CHECK (script IN ('writing', 'kana', 'romaji', 'gloss', 'name')),
    priority    INTEGER NOT NULL DEFAULT 0,
    score       INTEGER NOT NULL DEFAULT 0,
    is_prefix_searchable INTEGER NOT NULL DEFAULT 1 CHECK (is_prefix_searchable IN (0, 1)),
    is_substring_searchable INTEGER NOT NULL DEFAULT 1 CHECK (is_substring_searchable IN (0, 1))
);

CREATE VIRTUAL TABLE SearchTermFts USING fts5(
    term,
    normalized,
    content='SearchTerm',
    content_rowid='search_id',
    columnsize=0
);

CREATE TABLE SearchSuffix (
    search_id INTEGER NOT NULL REFERENCES SearchTerm(search_id),
    suffix    TEXT NOT NULL,
    PRIMARY KEY (search_id, suffix)
);

CREATE INDEX SearchSuffixText ON SearchSuffix(suffix);

CREATE VIRTUAL TABLE GlossSearchFts USING fts5(
    text,
    content='SenseGloss',
    content_rowid='rowid',
    columnsize=0
);

CREATE TABLE FormRule (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    rule    TEXT NOT NULL,
    PRIMARY KEY (form_id, rule)
);

CREATE TABLE DeinflectionRule (
    rule TEXT PRIMARY KEY,
    label TEXT NOT NULL
);

CREATE INDEX EntryType ON Entry(entry_type);
CREATE INDEX EntrySourceKey ON Entry(source_id, source_key);

CREATE INDEX EntryFormEntry ON EntryForm(entry_id, ord);
CREATE INDEX EntryFormText ON EntryForm(text);
CREATE INDEX EntryFormReading ON EntryForm(reading);

CREATE INDEX SenseEntry ON Sense(entry_id, ord);
CREATE INDEX SenseGroupEntry ON SenseGroup(entry_id, ord);
CREATE INDEX SenseAppliesForm ON SenseAppliesToForm(form_id, sense_id);

CREATE INDEX SenseGlossLang ON SenseGloss(lang, text);
CREATE INDEX SenseReferenceTarget ON SenseReference(target_entry_id);

CREATE INDEX EntryExampleEntry ON EntryExample(entry_id, ord);
CREATE INDEX FormPitchForm ON FormPitch(form_id);
CREATE INDEX PitchLookup ON PitchAccent(word, reading);
CREATE INDEX PitchReading ON PitchAccent(reading);

CREATE INDEX SearchTermNormalized ON SearchTerm(normalized, script);
CREATE INDEX SearchTermEntry ON SearchTerm(entry_id);
CREATE INDEX SearchTermForm ON SearchTerm(form_id);
CREATE INDEX FormRuleRule ON FormRule(rule, form_id);
"""

# Tag is referenced by FormTag before it is declared in the prose order of
# schema-v2.md; SQLite resolves forward references at DML time (not DDL time)
# as long as foreign_keys enforcement is off during CREATE, so table order
# above is fine to execute as a single script.

_DATA_SOURCES = [
    ('jmdict', 'JMdict', 'https://www.edrdg.org/jmdict/j_jmdict.html',
     'CC BY-SA 4.0', 'JMdict/EDICT project, Electronic Dictionary Research and Development Group'),
    ('jmnedict', 'JMnedict', 'https://www.edrdg.org/enamdict/enamdict_doc.html',
     'CC BY-SA 4.0', 'JMnedict, Electronic Dictionary Research and Development Group'),
    ('kanjidic2', 'KANJIDIC2', 'https://www.edrdg.org/wiki/index.php/KANJIDIC_Project',
     'CC BY-SA 4.0', 'KANJIDIC2, Electronic Dictionary Research and Development Group'),
    ('tatoeba', 'Tatoeba', 'https://tatoeba.org/', 'CC BY 2.0 FR', 'Tatoeba contributors'),
    ('unidic', 'UniDic', 'https://clrd.ninjal.ac.jp/unidic/', 'GPL v2.0 / LGPL v2.1 / BSD',
     'UniDic-cwj, National Institute for Japanese Language and Linguistics (NINJAL)'),
    ('pitch', 'Curated pitch accent data', None, None, 'SumatoraIndex curated TSV overlay'),
    ('sumatora_patches', 'SumatoraIndex entry patches', None, None, 'SumatoraIndex maintainers'),
]


def init_db(path):
    """Create sumatora.db with the full v2 schema and return the connection.

    Raises if tables already exist, so callers that want a clean rebuild should
    remove the file first (or use open_or_init_db, which does this check for you).
    """
    conn = sqlite3.connect(path)
    conn.executescript(_DDL)
    conn.executemany(
        'INSERT INTO DataSource (code, name, url, license, attribution) VALUES (?, ?, ?, ?, ?)',
        _DATA_SOURCES,
    )
    conn.commit()
    return conn


def open_or_init_db(path):
    """Open sumatora.db, creating it with the full v2 schema if it doesn't exist yet.

    Each stage-2 generator (kanjidic2-to-sumatora-db.py, jmdict-to-sumatora-db.py, ...)
    calls this with the same -d path; whichever one runs first creates the schema,
    later ones just add rows to the tables the earlier ones already populated.
    """
    if os.path.exists(path):
        return sqlite3.connect(path)
    return init_db(path)


def source_id(conn, code):
    row = conn.execute('SELECT source_id FROM DataSource WHERE code = ?', (code,)).fetchone()
    if row is None:
        raise KeyError(f'unknown DataSource code: {code!r}')
    return row[0]


def set_build_metadata(conn, **kwargs):
    conn.executemany(
        'INSERT OR REPLACE INTO BuildMetadata (key, value) VALUES (?, ?)',
        list(kwargs.items()),
    )
    conn.commit()
