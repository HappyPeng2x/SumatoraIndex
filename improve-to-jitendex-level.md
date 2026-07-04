# Gap Analysis: Sumatora vs. Jitendex Pipeline

## What Sumatora currently reproduces ✓

| Jitendex feature | Sumatora equivalent |
|---|---|
| JMdict entry data (seq, readings, writings, senses) | `DictionaryEntry` table — complete |
| Priority vs. non-priority readings/writings split | `readingsPrio` / `writingsPrio` / `readings` / `writings` — matches |
| Per-sense POS, misc, field, dial, s_inf, xref, ant, lsource | JSON columns in `DictionaryEntry` — matches |
| stagk / stagr per-sense restrictions | `stagk` / `stagr` JSON columns — stored |
| Full kanji element metadata (tags: iK, io, rK, ateji…) | `kanjiData` JSON column — stored |
| Full kana element metadata (nokanji, appliesToKanji…) | `kanaData` JSON column — stored |
| Entity code → human-readable expansion | `DictionaryEntity` table — matches |
| FTS5 forward search (exact → prefix → substring, kana + kanji) | `DictionaryIndex` with 8 columns — matches |
| Per-language translation tables + FTS5 reverse search | `DictionaryTranslation` + `DictionaryTranslationIndex` — matches |
| Tatoeba sentences linked to entries | `ExamplePairs` / `ExamplesSummary` view — present |
| Tatoeba sentence furigana markup | `{expression;reading}` token markup in `gitoeba-to-sqlite.py` — full coverage via MeCab/UniDic tokenization (Algorithms.md §15), not limited to Tatoeba's own token annotations |
| Furigana for kanji headword display (basic) | `DictionaryEntry.furigana` in bracket notation — present but limited |

---

## Gap 1 — Furigana quality for consecutive kanji (HIGH)

**What Jitendex does:** Uses an *informed* solver backed by Kanjidic2 on/kun readings + curated `characters.json` kanwa data. Each kanji character has a known reading set, including rendaku variants and sokuon prefix forms. For `東京湾` / `とうきょうわん` it produces `東[とう]京[きょう]湾[わん]`.

**What Sumatora does:** The `compute_furigana` function in `jmdict-to-git.py` is the "ignorant" algorithm — it relies solely on kana anchors between kanji runs. Consecutive kanji without interleaved kana produce a single block bracket: `東京湾[とうきょうわん]`. This affects the majority of compound nouns and verbs with multiple-kanji stems.

**Impact on the Android app:** `DictionaryEntry.furigana` is the sole source for headword ruby display (`SearchElementRenderer.kt:appendFurigana`). Block brackets render correctly but look like a lazy fallback — no per-character annotation.

**Fix documented:** `Furigana.md` already describes exactly what to add (download Kanjidic2, build `{char → [hiragana_readings]}` table, partition-matching solver). The work fits inside `jmdict-to-git.py::compute_furigana` with an optional `knowledge` parameter — no schema changes needed.

---

## Gap 2 — Furigana only for first kanji form (MEDIUM)

**What Jitendex does:** Computes and stores furigana for every valid `(reading, kanji form)` bridge — e.g., `食べ物【たべもの】` and `食物【たべもの】` and `食物【しょくもつ】` each get their own segment sequence.

**What Sumatora does:** `jmdict-to-git.py` computes furigana for every kanji element in the entry JSON (stored inside `kanjiData`), but `gitmdict-to-sqlite.py:340` extracts only `kanji_list[0].get('furigana')` into `DictionaryEntry.furigana`. Secondary kanji forms have furigana computed and present in the `kanjiData` JSON but are never surfaced by any query.

**Impact:** If an entry has multiple kanji forms (e.g., irregular variant `飮む` alongside standard `飲む`), only the first form's furigana reaches the app's headword display. The `kanjiData` furigana for all other forms is dead data.

**Fix:** Change `gitmdict-to-sqlite.py` to store furigana as a JSON object or keep it only in `kanjiData`, and update the Android rendering to look up the correct form's furigana from `kanjiData` based on which writing matched the search. Alternatively, expand `DictionaryEntry.furigana` to a JSON map `{kanji_text: furigana_string}`.

---

