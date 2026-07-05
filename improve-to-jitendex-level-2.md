# Gap Analysis 2: Schema v2 Pipeline vs. Jitendex Display Quality

This document supersedes the earlier `improve-to-jitendex-level-2.md`, which
was written against the pre-schema-v2 pipeline (raw `DictionaryEntry` JSON
blobs, bracket-notation furigana strings, unresolved `stagk`/`stagr` arrays).
Schema v2 (see `schema-v2.md` and `Database.md`) has since replaced all of
that with `EntryForm`, `FormFuriganaSegment`, `SenseAppliesToForm`,
`SenseReference`, and friends, and the pipeline that populates them
(`jmdict-to-git.py`, `jmdict-to-sumatora-db.py`, `gitoeba-to-sumatora-db.py`)
already implements most of the old document's wishlist.

This document instead tracks the gap between what `Database.md` *documents*
as available and what the build pipeline *actually produces* today, found by
reading the current pipeline code directly rather than by re-deriving
requirements from scratch. The goal, per the schema v2 design principle, is
unchanged: SumatoraIndex should do dictionary-domain assembly once, so the
Android rewrite renders structured rows instead of making its own judgment
calls about headword selection, furigana, cross-reference previews, or
example-sentence quality.

Most of the items below are real code gaps — a schema column exists but is
never populated correctly, or is populated using a heuristic that quietly
produces a wrong or low-quality result. One is a documentation gap: the
schema has enough data to build a Jitendex-style alternate-forms table, but
`Database.md` never spells out the recipe, which invites the Android app to
reinvent it (possibly incorrectly) in Kotlin. This is a living document:
gaps 1–5 came from a first audit of the JMdict/Tatoeba side of the pipeline;
gaps 6–7 came from a follow-up audit that widened the scope to the JMnedict
(proper names) side, which turned out to have the same *class* of bug as
gap 1, just never fixed there.

## Status

| # | Gap | File(s) | Status |
|---|---|---|---|
| 1 | `is_primary` chosen by source position, not score (words) | `jmdict-to-sumatora-db.py` | Fixed |
| 2 | Furigana blob fallback for secondary readings (words) | `jmdict-to-git.py`, `jmdict-to-sumatora-db.py` | Fixed |
| 3 | `SenseReference.preview_text`/`target_sense_id` never populated | `jmdict-to-sumatora-db.py` | Fixed |
| 4 | `EntryExample` unranked and uncapped | `gitoeba-to-sumatora-db.py` | Fixed |
| 5 | No documented alternate-forms-table recipe | `Database.md` | Fixed |
| 6 | `is_primary` chosen by source position, not score (names) | `jmnedict-to-sumatora-db.py` | Fixed |
| 7 | No furigana at all for proper names | `jmnedict-to-git.py`, `jmnedict-to-sumatora-db.py` | Fixed |

## 1. `is_primary` Was Chosen By Source Position, Not Score

**Where:** `jmdict-to-sumatora-db.py::_pass1_forms` (pre-fix: line 196/225).

**The bug:** `is_primary` was set to `1 if form_ord == 0 else 0`, where
`form_ord` was a simple counter over the order JMdict happened to list kanji
forms, their readings, and then kana forms. JMdict usually lists preferred
forms first, but this is not guaranteed, and it does not account for
per-form irregularity tags at all. A rare/irregular/search-only form listed
first would be marked primary — i.e. become the entry's display headword —
ahead of the entry's actual common form.

Two related bugs made this worse:

