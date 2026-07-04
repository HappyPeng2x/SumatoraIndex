# Sumatora Database Structure

Five SQLite databases are distributed:

| File | Built by | Contents |
|------|----------|----------|
| `jmdict.db` | `gitmdict-to-sqlite.py` | Dictionary entries, proper names, FTS5 indexes |
| `{lang}.db` | `gitmdict-to-sqlite.py` | Per-language gloss translations + FTS5 |
| `examples_{lang}.db` | `gitoeba-to-sqlite.py` | Tatoeba example sentences linked to entries |
| `kanjidic2.db` | `gitjidic2-to-sqlite.py` | Kanji character metadata |
| `pitch.db` | `gitch-to-sqlite.py` | Pitch accent data |

---

## jmdict.db

### DictionaryEntry

The main entry table. One row per JMdict entry.

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER PK | JMdict sequence number |
| `readingsPrio` | TEXT | Space-separated **priority** kana readings |
| `readings` | TEXT | Space-separated non-priority kana readings |
| `writingsPrio` | TEXT | Space-separated **priority** kanji writings |
| `writings` | TEXT | Space-separated non-priority kanji writings |
| `pos` | TEXT | JSON: per-sense arrays of part-of-speech codes |
| `xref` | TEXT | JSON: per-sense arrays of resolved cross-references (see format below) |
| `ant` | TEXT | JSON: per-sense arrays of resolved antonyms (same format as `xref`) |
| `misc` | TEXT | JSON: per-sense miscellaneous info |
| `lsource` | TEXT | JSON: per-sense language source info (see format below) |
| `dial` | TEXT | JSON: per-sense dialect codes |
| `s_inf` | TEXT | JSON: per-sense sense information strings |
| `field` | TEXT | JSON: per-sense field domain codes |
| `kanjiData` | TEXT | JSON: full kanji element array (see format below) |
| `kanaData` | TEXT | JSON: full kana element array (see format below) |
| `stagk` | TEXT | JSON: per-sense kanji form restrictions (NULL when unrestricted) |
| `stagr` | TEXT | JSON: per-sense reading form restrictions (NULL when unrestricted) |
| `furigana` | TEXT | JSON: map from kanji writing form to bracket-notation furigana string (see format below) |
| `rules` | TEXT | Space-separated deinflection rule codes, or NULL for uninflectable entries |
| `score` | INTEGER | Headword score: `+1` priority, `0` standard, `-1` irregular/rare |

**Indexes:**
- `DictionaryEntryRules ON DictionaryEntry (rules)` — for deinflection lookup
- `DictionaryEntryScore ON DictionaryEntry (score)` — for score-ordered result ranking

#### `kanjiData` format

Array of kanji element objects in the order they appear in JMdict (priority forms first, then non-priority). Each object:

```json
[
  {"text": "漢字形", "common": true, "tags": ["ichi1", "news1"]},
  {"text": "旧字体", "common": false, "tags": ["iK", "rK"]}
]
```

`tags` contains both priority codes (`ke_pri`: `ichi1`, `news1`, `nf*`, `spec1`, `spec2`, `gai1`, `gai2`) and information codes (`ke_inf`: `iK` irregular kanji, `io` outdated, `rK` rarely-used kanji, `oK` out-dated kanji, `ateji`).

#### `kanaData` format

Array of kana element objects in the same order as the source. Each object:

```json
[
  {"text": "よみかた", "common": true, "tags": ["ichi1"], "appliesToKanji": ["*"], "nokanji": false},
  {"text": "よみがな", "common": false, "tags": ["ok"], "appliesToKanji": ["漢字形"], "nokanji": false}
]
```

- `appliesToKanji`: list of kanji text values this reading applies to, or `["*"]` for all.
- `nokanji`: true when this reading is valid for the entry even without any kanji form (`<re_nokanji/>`).
- `tags` contains both `re_pri` priority codes and `re_inf` info codes (`ik` irregular kana, `ok` outdated, `gikun` gikun/jukujikun reading, etc.).

#### `lsource` format

```json
[[{"lang": "fra", "text": "mot", "full": true, "wasei": false}], []]
```

Outer array is per-sense; inner array is the language source list for that sense. Each object has `lang` (ISO 639-2), `text` (source word, may be empty), `full` (true = fully sourced, false = partial/`ls_type=part`), `wasei` (true = wasei-eigo).

#### `stagk` / `stagr` format

Per-sense arrays of form strings; NULL when every sense is unrestricted.

```json
[[], ["漢字形1"], []]
```

#### `furigana` format

JSON object mapping each kanji writing form to its bracket-notation furigana string. NULL when the entry has no kanji forms.