## Gap 3 — Cross-reference resolution: plain text vs. linked entries (HIGH)

**What Jitendex does:** `CrossReferenceService` resolves every `xref`/`ant` text string (e.g., `来る・くる`) to a concrete `(entryId, readingOrder, kanjiFormOrder, senseOrder)` tuple. The rendered `CrossReference` record includes the target's surface form, furigana segments, headword number, sense number, and a snippet of the target's glosses. In MDict output, cross-references become tappable `entry:TARGET` links.

**What Sumatora does:** `xref` and `ant` columns store the raw text strings from JMdict (e.g. `["来る・くる"]`). `EntryDetailBottomSheet.kt` displays them as plain "See also" / "Antonym" boxes with the raw string. No resolution, no links, no target glosses.

**Impact:** Cross-references in the Android app are informational strings only — the user cannot tap them to navigate. This is a significant UX gap for entries with important antonyms or related forms (e.g., 行く ↔ 来る).

**Fix:** Add a resolution pass in `gitmdict-to-sqlite.py` (or a post-processing step) that resolves `xref`/`ant` text to seq numbers via FTS5 lookup, then stores a JSON structure like `[[{"text":"来る","seq":1547720}], ...]`. The Android query and renderer would need updates to open the referenced entry on tap.

---

## Gap 4 — Inflection/deinflection rules (MEDIUM-HIGH for Japanese learner use)

**What Jitendex does:** Derives inflection rule codes (`v1`, `v5`, `vs`, `adj-i`, `vk`, `vz`) from POS tags per headword, stored as `TermRule` rows. MDict apps use these to deinflect conjugated forms and match the dictionary form — so `食べた` finds `食べる`.

**What Sumatora does:** POS tags are in the `pos` JSON column but no precomputed rule strings exist. The Android app only searches the literal typed string. If a user types an inflected form (`食べた`, `高かった`, `してみる`), they get zero results.

**Impact:** Critical for language learners reading Japanese text. The app currently requires users to know and type the dictionary form. This is the most commonly cited limitation of lookup-style dictionaries.

**Fix:** Add a `DictionaryRule` table or column to `jmdict.db` storing per-entry rule codes derived from the first priority reading's POS. Add a client-side deinflection step in the Android search query path (the rule table enables filtering after deinflection). This is significant work but the rule derivation logic is simple (a mapping from POS entity codes to rule strings, as documented in §4.10 of the Jitendex pipeline document).

---

## Gap 5 — stagk/stagr restrictions not applied at query time (MEDIUM)

**What Jitendex does:** The `HeadwordSenseService` filters each sense against the headword being displayed — sense restrictions (`<stagk>`, `<stagr>`) are respected so only applicable senses appear.

**What Sumatora does:** `stagk` and `stagr` are stored as JSON in `DictionaryEntry` but are never consulted during query construction or in the Android renderer. `EntryDetailBottomSheet.kt` displays all senses for every matched entry regardless of which reading/kanji form the search matched.

**Impact:** For entries with per-form sense restrictions, Sumatora shows all senses even those that technically only apply to another form. Example: 御父さん has a sense restricted to its irregular form — Sumatora shows it for the primary form too.

**Fix:** The Android renderer already has access to `kanjiData`/`kanaData` (via the `DictionarySearchElement` fields) and `stagk`/`stagr`. A rendering-side filter (not DB-side) that hides senses whose `stagk`/`stagr` list doesn't include the matched form would address this without schema changes. The matched form can be inferred from whichever `writingsPrio` / `writings` token the FTS query returned (requires tracking which FTS tier produced the hit, which the search query tool doesn't currently propagate).

---

## Gap 6 — Headword scoring / irregular-form deprioritization (LOW-MEDIUM)

**What Jitendex does:** Each headword has a `Score` (+1 priority, 0 standard, −1 irregular/rare) used to rank results within the same FTS tier. Rare forms like `飮む` (old kanji) sort after `飲む` (standard).

**What Sumatora does:** The FTS tiers (prio before non-prio, exact before prefix before substring) provide coarse ordering. Within a tier, entry order is insertion order. Irregular and rare forms (`iK`, `rK`, `io` tags present in `kanjiData`) are not deprioritized relative to standard forms within the same tier.

