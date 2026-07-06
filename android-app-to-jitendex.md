# Android/Desktop App Changes Required for the Schema v2 Pipeline

This document replaces the previous version, which mapped app changes to the
twelve gaps in `improve-to-jitendex-level.md` — a document written against
the **v1** pipeline (`gitmdict-to-sqlite.py` → `jmdict.db` / `{lang}.db` /
`kanjidic2.db` / `pitch.db` / `examples_{lang}.db`, one flat
`DictionaryEntry` row per JMdict sequence number with several JSON/
space-separated-string columns).

SumatoraIndex has since replaced that pipeline with the schema v2 build
(`build-sumatora-db.py`, described in `schema-v2.md` and `Database.md`):
a fully normalized schema (`Entry`, `EntryForm`, `Sense`, `SenseGloss`,
`SenseReference`, ...) compiled once into a monolithic `sumatora.db`, then
split into installable packs (`sumatora_core.db` + optional
`sumatora_gloss_{lang}.db` / `sumatora_names.db` / `sumatora_pitch.db` /
`sumatora_kanji.db` / `sumatora_examples_{lang}.db` /
`sumatora_search_suffix.db`). `~/StudioProjects/SumatoraDictionary` — both
the `app` (Android) and `desktop` targets, which share the `core` module —
still consumes the **v1** shape: `core/dict/DictionaryResult.kt` is the old
flat interface (`readingsPrio`, `writings`, `furigana: String?`,
`xref: String?`, `stagk`, `stagr`, `rules` all still typed as raw strings),
`core/search/MatchedForm.kt` reconstructs the matched token by re-parsing
those space-separated strings after the fact, and
`desktop/.../DatabaseManager.kt`/`DesktopApp.kt` still `ATTACH` databases
under a `"jmdict"` alias. None of this has been migrated yet.

This is therefore not an incremental patch list — it is a from-scratch
description of what the app needs to become to consume schema v2. Every
capability schema v2 provides (per `Database.md` and the fixes recorded in
`improve-to-jitendex-level-2.md`) is described below in terms of what it
replaces in the app, and what app-side logic can be deleted as a result.

## 1. Attachment Model

**Was:** attach `jmdict.db` under alias `"jmdict"`, attach each installed
`{lang}.db` under its own alias (`DatabaseManager.attachDictionary`,
`DesktopApp.kt:60`).

**Now:** open `sumatora_core.db` as the *main* connection (not an attached
alias), then `ATTACH DATABASE` each installed pack:

```sql
ATTACH DATABASE '/path/sumatora_gloss_eng.db' AS gloss_eng;
ATTACH DATABASE '/path/sumatora_search_suffix.db' AS suffix;
ATTACH DATABASE '/path/sumatora_names.db' AS names;
ATTACH DATABASE '/path/sumatora_pitch.db' AS pitch;
ATTACH DATABASE '/path/sumatora_kanji.db' AS kanji;
ATTACH DATABASE '/path/sumatora_examples_eng.db' AS examples_eng;
```

`sumatora_core.db` is required; `sumatora_gloss_{lang}.db` is required for at
least one language (English is the default install). Everything else is
optional and the app should degrade gracefully when a pack isn't installed
(no suffix search, no names section, no pitch badges, no kanji detail, no
examples) rather than failing to open the database.

**App changes:**

1. Replace the `"jmdict"`/per-language alias scheme in `DatabaseManager`/
   `DesktopApp.kt` with core-as-main plus named pack attachments above.
2. Track installed packs by file presence, not by a fixed alias list —
   `sumatora_names.db`/`sumatora_pitch.db`/`sumatora_kanji.db`/
   `sumatora_search_suffix.db` are each independently optional.
3. `DictionaryEntry.kt` (the desktop download-catalog model, not the
   `DictionaryResult` row model) needs its filename scheme updated from
   `"$lang.db"` to the pack filenames above, and `isSearchable` needs a third
   case for a names/pitch/kanji/suffix pack (not just `main`/`translation`).

## 2. The Flat `DictionaryResult` Row Is Gone

