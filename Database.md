# Sumatora Database Structure

This document describes the schema-v2 database layout used by
`build-sumatora-db.py` and `split-sumatora-packs.py`.

The build still preserves the git-friendly pipeline:

```text
XML/source data -> JSON repositories -> monolithic sumatora.db -> installable packs
```

The monolithic `sumatora.db` is useful for validation and pack generation. Phone
distribution should use packs.

## Pack Files

Default English install:

| File | Required | Contents |
|---|---:|---|
| `sumatora_core.db` | yes | JMdict word entries, forms, senses, tags, furigana, references, form rules, exact/prefix search |
| `sumatora_gloss_eng.db` | yes for English | English glosses and English reverse-search FTS |

Optional packs:

| File | Contents |
|---|---|
| `sumatora_search_suffix.db` | suffix/substring search support for word forms |
| `sumatora_names.db` | JMnedict names, name translations, name-type tags, name search |
| `sumatora_pitch.db` | pitch accent rows and links to word forms |
| `sumatora_kanji.db` | KANJIDIC2 character details and kanji search |
| `sumatora_examples_{lang}.db` | Tatoeba examples, segmented Japanese text, matched token, optional `sense_id` |
| `sumatora_gloss_{lang}.db` | one language's glosses and reverse-search FTS |

Measured English pack output from `/tmp/sumatora-packs-eng`:

| File | Size | zstd `-6` |
|---|---:|---:|
| `sumatora_core.db` | 240M | 82M |
| `sumatora_gloss_eng.db` | 53M | 21M |
| `sumatora_search_suffix.db` | 272M | 88M |
| `sumatora_names.db` | 418M | 124M |
| `sumatora_pitch.db` | 52M | 15M |
| `sumatora_kanji.db` | 8.3M | 2.8M |
| `sumatora_examples_eng.db` | 5.6M | 2.4M |

The default English install is therefore about `293M` uncompressed, or `103M`
compressed before any app-specific packaging overhead.

## Core Pack

`sumatora_core.db` contains language-neutral JMdict word display and forward
search.

### `BuildMetadata`

| Column | Type | Description |
|---|---|---|
| `key` | TEXT PK | Metadata key |
| `value` | TEXT | Metadata value |

Important keys include `schema_version`, source counts, build timestamp, and
source version identifiers when available.

### `DataSource`

Source attribution table.

| Column | Type |
|---|---|
| `source_id` | INTEGER PK |
| `code` | TEXT UNIQUE |
| `name` | TEXT |
| `url` | TEXT |
| `license` | TEXT |
| `attribution` | TEXT |

### `Entry`

One renderable dictionary entry.

| Column | Type | Description |
|---|---|---|
| `entry_id` | INTEGER PK | Internal stable row id |
| `source_id` | INTEGER | Source table id |
| `source_key` | TEXT | JMdict sequence number as text |
| `entry_type` | TEXT | `word` in core |
| `sort_key` | TEXT | Optional sort key |
| `score` | INTEGER | Entry-level score |

### `EntryForm`

One searchable/renderable form. This is the central v2 table.

| Column | Type | Description |
|---|---|---|
| `form_id` | INTEGER PK |
| `entry_id` | INTEGER |
| `ord` | INTEGER | Source/display order |
| `form_type` | TEXT | `writing` or `reading` |
| `text` | TEXT | Written/kana form |
| `reading` | TEXT | Reading for writing forms when known |
| `is_primary` | INTEGER | Primary display form |
| `is_common` | INTEGER | Priority/common marker |
| `is_search_only` | INTEGER | Search-only redirect/variant marker |
| `score` | INTEGER | Form-level score |

JMdict writing forms are emitted per valid writing-reading pair. For example,
`人気` can have separate rows for `にんき` and `ひとけ`.

### `FormFuriganaSegment`

Display-ready ruby segments for a form.

| Column | Type |
|---|---|
| `form_id` | INTEGER |
| `ord` | INTEGER |
| `base` | TEXT |
| `ruby` | TEXT nullable |

Clients should render this directly instead of parsing bracket furigana.

### Tags

Tables:

| Table | Purpose |
|---|---|
| `Tag` | Shared tag dictionary |
| `FormTag` | Tags attached to forms |
| `EntryTag` | Tags attached to entries |
| `SenseGroupTag` | POS/misc/field/dialect tags attached to sense groups |

### Senses

Tables:

| Table | Purpose |
|---|---|
| `SenseGroup` | Ordered display grouping |
| `Sense` | One sense row |
| `SenseNote` | Sense information notes |
| `SenseLanguageSource` | Loanword/source-language details |
| `SenseAppliesToForm` | Replacement for `stagk`/`stagr` parsing |
| `SenseReference` | Cross-references and antonyms with resolved targets where possible |

`SenseAppliesToForm` lets the app filter senses using the matched `form_id`.

### Deinflection

| Table | Purpose |
|---|---|
| `FormRule` | Rules valid for each form |
| `DeinflectionRule` | Rule labels |

The app still generates deinflection candidates. The DB verifies whether the
matched `form_id` supports a candidate rule.

### Forward Search

#### `SearchTerm`

One searchable form.

| Column | Type | Description |
|---|---|---|
| `search_id` | INTEGER PK |
| `entry_id` | INTEGER |
| `form_id` | INTEGER nullable |
| `term` | TEXT |
| `normalized` | TEXT |
| `script` | TEXT | `writing`, `kana`, `romaji`, `gloss`, `name` |
| `priority` | INTEGER |
| `score` | INTEGER |
| `is_prefix_searchable` | INTEGER |
| `is_substring_searchable` | INTEGER |

