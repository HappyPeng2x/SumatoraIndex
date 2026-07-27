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

`is_primary` is set on exactly one row per entry: the highest-`(score,
is_common)` candidate among rows that are not `is_search_only`, not simply the
first form JMdict happens to list. `is_search_only` is set for JMdict
`sK`/`sk`-tagged forms (search-only kanji/kana) — these remain valid
`SearchTerm` rows but should never be shown as a headline or in an
alternate-forms table; clients should filter `WHERE is_search_only = 0` when
building anything user-visible from `EntryForm`.

#### Building an Alternate-Forms Table

`EntryForm` plus `FormTag` contain everything needed to build a Jitendex-style
alternate-forms matrix (kanji forms as columns, readings as rows, cell
validity/badges) without any further storage-format parsing.

Columns — visible writing forms, in display order:

```sql
SELECT form_id, text
FROM EntryForm
WHERE entry_id = :entry_id AND form_type = 'writing' AND is_search_only = 0
GROUP BY text
ORDER BY MIN(ord);
```

Rows that bridge to at least one kanji column — readings that appear as the
`reading` of some writing-form row:

```sql
SELECT DISTINCT reading
FROM EntryForm
WHERE entry_id = :entry_id AND form_type = 'writing'
  AND reading IS NOT NULL AND is_search_only = 0;
```

Readings with no kanji bridge at all (JMdict `re_nokanji`-style readings) —
belong in the `∅` column group instead of a normal row: every visible
`form_type = 'reading'` row whose `text` never appears in the bridging-readings
query above.

```sql
SELECT text
FROM EntryForm
WHERE entry_id = :entry_id AND form_type = 'reading' AND is_search_only = 0
  AND text NOT IN (
    SELECT reading FROM EntryForm
    WHERE entry_id = :entry_id AND form_type = 'writing'
      AND reading IS NOT NULL AND is_search_only = 0
  );
```

Cell validity/badge for one (reading, kanji-form) pair — a cell is valid if a
matching writing-form row exists; its badge comes from that row's `FormTag`
rows (map `Tag.code` to a badge class client-side, e.g. `rK`/`rk` → rare,
`iK`/`ik`/`io` → irregular, `oK`/`ok` → old):

```sql
SELECT f.form_id, t.code, t.label
FROM EntryForm f
LEFT JOIN FormTag ft ON ft.form_id = f.form_id
LEFT JOIN Tag t ON t.tag_id = ft.tag_id
WHERE f.entry_id = :entry_id AND f.form_type = 'writing'
  AND f.text = :kanji_form AND f.reading = :reading;
```

If the whole entry has exactly one writing form and one bridging reading (the
common case), clients should omit the alternate-forms table entirely rather
than render a trivial one-cell matrix — this can be decided from the row
counts above without any additional query.

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

`SenseReference.target_sense_id` and `.preview_text` are populated for every
reference that resolves to a `target_entry_id`: `target_sense_id` points at
the specific sense named by a `headword・reading・N` xref suffix, or the
target entry's first sense otherwise; `preview_text` is that sense's
semicolon-joined `main`-type English glosses, so clients can render a
Jitendex-style target preview without an extra join at render time. Note this
preview is always in English regardless of the installed gloss language pack,
since `SenseReference` lives in the language-neutral core pack while
`SenseGloss` is per-language.

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

## Web Search Pack

`sumatora_web_search.db` is a read-only forward-search index for the PWA's
online mode. It is published uncompressed so SQLite WASM can query it through
HTTP range requests, then use the returned JMdict sequence numbers to fetch
pre-rendered entries from gitender.

It is built from scratch rather than by pruning `sumatora_core.db`:

```sql
CREATE TABLE WebSearchResult (
    search_id  INTEGER PRIMARY KEY,
    source_key INTEGER NOT NULL,
    entry_id   INTEGER NOT NULL,
    script_order INTEGER NOT NULL,
    priority   INTEGER NOT NULL,
    entry_score INTEGER NOT NULL
);

CREATE VIRTUAL TABLE WebSearchFts USING fts5(
    normalized,
    content='',
    columnsize=0,
    detail=column,
    prefix='1 2 3 4'
);

CREATE TABLE WebSearchPrefixTop (
    script_order   INTEGER NOT NULL,
    prefix         TEXT NOT NULL,
    priority_class INTEGER NOT NULL,
    entry_score    INTEGER NOT NULL,
    entry_id       INTEGER NOT NULL,
    source_key     INTEGER NOT NULL,
    PRIMARY KEY (
        script_order, prefix, priority_class,
        entry_score DESC, entry_id, source_key
    )
) WITHOUT ROWID;
```