```json
{"食べ物": "食[た]べ物[もの]", "食物": "食[しょく]物[もつ]"}
```

Bracket notation: `base[ruby]` for kanji runs, plain text for kana runs.  To display headword ruby, look up the matched writing form in this map.

#### `xref` / `ant` format

Outer array indexed by sense (parallel to `pos`). Each element is an array of reference objects. References with a known `seq` have been resolved to a concrete entry; those without could not be resolved (display as plain text).

```json
[
  [{"text": "来る", "seq": 1547720}],
  [{"text": "行く", "seq": 1289010, "sense": 2}]
]
```

| Field | Type | Always present | Meaning |
|-------|------|----------------|---------|
| `text` | string | yes | Display form (kanji or kana) |
| `seq` | integer | no | Target entry sequence number |
| `sense` | integer | no | 1-based sense number within the target entry |

#### `rules` values

| Code | Part of speech |
|------|----------------|
| `v1` | Ichidan verb (食べる) |
| `v5` | Godan verb (書く, 飲む, …) |
| `vk` | Irregular くる |
| `vs` | Suru-verb (勉強する) |
| `vz` | Zuru-verb (感ずる) |
| `adj-i` | I-adjective (高い) |

Multiple codes are space-separated, e.g. `"v1 vs"` for 〜する variants of ichidan verbs.

---

### DictionaryIndex (FTS5, contentless)

FTS5 virtual table used for fast reading/writing lookup. **Contentless** (`content=""`): it stores only the FTS5 token index, not the original text. Column values must be retrieved from `DictionaryEntry`.

The `rowid` of each FTS5 row equals the `seq` of the corresponding `DictionaryEntry` row, so a MATCH result can be joined directly:

```sql
SELECT DictionaryEntry.*
FROM DictionaryEntry
WHERE seq IN (SELECT rowid FROM DictionaryIndex WHERE writingsPrio MATCH ?)
ORDER BY DictionaryEntry.score DESC
```

| Column | Description |
|---|---|
| `readingsPrioKana` | Priority readings converted to katakana |
| `readingsPrioKanaParts` | Space-separated katakana suffixes of each priority reading (enables substring search) |
| `readingsKana` | Non-priority readings converted to katakana |
| `readingsKanaParts` | Katakana suffixes of non-priority readings |
| `writingsPrio` | Priority kanji writings (verbatim) |
| `writingsPrioParts` | Character suffixes of each priority writing |
| `writings` | Non-priority kanji writings |
| `writingsParts` | Character suffixes of non-priority writings |

**Suffix-parts columns** store all suffixes starting from position 1 of each token (e.g. `カタカナ` → `タカナ カナ ナ`). A `MATCH term*` on a parts column finds entries where `term` appears as a substring within the original word.

**All kana columns store katakana.** Hiragana in the source data is converted to katakana before indexing. Search queries against these columns must also be katakana.

---

### DictionaryEntity

JMdict XML entity definitions (e.g. `v5k` → `"Godan verb with ku ending"`).

| Column | Type | Description |
|---|---|---|
| `name` | TEXT PK | Entity code |
| `content` | TEXT | Human-readable expansion |

---

### DictionaryControl

Key/value metadata for the database build.

| Column | Type |
|---|---|
| `control` | TEXT PK |
| `value` | INTEGER |

Rows present after a standard build:

| `control` | Meaning |
|-----------|---------|
| `build_timestamp` | Unix epoch (seconds) when the database was built |
| `format_version` | Schema/format version number (currently `1`) |
| `entry_count` | Number of rows in `DictionaryEntry` |

Consumers should check `format_version` on database open and refuse to use an unrecognized version.

---

### ProperNounEntry

One row per JMnedict entry (people, places, organisations, etc.).

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER PK | JMnedict sequence number |
| `readings` | TEXT | Space-separated kana readings |
| `writings` | TEXT | Space-separated kanji writings; empty string `''` for kana-only names |
| `types` | TEXT | JSON array of name type strings (see below) |
| `translations` | TEXT | JSON array of translation strings |

Common `types` values: `place`, `person`, `given`, `surname`, `station`, `company`, `org`, `product`, `work`.

---

### ProperNounIndex (FTS5, contentless)

FTS5 virtual table for proper name lookup. Rowid equals `ProperNounEntry.rowid` (which equals `seq`).

```sql
CREATE VIRTUAL TABLE ProperNounIndex USING fts5(
    readingsKana, readingsKanaParts,
    writings, writingsParts,
    content="")
```

Column layout mirrors `DictionaryIndex` (kana in katakana, suffix-parts columns for substring search). Apply the same tier search strategy as for `DictionaryIndex`.

---

## {lang}.db  (e.g. eng.db, ger.db)

