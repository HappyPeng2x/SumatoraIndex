# Sumatora Dictionary Database Schema v2

This document proposes a new database schema for SumatoraIndex output.

The goal is not backward compatibility with the current Android database. The
goal is to generate databases that directly support SumatoraDictionary and
future equivalent clients such as web and desktop apps.

The schema separates three concerns:

1. **Source identity**: stable entry IDs and source attribution.
2. **Search**: fast lookup by writing, reading, romaji/kana-normalized reading,
   translation text, proper names, and deinflected forms.
3. **Rendering**: display-ready rows for headwords, furigana, senses, examples,
   cross-references, pitch, names, and kanji details.

The core design principle:

> SumatoraIndex should do dictionary-domain assembly once. Clients should render
> structured rows, not reverse-engineer parallel JSON blobs.

SQLite remains a good target because it works well on Android, desktop, and
server-side/web tooling.

## File Layout

There are two reasonable deployment models.

### Option A: One Main Database Plus Optional Assets

```text
sumatora.db
assets/
```

Pros:

- simplest for clients
- no `ATTACH DATABASE` coordination
- foreign keys can be used throughout
- easier web/desktop distribution

Cons:

- one large file
- language packs cannot be swapped independently

### Option B: Core Database Plus Language Databases

```text
sumatora_core.db
sumatora_eng.db
sumatora_ger.db
sumatora_examples_eng.db
...
```

Pros:

- users can install only selected languages
- smaller per-language updates

Cons:

- clients must attach several databases
- cross-database foreign keys are not available
- rendering assembly becomes more complicated

Recommended v2 default: **Option A**. If size becomes a real issue, split
translations/examples later while keeping the table shapes the same.

## Naming Conventions

- Primary keys use `INTEGER`.
- Source sequence IDs are preserved, but internal display IDs are separate.
- Ordered child rows use `ord INTEGER NOT NULL`.
- Booleans use `INTEGER NOT NULL CHECK (... IN (0, 1))`.
- JSON is reserved for genuinely open-ended data, not ordinary repeated
  structures.
- Search tables are allowed to duplicate display data for speed.

## Metadata Tables

### `BuildMetadata`