Only `word` terms in the `writing`, `kana`, and `romaji` scripts are included.
`WebSearchFts.rowid` equals `WebSearchResult.search_id`.

The database is optimized for latency rather than minimum artifact size:

- Contentless FTS avoids storing normalized terms twice.
- One-to-four-character FTS prefix indexes accelerate short prefixes.
- A 16 KiB SQLite page size reduces range requests without making random
  cold reads excessively large.
- `Entry.source_key` is stored directly, avoiding access to the full core pack
  before fetching gitender content.
- `script_order`, `priority`, `entry_score`, and `entry_id` preserve Android's
  tier, rank, and deterministic tie-break ordering without querying the core
  pack.
- `WebSearchPrefixTop` covers whichever `(script, prefix)` pairs are actually
  broad, not a fixed prefix length. At build time, every prefix of every
  `word` search term (lengths 1-8, either script) is counted; any
  `(script_order, prefix, priority_class)` group with more than 50 raw
  candidates is materialized, capped to its top 80 rows (already sorted in
  Android tier order: `entry_score DESC, entry_id`). A length-based cutoff
  doesn't work here — breadth doesn't track length. One-character kana
  prefixes average 3000+ candidates, but so do a handful of common single
  kanji (大: 2158) and even some three-character kana prefixes (ショウ:
  2000), while most three- and four-character prefixes of either script have
  only a few candidates and are already cheap to query live. Against a real
  v14-era database this selects ~2600 groups (~190K rows total) — smaller
  than a naive "every 1-2 char kana prefix" table, while covering every
  script and length that actually needs it. A query for a prefix that
  wasn't broad enough to materialize simply finds no rows and falls back to
  live FTS, which is fine because narrow prefixes are cheap regardless.

  Prefixes are generated from `WebSearchFts`'s own tokenizer output (via
  `fts5vocab('main', 'WebSearchFts', 'instance')`), not from
  `substr(normalized, 1, n)`. Some `normalized` values contain an internal
  separator (e.g. the middle dot in `アーリー・アメリカン`), which the
  tokenizer splits into two tokens (`アーリー`, `アメリカン`); a `MATCH`
  query can match the second token even though the whole string doesn't
  start with it. Reading prefixes from the same token index `MATCH` itself
  reads from guarantees agreement, without reimplementing FTS5's tokenizer
  rules by hand.

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

## Web Gloss Pack

`sumatora_web_gloss_{lang}.db` is a small, range-request-friendly reverse
(translation) prefix index for the PWA's online mode, one file per gloss
language, published alongside the corresponding `sumatora_gloss_{lang}.db`.

### Pack version 1 (covering indexes only, `user_version = 1`)

```sql
CREATE TABLE WebGlossPrefixTop (
    prefix     TEXT NOT NULL,
    sense_ord  INTEGER NOT NULL,
    entry_id   INTEGER NOT NULL,
    source_key INTEGER NOT NULL,
    PRIMARY KEY (prefix, sense_ord, entry_id, source_key)
) WITHOUT ROWID;

CREATE TABLE WebGlossExactTop (
    term       TEXT NOT NULL,
    sense_ord  INTEGER NOT NULL,
    entry_id   INTEGER NOT NULL,
    source_key INTEGER NOT NULL,
    PRIMARY KEY (term, sense_ord, entry_id, source_key)
) WITHOUT ROWID;
```