### DictionaryTranslation

One row per sense per entry. `gloss` contains all glosses for a single sense joined with `, `.

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER | JMdict sequence number (foreign key to DictionaryEntry.seq) |
| `gloss_id` | INTEGER | Sense index within the entry (0-based) |
| `gloss` | TEXT | Comma-joined gloss strings for this sense |
| PRIMARY KEY | (seq, gloss_id) | |

### DictionaryTranslationIndex (FTS5, content table)

FTS5 virtual table backed by `DictionaryTranslation`. The `rowid` of the FTS5 row equals the `rowid` of the corresponding `DictionaryTranslation` row (the implicit SQLite rowid, not `seq`).

```sql
CREATE VIRTUAL TABLE DictionaryTranslationIndex USING fts5(gloss, content="DictionaryTranslation")
```

To find entries matching a gloss term:

```sql
SELECT dt.seq
FROM DictionaryTranslationIndex AS fts
JOIN DictionaryTranslation AS dt ON dt.rowid = fts.rowid
WHERE fts.gloss MATCH ?
```

---

## examples_{lang}.db  (e.g. examples_eng.db)

Built by `gitoeba-to-sqlite.py` from a Tatoeba sentence corpus linked to JMdict entries.

### ExamplePairs

One row per (entry, sentence) link.

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER | JMdict sequence number |
| `sentence_id` | INTEGER | Tatoeba sentence ID |
| `sentence` | TEXT | Japanese sentence text (with `{expression;reading}` furigana markup) |
| `translation` | TEXT | Translation in the target language |
| `matched_token` | TEXT | Surface writing of the token that caused this sentence to be linked to the entry |

### ExamplesSummary (VIEW)

Aggregates `ExamplePairs` to one row per `seq` (entry), collecting all sentences into parallel JSON arrays.

```sql
CREATE VIEW ExamplesSummary AS
    SELECT seq,
           json_group_array(sentence)      AS sentences,
           json_group_array(translation)   AS translations,
           json_group_array(matched_token) AS matched_tokens
    FROM ExamplePairs
    GROUP BY seq
```

`sentences`, `translations`, and `matched_tokens` are parallel JSON arrays of the same length: `sentences[i]` is paired with `translations[i]`, and `matched_tokens[i]` is the surface writing of the token that linked that specific sentence to the entry.

---

## kanjidic2.db

Built by `gitjidic2-to-sqlite.py` from a gitjidic2 JSON repository (produced by `kanjidic2-to-git.py`).

### KanjiEntry

One row per kanji character.

| Column | Type | Description |
|---|---|---|
| `char` | TEXT PK | Single kanji character |
| `"on"` | TEXT | Space-separated on readings (katakana) — column name is SQL-quoted because `on` is a reserved word |
| `kun` | TEXT | Space-separated kun readings (hiragana; okurigana after `.`) |
| `meanings` | TEXT | JSON array of English meaning strings |
| `strokes` | INTEGER | Stroke count (NULL if absent) |
| `grade` | INTEGER | School grade: 1–6 kyōiku, 8 jōyō/jinmeiyō; NULL otherwise |
| `jlpt` | INTEGER | Old JLPT level 1–4 (4 = N5, 1 = N1); NULL if not listed |
| `freq` | INTEGER | Newspaper frequency rank; NULL if not listed |
| `radical` | INTEGER | Classical radical number |

### KanjiControl

| `control` | Meaning |
|-----------|---------|
| `build_timestamp` | Unix epoch when the database was built |
| `char_count` | Number of rows in `KanjiEntry` |

---

## pitch.db

Built by `gitch-to-sqlite.py` from a gitch JSON repository (produced by `pitch-to-git.py`).

### PitchAccent

One row per (word, reading) pair. Multiple valid pitch patterns for the same pair are merged into a single row.

| Column | Type | Description |
|---|---|---|
| `word` | TEXT | Dictionary headword (kanji or kana surface form) |
| `reading` | TEXT | Hiragana reading |
| `pitches` | TEXT | JSON array of integer pitch drop positions |
| PRIMARY KEY | (word, reading) | |

**Index:** `PitchAccentReading ON PitchAccent (reading)` — for reading-only lookup when no kanji form is known.

**Pitch position encoding:**
- `0` — heiban: rises after mora 1, stays high (LH…H)
- `1` — atamadaka: drops after mora 1 (HL…L)
- `N` — drops after mora N; if N equals the mora count of the reading the word is odaka (LH…HL)

### PitchControl

| `control` | Meaning |
|-----------|---------|
| `build_timestamp` | Unix epoch when the database was built |
| `entry_count` | Number of rows in `PitchAccent` |

