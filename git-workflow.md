# Release Workflow — Remaining Work

`.github/workflows/release-dictionaries.yml` (see `release-pipeline.md` for
the full design) has now been triggered manually and completed successfully:
run `29020531599` on 2026-07-09 (`workflow_dispatch`, default `pack_langs`),
29m42s, published `dictionaries-v9`. All 22 expected assets (core, kanji,
pitch, suffix, names, plus gloss/examples for the 9 curated languages) are
attached, `dictionaries.xml` on `master` was updated to `version="9"
date="20260709"`, and a spot-checked asset's SHA-256 matched the manifest.
The blocking setup issues below (branch-name bug, unpushed commits, Actions
enabled) are all resolved. What's left is downstream follow-up, not pipeline
verification.

## Follow-up once the first release is confirmed good

1. **Update `OptionalDictionaryCatalog.kt`** (SumatoraDictionary) — it still
   points at the old `HappyPeng2x/SumatoraDictionary` release for the
   suffix/names packs (a `TODO` comment already flags this). Either bump its
   URL/version to the new SumatoraIndex release, or better, replace it with
   a fetch against the same `dictionaries.xml` the update checker already
   uses, so initial-install and update-checking share one source of truth
   instead of two hardcoded lists.

2. **Confirm the app itself picks up the update** — install a build with the
   old bundled `dictionaries.xml`, either wait for the periodic background
   check or use the "Check Now" button, and confirm it downloads, verifies,
   and installs the new pack after a restart.

## Not urgent, but worth deciding at some point

3. **Runtime/cost on GitHub-hosted runners** — the first real run took
   29m42s on a 2-core GitHub-hosted runner. Watch the next few scheduled
   runs; if it grows uncomfortably long, options include trimming the
   curated language list further, or splitting the build into parallel jobs.

4. **Curated language list** (`eng,ger,rus,spa,dut,hun,swe,fre,slv`) is a
   starting point matching what's already bundled. Expanding it (or
   switching to `--all-pack-languages`) is a product decision, not a
   technical blocker.

5. **No pre-publish sanity check exists yet.** The workflow trusts the
   build completely — it doesn't check that pack sizes or entry counts are
   within a sane range before publishing. Worth adding if a bad upstream
   JMdict/JMnedict release, or a pipeline bug, should ever be caught before
   it reaches users rather than after.