**Was:** `core/dict/DictionaryResult.kt` — one flat interface with `seq`,
`readingsPrio`/`readings`/`writingsPrio`/`writings` (space-separated
strings), `pos`/`misc`/`field`/`dial` (parallel per-sense arrays baked into
strings), `xref`/`ant` (raw or resolved JSON strings), `furigana`
(bracket-notation string), `stagk`/`stagr`, `tags`, `score`, `rules`
(implied — not in this interface, but present on v1 `DictionaryEntry`),
`exampleSentences`/`exampleTranslations`/`exampleMatchedTokens` (parallel
JSON arrays), `deinflectionLabel`, `isProperNoun`/`properNounTypes`.

**Now:** no single row has all of this. The equivalent data is spread across
normalized tables the app assembles per `entry_id`:

| Old `DictionaryResult` field | New source |
|---|---|
| `seq` | `Entry.entry_id` (internal id) + `Entry.source_key` (original JMdict seq, as text) |
| `readingsPrio`/`readings`/`writingsPrio`/`writings` | `EntryForm` rows (`form_type`, `text`, `reading`, `is_primary`, `is_common`, `is_search_only`, `score`) — one row per form, not a space-separated blob |
| `furigana` | `FormFuriganaSegment` rows per `form_id` — pre-split `(base, ruby)` pairs, not a bracket string to parse |
| `pos`/`misc`/`field`/`dial` | `SenseGroupTag` → `Tag` (category `pos`/`misc`/`field`/`dialect`), hoisted to the sense-group level |
| `xref`/`ant` | `SenseReference` rows: `reference_type` (`xref`/`antonym`), `display_text`, `target_entry_id`, `target_form_id`, `target_sense_id`, `target_sense_number`, and now `preview_text` (a ready-made target-gloss preview — see §6) |
| `stagk`/`stagr` | `SenseAppliesToForm` — join against the matched `form_id`, no string parsing |
| `tags` (form-level irregular/priority tags) | `FormTag` → `Tag` |
| `score` | `Entry.score` (entry-level), `EntryForm.score` (form-level), `SearchTerm.score` (search-tier level) — three separate scores, not one |
| `rules` (deinflection) | `FormRule(form_id, rule)` — per form, not per entry (see §5) |
| `exampleSentences`/`exampleTranslations`/`exampleMatchedTokens` | `Example`/`ExampleSegment`/`EntryExample` — ranked and capped at build time (see §7), segments pre-split instead of `{expression;reading}` markup |
| `deinflectionLabel` | `DeinflectionRule.label`, joined from the rule code that verified |
| `isProperNoun`/`properNounTypes` | `Entry.entry_type = 'name'` (separate rows, not a flag on word rows) + `EntryTag` (category `name_type`) → `Tag` |

**App changes:** delete `DictionaryResult` and rebuild the display layer
around a per-`entry_id` assembly step that queries `EntryForm`,
`FormFuriganaSegment`, `SenseGroup`/`Sense`/`SenseGloss`/`SenseNote`/
`SenseLanguageSource`, `SenseAppliesToForm`, `SenseReference`, `FormRule`,
`EntryExample`, `FormPitch`, and `Tag` by `entry_id`/`form_id`, per the
"Display Assembly Query" example in `Database.md`. This is the single
biggest change in this document — everything else below is a consequence of
it.

## 3. Matched-Form Reconstruction Is No Longer Needed

**Was:** `core/search/MatchedForm.kt`'s `MatchedFormResolver` re-derives
which writing/reading token a query matched by re-tokenizing
`writingsPrio`/`writings`/`readingsPrio`/`readings` after the fact and
re-running the same normalization/tier logic the query itself used. This is
inherently fragile for prefix/substring/deinflection/romaji hits, as the old
`improve-to-jitendex-level-2.md` already noted.

**Now:** `SearchTerm.form_id` (nullable) already names the exact matched
form when a hit came from a specific writing/reading row (`script IN
('writing','kana')`); it's `NULL` for gloss/name search-term rows, where a
form isn't the match target. The app's query layer should carry
`entry_id` + `form_id` + match metadata straight through from the query
result, per `Database.md`'s documented `QueryResult` shape:

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

**App changes:**

1. Delete `MatchedFormResolver` — stop reconstructing the match after the
   fact.