---

## How apps consume the databases

The main databases are opened individually; the language database is ATTACHed:

```sql
ATTACH DATABASE '/path/to/eng.db' AS "eng"
-- then query as: DictionaryEntry, eng.DictionaryTranslation, eng.DictionaryTranslationIndex
```

For examples, attach separately:

```sql
ATTACH DATABASE '/path/to/examples_eng.db' AS "examples_eng"
-- then join: LEFT JOIN examples_eng.ExamplesSummary ON DictionaryEntry.seq = ExamplesSummary.seq
```

### Search strategy (priority order)

Forward search steps (stopping when enough results are found), results ordered by `DictionaryEntry.score DESC` within each tier:

1. `writingsPrio MATCH term` — exact kanji, priority
2. `readingsPrioKana MATCH kata` — exact kana, priority
3. `writings MATCH term` — exact kanji, non-priority
4. `readingsKana MATCH kata` — exact kana, non-priority
5. `writingsPrio MATCH term*` — prefix kanji, priority
6. `readingsPrioKana MATCH kata*` — prefix kana, priority
7. `writings MATCH term*` — prefix kanji, non-priority
8. `readingsKana MATCH kata*` — prefix kana, non-priority
9. `writingsPrioParts MATCH term*` — substring kanji, priority
10. `readingsPrioKanaParts MATCH kata*` — substring kana, priority
11. `writingsParts MATCH term*` — substring kanji, non-priority
12. `readingsKanaParts MATCH kata*` — substring kana, non-priority
13. `DictionaryTranslationIndex.gloss MATCH term` — exact gloss
14. `DictionaryTranslationIndex.gloss MATCH term*` — prefix gloss

`kata` is the search term normalized to katakana (hiragana is converted before querying).

Apply the same tier strategy to `ProperNounIndex` for proper name lookup, and display the results in a separate section.

---

## Building the databases

### Full build (recommended)

```sh
# All databases except examples and pitch (which need external data):
python3 generate-jmdict.py -o output/

# With pitch accent data:
python3 generate-jmdict.py -o output/ --pitch-tsv pitch_data.tsv

# With Tatoeba example sentences:
python3 generate-jmdict.py -o output/ --gitoeba ~/Code/gitoeba/

# Full build with everything:
python3 generate-jmdict.py -o output/ --pitch-tsv pitch_data.tsv --gitoeba ~/Code/gitoeba/
```

`generate-jmdict.py` runs all steps in dependency order.  Intermediate JSON
repos are written to `~/Code/gitjidic2/`, `~/Code/gitmdict/`,
`~/Code/gitnedict/`, and `~/Code/gitch/` by default (override with
`--gitjidic2`, `--gitmdict`, `--gitnedict`, `--gitch`).  Downloads are cached
in `~/.cache/` (override with `--cache`).

The pitch step is skipped when no `--pitch-tsv` is given but runs automatically
if `~/Code/gitch/entries/` already exists from a previous run.
The examples step is skipped unless `--gitoeba` is given.

### Step by step

```sh
# Stage 1 — JSON repos (git-friendly intermediate data)
python3 kanjidic2-to-git.py  -o ~/Code/gitjidic2/ [--cache ~/.cache/kanjidic2]
python3 jmnedict-to-git.py   -o ~/Code/gitnedict/  [--cache ~/.cache/jmnedict]
python3 jmdict-to-git.py     -o ~/Code/gitmdict/  --kanjidic2 ~/Code/gitjidic2/ [--cache ~/.cache/jmdict]
python3 pitch-to-git.py      -i pitch_data.tsv    -o ~/Code/gitch/

# Stage 2 — SQLite databases
python3 gitjidic2-to-sqlite.py  -i ~/Code/gitjidic2/ -o output/
python3 gitmdict-to-sqlite.py   -i ~/Code/gitmdict/  --nedict ~/Code/gitnedict/ -o output/
python3 gitch-to-sqlite.py   -i ~/Code/gitch/     -o output/
python3 gitoeba-to-sqlite.py    -i ~/Code/gitoeba/   -j output/jmdict.db -o output/
```

`kanjidic2-to-git.py`, `jmdict-to-git.py`, and `jmnedict-to-git.py` download
their source XML automatically (cached locally).  `pitch-to-git.py` does not
download anything — supply your own TSV data.

Curated entry corrections can be placed in `patches/entries/{shard}/{seq}.json`
as RFC 7396 JSON Merge Patches; they are applied automatically during
`jmdict-to-git.py`.

Output files: `output/jmdict.db`, `output/eng.db`, `output/ger.db`, …,
`output/kanjidic2.db`, `output/pitch.db`, `output/examples_eng.db`, …