```sql
CREATE TABLE BuildMetadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Rows:

| key | Example |
|---|---|
| `schema_version` | `2` |
| `build_timestamp` | Unix timestamp |
| `jmdict_version` | source revision/date |
| `jmnedict_version` | source revision/date |
| `kanjidic2_version` | source revision/date |
| `tatoeba_version` | source revision/date |
| `sumatora_index_version` | generator version/git commit |

### `DataSource`

```sql
CREATE TABLE DataSource (
    source_id   INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    url         TEXT,
    license     TEXT,
    attribution TEXT
);
```

Examples:

- `jmdict`
- `jmnedict`
- `kanjidic2`
- `tatoeba`
- `unidic`
- `pitch`
- `sumatora_patches`

## Entry Identity

### `Entry`

One row per renderable dictionary entry.

```sql
CREATE TABLE Entry (
    entry_id    INTEGER PRIMARY KEY,
    source_id   INTEGER NOT NULL REFERENCES DataSource(source_id),
    source_key  TEXT NOT NULL,
    entry_type  TEXT NOT NULL CHECK (entry_type IN ('word', 'name', 'kanji')),
    sort_key    TEXT,
    score       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (source_id, source_key)
);
```

For JMdict, `source_key` is the JMdict sequence number as text. For JMnedict,
it is the JMnedict sequence number. For KANJIDIC2, it is the character.

### `EntrySource`

Optional extra attribution per entry.

```sql
CREATE TABLE EntrySource (
    entry_id  INTEGER NOT NULL REFERENCES Entry(entry_id),
    source_id INTEGER NOT NULL REFERENCES DataSource(source_id),
    note      TEXT,
    url       TEXT,
    PRIMARY KEY (entry_id, source_id)
);
```

## Forms and Headwords

Forms are the central bridge between search and rendering.

A JMdict entry may have several written forms and several readings. The current
schema stores these as space-separated strings and parallel JSON. In v2, each
searchable/renderable form is a row.

### `EntryForm`

```sql
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
```

Meaning:

- `form_type = 'writing'`: kanji/mixed written form such as `食べる`.
- `form_type = 'reading'`: kana-only form such as `たべる`.
- `reading` is filled for writing forms when a specific reading is known.
- `is_search_only` marks forms that should be searchable but visually treated as
  redirects/related forms.

For JMdict, the generator should create writing-form rows for valid
writing-reading pairs, not just raw kanji elements. That makes matched-form
rendering precise.

Examples:

| text | reading | type |
|---|---|---|
| `食べる` | `たべる` | `writing` |
| `たべる` | `NULL` | `reading` |
| `食物` | `しょくもつ` | `writing` |
| `食物` | `たべもの` | `writing` |

### `FormTag`

```sql
CREATE TABLE FormTag (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    tag_id  INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (form_id, tag_id)
);
```

Used for priority, rare, irregular, old kanji, obsolete reading, ateji, gikun,
and similar form-level tags.

### `FormFuriganaSegment`

```sql
CREATE TABLE FormFuriganaSegment (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    ord     INTEGER NOT NULL,
    base    TEXT NOT NULL,
    ruby    TEXT,
    PRIMARY KEY (form_id, ord)
);
```

This replaces bracket-notation furigana for client rendering. The generator can
still keep bracket notation in debug output, but clients should use this table.

Example:

| form | ord | base | ruby |
|---|---:|---|---|
| 食べ物 | 0 | 食 | た |
| 食べ物 | 1 | べ | NULL |
| 食べ物 | 2 | 物 | もの |

## Tags and Labels

### `Tag`

```sql
CREATE TABLE Tag (
    tag_id      INTEGER PRIMARY KEY,
    code        TEXT NOT NULL,
    category    TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (category, code)
);
```

Categories:

- `pos`
- `misc`
- `field`
- `dialect`
- `form`
- `name_type`
- `source`

The generator should expand JMdict/JMnedict entity codes here. Clients should
not maintain their own large static entity maps.

## Word Senses

### `SenseGroup`

Adjacent senses with the same structural tags can be grouped at build time.

```sql
CREATE TABLE SenseGroup (
    sense_group_id INTEGER PRIMARY KEY,
    entry_id       INTEGER NOT NULL REFERENCES Entry(entry_id),
    ord            INTEGER NOT NULL,
    display_number INTEGER
);
```

### `SenseGroupTag`

```sql
CREATE TABLE SenseGroupTag (
    sense_group_id INTEGER NOT NULL REFERENCES SenseGroup(sense_group_id),
    tag_id         INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (sense_group_id, tag_id)
);
```

Typical tags:

- part of speech
- field
- dialect
- misc usage labels

### `Sense`

```sql
CREATE TABLE Sense (
    sense_id       INTEGER PRIMARY KEY,
    entry_id       INTEGER NOT NULL REFERENCES Entry(entry_id),
    sense_group_id INTEGER NOT NULL REFERENCES SenseGroup(sense_group_id),
    source_ord     INTEGER NOT NULL,
    ord            INTEGER NOT NULL,
    display_number INTEGER
);
```

`source_ord` preserves the original JMdict sense index. `ord` is the display
order after filtering/grouping decisions that are independent of query match.

### `SenseGloss`

```sql
CREATE TABLE SenseGloss (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    lang     TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    gloss_type TEXT NOT NULL DEFAULT 'main'
        CHECK (gloss_type IN ('main', 'literal', 'figurative', 'explanation')),
    PRIMARY KEY (sense_id, lang, ord, gloss_type)
);
```

This replaces language-specific translation tables for display. Search can still
use FTS tables derived from this table.

### `SenseNote`

```sql
CREATE TABLE SenseNote (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (sense_id, ord)
);
```

### `SenseLanguageSource`

```sql
CREATE TABLE SenseLanguageSource (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    ord      INTEGER NOT NULL,
    lang     TEXT NOT NULL,
    text     TEXT,
    is_full  INTEGER NOT NULL CHECK (is_full IN (0, 1)),
    is_wasei INTEGER NOT NULL CHECK (is_wasei IN (0, 1)),
    PRIMARY KEY (sense_id, ord)
);
```

## Sense Applicability

Sense restrictions depend on the matched form. The database should represent
them directly instead of leaving clients to parse `stagk` and `stagr`.

### `SenseAppliesToForm`

```sql
CREATE TABLE SenseAppliesToForm (
    sense_id INTEGER NOT NULL REFERENCES Sense(sense_id),
    form_id  INTEGER NOT NULL REFERENCES EntryForm(form_id),
    PRIMARY KEY (sense_id, form_id)
);
```

Interpretation:

- If a sense has no rows in this table, it applies to all forms.
- If a sense has rows, it applies only to listed forms.

This is much easier for clients:

```sql
-- include a sense for matched :form_id
WHERE NOT EXISTS (
    SELECT 1 FROM SenseAppliesToForm a WHERE a.sense_id = Sense.sense_id
)
OR EXISTS (
    SELECT 1 FROM SenseAppliesToForm a
    WHERE a.sense_id = Sense.sense_id AND a.form_id = :form_id
)
```

## Cross-References and Antonyms

### `SenseReference`

```sql
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
```

The generator should resolve as much as possible. Clients can render:

- `display_text`
- tap target if `target_entry_id` exists
- sense jump if `target_sense_id` or `target_sense_number` exists
- preview gloss if `preview_text` exists

## Examples

Tatoeba examples should be structured for rendering.

### `Example`

```sql
CREATE TABLE Example (
    example_id INTEGER PRIMARY KEY,
    source_id  INTEGER NOT NULL REFERENCES DataSource(source_id),
    source_key TEXT NOT NULL,
    lang       TEXT NOT NULL,
    translation TEXT NOT NULL,
    UNIQUE (source_id, source_key, lang)
);
```

For Tatoeba, `source_key` is the Japanese sentence ID plus translation ID when
needed.

### `ExampleSegment`

```sql
CREATE TABLE ExampleSegment (
    example_id INTEGER NOT NULL REFERENCES Example(example_id),
    ord        INTEGER NOT NULL,
    base       TEXT NOT NULL,
    ruby       TEXT,
    PRIMARY KEY (example_id, ord)
);
```

This replaces `{expression;reading}` markup for client rendering.

### `EntryExample`

```sql
CREATE TABLE EntryExample (
    entry_id      INTEGER NOT NULL REFERENCES Entry(entry_id),
    example_id    INTEGER NOT NULL REFERENCES Example(example_id),
    ord           INTEGER NOT NULL,
    matched_text  TEXT,
    sense_id      INTEGER REFERENCES Sense(sense_id),
    PRIMARY KEY (entry_id, example_id)
);
```

`matched_text` tells clients what to highlight. If future linking becomes
sense-specific, `sense_id` can be filled.

## Pitch Accent

### `PitchAccent`

```sql
CREATE TABLE PitchAccent (
    pitch_id INTEGER PRIMARY KEY,
    word     TEXT,
    reading  TEXT NOT NULL,
    source_id INTEGER REFERENCES DataSource(source_id),
    UNIQUE (word, reading, source_id)
);
```

### `PitchPattern`

```sql
CREATE TABLE PitchPattern (
    pitch_id INTEGER NOT NULL REFERENCES PitchAccent(pitch_id),
    ord      INTEGER NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (pitch_id, ord)
);
```

### `FormPitch`

Optional precomputed form-to-pitch link.

```sql
CREATE TABLE FormPitch (
    form_id  INTEGER NOT NULL REFERENCES EntryForm(form_id),
    pitch_id INTEGER NOT NULL REFERENCES PitchAccent(pitch_id),
    confidence TEXT NOT NULL CHECK (confidence IN ('exact', 'reading_fallback')),
    PRIMARY KEY (form_id, pitch_id)
);
```

This lets clients show pitch for the matched form without guessing.

## Proper Names

Proper names can use the same `Entry` and `EntryForm` tables with
`entry_type = 'name'`.

Additional name-specific content:

### `NameTranslation`

```sql
CREATE TABLE NameTranslation (
    entry_id INTEGER NOT NULL REFERENCES Entry(entry_id),
    ord      INTEGER NOT NULL,
    text     TEXT NOT NULL,
    PRIMARY KEY (entry_id, ord)
);
```

Name type tags use `Tag.category = 'name_type'` and can attach through
`EntryTag`.

### `EntryTag`

```sql
CREATE TABLE EntryTag (
    entry_id INTEGER NOT NULL REFERENCES Entry(entry_id),
    tag_id   INTEGER NOT NULL REFERENCES Tag(tag_id),
    PRIMARY KEY (entry_id, tag_id)
);
```

This is useful for name types, entry-level priority tags, and source-level
labels.

## Kanji Entries

KANJIDIC2 can be integrated into the same `Entry` table with
`entry_type = 'kanji'`, or remain in dedicated tables. Dedicated tables are
cleaner.

### `KanjiEntry`

```sql
CREATE TABLE KanjiEntry (
    character TEXT PRIMARY KEY,
    entry_id  INTEGER UNIQUE REFERENCES Entry(entry_id),
    strokes   INTEGER,
    grade     INTEGER,
    jlpt      INTEGER,
    frequency INTEGER,
    radical   INTEGER
);
```

### `KanjiReading`

```sql
CREATE TABLE KanjiReading (
    character TEXT NOT NULL REFERENCES KanjiEntry(character),
    reading_type TEXT NOT NULL CHECK (reading_type IN ('on', 'kun', 'nanori')),
    ord       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (character, reading_type, ord)
);
```

### `KanjiMeaning`

```sql
CREATE TABLE KanjiMeaning (
    character TEXT NOT NULL REFERENCES KanjiEntry(character),
    lang      TEXT NOT NULL,
    ord       INTEGER NOT NULL,
    text      TEXT NOT NULL,
    PRIMARY KEY (character, lang, ord)
);
```

## Search Schema

The display schema is normalized. Search should be denormalized and fast.

### `SearchTerm`

One row per searchable form.

```sql
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
```

`normalized` should contain:

- writing forms as-is
- kana forms normalized to katakana
- romaji-normalized forms if desired
- lowercased gloss terms for translation search

### `SearchTermFts`

```sql
CREATE VIRTUAL TABLE SearchTermFts USING fts5(
    term,
    normalized,
    content='SearchTerm',
    content_rowid='search_id',
    columnsize=0
);
```

This replaces separate priority/non-priority FTS columns. Ranking can use
`SearchTerm.priority`, `SearchTerm.score`, exact/prefix/substr tier, and
`Entry.score`.

### `SearchSuffix`

FTS5 is not always ideal for Japanese substring search. Keep precomputed suffix
rows if substring search is important.

```sql
CREATE TABLE SearchSuffix (
    search_id INTEGER NOT NULL REFERENCES SearchTerm(search_id),
    suffix    TEXT NOT NULL,
    PRIMARY KEY (search_id, suffix)
);

