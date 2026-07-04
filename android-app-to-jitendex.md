# Android App Changes Required by the Pipeline Upgrades

This document lists every change the Android app must make to consume the
database produced by the upgraded pipeline.  Each section maps to one of the
twelve gaps in `improve-to-jitendex-level.md`.

---

## No app change required

### Gap 1 — Furigana quality (informed solver)

The pipeline now runs the Kanjidic2-informed solver when built with
`generate-jmdict.py`.  The bracket-notation format (`食[た]べ物[もの]`) is
unchanged.  The app's existing `appendFurigana` parser works without
modification.

### Gap 11 — JMdict patches

Patches are applied at build time.  The resulting JSON and SQLite data look
identical to unpatched data from the app's perspective.

---

## Schema changes — existing features, data format changed

### Gap 2 — `DictionaryEntry.furigana` is now a JSON object

**Was:** plain string `"食[た]べ物[もの]"` or `null`.

**Now:** JSON object keyed by kanji writing form, or `null`.

```json
{"食べ物": "食[た]べ物[もの]", "食物": "食[しょく]物[もつ]"}
```

**App changes:**

1. Deserialize the column as a `Map<String, String>` (key = writing form,
   value = bracket-notation furigana string) instead of a plain string.
2. Look up the matched writing in that map to get the correct furigana for the
   headword being displayed.  If the search matched a kana-only form the map
   will have no entry for it — display the kana form without furigana.
3. Pass the looked-up string to the existing `appendFurigana` renderer.

Affected code: wherever `DictionaryEntry.furigana` is read
(`SearchElementRenderer`, `EntryDetailBottomSheet`, or equivalent).

---

### Gap 3 — `DictionaryEntry.xref` and `.ant` are now resolved JSON

**Was:** raw JMdict text arrays — e.g. `[["来る・くる"]]`.

**Now:** resolved JSON.  Outer array is indexed by sense (parallel to `pos`).
Each element is an array of reference objects.

```json
[
  [{"text": "来る", "seq": 1547720}],
  [{"text": "行く", "seq": 1289010, "sense": 2}]
]
```

Fields per reference object:

| Field   | Type    | Always present | Meaning |
|---------|---------|----------------|---------|
| `text`  | string  | yes            | Display form (kanji or kana) |
| `seq`   | integer | no             | Target entry sequence number; absent if resolution failed |
| `sense` | integer | no             | 1-based sense number within the target entry |

**App changes:**

1. Replace the raw-string parser with a two-level JSON deserializer.
2. Render references that have a `seq` as tappable links that open the target
   entry.  References without `seq` (resolution failed) render as plain text,
   same as before.
3. When `sense` is present, scroll the target entry detail to that sense.

Affected code: cross-reference / antonym sections in `EntryDetailBottomSheet`
(or equivalent).

---

### Gap 12 — `DictionaryControl` is now populated

The table `DictionaryControl(control TEXT PK, value INTEGER)` now contains:

| `control`         | `value`                      |
|-------------------|------------------------------|
| `build_timestamp` | Unix epoch (seconds)         |
| `format_version`  | `1`                          |
| `entry_count`     | number of `DictionaryEntry` rows |

**App changes:**

1. On database open, query all rows from `DictionaryControl`.
2. If `format_version` is absent or greater than the highest version the app
   understands, refuse to use the database and show a "please update the app"
   message.
3. Display `build_timestamp` (formatted as a date) and `entry_count` in
   Settings → Dictionary Info or the About screen.

---

## Query and renderer changes — existing UI, new behaviour

### Gap 6 — Headword scoring (`DictionaryEntry.score`)

`DictionaryEntry` now has a `score INTEGER` column:
- `+1` — priority form (common in nf01–nf24 newspapers, spec1/spec2, etc.)
- `0`  — standard form
- `-1` — irregular or rare form (`iK`, `rK`, `io` tags)

Index `DictionaryEntryScore ON DictionaryEntry (score)` is available.

**App changes:**

Add `ORDER BY DictionaryEntry.score DESC` to the entry-fetch query, after the
FTS tier ordering (priority tier first, then within each tier highest score
first).  This prevents rare forms like `飮む` from appearing before `飲む`.

---

### Gap 5 — `stagk`/`stagr` sense restrictions applied at render time