#### `SearchTermFts`

FTS5 index over `SearchTerm`.

```sql
CREATE VIRTUAL TABLE SearchTermFts USING fts5(
    term,
    normalized,
    content='SearchTerm',
    content_rowid='search_id',
    columnsize=0
);
```

`columnsize=0` keeps FTS matching but avoids FTS docsize storage.

## Gloss Language Packs

`sumatora_gloss_{lang}.db` contains one language's translations.

### `Sense`

A minimal copy of `Sense` is kept so `SenseGloss.sense_id` can be resolved to
`entry_id` inside the language pack.

### `SenseGloss`

| Column | Type |
|---|---|
| `sense_id` | INTEGER |
| `lang` | TEXT |
| `ord` | INTEGER |
| `text` | TEXT |
| `gloss_type` | TEXT |

### `GlossSearchFts`

Reverse gloss search FTS. It indexes `SenseGloss` directly; there is no separate
duplicated `GlossSearch` content table.

```sql
CREATE VIRTUAL TABLE GlossSearchFts USING fts5(
    text,
    content='SenseGloss',
    content_rowid='rowid',
    columnsize=0
);
```

Example reverse-search query:

```sql
SELECT sg.sense_id, s.entry_id, sg.text
FROM gloss_eng.GlossSearchFts AS f
JOIN gloss_eng.SenseGloss AS sg ON sg.rowid = f.rowid
JOIN gloss_eng.Sense AS s ON s.sense_id = sg.sense_id
WHERE GlossSearchFts MATCH ?;
```

## Suffix Search Pack

`sumatora_search_suffix.db` contains fast substring/suffix lookup.

### `SearchTerm`

Word-only `SearchTerm` rows needed to interpret suffix hits.

### `SearchSuffix`

| Column | Type |
|---|---|
| `search_id` | INTEGER |
| `suffix` | TEXT |

Indexes:

```sql
CREATE INDEX SearchSuffixText ON SearchSuffix(suffix);
```

This pack is optional because it is large. Without it, exact, prefix, kana, and
deinflection search still work from `sumatora_core.db`; fast substring search is
disabled or must use a slower fallback.

## Names Pack

`sumatora_names.db` contains proper names from JMnedict.

Important tables:

| Table | Purpose |
|---|---|
| `Entry` | `entry_type='name'` |
| `EntryForm` | name writings/readings |
| `NameTranslation` | name translations |
| `EntryTag` / `Tag` | name type tags |
| `SearchTerm` / `SearchTermFts` | name search |

This pack is optional because JMnedict is very large.

## Pitch Pack

`sumatora_pitch.db` contains pitch accents.

| Table | Purpose |
|---|---|
| `PitchAccent` | `(word, reading, source_id)` |
| `PitchPattern` | ordered pitch drop positions |
| `FormPitch` | links pitch rows to core `form_id` values |

`FormPitch.confidence` is `exact` or `reading_fallback`.

## Kanji Pack

`sumatora_kanji.db` contains KANJIDIC2 details.

| Table | Purpose |
|---|---|
| `Entry` / `EntryForm` | kanji lookup rows |
| `KanjiEntry` | strokes, grade, JLPT, frequency, radical |
| `KanjiReading` | on/kun/nanori readings |
| `KanjiMeaning` | meanings by language |
| `SearchTerm` / `SearchTermFts` | kanji search |

## Example Packs

`sumatora_examples_{lang}.db` contains Tatoeba examples for one language.

| Table | Purpose |
|---|---|
| `Example` | translated example sentence metadata |
| `ExampleSegment` | display-ready Japanese sentence ruby segments |
| `EntryExample` | links examples to entries and optionally senses |

`EntryExample.sense_id` is populated when the Tatoeba index supplies a sense
number and the target sense can be resolved.

## App Attachment Model

Open `sumatora_core.db` as the main DB, then attach installed packs:

```sql
ATTACH DATABASE '/path/sumatora_gloss_eng.db' AS gloss_eng;
ATTACH DATABASE '/path/sumatora_search_suffix.db' AS suffix;
ATTACH DATABASE '/path/sumatora_names.db' AS names;
ATTACH DATABASE '/path/sumatora_pitch.db' AS pitch;
ATTACH DATABASE '/path/sumatora_kanji.db' AS kanji;
ATTACH DATABASE '/path/sumatora_examples_eng.db' AS examples_eng;
```

Clients should carry query result metadata:

```text
entry_id
form_id
match_kind
matched_text
original_query
dictionary_form
deinflection_label
rank
```

The renderer then loads core display rows by `entry_id`, filters senses by
matched `form_id`, and fetches optional data from attached packs.

## Build Commands

Build monolithic v2 DB:

```sh
python3 build-sumatora-db.py -o output/
```

Build monolithic DB and English install packs:

```sh
python3 build-sumatora-db.py -o output/ --split-packs
```

Build selected language packs:

```sh
python3 build-sumatora-db.py -o output/ --split-packs --pack-lang eng --pack-lang ger
```

Build every language pack present in the monolithic DB:

```sh
python3 build-sumatora-db.py -o output/ --split-packs --all-pack-languages
```

Split an existing monolithic DB:

```sh
python3 split-sumatora-packs.py -i output/sumatora.db -o output/packs --lang eng
```

## Notes

- Cross-database foreign keys are not available in SQLite. Pack tables preserve
  the same ids (`entry_id`, `form_id`, `sense_id`) and the app joins across
  attached databases using those ids.
- The monolithic DB remains useful for validation, but it is not the recommended
  phone distribution artifact.
- Pack splitting keeps the v2 structured display model while avoiding a large
  mandatory install.