Same rationale and selection rule as `WebSearchPrefixTop` (see the Web Search
Pack section above), applied to the reverse-gloss tier instead of the
forward-word tier: any `prefix` with more than 50 raw candidate entries is
materialized, capped to its top 80 rows ordered `sense_ord, entry_id` (the
same tie-break the live reverse-gloss query already uses: first matching
sense, then entry). Prefixes are read from `GlossSearchFts`'s own tokenizer
output via `fts5vocab(..., 'instance')`, not `substr()`, since multi-word
glosses tokenize on spaces (`"test drive"` → `test`, `drive`) exactly the
way `WebSearchFts`'s tokenizer splits on the Japanese middle dot.

Natural-language gloss prefixes are far broader than Japanese kana/kanji
ones: against the real v18 English gloss pack, even 5-character prefixes
average 22 candidates with some as high as ~3900, and shorter prefixes are
far worse (a single letter averages over 20,000). This table exists because
a live prefix scan over one of those is exactly what a single Latin letter
typed mid-romaji-entry triggers online (the forward/word search finds
nothing, so the reverse/gloss search runs) — one observed case took 215
HTTP range requests and 15+ seconds before this fix.

The same pack also carries `WebGlossExactTop`, for Android's *exact* gloss
tier (tried before the prefix tier):

Word/forward search's exact tier is safely left unaccelerated (see
`WebSearchPrefixTop` above) because homograph counts are inherently small.
That assumption does not carry over to gloss text: a single common word as
someone's *entire* gloss is ordinary English (24523 entries have exactly
`"a"` as a gloss token in real v18 data; 20848 have `"the"`; even `"t"` alone
has 610), so the exact tier needs the identical fix, just keyed by the full
token instead of a prefix of it. This was found live, after
`WebGlossPrefixTop` alone shipped: typing a single letter with a much
smaller exact-match count (e.g. `"w"`, 8 exact matches) worked fine, while
one with a larger count (`"t"`, 610) hung indefinitely — the exact tier's
live FTS scan has no timeout, so a synchronous HTTP-VFS read that needs
enough scattered range requests can block the search worker forever, not
just run slowly.

In v1, the pack carries only the two covering indexes — no full FTS5 table.
A prefix or term that wasn't broad enough to materialize falls back to a
live `GlossSearchFts` query on the already-attached
`sumatora_gloss_{lang}.db`, joined across to the core pack:

```sql
SELECT s.entry_id, e.source_key, s.ord
FROM gloss_eng.SenseGloss sg
JOIN main.Sense s ON s.sense_id = sg.sense_id
JOIN main.Entry e ON e.entry_id = s.entry_id
WHERE sg.rowid IN (
  SELECT rowid FROM gloss_eng.GlossSearchFts WHERE text MATCH ?
)
```

This cross-pack JOIN is fast locally (SQLite does indexed lookups into both
files on disk) but expensive over HTTP: each matched sense requires a random
page read into the 200 MB core pack. With the HTTP VFS cache at 16 MB, most
miss, and each miss is a synchronous `XMLHttpRequest`. A narrow term like
"therefore" matching ~60 gloss entries causes ~120 random core-pack reads
— measured at 97 HTTP Range requests taking 3-4 seconds online.

### Pack version 2 (covering indexes + full FTS5 fallback, `user_version = 2`)

Version 2 adds a self-contained FTS5 fallback that eliminates the cross-pack
JOIN entirely:

```sql
-- Pre-joined data: one row per SenseGloss.rowid, with the sense/entry
-- columns the gloss search needs. No JOIN to core at query time.
CREATE TABLE GlossAll (
    rowid INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL,
    source_key INTEGER NOT NULL,
    sense_ord INTEGER NOT NULL
);

-- Contentless FTS5 index (content='', columnsize=0) with detail=none.
-- detail=none drops column-level detail storage (matchinfo/highlight),
-- saving ~40% of the FTS index size, since the gloss search only needs
-- rowid lookup. Table-level MATCH syntax is required (GlossAllFts MATCH
-- '...') because detail=none disables column-qualified queries.
CREATE VIRTUAL TABLE GlossAllFts USING fts5(
    term,
    content='',
    columnsize=0,
    detail=none,
    prefix='1 2 3 4 5 6 7 8'
);
```

These are populated at build time from the already-attached gloss and core
packs:

```sql
-- Pre-join every SenseGloss row with its entry/sense data
INSERT INTO GlossAll(rowid, entry_id, source_key, sense_ord)
SELECT sg.rowid, s.entry_id, CAST(e.source_key AS INTEGER), s.ord
FROM gloss.SenseGloss sg
JOIN core.Sense s ON s.sense_id = sg.sense_id
JOIN core.Entry e ON e.entry_id = s.entry_id;

-- Index the raw gloss text (tokenized by FTS5's default tokenizer)
INSERT INTO GlossAllFts(rowid, term)
SELECT sg.rowid, sg.text
FROM gloss.SenseGloss sg;
```

At query time, a term that misses the covering tables runs:

```sql
SELECT ga.entry_id, ga.source_key, ga.sense_ord
FROM webgloss.GlossAll ga
WHERE ga.rowid IN (
  SELECT rowid FROM webgloss.GlossAllFts WHERE GlossAllFts MATCH '"therefore"*'
)
```

Everything stays within the small webgloss pack — no cross-pack JOIN, no
touching the 200 MB core pack at all. The FTS5 index and data table are
contiguous within one 21 MB file, so even a broad prefix like `"the"*`
(~23,000 matches) reads from sequentially-stored FTS postings, benefiting
from the HTTP VFS's super-page merging.

### Two-tier query strategy

The PWA worker uses a three-tier fallback for reverse-gloss matching:

1. **Covering table hit** (`WebGlossPrefixTop` / `WebGlossExactTop`): A
   single indexed seek returns pre-ranked, pre-joined results for common
   prefixes and terms. Instant — one HTTP Range request.

2. **Full FTS5 fallback** (`GlossAllFts` + `GlossAll`, v2+): An FTS5 scan
   within the webgloss pack, followed by a `GlossAll` lookup (single-pack
   index seek per matched rowid). No core pack involved. Fast — ~10-30
   HTTP Range requests for a typical prefix, served from contiguous pages
   the super-page merger coalesces efficiently.

3. **Cross-pack live-FTS fallback** (pre-v2 or no webgloss pack): FTS5 in
   the gloss pack, JOINed to Sense and Entry in the core pack. This is the
   slow fallback retained for backward compatibility with v1 webgloss packs
   and for the local SQL-assembly path that already has the core pack open
   on disk.

For a PWA with a v2 webgloss pack, tier 2 serves every term that tier 1
doesn't cover — the 3-4 second wait for uncommon English terms like
"therefore" or "sycophant" drops to the same ~200-500 ms range as forward
search.

### Size

Measured English pack output from `split-sumatora-packs.py`:

| Version | Contents | Size |
|---|---|---|
| v1 | WebGlossPrefixTop, WebGlossExactTop | 21 MB |
| **v2** | WebGlossPrefixTop, WebGlossExactTop, **GlossAll, GlossAllFts** | **41 MB** |

The covering tables alone are 21 MB; adding the full FTS5 index brings the
total to 41 MB. If the covering tables were removed in favor of the FTS5
index alone (tier 2 for everything), the pack would be 21 MB — the same size
as the current v1 pack, with complete coverage but without the single-seek
fast path for the broadest prefixes. The combined 41 MB design keeps instant
response for common prefixes while providing fast-enough fallback for
everything else.

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
| `EntryForm` | name writings/readings, one row per valid kanji/reading pair (same expansion as JMdict words) |
| `FormFuriganaSegment` | display-ready ruby for name kanji forms, when built with `--kanjidic2` |
| `NameTranslation` | name translations |
| `EntryTag` / `Tag` | name type tags |
| `SearchTerm` / `SearchTermFts` | name search |

`EntryForm.is_primary` for names is chosen by `is_common`, same as words —
not by JMnedict source order. JMnedict doesn't carry JMdict's finer-grained
irregular-form tags (`iK`/`rK`/`io`), so there is no `is_search_only`
equivalent for names.

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

Examples are ranked and capped per entry at build time: candidate sentences
are sorted by Japanese sentence character length (shorter first) and only the
best 8 per entry are kept. `EntryExample.ord` reflects this rank — `0` is the
best/first example to show — so clients can simply `ORDER BY ord` and take
as many as their UI has room for, instead of implementing their own
selection or ranking policy.

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