`stagk` and `stagr` are already stored as JSON arrays (one element per sense).

`stagk[i]` is the list of kanji forms to which sense `i` applies; `stagr[i]`
is the list of kana forms.  An empty list means the sense is unrestricted.

**App changes:**

1. Track which writing or reading matched the search query (i.e., which FTS
   column — `writingsPrio`, `writings`, `readingsPrioKana`, `readingsKana` —
   produced the hit, and what surface token matched).
2. In the sense renderer, before displaying sense `i`, check:
   - If `stagk[i]` is non-empty and the matched form is a kanji form: only show
     the sense if `stagk[i]` contains the matched kanji form.
   - If `stagr[i]` is non-empty and the matched form is a kana form: only show
     the sense if `stagr[i]` contains the matched kana form.
   - If both lists are empty: show the sense unconditionally.
3. See `sumatora-query.py::applicable_senses()` for the reference
   implementation of this filter.

---

### Gap 4 — Deinflection rules (`DictionaryEntry.rules`)

`DictionaryEntry` now has a `rules TEXT` column: a space-separated set of
Yomitan-compatible deinflection codes, or `null` for uninflectable entries.

| Code    | Part of speech |
|---------|----------------|
| `v1`    | Ichidan verb (食べる) |
| `v5`    | Godan verb (書く, 飲む, …) |
| `vk`    | Irregular くる |
| `vs`    | Suru-verb (勉強する) |
| `vz`    | Zuru-verb (感ずる) |
| `adj-i` | I-adjective (高い) |

Index `DictionaryEntryRules ON DictionaryEntry (rules)` is available.

**App changes (significant new feature):**

Implement a client-side deinflection engine in the search path:

1. For each user query string, generate all candidate dictionary forms by
   applying the inverse of common conjugation rules (negative, past, te-form,
   etc.) for each rule code.
2. For each candidate, search `DictionaryIndex` FTS5 as usual.
3. After fetching `DictionaryEntry` rows for hits, verify that the entry's
   `rules` column includes the rule code that was applied to produce the
   candidate.  Discard rows that fail this check.
4. Display verified hits alongside any direct (uninflected) hits; label them
   with the conjugation type (e.g., "past tense of 食べる").

This is the most significant Android-side change required.  The rule derivation
table in the pipeline is simple; the deinflection transformation table is the
complex part and must be implemented separately in the app.

---

### Gap 7 — Token highlighting in Tatoeba examples

`ExamplesSummary` is a view that groups by `seq`, returning one row per entry
with three parallel JSON arrays:

```sql
SELECT seq,
       json_group_array(sentence)      AS sentences,
       json_group_array(translation)   AS translations,
       json_group_array(matched_token) AS matched_tokens
FROM ExamplePairs
GROUP BY seq
```

`sentences[i]`, `translations[i]`, and `matched_tokens[i]` are always
co-indexed: `matched_tokens[i]` is the surface writing of the token that caused
`sentences[i]` to be linked to the entry.

**App changes:**

1. Deserialize `sentences`, `translations`, and `matched_tokens` as parallel
   `List<String>`.
2. Iterate by index `i` to render each `sentences[i]` / `translations[i]` pair.
3. In the renderer for `sentences[i]`, after applying furigana spans, apply an
   additional bold or highlight span to the substring matching `matched_tokens[i]`.
   The match is a simple substring search against the sentence text (without
   furigana interleaving).

Affected code: example sentence rendering in `EntryDetailBottomSheet` (or
equivalent).

---

## New features — new databases and new UI

### Gap 8 — Proper name search (JMnedict)

Two new tables in `jmdict.db`:

```sql
ProperNounEntry (seq INTEGER PK, readings TEXT, writings TEXT,
                 types TEXT, translations TEXT)

ProperNounIndex USING fts5(
    readingsKana, readingsKanaParts,
    writings, writingsParts,
    content="")
```

`types` and `translations` are JSON string arrays.  Common type values:
`place`, `person`, `given`, `surname`, `station`, `company`, `org`, `product`.

`ProperNounIndex` is a contentless FTS5 table; rowid joins back to
`ProperNounEntry.rowid` (which equals `seq`).

**App changes:**

1. Add FTS5 queries against `ProperNounIndex` in the search pipeline, using the
   same tier strategy as `DictionaryIndex` (exact → prefix → substring).
