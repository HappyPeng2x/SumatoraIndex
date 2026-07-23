# "Recent dictionary updates" feature (design notes)

Not yet implemented. Written up so it can be picked up later — ask Claude to
implement this plan when ready.

## Motivation

`release-dictionaries.yml` now runs weekly and republishes every pack, but the
app only ever shows a silent version bump. The goal: a "recent updates"
screen in `SumatoraDictionary` (the Android app) that tells users what
actually changed release to release, to reinforce the sense of freshness the
weekly cadence is meant to convey. This needs two things: a data source
describing what changed (SumatoraIndex side, doesn't exist today), and
app-side storage/UI to consume it (SumatoraDictionary side).

**Key finding that makes this cheap:** `sync-stage1-repo.sh` already does
`git clone --depth 1` of each stage-1 JSON repo (gitmdict, gitnedict, gitjidic2,
gitoeba, gitch) before overwriting it with this run's freshly generated files.
At that moment, the clone's `HEAD` *is* last release's content and the working
tree (after `cp -r`) *is* this release's content — `git diff --cached
--name-status` between them is an exact, free, per-entry add/modify/delete diff
against the previous release. No extra downloads, no extra build step, no
diffing logic to invent — just capture output that's already sitting there
right before the existing `git commit`.

Each stage-1 repo's file layout (confirmed by reading the generator scripts):

| Repo | Path shape | id encodes |
|---|---|---|
| gitmdict | `entries/<shard>/<seq>.json`, `translations/<lang>/<shard>/<seq>.json` | numeric JMdict seq |
| gitnedict | `entries/<shard>/<seq>.json` | numeric JMnedict seq |
| gitjidic2 | `characters/<shard>/<HEXCODEPOINT>.json` | kanji codepoint (hex) |
| gitoeba | `sentences/<shard>/<id>.json`, `translations/<lang>/<shard>/<id>.json` | numeric Tatoeba id |
| gitch | `entries/<shard>/<word>.json` (word `/`→`_` encoded) | headword string |

`git diff --cached` never passes `-M`, so every change is a plain `A`/`M`/`D`
line, no renames to special-case.

## Phase 1 — SumatoraIndex: produce `changelog.json` per release

1. **`sync-stage1-repo.sh`**: right after `git add -A -- "${GENERATED_PATHS[@]}"`
   (before the existing `git diff --cached --quiet` check), if a `DIFF_OUT` env
   var is set, write `git diff --cached --name-status -- "${GENERATED_PATHS[@]}"`
   to it. No-op (script behaves exactly as today) when `DIFF_OUT` is unset, so
   manual/local invocations are unaffected.

2. **New `build-changelog.py`**: reads `--diffs-dir` (files named
   `gitmdict.diff`, `gitnedict.diff`, `gitjidic2.diff`, `gitoeba.diff`,
   `gitch.diff` — a missing file means "no changes recorded", not an error, so
   the step never fails when `DICT_REPOS_PAT` isn't configured and the sync
   step didn't run), `--version`, `--previous-version`, `--date`, `-o`. Per
   repo, parses `STATUS\tpath` lines (skip `metadata.json`), maps each path
   through a repo-specific parser (per the table above — for gitch, reuse
   whichever `/`↔`_` encode/decode helper `unidic-to-git.py`/`pitch-to-git.py`
   already use internally rather than re-deriving it) into
   `(category, lang_or_none, id)`, and buckets into:
   ```json
   {
     "version": 14, "previous_version": 13, "date": "20260727",
     "jmdict": {
       "entries": {"added": [2843600], "modified": [1000000], "removed": []},
       "translations": {"fre": {"added": [1000010], "modified": [], "removed": []}, "eng": {...}}
     },
     "jmnedict": {"entries": {"added": [...], "modified": [...], "removed": [...]}},
     "kanjidic2": {"characters": {"added": ["龍"], "modified": [], "removed": []}},
     "tatoeba": {
       "sentences": {"added": [...], "modified": [...], "removed": []},
       "translations": {"fre": {...}, "eng": {...}}
     },
     "pitch": {"entries": {"added": ["あう"], "modified": [...], "removed": []}}
   }
   ```
   Given the earlier weekly entry-count analysis (single/double/low-triple-digit
   deltas per language per week), this file stays a few KB — no need to sample
   or truncate, it can carry the *complete* id list as originally requested.

3. **`release-dictionaries.py`**: add `--changelog-path` (optional). If given
   and the file exists, checksum it with the same sha256 logic
   `gzip_and_checksum` already uses (factor into a shared `_sha256_file()`
   helper) and add `changelog`/`changelog_sha256` attributes on the
   `<repository>` element (alongside existing `version`/`date`), pointing at
   `{download_base_url}/changelog.json`.

4. **`.github/workflows/release-dictionaries.yml`**:
   - "Compute next version and date" step: also
     `echo "current_version=$CURRENT" >> "$GITHUB_OUTPUT"` (needed as
     `--previous-version`).
   - "Sync stage-1 JSON repos" step: `mkdir -p /tmp/stage1-diffs` first, then
     prefix each of the 5 `sync-stage1-repo.sh` calls with
     `DIFF_OUT=/tmp/stage1-diffs/<name>.diff`.
   - New step "Build changelog" (runs unconditionally — `build-changelog.py`
     tolerates missing diff files, so this never depends on
     `DICT_REPOS_PAT_SET`): `mkdir -p release && python3 build-changelog.py
     --diffs-dir /tmp/stage1-diffs --version ${{ steps.version.outputs.next_version }}
     --previous-version ${{ steps.version.outputs.current_version }} --date ${{ steps.version.outputs.date }}
     -o release/changelog.json`.
   - "Gzip, checksum, and render dictionaries.xml" step: add
     `--changelog-path release/changelog.json` to the `release-dictionaries.py`
     call.
   - "Publish release" step: `gh release create` currently only globs
     `release/*.db.gz` — add `release/changelog.json` explicitly so it's
     attached too.

## Phase 2 — SumatoraDictionary: ingest and display

1. **Manifest parsing**: `BaseDictionaryObject.fromXML()`
   (`db/tools/BaseDictionaryObject.java:91-152`) currently returns only
   `List<T>` and is shared by asset/local/remote loaders. Rather than change
   its signature for everyone, give it an optional repository-attributes
   callback (`null` from the asset/local call sites, which don't care) invoked
   once when the `<repository>` start tag is seen, so `RemoteManifestFetcher`
   alone picks up `changelog`/`changelog_sha256`. Minimal-diff, zero behavior
   change for existing callers.

2. **New Room entity `DictionaryChangelog`** (version PK, date, raw `json:
   String`, `fetchedAt: Long`) — store the fetched file verbatim rather than
   normalizing every nested id-list into SQL columns; parse into a small
   `ChangelogSnapshot` data-class model on read. Add to `PersistentDatabase`'s
   entity list (currently v12) and a new `MIGRATION_12_13` in
   `PersistentDatabaseParameters.java` (same one-file-of-static-migrations
   pattern already used for 1→12) creating the table. New
   `DictionaryChangelogDao` (`insert`, `getAllOrderByVersionDesc`,
   `hasVersion(version)`).

3. **Fetch trigger**: extend `DictionaryUpdateChecker.checkAndEnqueue`
   (`update/DictionaryUpdateChecker.kt:35`) — after the existing manifest fetch,
   if the manifest carries a `changelogUrl` and `!dao.hasVersion(remote.version)`,
   download it (plain `HttpURLConnection` GET, matching
   `RemoteManifestFetcher`'s style), verify sha256 against
   `changelog_sha256` (reuse the digest/hex-compare logic already in
   `DictionaryDownloadCompleteReceiver.java:176-197` rather than
   reimplementing it — factor into a small shared utility both call), and
   insert the row. Runs on the existing 7-day `DictionaryUpdateWorker`
   schedule — piggybacks on a job that already runs periodically instead of
   adding a new one. Deliberately unconditional on whether the user has any
   packs installed, so users are told about updates for dictionaries they
   haven't downloaded yet, too.

4. **UI**: new `DictionaryChangelogActivity`, reached from `SettingsFragment`
   next to "Manage dictionaries" (same `SettingsFragmentActions` callback +
   `MainActivity` wiring `DictionariesManagementActivity` already uses). Each
   `DictionaryChangelog` row renders as "vN — YYYY-MM-DD" with per
   pack/language lines for any nonzero delta ("German: +33 entries", "French:
   +34 translations"), using `added.size`/`modified.size`/`removed.size` —
   count-only for v1, no per-entry headword lookup (that's a natural v2
   enhancement once this ships, using the same raw-SQL/attach pattern
   `PersistentDatabaseComponent.fetchEntryDetail` uses today, against a
   temporarily-opened pack file). Unlike `DictionariesManagementActivity`'s
   static, small pack list — which deliberately avoids a RecyclerView since
   its row count never grows — this list grows by one entry every week
   forever, so use a real `RecyclerView` here instead of copying the
   programmatic-row pattern.

## Verification

- **SumatoraIndex**: dry-run `build-changelog.py` against a hand-made
  `--diffs-dir` fixture (a couple of representative `A`/`M`/`D` lines per repo)
  and check the emitted JSON matches the schema above. Then trigger the real
  workflow once via `workflow_dispatch` and confirm `changelog.json` shows up
  as a release asset and `dictionaries.xml` gains `changelog`/`changelog_sha256`
  attributes.
- **SumatoraDictionary**: run the `run-android-app` skill on the emulator,
  force `DictionaryUpdateWorker` to fire (existing manual "Check Now" path),
  confirm a `DictionaryChangelog` row is inserted and the new screen renders
  it; check a Room migration test (project already has instrumented DB tests,
  per `CHANGELOG.md`'s recent migration-related entries) covers
  `MIGRATION_12_13`.