- `is_search_only` (a schema column documented in `Database.md` as marking
  "forms that should be searchable but visually treated as
  redirects/related forms") was never set to `1` anywhere in the pipeline —
  JMdict's `sK`/`sk` (search-only kanji/kana) entity codes were stored as
  ordinary `FormTag` rows like any other informational tag, with no effect
  on `is_search_only`. Jitendex explicitly never shows `sK`/`sk` forms as a
  headline or in the forms table — they exist only as hidden search keys.
- `_form_score` (used for form-level scoring) does not treat `sK`/`sk` as
  irregular, so a search-only form could tie an entry's real standard form
  at score `0` and, depending on iteration order, win the position-based
  `is_primary` selection.

**The fix:** `_pass1_forms` now builds every candidate `EntryForm` row for an
entry (kanji×reading pairs, then kana-only forms) into a list before
inserting anything, sets `is_search_only = 1` for any form tagged `sK`/`sk`,
and chooses `is_primary` as the highest-`(score, is_common)` candidate among
the non-search-only ones (ties keep the original source order, matching
prior behavior when scores are equal). `is_search_only` is now a real,
populated column instead of a permanent `0`.

## 2. Furigana Blob Fallback for Secondary Readings

**Where:** `jmdict-to-git.py::parse_entry` (furigana computation) and
`jmdict-to-sumatora-db.py::_fallback_furigana_segments`.

**The bug:** `jmdict-to-git.py` only ran the informed furigana solver once
per kanji form, against the *first* applicable reading
(`_find_reading` returned a single string). When a kanji form has more than
one valid reading — e.g. 人気 → にんき / ひとけ — every reading past the
first fell through to `_fallback_furigana_segments`, which returns the
entire written form as one opaque `(text, reading)` span with no
per-character ruby breakdown at all. `Database.md` documents
`FormFuriganaSegment` as uniformly "display-ready" ruby the client should
render directly; this silently wasn't true for any non-first reading of a
multi-reading kanji form.

**The fix:** `jmdict-to-git.py` now computes furigana for *every* reading
that applies to a kanji form (`furiganaByReading`, a `{reading: bracket_notation}`
map), reusing the existing `compute_furigana` solver per reading. The
original single `furigana` string (first reading only) is kept unchanged
for backward compatibility with `gitmdict-to-sqlite.py`, the older v1
pipeline that still consumes it. `jmdict-to-sumatora-db.py` now looks up
furigana by the exact reading of each `EntryForm` row instead of only
trusting the first one; `_fallback_furigana_segments` remains only as a
safety net for the (now rare) case where a reading is missing from the map.

## 3. `SenseReference.preview_text`/`target_sense_id` Were Dead Columns

**Where:** `jmdict-to-sumatora-db.py::_pass2_senses`.

**The bug:** Both `schema-v2.md` and `Database.md` advertise
`SenseReference.preview_text` ("preview gloss if `preview_text` exists") and
`target_sense_id` as available for Jitendex-style cross-reference previews
(`xref-glossary` in Jitendex's HTML). The build code only ever set
`target_entry_id`, `target_form_id`, and `target_sense_number` — the code
comment even said resolving `target_sense_id` "would require a third full
pass for a marginal benefit," and `preview_text` was never touched at all,
always `NULL`. Without this, the Android rewrite would have had to do its
own live join-and-gloss-lookup at render time for every cross-reference —
exactly the kind of app-side assembly schema v2 was meant to eliminate.

**The fix:** A new pass (`_resolve_reference_previews`) runs after
`_pass2_senses`, once every entry's `Sense`/`SenseGloss` rows exist (a
forward-pointing xref's target may not have been processed yet during
`_pass2_senses`'s single streaming pass). For each `SenseReference` row with
a resolved `target_entry_id`, it resolves the target sense (the specific
sense named by `target_sense_number` if present, otherwise the target
entry's first sense) and fills in `target_sense_id` plus `preview_text`
(that sense's `main`-type English glosses, semicolon-joined).

**Known limitation, intentionally left as-is:** `preview_text` is populated
from English (`eng`) glosses regardless of which gloss language pack the
Sense/SenseReference row ends up split into by `split-sumatora-packs.py`.
`SenseReference` lives in the language-neutral core pack, but `SenseGloss`
is per-language — a fully correct per-language preview would require either
moving `SenseReference` into each language pack (duplicated per language) or
adding a `preview_text_by_lang` table, which is a larger schema change than
"populate the columns the schema already has." English is the one gloss
language guaranteed present (it's the required pack per `Database.md`), so
this is a reasonable default, but non-English installs will show English
cross-reference previews until this is revisited.

**Related bug found and fixed while verifying this gap:** `_resolve_reference`
(used to resolve `target_entry_id`/`target_form_id` for every xref/antonym,
independent of the `preview_text` work above) collapsed `kanji_index[headword]`
into one `form_id` per JMdict `seq` via a plain dict comprehension, discarding
which reading each row belonged to. For a kanji form with more than one valid
reading (the same 開く/ひらく/あく case from gap 2), a `headword・reading` xref
resolved to whichever of that entry's writing-form rows happened to be
inserted last — not necessarily the one matching the named reading. Confirmed
with a synthetic xref `開く・ひらく`: it returned the `form_id` for 開く/あく
instead of 開く/ひらく. `kanji_index` now carries the reading alongside each
`(seq, entry_id, form_id)` tuple, and `_resolve_reference` matches on the
exact `(headword, reading)` pair before picking a `form_id`. This didn't
affect `target_sense_id`/`preview_text` correctness (those only depend on
`target_entry_id` and `target_sense_number`), but it would have affected any
future use of `target_form_id` for a precise furigana/pitch match on the xref
target.

## 4. `EntryExample` Was Unranked and Uncapped

**Where:** `gitoeba-to-sumatora-db.py::process`.

**The bug:** Every Tatoeba sentence that linked to an entry was inserted
into `EntryExample` with no cap and no quality ranking. `ord` was actually
the index of an entry *within one sentence's set of linked entries*, not the
rank of that sentence among an entry's *own* example list — it carried no
"best examples first" meaning at all. An entry with many Tatoeba matches
would get an unbounded, arbitrarily-ordered example list, pushing "which
examples to show, how many, in what order" back onto the Android app —
again the app-side judgment call schema v2 was meant to eliminate. Jitendex,
by contrast, caps at 3 well-chosen example sentences per sense.

**The fix:** For each language pack, candidate sentences are now collected
per `entry_id` first, ranked by Japanese sentence character length (shorter
sentences are simpler and more legible as dictionary examples — a
deterministic, easily-explained heuristic), and capped to
`_MAX_EXAMPLES_PER_ENTRY` (8, a module-level constant, tunable) before any
row is written. `EntryExample.ord` now reflects that rank (`0` = best/shown
first) instead of arbitrary file-iteration order. Only the sentences that
survive the cap for at least one entry get an `Example`/`ExampleSegment`
row at all, avoiding unused rows for sentences no entry will ever display.

## 5. No Documented Alternate-Forms-Table Recipe

**Where:** `Database.md`.

**The gap:** `EntryForm` (with `FormTag` for badges) already contains
everything needed to reconstruct a Jitendex-style alternate-forms matrix —
kanji forms as columns, readings as rows, cell validity and per-cell
irregular/rare/priority/old badges, and a `∅` column for readings with no
kanji bridge at all. But `Database.md` never spelled out how to build it,
which invites the Android rewrite to reinvent (and likely get subtly wrong)
a non-trivial pivot: how columns/rows are derived, how a "no kanji bridge"
reading is distinguished from a bridging one, and how `is_search_only` forms
are excluded from the visible matrix while staying searchable.

**The fix:** `Database.md` now has a "Building an Alternate-Forms Table"
section under `EntryForm` with the exact SQL recipe: columns from
`form_type='writing'` rows (excluding `is_search_only`), rows from readings
that do bridge to a kanji form plus a synthetic `∅` row group for the ones
that don't, and cell resolution via presence of a matching writing-form row
joined to `FormTag` for badges.

## 6. `is_primary` Was Also Positional For Proper Names

**Where:** `jmnedict-to-sumatora-db.py::process` (pre-fix: lines 63–67, 82–87).

**The bug:** The exact same class of bug as gap 1, just never applied to the
JMnedict (proper names) side of the pipeline: `is_primary` was
`1 if ord_ == 0 else 0`, chosen by JMnedict source order rather than by
commonality. JMnedict entries carry the same `ke_pri`/`ke_inf` priority and
info tags JMdict entries do (confirmed in `jmnedict-to-git.py::parse_entry`),
so a name entry listing an uncommon kanji form before its common one picked
the wrong form as primary — the same headword-selection defect gap 1 fixed
for words, undetected in the first audit because that pass only looked at
the JMdict/Tatoeba files.

**The fix:** `jmnedict-to-sumatora-db.py` now buffers every candidate form
for an entry (kanji×reading pairs, then kana-only forms — see gap 7 below
for why kanji forms are now expanded per reading) before inserting anything,
and chooses `is_primary` as the highest-`is_common` candidate, mirroring
gap 1's fix. JMnedict doesn't carry JMdict's finer-grained irregular-form
tags (`iK`/`rK`/`io`), so there's no equivalent of gap 1's `is_search_only`
exclusion to add here — `is_common` is the only signal available to rank on.

## 7. No Furigana At All For Proper Names

**Where:** `jmnedict-to-git.py` (no furigana computation existed) and
`jmnedict-to-sumatora-db.py` (no `FormFuriganaSegment` inserts existed).

**The gap:** Unlike gap 2 (a furigana *quality* regression for secondary
readings), this was a total absence: `jmnedict-to-git.py` never called the
furigana solver at all, so every name entry with a kanji headword had zero
`FormFuriganaSegment` rows. `Database.md`'s own "Names Pack" table doesn't
claim furigana as part of the names pack, so the documentation wasn't wrong
about it — but it meant the Android app couldn't render ruby for proper-name
search results without its own fallback parsing, the exact kind of
storage-format logic schema v2 eliminated for words. Since Jitendex doesn't
cover JMnedict at all, this wasn't a "Jitendex-parity" gap, but it was a real
consistency gap for an app that wants names to render as polished as words.

**The fix:** The furigana solver (`build_knowledge`, `compute_furigana`, and
the reading-applicability helper) was extracted from `jmdict-to-git.py` into
a new shared module, `furigana_solver.py`, so both git-repo generators use
the same implementation instead of duplicating it. `jmnedict-to-git.py` now
accepts an optional `--kanjidic2 <gitjidic2 directory>` flag (mirroring
`jmdict-to-git.py`'s existing flag) and computes a `furiganaByReading` map
per kanji form, covering every reading that applies to it — a name can have
more than one valid reading for the same kanji form just like a JMdict word.
`jmnedict-to-sumatora-db.py` now expands each kanji form into one `EntryForm`
row per valid (kanji, reading) pair (previously one row per kanji text with
no reading recorded at all) and inserts `FormFuriganaSegment` rows from the
matched reading's solved furigana, exactly like the JMdict path.
`build-sumatora-db.py`'s Step 2 now passes `--kanjidic2` through, since
kanjidic2-to-git (Step 1) already runs first and produces the data
`build_knowledge` needs.

## What Not To Do

Same guidance as before, still holds:

- Do not render directly from raw JSON columns in Compose/View code.
- Do not pick the first kanji form's furigana when the matched form/reading
  is known — use the exact `(form_id)` row's `FormFuriganaSegment` rows.
- Do not show all senses when `SenseAppliesToForm` restricts them.
- Do not show raw JMdict entity codes as final UI labels — use `Tag.label`.
- Do not reinvent the alternate-forms pivot in Kotlin — follow the recipe in
  `Database.md` §"Building an Alternate-Forms Table".
- Do not assume `EntryExample.ord` was meaningful before this fix if working
  from an older build; rebuild the database to pick up ranked examples.
- Do not assume proper names lack furigana going forward — rebuild with
  `--kanjidic2` passed to `jmnedict-to-git.py` (or via `build-sumatora-db.py`,
  which now wires this automatically) to get `FormFuriganaSegment` rows for
  name headwords.

## Summary

All six code-level gaps found by reading the pipeline — positional
`is_primary` for both words and names, furigana fallback for secondary word
readings, total absence of furigana for names, dead
`SenseReference.preview_text`/`target_sense_id` columns, and unranked/uncapped
`EntryExample` rows — are now fixed at the source, plus the one
documentation gap (the alternate-forms-table recipe). The schema v2 pipeline
should now deliver what `Database.md` already claimed it delivers — uniformly
for words and proper names — so the Android rewrite can render these fields
directly rather than re-deriving them.