2. Change every query (`DictionarySearchQueryTool` and friends) to select
   `SearchTerm.form_id` alongside `entry_id`, and carry it into the result
   row instead of just `entry_id` + raw matched text.
3. Use that `form_id` directly for: correct furigana (§2), correct sense
   filtering via `SenseAppliesToForm` (§2), correct pitch lookup (§8), and
   highlighting the matched form in an alternate-forms display (§9).

## 4. Sense Tags, Restrictions, and Grouping Move Into the Query Layer

**Was:** `pos`/`misc`/`field`/`dial` parsed from parallel string arrays per
sense; `stagk`/`stagr` applied by reconstructing the matched form via
`MatchedFormResolver` and checking list membership in app code.

**Now:**

- Tags: join `Sense`/`SenseGroup` → `SenseGroupTag` → `Tag`. `Tag.label` is
  a short curated display label, `Tag.description` the longer text, so the
  app should stop maintaining its own `TagSystem`-style static label map and
  read labels from `Tag` instead.
- Restrictions: a sense with no `SenseAppliesToForm` rows applies to every
  form; a sense with rows applies only to the listed `form_id`s. With the
  matched `form_id` from §3 already in hand, the filter is a plain `EXISTS`
  check — see `Database.md`'s "Display Assembly Query" for the exact SQL.
  There is no more "conservative when only one side of the match is known"
  fallback logic to write, since the query layer now always knows the exact
  matched `form_id`.
- Grouping: `SenseGroup` is currently 1:1 with `Sense` (schema-v2.md's
  documented starting point — no adjacent-sense merging yet), so there is no
  Jitendex-style "merge senses with identical tag sets" grouping to consume
  yet. If that merging is added to the pipeline later, it will show up as
  multiple `Sense` rows sharing one `SenseGroup`; nothing in the app needs to
  anticipate it today beyond querying by `SenseGroup` rather than assuming
  one group per sense.

**App changes:** replace tag-string parsing and `MatchedFormResolver`-based
restriction filtering with the joins above; drop any static POS/misc/field/
dialect label table in favor of `Tag.label`/`Tag.description`.

## 5. Deinflection: Verification Query Changes, Generation Doesn't

**Was:** `core/search/Deinflector.kt` generates `DeinflectionCandidate`
(`dictionaryForm`, `ruleCode`, `label`) from a conjugated surface form —
this candidate-generation logic is storage-format-independent and needs no
changes. The comment at `Deinflector.kt:29` says candidates are verified
"against `DictionaryEntry.rules`" — an entry-level column.

**Now:** `FormRule(form_id, rule)` is per-*form*, not per-entry — schema
v2's improvement over v1 (see `schema-v2.md`'s compatibility table). A form
that isn't inflectable no longer incorrectly inherits a rule just because
some other form of the same entry is.

**App changes:**

1. Keep `Deinflector.kt` as-is (candidate generation is unchanged).
2. Change `DictionarySearchQueryTool`'s verification step from
   `WHERE DictionaryEntry.rules LIKE '%v1%'`-style matching to
   `EXISTS (SELECT 1 FROM FormRule WHERE form_id = ? AND rule = ?)` against
   the specific matched `form_id`.
3. Carry the original inflected query and the recovered dictionary form
   through to the result model (not just the label) so the UI can render
   `食べた → 食べる (past)` instead of only `past` — this was already a
   known-desirable improvement in the old gap document and nothing about
   schema v2 blocks it now that `form_id` is known precisely.
4. `DeinflectionRule.label` replaces any hardcoded rule→label string map.

## 6. Cross-References Can Show a Real Target Preview Now

**Was:** `xref`/`ant` as JSON strings; even once resolved to a target `seq`,
showing "target headword + gloss preview" would have required the app to
fetch and query the target entry live at render time.

