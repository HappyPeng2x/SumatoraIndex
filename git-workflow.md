# Release Workflow — Remaining Work

`.github/workflows/release-dictionaries.yml` (see `release-pipeline.md` for
the full design) is written and locally dry-run tested, but has never
actually executed on GitHub — the environment it was built in has no
reliable GitHub network access. This tracks what's left before it can be
trusted to run unattended.

## Blocking — must happen before the first run can work at all

1. **Push the local commits.** Both repos currently only have these changes
   committed locally:
   - SumatoraIndex, branch `master`: not yet pushed to `origin/master`.
   - SumatoraDictionary, branch `ui`: not yet pushed to `origin/ui`, and
     `ui` is not that repo's default branch (`master` is) — the
     `dictionaries_url` fix won't reach a real build until `ui` is merged.
   The workflow reads/writes `dictionaries.xml` on SumatoraIndex's `master`
   directly from GitHub, so none of this works against unpushed local
   commits.

2. **Branch-name bug, already found and fixed while writing this doc:** the
   workflow and `dictionaries_url` were written assuming SumatoraIndex's
   default branch was `main`. It's actually `master`
   (`git ls-remote --symref origin HEAD` confirmed this). Every `main`
   reference (the workflow's commit/push step, its release notes text,
   `release-pipeline.md`, and SumatoraDictionary's `strings.xml`) has been
   corrected to `master`. Mentioning this here so it doesn't get
   silently re-broken later — if this repo's default branch ever changes,
   both the workflow and the app's `dictionaries_url` need to change together.

3. **Confirm GitHub Actions is enabled** for `HappyPeng2x/SumatoraIndex`
   (Settings → Actions → General). Should be on by default for a public
   repo that's never had a workflow before, but worth a first-time check.

## Must do — first real run

4. **Trigger it manually once** (Actions tab → "Release dictionaries" → "Run
   workflow") rather than waiting for the monthly schedule, so the first run
   can be watched live.

5. **Watch it end to end** and expect it to take a while — the local
   equivalent run took roughly 15 minutes on a 16-core dev machine;
   GitHub-hosted runners are weaker (2 cores), so this could run notably
   longer. Nothing about the pipeline requires it to finish quickly, but
   confirm it doesn't hit the job's time limit.

6. **After it finishes, verify by hand:**
   - The release exists: `github.com/HappyPeng2x/SumatoraIndex/releases/tag/dictionaries-v9`
     (or whatever version it lands on), with every expected pack file
     attached.
   - The manifest updated: fetch
     `raw.githubusercontent.com/HappyPeng2x/SumatoraIndex/master/dictionaries.xml`
     and confirm the version bumped and the URLs/checksums point at the new
     release.
   - Download one asset and confirm its SHA-256 matches what the manifest
     says (a quick `sha256sum` locally).

## Follow-up once the first release is confirmed good

7. **Update `OptionalDictionaryCatalog.kt`** (SumatoraDictionary) — it still
   points at the old `HappyPeng2x/SumatoraDictionary` release for the
   suffix/names packs (a `TODO` comment already flags this). Either bump its
   URL/version to the new SumatoraIndex release, or better, replace it with
   a fetch against the same `dictionaries.xml` the update checker already
   uses, so initial-install and update-checking share one source of truth
   instead of two hardcoded lists.

8. **Confirm the app itself picks up the update** — install a build with the
   old bundled `dictionaries.xml`, either wait for the periodic background
   check or use the "Check Now" button, and confirm it downloads, verifies,
   and installs the new pack after a restart.

## Not urgent, but worth deciding at some point

9. **Runtime/cost on GitHub-hosted runners** — watch the actual duration of
   the first few runs. If it's uncomfortably long or the schedule needs to
   run more often later, options include trimming the curated language list
   further, or splitting the build into parallel jobs.

10. **Curated language list** (`eng,ger,rus,spa,dut,hun,swe,fre,slv`) is a
    starting point matching what's already bundled. Expanding it (or
    switching to `--all-pack-languages`) is a product decision, not a
    technical blocker.

11. **No pre-publish sanity check exists yet.** The workflow trusts the
    build completely — it doesn't check that pack sizes or entry counts are
    within a sane range before publishing. Worth adding if a bad upstream
    JMdict/JMnedict release, or a pipeline bug, should ever be caught before
    it reaches users rather than after.