**Impact:** Minor in practice — irregular forms are already in `writings` (non-prio bucket) rather than `writingsPrio`, so they only show up after priority-bucket hits. The main gap is within the non-priority bucket where rare and standard forms are interleaved.

---

## Gap 7 — Token highlighting in Tatoeba examples (LOW-MEDIUM)

**What Jitendex does:** Each `ExampleSegment` carries `IsHighlighted = true` for the token that matched the current headword. The HTML renders matched tokens in bold.

**What Sumatora does:** `ExamplesSummary` stores complete sentences and translations as flat JSON arrays. There is no per-token annotation indicating which token caused the sentence to be linked. The Android app (`EntryDetailBottomSheet.kt`) renders example sentences with ruby via `JapaneseText.spannifyWithFurigana` but without any highlight on the relevant token.

**Impact:** Users can't quickly spot why an example sentence was shown for a given entry.

**Fix:** Store the `{seq, token_expression}` pair in `ExamplePairs` (already has `seq`). On the read path, the renderer could bold the token matching the entry's writing/reading. This requires schema additions (a `matched_token` column in `ExamplePairs`) and a renderer update.

---

## Gap 8 — JMnedict / proper name entries (MISSING FEATURE)

**Jitendex:** Imports JMnedict (people, places, organisations).  
**Sumatora:** No proper name database. Searching for `東京` as a place name produces only common-word results.

---

## Gap 9 — Kanjidic2 character-level data (MISSING FEATURE)

**Jitendex:** Stroke count, radical, JLPT level, English meaning per character.  
**Sumatora:** No character database. A character detail view (tap a kanji in the headword to see its stroke count and readings) is not possible.

---

## Gap 10 — Pitch accent / audio (MISSING FEATURE)

**Jitendex:** `Pronunciations` field in the glossary blob (KanjiAlive audio references).  
**Sumatora:** No pronunciation data of any kind.

---

## Gap 11 — JMdict patches / curated corrections (MINOR)

**Jitendex:** Community JSON patches applied to fix JMdict errors.  
**Sumatora:** Raw JMdict as-is. Errors in JMdict are propagated.

---

## Gap 12 — DictionaryControl not populated (MINOR)

The `DictionaryControl` table is created but `gitmdict-to-sqlite.py` never inserts any rows. There's no database build timestamp, JMdict version, or format version stored. The app has no way to report which dictionary version is installed.

---

## Summary (ordered by impact on the Android app)

| # | Gap | Impact | Fix complexity |
|---|---|---|---|
| 1 | Furigana: ignorant solver (block brackets for consecutive kanji) | High — most compound words look imprecise | Medium (Kanjidic2 integration, documented in Furigana.md) |
| 3 | Cross-references: plain text, not linked to entries | High — no navigation from xref/ant | Medium (resolution pass + Android tap handler) |
| 4 | No deinflection rules | High for learner use — can't look up conjugated forms | High (rule derivation + client deinflection) |
| 2 | furigana field only stores first kanji form | Medium — secondary forms shown without ruby | Low (query fix or schema extension) |
| 5 | stagk/stagr not applied at render time | Medium — wrong senses shown for restricted entries | Low-Medium (renderer-side filter) |
| 7 | No token highlighting in examples | Low-Medium — harder to read examples | Low (schema + renderer) |
| 6 | No headword scoring for rare/irregular forms | Low — ordering within non-prio tier is arbitrary | Low (add score column) |
| 12 | DictionaryControl not populated | Low — no version display | Trivial |
| 8 | No JMnedict / proper names | Feature gap | High (new pipeline) |
| 9 | No Kanjidic2 character detail | Feature gap | Medium (new pipeline + UI) |
| 10 | No pitch accent / audio | Feature gap | High (new data source) |
| 11 | No JMdict patches | Minor quality | Medium (patch system) |

The most actionable near-term improvements for the Android app are **Gap 1** (Kanjidic2 furigana — fully documented in `Furigana.md`) and **Gap 2** (surface the `kanjiData` furigana for all forms in the query result), as they require only changes to `jmdict-to-git.py` and a minor query/rendering update with no schema migration needed on the Android side.