2. Retrieve `ProperNounEntry` rows for matched rowids.
3. Display results in a "Proper names" section below or alongside regular
   dictionary results.  Show `writings` (or `readings` for kana-only names),
   the `types` list (e.g., "place, station"), and `translations`.

---

### Gap 9 — Kanji character detail (Kanjidic2)

New database `kanjidic2.db`:

```sql
KanjiEntry (
    char     TEXT PRIMARY KEY,   -- single kanji character
    "on"     TEXT,               -- space-separated on readings (katakana)
    kun      TEXT,               -- space-separated kun readings (hiragana, okurigana after ".")
    meanings TEXT,               -- JSON array of English meaning strings
    strokes  INTEGER,
    grade    INTEGER,            -- 1–6 kyōiku, 8 jōyō/jinmeiyō; NULL otherwise
    jlpt     INTEGER,            -- old scale 1–4 (4 = N5, 1 = N1); NULL if unlisted
    freq     INTEGER,            -- newspaper frequency rank; NULL if unlisted
    radical  INTEGER             -- classical radical number
)
```

All columns except `char` are nullable.

**App changes:**

1. Open `kanjidic2.db` at startup alongside `jmdict.db`.
2. Implement a character detail view or dialog.  Trigger it when the user taps
   an individual kanji character in a headword, in an example sentence, or in a
   dedicated kanji-search mode.
3. Query `SELECT * FROM KanjiEntry WHERE char = ?` for the tapped character.
4. Display: stroke count, grade (translate to school year or "Jōyō"/"Jinmeiyō"),
   JLPT level (translate old scale to N1–N5), frequency rank, classical radical
   number, on and kun readings (split on spaces), and the `meanings` JSON array.

---

### Gap 10 — Pitch accent display

New database `pitch.db`:

```sql
PitchAccent (
    word     TEXT,               -- dictionary headword (kanji or kana)
    reading  TEXT,               -- hiragana reading
    pitches  TEXT,               -- JSON array of integers (pitch drop positions)
    PRIMARY KEY (word, reading)
)
-- INDEX PitchAccentReading ON PitchAccent (reading)
```

Pitch position encoding:
- `0` — heiban: rises after mora 1 and stays high (LH…H)
- `1` — atamadaka: drops after mora 1 (HL…L)
- `N` — drops after mora N; if N equals the mora count of the reading the word
  is odaka (LH…HL)

Multiple valid pitch patterns per entry are stored as a JSON integer array,
e.g. `[0, 2]`.

**App changes:**

1. Open `pitch.db` at startup.
2. For each displayed entry, query by the matched writing and reading:
   ```sql
   SELECT pitches FROM PitchAccent WHERE word = ? AND reading = ?
   ```
   Fall back to a reading-only lookup if the writing query returns no rows:
   ```sql
   SELECT pitches FROM PitchAccent WHERE reading = ?
   ```
3. Deserialize `pitches` as `List<Int>`.
4. Render each pitch position as either a numeric badge (e.g., `[0]` for
   heiban, `[2]` for nakadaka position 2) or a standard pitch accent graph
   (a line showing H/L mora sequence).  If multiple patterns are present
   display all of them.

---

## Summary

| Gap | Change type | Effort |
|-----|-------------|--------|
| 1 — Furigana quality | None (format unchanged) | — |
| 2 — Furigana JSON map | Deserialize JSON map; look up matched writing | Trivial |
| 3 — Resolved xref/ant | New JSON parser; tappable cross-reference links | Low |
| 4 — Deinflection rules | New deinflection engine + query filter | High |
| 5 — stagk/stagr filtering | Track matched form; filter senses in renderer | Low-Medium |
| 6 — Headword scoring | Add `ORDER BY score DESC` to entry query | Trivial |
| 7 — Token highlighting | Highlight `matched_tokens` in example renderer | Low |
| 8 — Proper names | New FTS5 query + "Proper names" result section | Medium |
| 9 — Kanjidic2 | New database + character detail view | Medium |
| 10 — Pitch accent | New database + pitch accent display | Medium |
| 11 — Patches | None (transparent to app) | — |
| 12 — DictionaryControl | Read on open; version check; display in Settings | Trivial |
