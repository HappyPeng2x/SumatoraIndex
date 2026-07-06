# Dictionary Release Pipeline

This document describes how SumatoraIndex publishes installable dictionary
packs so client apps (Android/desktop `SumatoraDictionary`, and eventually
`sumatora-pwa`) can check for and download updates without a full app
release. It's the SumatoraIndex-side counterpart to
`~/StudioProjects/SumatoraDictionary/update-pipeline.md`, which describes
the (already-implemented) app-side download/install flow.

## Hosting: SumatoraIndex, not SumatoraDictionary

`SumatoraDictionary/update-pipeline.md`'s original design notes said
releases should live on SumatoraIndex, but the first implemented piece
(`OptionalDictionaryCatalog.kt`'s hardcoded suffix/names download URLs, and
the bundled `dictionaries.xml`'s `dictionaries_url` string resource) ended
up pointing at `github.com/HappyPeng2x/SumatoraDictionary/releases/...`
instead — a pragmatic shortcut at the time, since that's the repo the
Android work was happening in.

That shortcut doesn't generalize. SumatoraIndex is the single upstream
producer of every pack; Android, desktop, and a future PWA client are all
independent downstream consumers. Hosting the canonical release/manifest on
one specific client's repo would mean:

- every other client points at a repo that isn't conceptually "theirs" (a
  PWA depending on `SumatoraDictionary`'s releases is a strange coupling to
  explain and maintain), and
- the expensive, CPU-heavy rebuild (JMdict/JMnedict/Tatoeba processing) would
  need to happen once per client repo if each hosted its own copy, instead
  of once here.

So: **releases and `dictionaries.xml` live on SumatoraIndex.** Every client
fetches from the same place. `SumatoraDictionary/update-pipeline.md` should
be treated as superseded on this one point; everything else in it (the
download/verify/install flow, WorkManager scheduling, checksum validation)
is unaffected and already implemented.

## Version/date bootstrap

The app already has `InstalledDictionary` rows at `(version=8,
date=20260705)` baked into the shipped APK's bundled assets, and
`OptionalDictionaryCatalog.kt` references that same version for the
suffix/names packs it can download. `BaseDictionaryObject.isSuperiorVersion`
only enqueues an update when the new `(version, date)` is strictly greater,
so the first SumatoraIndex-hosted release has to continue that numbering,
not restart at 1 — otherwise no already-installed app would ever see it as
an update.

`dictionaries.xml` at this repo's root is seeded at `version="8"
date="20260705"` with only the two pack types that are confirmed to already
exist as real, working GitHub release assets (`suffix`, `names` — the only
types Phase 0b ever needed as standalone downloads; core/gloss/pitch/kanji
are bundled in the APK and have never been published as separate release
assets before now). Those two entries point at the *existing*
`HappyPeng2x/SumatoraDictionary` release, which is real and still valid — no
functionality regresses by pointing the manifest fetch at this repo instead.

The first `release-dictionaries` workflow run reads that seed, computes
`version=9`, and republishes *every* pack type (bundled ones included) as a
SumatoraIndex-hosted release for the first time. From then on, the workflow
always continues from whatever `dictionaries.xml` currently says.

## What the workflow does

`.github/workflows/release-dictionaries.yml`, triggered manually
(`workflow_dispatch`) or monthly (upstream JMdict/JMnedict/Tatoeba don't
need more frequent republishing — see `update-pipeline.md`'s bandwidth
rationale):

1. Runs the full build (`tatoeba-to-git.py` → ... → `build-sumatora-db.py
   --split-packs`) from scratch on a clean runner every time. This is
   deliberate: it's the only way to guarantee the published packs actually
   reflect a from-scratch, reproducible build, not runner-specific leftover
   state.
2. Gzips each pack and computes its SHA-256 (`release-dictionaries.py`).
3. Publishes a GitHub Release tagged `dictionaries-v{N}` with the gzipped
   packs as assets.
4. Regenerates `dictionaries.xml` pointing at those assets and commits it to
   `main`.

Because `dictionaries_url` is a stable `raw.githubusercontent.com/.../main/`
URL (not tied to a release tag), updating step 4 is what actually makes a
new release visible to the app — cutting the GitHub Release alone isn't
enough.

### Why `tatoeba-to-git.py` is now part of Stage 1

`build-sumatora-db.py` never actually invoked `tatoeba-to-git.py` — it only
checked whether `~/Code/gitoeba` already existed, and silently skipped the
examples step otherwise. That was fine on a dev machine with a
pre-populated `~/Code/gitoeba`, but a fresh CI runner has nothing there, so
the first CI run would have silently produced zero example packs. Fixed by
adding `tatoeba-to-git.py` as an explicit Stage 1 step (see
`build-sumatora-db.py`'s dependency-graph comment and step numbering), so
`--skip-stage1` is genuinely the only way to skip it now, not "missing a
directory."

### Curated language set, not every language

The workflow defaults to the same 9 gloss languages (and their matching
example packs) the app's bundled `dictionaries.xml` already advertises
(`eng,ger,rus,spa,dut,hun,swe,fre,slv`), passed as `--pack-lang`. Tatoeba
alone has translations in 60+ languages; publishing all of them by default
would mean dozens of low-traffic release assets and manifest entries for
languages the app has no curated display name for. `--all-pack-languages`
is still available (`workflow_dispatch` input `pack_langs: all`) if that's
ever wanted.

## Manual follow-up once the first real release ships

`OptionalDictionaryCatalog.kt` (the hardcoded first-install source for the
suffix/names packs, used by `DictionariesManagementActivity`'s "install this
optional pack" flow — a different code path than the manifest-driven update
checker, since that checker deliberately never auto-installs a pack the user
hasn't already opted into) still points at the old
`HappyPeng2x/SumatoraDictionary` v8 URLs. That's intentionally left alone
for now — it's still correct today. Once the first SumatoraIndex-hosted
release (`dictionaries-v9` or whatever version actually ships first) is
confirmed working, update `RELEASE_BASE_URL`/`version`/`date` there to point
at it (or, better, replace it with a fetch against the same
`dictionaries.xml` manifest the update checker already uses, so there's only
one source of truth instead of two).

## Verifying this pipeline

`release-dictionaries.py` was dry-run locally against a real, already-built
`output/packs` directory (gzip + checksum + manifest rendering, without
touching GitHub) before this was wired into a workflow — see its module
docstring for usage. The workflow itself has not been triggered for a real
run as of writing this; the sandbox this was written in doesn't have
reliable GitHub network access to verify a live run. Trigger it manually
once and watch the Actions log before relying on the monthly schedule.