CREATE INDEX SearchSuffixText ON SearchSuffix(suffix);
```

Or use a separate FTS table:

```sql
CREATE VIRTUAL TABLE SearchSuffixFts USING fts5(
    suffix,
    content=''
);
```

The current suffix-parts strategy can be preserved behind this cleaner table
shape.

### `GlossSearchFts`

```sql
CREATE VIRTUAL TABLE GlossSearchFts USING fts5(
    text,
    content='SenseGloss',
    content_rowid='rowid',
    columnsize=0
);
```

This supports reverse search without copying gloss text into a second content
table. Clients can join FTS rowids back to `SenseGloss.rowid`, then to `Sense`
for `entry_id`.

## Deinflection Support

The app can continue generating deinflection candidates, but the database should
make verification and result explanation cleaner.

### `FormRule`

```sql
CREATE TABLE FormRule (
    form_id INTEGER NOT NULL REFERENCES EntryForm(form_id),
    rule    TEXT NOT NULL,
    PRIMARY KEY (form_id, rule)
);
```

This improves on entry-level `rules`. If one form is inflectable and another is
not, clients can verify the matched form precisely.

Client flow:

1. Deinflect query into candidate `(dictionary_form, rule, label)`.
2. Search `SearchTerm` for `dictionary_form`.
3. Keep hits where `FormRule(form_id, rule)` exists.
4. Carry `original_query`, `dictionary_form`, and `label` into the display
   model.

### Optional `DeinflectionRule`

```sql
CREATE TABLE DeinflectionRule (
    rule TEXT PRIMARY KEY,
    label TEXT NOT NULL
);
```

This is mostly metadata; candidate generation still belongs in clients unless
SumatoraIndex also wants to generate a full deinflection index.

## Query Result Shape

All clients should be able to assemble this result from search tables:

```text
entry_id
form_id
match_kind        -- exact, prefix, substring, gloss, deinflection, name
matched_text
original_query
dictionary_form
deinflection_label
rank
```

Recommended temporary table:

```sql
CREATE TEMP TABLE QueryResult (
    query_result_id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    form_id INTEGER,
    match_kind TEXT NOT NULL,
    matched_text TEXT,
    original_query TEXT,
    dictionary_form TEXT,
    deinflection_label TEXT,
    rank INTEGER NOT NULL
);