**Now:** `SenseReference.preview_text` is populated at build time — a
semitolon-joined preview of the target sense's main-type English glosses
(see `improve-to-jitendex-level-2.md` gap 3) — and `target_sense_id` points
at the exact target `Sense` row (the one named by a `headword・reading・N`
suffix, or the target entry's first sense otherwise). One caveat carried
over from the pipeline doc: `preview_text` is always English regardless of
the installed gloss language pack, since `SenseReference` lives in the
language-neutral core pack while `SenseGloss` is per-language.

**App changes:**

1. Render `SenseReference.display_text` as the tappable label; if
   `target_entry_id` is null, render plain unlinked text.
2. Render `preview_text` directly under/beside the reference instead of
   doing a live lookup — no extra query needed at render time.
3. Tapping a reference with `target_entry_id` set opens that entry; if
   `target_sense_id`/`target_sense_number` is set, scroll/highlight that
   sense.

## 7. Examples Are Pre-Ranked and Pre-Capped

**Was:** `exampleSentences`/`exampleTranslations`/`exampleMatchedTokens`
parallel JSON arrays, unranked and uncapped by the v1 pipeline; the app
would have needed its own truncation/ordering policy for entries with many
matches.

**Now:** `EntryExample.ord` is a real "best example first" rank (shorter
Japanese sentences rank higher), and every entry is capped at 8 examples per
language pack at build time (`improve-to-jitendex-level-2.md` gap 4).
`ExampleSegment` gives pre-split `(base, ruby)` ruby segments instead of
`{expression;reading}` markup, and `EntryExample.matched_text` names the
token to highlight.

**App changes:**

1. Query `EntryExample` `ORDER BY ord` and take as many as the UI has room
   for — no client-side ranking or cap needed.
2. Render `ExampleSegment` rows directly for ruby, reusing the same
   ruby-rendering path as headword furigana (§2) instead of a separate
   `{expression;reading}` parser.
3. Bold/highlight the segment(s) matching `EntryExample.matched_text`.

## 8. Pitch Lookup Uses the Matched Form, Not the First Form

**Was:** `pitch.db` keyed by `(word, reading)` text, looked up using
whichever writing/reading the app happened to have on hand — often the
first form, not necessarily the matched one.

**Now:** `FormPitch(form_id, pitch_id, confidence)` links pitch data
directly to a specific `form_id`, with `confidence` = `exact` or
`reading_fallback`. With the matched `form_id` from §3 in hand, pitch lookup
is `SELECT ... FROM FormPitch WHERE form_id = ?` — no more guessing.

**App changes:** replace `(word, reading)` text lookups with a `form_id`
join; show `reading_fallback` results with lower confidence or only when
`exact` returns nothing.

## 9. Alternate-Forms Display Has a Documented Recipe Now

**Was:** no equivalent existed; the app would have had to invent its own
"other readings/writings" logic from scratch (`stagk`/`stagr` parsing, or
just `writings`/`readings` string splitting).

**Now:** `Database.md`'s "Building an Alternate-Forms Table" section under
`EntryForm` gives the exact SQL for a Jitendex-style alternate-forms matrix:
columns from visible (`is_search_only = 0`) writing forms, rows from
readings that bridge to a kanji form plus a synthetic `∅` group for ones
that don't, and cell badges from `FormTag`. `EntryForm.is_primary` is
score-based (highest `(score, is_common)` among non-search-only candidates,
not source order — `improve-to-jitendex-level-2.md` gaps 1 and 6), so the
headline form the app should show by default is simply
`WHERE is_primary = 1`.

**App changes:**

1. Use `EntryForm.is_primary` for the default headline instead of "first
   form in whatever order the old row exposed them."
2. Follow `Database.md`'s recipe verbatim for any "other forms"/alternate
   spellings UI, for both word and name entries — the same `EntryForm`
   shape now applies uniformly to `entry_type IN ('word', 'name')`.
3. Filter `is_search_only = 1` forms out of anything user-visible (headline,
   alternate-forms table); they remain valid `SearchTerm` rows so search
   still finds them.

## 10. Proper Names Get the Same Treatment as Words

**Was:** `isProperNoun`/`properNounTypes` flags on what was otherwise a
word-shaped row, in a separate `jmnedict`-ish structure historically.

**Now:** names are `Entry(entry_type = 'name')` rows using the *same*
`EntryForm`/`FormTag`/`SearchTerm` tables as words, plus `NameTranslation`
(flat translation list, not per-language `SenseGloss`) and
`EntryTag(category='name_type')` for JMnedict's place/person/surname/etc.
codes. As of this pipeline's latest fixes, names also get real furigana
(`FormFuriganaSegment`, when built with `--kanjidic2`) and a score-based
`is_primary`, same as words (`improve-to-jitendex-level-2.md` gaps 6–7).

**App changes:**

1. Query names through the same `EntryForm`/furigana/tag machinery as
   words, filtered by `entry_type = 'name'` — do not maintain a separate
   name-rendering code path for headword display.
2. Render `NameTranslation` (a flat ordered list) instead of per-language
   glosses for the translation text.
3. Render `EntryTag` (category `name_type`) joined to `Tag.label` for the
   place/person/surname/etc. badge, instead of parsing a
   `properNounTypes` string.
4. Continue showing names in a separate results section from words — that
   product decision doesn't change, only the query/render mechanics do.

## 11. Kanji Detail

**Was:** `kanjidic2.db` with `char`/`on`/`kun`/`meanings` (JSON array)/
`strokes`/`grade`/`jlpt`/`freq`/`radical` columns.

**Now:** `sumatora_kanji.db` with `KanjiEntry` (strokes/grade/jlpt/
frequency/radical), `KanjiReading` (`reading_type IN ('on','kun','nanori')`,
one row per reading instead of a space-separated string), `KanjiMeaning`
(one row per language+meaning instead of a JSON array). Kanji also get an
`Entry`/`EntryForm` row (`entry_type = 'kanji'`) purely so `SearchTerm` can
index them the same way as everything else; nothing cross-references a
kanji by `entry_id`, so this can be treated as an implementation detail.

**App changes:** replace `on`/`kun` space-splitting and `meanings` JSON
parsing with `KanjiReading`/`KanjiMeaning` row queries filtered by
`character`.

## Priority Order

1. Attachment model (§1) and the `DictionaryResult` replacement (§2) —
   nothing else works until the app queries the new tables at all.
2. Carry `form_id` + match metadata through the query layer (§3) — almost
   every other section depends on the app actually knowing which form
   matched.
3. Sense tags/restrictions/grouping (§4) and deinflection's verification
   query (§5) — restores existing behavior on the new schema.
4. Cross-reference previews (§6), ranked examples (§7), pitch-by-form (§8)
   — each is a quality improvement that previously required either app-side
   judgment calls or wasn't possible at all.
5. Alternate-forms table (§9) — new UI surface, follow the documented
   recipe rather than inventing one.
6. Proper names on the same rendering path as words (§10), kanji detail
   query updates (§11) — consistency/parity cleanup once the word path is
   solid.

## What Not To Do

- Do not keep `DictionaryResult`/`MatchedFormResolver` "for compatibility"
  alongside the new schema — the whole point of schema v2 is that the app
  no longer needs to reconstruct match context after the fact.
- Do not re-derive `is_primary`/headline selection in Kotlin from raw
  `EntryForm` rows — the DB already picked it; just filter
  `WHERE is_primary = 1`.
- Do not reinvent the alternate-forms pivot — follow `Database.md`'s
  documented recipe.
- Do not treat `preview_text` as needing a live join at render time — it's
  already resolved.
- Do not build a separate rendering path for proper names' headword/
  furigana display — it's the same `EntryForm`/`FormFuriganaSegment` shape
  as words now.
- Do not assume every optional pack is installed — check file presence and
  degrade features gracefully (no suffix search, no names, no pitch, no
  kanji detail, no examples) rather than failing to open the database.

## Summary

The Android/desktop app has not started this migration: it still speaks the
v1 flat-row schema end to end (`DictionaryResult`, `MatchedFormResolver`,
`"jmdict"`-alias attachment). Schema v2 moves essentially all of the
storage-format parsing and best-effort reconstruction this app currently
does in Kotlin into the database itself, and the two follow-up fixes in
`improve-to-jitendex-level-2.md` closed the remaining gaps between what
`Database.md` documents and what the pipeline actually produces. The app
side of this migration is now purely "query the normalized tables and
render them" — there is no remaining pipeline gap blocking it.