CREATE UNIQUE INDEX QueryResultUnique
ON QueryResult(entry_id, IFNULL(form_id, -1), match_kind, IFNULL(dictionary_form, ''));
```

The renderer then receives `entry_id + form_id + match metadata`, which solves
many current weaknesses:

- correct furigana for the matched form
- correct pitch lookup
- correct sense applicability
- correct form highlighting
- better deinflection explanation

## Display Assembly Query

Clients can either:

1. Query child tables directly and assemble models in Kotlin/Swift/TypeScript.
2. Use generated JSON views for convenience.

For cross-platform apps, option 1 is more predictable. For web APIs, generated
JSON views may be useful.

Example core load:

```sql
SELECT *
FROM Entry
WHERE entry_id = :entry_id;

SELECT *
FROM EntryForm
WHERE entry_id = :entry_id
ORDER BY is_primary DESC, score DESC, ord;

SELECT *
FROM FormFuriganaSegment
WHERE form_id IN (SELECT form_id FROM EntryForm WHERE entry_id = :entry_id)
ORDER BY form_id, ord;

SELECT *
FROM SenseGroup
WHERE entry_id = :entry_id
ORDER BY ord;

SELECT *
FROM Sense
WHERE entry_id = :entry_id
AND (
    NOT EXISTS (SELECT 1 FROM SenseAppliesToForm a WHERE a.sense_id = Sense.sense_id)
    OR EXISTS (
        SELECT 1 FROM SenseAppliesToForm a
        WHERE a.sense_id = Sense.sense_id AND a.form_id = :matched_form_id
    )
)
ORDER BY ord;
```

## Compatibility With Current Features

| Current feature | v2 location |
|---|---|
| `readingsPrio`, `readings` | `EntryForm` rows |
| `writingsPrio`, `writings` | `EntryForm` rows |
| `furigana` JSON map | `FormFuriganaSegment` |
| `pos`, `misc`, `field`, `dial` | `Tag`, `SenseGroupTag` |
| `s_inf` | `SenseNote` |
| `lsource` | `SenseLanguageSource` |
| `xref`, `ant` | `SenseReference` |
| `stagk`, `stagr` | `SenseAppliesToForm` |
| `rules` | `FormRule` |
| `score` | `Entry.score`, `EntryForm.score`, `SearchTerm.score` |
| `ExamplesSummary` | `Example`, `ExampleSegment`, `EntryExample` |
| `ProperNounEntry` | `Entry(entry_type='name')`, `NameTranslation`, `EntryTag` |
| `kanjidic2.db` | `KanjiEntry`, `KanjiReading`, `KanjiMeaning` |
| `pitch.db` | `PitchAccent`, `PitchPattern`, `FormPitch` |

## Indexes

Recommended indexes:

```sql
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
```

## Build Pipeline Changes

SumatoraIndex should change from:

```text
JMdict JSON -> compact DictionaryEntry row with JSON columns
```

to:

```text
JMdict JSON
  -> Entry
  -> EntryForm / FormFuriganaSegment / FormTag / FormRule
  -> SenseGroup / Sense / SenseGloss / SenseNote / SenseLanguageSource
  -> SenseAppliesToForm / SenseReference
  -> SearchTerm / GlossSearchFts
```

Recommended implementation order:

1. Generate `Entry`, `EntryForm`, `Tag`, and `SenseGloss`.
2. Generate `SearchTerm` and rebuild `GlossSearchFts`.
3. Generate `FormFuriganaSegment`.
4. Generate `SenseGroup`, `SenseGroupTag`, `SenseNote`,
   `SenseLanguageSource`.
5. Generate `SenseAppliesToForm`.
6. Generate `SenseReference`.
7. Generate `Example`, `ExampleSegment`, `EntryExample`.
8. Generate `FormRule`.
9. Generate name, pitch, and kanji tables.
10. Update Android to consume `QueryResult(entry_id, form_id, match metadata)`.

## What Clients Should No Longer Do

Clients should no longer need to:

- split space-separated headword fields for core rendering
- parse bracket furigana
- parse `{expression;reading}` example markup
- parse parallel `pos`/`misc`/`field`/`dial` JSON arrays
- parse `stagk`/`stagr`
- resolve xrefs
- maintain large JMdict entity-label maps
- guess the matched form from the search term
- choose pitch from the first form when the matched form is known

Clients should still do:

- layout and styling
- user-language selection
- query-time deinflection candidate generation
- query result ranking policy if client-specific
- lazy loading and pagination
- history/bookmark/memo/tag user data

## Summary

The current schema is search-friendly but rendering-hostile. A v2 schema should
make forms, senses, tags, furigana, examples, references, pitch, and
applicability explicit.

The single most important change is `EntryForm` plus `form_id` in search
results. Once clients know exactly which form matched, rendering becomes simpler
and more correct:

- form-specific furigana
- form-specific pitch
- form-specific sense filtering
- form highlighting
- deinflection explanation

This turns SumatoraIndex from a database packer into a shared dictionary display
compiler for Android, desktop, web, and future clients.
