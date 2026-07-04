# Algorithms

This document describes every non-trivial algorithm implemented across the
pipeline scripts.  Each section names the source file and function(s) where the
algorithm lives.

---

## 1 — Kana normalisation

**Files:** all scripts  
**Functions:** `hira_to_kata`, `_kata_to_hira`

Japanese text uses two parallel syllabic scripts.  Hiragana (U+3041–U+3096)
and katakana (U+30A1–U+30F6) encode the same sounds with a fixed codepoint
offset of 0x60.  The pipeline normalises to one script at each boundary:

- **→ katakana** before inserting into FTS5 kana columns (all search queries
  must also be katakana).
- **→ hiragana** before computing furigana (readings stored in Kanjidic2 are
  katakana; JMdict readings can be either).

```python
def hira_to_kata(s):
    return ''.join(chr(ord(c) + 0x60) if 'ぁ' <= c <= 'ゖ' else c for c in s)

def _kata_to_hira(s):
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ン' else c for c in s)
```

Only the core hiragana/katakana block is converted; half-width katakana,
combining characters, and the prolonged-sound mark `ー` are left unchanged.

---

## 2 — FTS5 suffix-parts indexing (substring search)

**File:** `gitmdict-to-sqlite.py`  
**Functions:** `calculate_parts_element`, `calculate_parts`, `calculate_parts_kana`

SQLite FTS5 supports prefix search (`term*`) but not infix/substring search.
Substring matches are enabled by storing all non-trivial suffixes of each token
as additional FTS5 index values.  A prefix search on these suffix values then
finds any term that appears inside the original token.

```
カタカナ  →  suffixes: タカナ カナ ナ
```

The full token itself is excluded (start index 1, not 0) so that an infix
search on the `*Parts` column does not also return exact-match hits — those are
already covered by the corresponding non-parts column.

```python
def calculate_parts_element(s, include_self=False):
    start = 0 if include_self else 1
    return {s[i:] for i in range(start, len(s))}

def calculate_parts(space_separated):
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(word)
    return ' '.join(parts)

def calculate_parts_kana(space_separated):
    parts = set()
    for word in space_separated.split():
        parts |= calculate_parts_element(hira_to_kata(word))
    return ' '.join(parts)
```

`calculate_parts_kana` also normalises to katakana so that the FTS5 kana
columns hold a consistent script.

The FTS5 `DictionaryIndex` has four pairs of columns:

| Base column | Parts column | Content |
|---|---|---|
| `readingsPrioKana` | `readingsPrioKanaParts` | Priority kana readings |
| `readingsKana` | `readingsKanaParts` | Non-priority kana readings |
| `writingsPrio` | `writingsPrioParts` | Priority kanji writings |
| `writings` | `writingsParts` | Non-priority kanji writings |

A substring search for `term` is expressed as `*Parts MATCH term*`.

---

## 3 — Furigana: ignorant solver (anchor-based)

**File:** `jmdict-to-git.py`  
**Functions:** `_parse_segments`, `_solve_ignorant`, `compute_furigana`

### Output format

Bracket notation: kanji runs are immediately followed by `[reading]`; kana
characters pass through unchanged.

```
食[た]べ物[もの]      ← kanji-kana-kanji with interleaved kana anchors
難[むずか]しい        ← single kanji run followed by okurigana
東京湾[とうきょうわん] ← block bracket fallback (no kana anchors)
```

`null` is stored when the kanji element contains no kanji characters.

### Algorithm

Input: `(kanji_form, reading)` where `reading` is already in hiragana.

**Step 1 — Segment.** Split `kanji_form` into alternating runs:

- **Kana run** — consecutive non-kanji characters.
- **Kanji run** — consecutive CJK Unified Ideographs (also covers CJK
  Compatibility Ideographs U+F900–U+FAFF and Extension B U+20000–U+2A6DF).

Example: `食べ物` → `[kanji:"食", kana:"べ", kanji:"物"]`

**Step 2 — Walk left to right** with a cursor `pos` into `reading`.

- **Kana run:** the run text (normalised to hiragana) must equal
  `reading[pos:pos+len(run)]`.  Advance `pos` by the run length.  Mismatch →
  fallback.
- **Kanji run:** look ahead for the next kana run.  Find that kana string in
  `reading[pos:]`; everything before it is the reading for this kanji run.
  If no kana run follows, consume all remaining reading characters.  Empty
  reading assigned to a kanji run → fallback.

**Step 3 — Validate.** `pos` must equal `len(reading)` after all segments.

**Fallback:** any failure produces `kanji_form[reading_hira]`.

### Examples

| Kanji form | Reading | Result |
|---|---|---|
| `食べ物` | `たべもの` | `食[た]べ物[もの]` |
| `難しい` | `むずかしい` | `難[むずか]しい` |
| `真っ青` | `まっさお` | `真[ま]っ青[さお]` |
| `毒を以て毒を制す` | `どくをもってどくをせいす` | `毒[どく]を以[もっ]て毒[どく]を制[せい]す` |
| `東京湾` | `とうきょうわん` | `東京湾[とうきょうわん]` ← block fallback |

### Limitation

Consecutive kanji without an interleaved kana anchor produce a single block
bracket because there is no anchor to split the reading.  The informed solver
(§4) resolves this.

---

## 4 — Furigana: Kanjidic2 knowledge (reading variants)

**File:** `jmdict-to-git.py`  
**Functions:** `_sokuon`, `_rendaku`, `_on_variants`, `build_knowledge`

Before running the informed solver the pipeline builds a lookup table
`{char → frozenset of valid hiragana reading stems}` from the gitjidic2 JSON
repository.

### Reading variants

A single Kanjidic2 on'yomi can surface as up to four forms in a compound:

| Variant | Derivation | Example (一, on イチ → いち) |
|---|---|---|
| Base | katakana → hiragana | いち |
| Sokuon | replace final mora with っ | いっ (一括 いっかつ) |
| Rendaku | voice initial mora | いぢ (rare, but stored) |
| Rendaku-sokuon | both transformations | いっ + voiced (uncommon) |

Sokuon is only applicable when the on'yomi ends in `く き ち つ`.

Rendaku voices the initial mora using the voicing table for か-row, さ-row,
た-row, and は-row kana.  Digraphs (e.g. `しゃ → じゃ`) are handled by voicing
the first mora and preserving the small-kana second character.

Kun'yomi: only the stem before the `.` okurigana separator is stored, plus its
rendaku variant.

```python
_SOKUON_FINALS = frozenset('くきちつ')

_RENDAKU = {
    'か':'が', 'き':'ぎ', 'く':'ぐ', 'け':'げ', 'こ':'ご',
    'さ':'ざ', 'し':'じ', 'す':'ず', 'せ':'ぜ', 'そ':'ぞ',
    'た':'だ', 'ち':'ぢ', 'つ':'づ', 'て':'で', 'と':'ど',
    'は':'ば', 'ひ':'び', 'ふ':'ぶ', 'へ':'べ', 'ほ':'ぼ',
}
```

The resulting frozenset for each character contains all forms that might
legitimately appear as that character's reading contribution in a compound.

---

## 5 — Furigana: informed solver (constrained backtracking)

**File:** `jmdict-to-git.py`  
**Function:** `_split_kanji_run`

Called by `_solve_ignorant` for multi-character kanji runs (two or more
consecutive kanji) when Kanjidic2 knowledge is available.

### Goal

Given a kanji run `A₁A₂…Aₙ` (e.g. `東京湾`) and its total reading `R`
(e.g. `とうきょうわん`), find the unique way to assign one reading per
character such that each assignment is a known reading of that character.

### Algorithm

Walk the characters left to right.  At each position, iterate over the known
reading variants for the current character (from the knowledge frozenset).
For each variant, check whether `R` starts with that variant at the current
cursor position (`str.startswith` — no substring allocation).  On a match,
recurse to the next character with the cursor advanced.

```python
def _split_kanji_run(run, reading, knowledge):
    n = len(run)
    found = []

    def search(char_idx, pos, current):
        if char_idx == n:
            if pos == len(reading):
                found.append(tuple(current))
            return len(found) < 2          # stop once ambiguous
        for stem in knowledge.get(run[char_idx], ()):
            if reading.startswith(stem, pos):
                current.append(stem)
                if not search(char_idx + 1, pos + len(stem), current):
                    return False
                current.pop()
        return True

    search(0, 0, [])
    return found[0] if len(found) == 1 else None
```

Returns the unique valid assignment as a tuple of per-character reading strings,
or `None` when the split is impossible or ambiguous.  `None` causes the caller
to keep the block bracket from the ignorant solver.

### Complexity

The old approach (exhaustive partition enumeration) visited C(len(R)−1, n−1)
candidates unconditionally.  The backtracking approach only visits nodes where
a known reading matches at that position.  In practice each character has
O(1–15) known readings, the reading string acts as a strong filter, and the
search tree is nearly linear.  Early termination fires as soon as a second
valid assignment is found (ambiguity detection).

### Examples

| Kanji run | Reading | Result |
|---|---|---|
| `東京湾` | `とうきょうわん` | `東[とう]京[きょう]湾[わん]` |
| `日本語` | `にほんご` | `日[に]本[ほん]語[ご]` |
| `勉強` | `べんきょう` | `勉[べん]強[きょう]` |

---

## 6 — Reading-to-writing bridge (appliesToKanji)

**File:** `jmdict-to-git.py`  
**Function:** `_find_reading`

Each kana element in JMdict carries an `appliesToKanji` list that restricts
which kanji forms the reading is valid for.  The value `["*"]` means
unrestricted.

```python
def _find_reading(kanji_text, kana_list):
    for k in kana_list:
        applies = k.get('appliesToKanji', ['*'])
        if '*' in applies or kanji_text in applies:
            return k['text']
    return None
```

Returns the first matching kana reading, or `None` when no reading applies.
Used to find the correct reading for each kanji form before computing furigana.

---

## 7 — JSON Merge Patch (RFC 7396)

**File:** `jmdict-to-git.py`  
**Functions:** `load_patches`, `apply_patch`

Community corrections to JMdict entries are stored as RFC 7396 JSON Merge
Patches under `patches/entries/{shard}/{seq}.json`.  The directory structure
mirrors the gitmdict JSON repo.

A merge patch is a JSON object.  Each key either replaces the corresponding key
in the entry data (any non-null value) or removes it (null value).  Keys absent
from the patch are left unchanged.

```python
def apply_patch(data, patch):
    for key, value in patch.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
```

Patches are applied to the assembled entry dict after furigana computation and
before writing the JSON file.  To correct a reading the patch must also include
corrected `kanji` data with updated `furigana` values, since furigana is
computed before patching.

`load_patches` silently returns an empty dict when the `patches/entries/`
directory is absent, so builds without any patches are unaffected.

---

## 8 — Cross-reference resolution (xref / ant)

**File:** `gitmdict-to-sqlite.py`  
**Functions:** `build_xref_index`, `_parse_xref_text`, `_resolve_one_xref`, `_resolve_xref_array`

JMdict cross-reference strings (`xref`, `ant`) use the formats:

```
headword
headword・reading
headword・sense_num
headword・reading・sense_num
```

The pipeline resolves these to concrete entry sequence numbers via a pre-built
index.

### Index building

Before the main insertion loop, `build_xref_index` scans the entire
`gitmdict/entries/` tree once and builds two dicts:

- `kanji_to_seqs`: `{kanji_text → [seq, …]}`
- `kana_to_seqs`:  `{kana_text  → [seq, …]}`

### Resolution

For each xref string, `_parse_xref_text` extracts `(headword, reading,
sense_num)`.  Then `_resolve_one_xref` intersects (headword present in both
kanji and kana index) or unions (headword-only lookup) the candidate seq sets
and takes the minimum seq as the target (lowest seq = earliest JMdict entry for
that headword).

```python
if reading:
    candidates = set(kanji_to_seqs.get(headword, [])) & set(kana_to_seqs.get(reading, []))
else:
    candidates = set(kanji_to_seqs.get(headword, [])) | set(kana_to_seqs.get(headword, []))
seq = min(candidates) if candidates else None
```

Unresolvable references retain `text` but omit `seq`.  The result is stored
as the JSON structure described in Database.md.

---

## 9 — Deinflection rule derivation

**File:** `gitmdict-to-sqlite.py`  
**Functions:** `derive_rules`, `_POS_TO_RULES`

The `rules` column in `DictionaryEntry` enables client-side deinflection
(matching inflected query forms against dictionary entries).

JMdict POS entity codes are mapped to Yomitan-compatible rule codes:

| POS codes | Rule |
|---|---|
| `v1`, `v1-s` | `v1` (ichidan verb) |
| `v5aru`, `v5b`, `v5g`, `v5k`, `v5k-s`, `v5m`, `v5n`, `v5r`, `v5r-i`, `v5s`, `v5t`, `v5u`, `v5u-s`, `v5uru` | `v5` (godan verb) |
| `vk` | `vk` (irregular くる) |
| `vs-i`, `vs-s` | `vs` (suru-verb) |
| `vz` | `vz` (zuru-verb) |
| `adj-i`, `adj-ix` | `adj-i` (i-adjective) |

All POS codes across all senses of an entry are collected, mapped, and
deduplicated.  The result is a space-separated sorted string, e.g. `"v1 vs"`.
Returns `null` for entries with no inflectable POS (nouns, particles, etc.).

---

## 10 — Headword scoring

**File:** `gitmdict-to-sqlite.py`  
**Functions:** `compute_score`, `_IRREGULAR_KANJI_TAGS`

The `score` column ranks entries within an FTS5 tier:

| Score | Condition |
|---|---|
| `+1` | At least one kanji or kana element is marked common (has any priority tag: `ichi1`, `news1`, `nf*`, `spec1`, `spec2`, `gai1`, `gai2`) |
| `-1` | Entry has kanji elements AND every kanji element carries at least one of `iK` (irregular kanji), `rK` (rarely-used kanji), `io` (outdated orthography) AND none are common |
| `0` | All other cases (standard non-priority, kana-only entries) |

```python
_IRREGULAR_KANJI_TAGS = frozenset({'iK', 'rK', 'io'})

def compute_score(kanji_list, kana_list):
    if any(k['common'] for k in kanji_list) or any(k['common'] for k in kana_list):
        return 1
    if kanji_list and all(
        set(k.get('tags', [])) & _IRREGULAR_KANJI_TAGS for k in kanji_list
    ):
        return -1
    return 0
```

Kana-only entries (empty `kanji_list`) can never score −1 since there are no
kanji elements to be irregular.

---

## 11 — FTS5 search tiers

**File:** `sumatora-query.py`  
**Variable:** `_TIERS`

Forward search uses four FTS5 column groups tried in priority order.  The
search stops at the first tier that produces any results.

```python
_TIERS = [
    ('writingsPrio',     'writingsPrio',  'kanji'),
    ('writings',         'writings',      'kanji'),
    ('readingsPrioKana', 'readingsPrio',  'kana'),
    ('readingsKana',     'readings',      'kana'),
]
```

Each tier is tried with three match modes in order:

1. **Exact** — `column MATCH term` (FTS5 exact token match)
2. **Prefix** — `column MATCH term*`
3. **Substring** — `columnParts MATCH term*` (suffix-parts index, §2)

Results within a tier are ordered by `DictionaryEntry.score DESC` (§10).
A `seen_seqs` set prevents the same entry appearing twice across tiers.

For reverse (gloss) search, `DictionaryTranslationIndex.gloss MATCH term` is
tried last (exact then prefix), independently of the kana/kanji tiers.

---

## 12 — stagk/stagr sense filtering

**File:** `sumatora-query.py`  
**Functions:** `matched_form`, `applicable_senses`

JMdict `<stagk>` and `<stagr>` restrict individual senses to specific kanji or
kana forms respectively.  These are applied at query time, not at index time.

### Identifying the matched form

`matched_form(expr, row)` walks the tier columns in priority order
(`writingsPrio`, `writings`, `readingsPrio`, `readings`) and returns the first
column whose space-separated token list contains `expr`.

```python
for entry_col_value, form_type in [(wp,'kanji'),(w,'kanji'),(rp,'kana'),(r,'kana')]:
    if entry_col_value and expr in entry_col_value.split():
        return (expr, None) if form_type == 'kanji' else (None, expr)
```

### Filtering

`applicable_senses(stagk_json, stagr_json, kanji_form, kana_form)` returns the
set of sense indices that apply to the matched form.  Sense `i` is included
when both conditions hold:

- `stagk[i]` is empty **or** `kanji_form` is `None` **or** `kanji_form ∈ stagk[i]`
- `stagr[i]` is empty **or** `kana_form` is `None` **or** `kana_form ∈ stagr[i]`

Returns `None` (no filtering) when neither `stagk` nor `stagr` carry any
restrictions across any sense.

---

## 13 — Tatoeba token resolution

**File:** `gitoeba-to-sqlite.py`  
**Class:** `TokenResolver`

Tatoeba B-line annotations provide per-token `(writing, reading)` pairs for
Japanese sentences.  Each token must be resolved to a JMdict `seq` number so
example sentences can be linked to dictionary entries.

### Resolution query

When `reading` is present, the token must match in both a writing column and a
kana column (intersection):

```sql
SELECT rowid FROM (
    SELECT rowid FROM DictionaryIndex WHERE writingsPrio MATCH ?
    UNION
    SELECT rowid FROM DictionaryIndex WHERE writings MATCH ?
) INTERSECT SELECT rowid FROM (
    SELECT rowid FROM DictionaryIndex WHERE readingsPrioKana MATCH ?
    UNION
    SELECT rowid FROM DictionaryIndex WHERE readingsKana MATCH ?
)
```

When `reading` is absent (kana-only token), only the writing columns are
searched (union of priority and non-priority).

Results are cached keyed by `(writing, reading)` since Tatoeba reuses the same
vocabulary across many sentences.

### Ambiguity

A token is ambiguous when more than one seq is returned.  All resolved seqs are
linked to the sentence; the `matched_token` stored is the surface form
(`expression` field if present, otherwise `writing`).  When the same `(seq,
sentence_id)` pair would be inserted twice (from different tokens in the same
sentence), `INSERT OR IGNORE` keeps only the first match.

---

## 14 — Tatoeba sentence furigana markup

**File:** `gitoeba-to-sqlite.py`  
**Function:** `markup_sentence`

Sentence text is stored with `{expression;reading}` spans over kanji-containing
tokens.  Pure-kana expressions are left unmarked.

```python
def markup_sentence(text, indices):
    remaining = text
    parts = []
    for tok in indices:
        reading = tok.get('reading')
        if not reading:
            continue
        expression = tok.get('expression') or tok['writing']
        if not _has_kanji(expression):
            continue
        idx = remaining.find(expression)
        if idx == -1:
            continue
        parts.append(remaining[:idx])
        parts.append(f'{{{expression};{reading}}}')
        remaining = remaining[idx + len(expression):]
    parts.append(remaining)
    return ''.join(parts)
```

Tokens are applied left to right.  If a token's expression is not found in the
remaining (unprocessed) sentence text it is silently skipped.

`_has_kanji` tests the CJK Unified Ideographs range (U+4E00–U+9FFF) plus CJK
Radicals Supplement and Extension A/B.

`indices` is generic — this function does not care where tokens come from.
Historically it was fed Tatoeba's own B-line annotations directly, which meant
furigana only appeared on words a Tatoeba contributor had manually indexed and
verified; kanji outside that manually-annotated subset, and entire sentences
with no B-line data at all, were left unmarked. §15 replaces that token source
with full MeCab tokenization, so `markup_sentence` itself needed no changes —
only what gets passed in as `indices` changed. The original B-line `indices`
are still used unchanged for JMdict seq resolution (§13); that's a distinct
concern (which dictionary entries a sentence should link to) from furigana
display coverage.

---

## 15 — MeCab tokenization for full-sentence furigana

**File:** `gitoeba-to-sqlite.py`  
**Class/Functions:** `MecabTokenizer`, `_reading_of`

Rather than depending on Tatoeba's partial B-line annotations for furigana
coverage, every sentence is tokenized directly with MeCab (via the `fugashi`
binding) against the UniDic dictionary directory produced by
`unidic-to-git.py`. Every morpheme MeCab finds — not just the ones a Tatoeba
contributor happened to annotate — becomes a candidate for a furigana span.

```python
_KANA_COL = 20

def _reading_of(word):
    feature = word.feature
    if len(feature) <= _KANA_COL:
        return None
    kana = feature[_KANA_COL]
    if not kana or kana == '*':
        return None
    return _kata_to_hira(kana)

class MecabTokenizer:
    def __init__(self, dicdir):
        self._tagger = fugashi.GenericTagger(f'-d {dicdir} -r /dev/null')

    def tokenize(self, text):
        tokens = []
        for word in self._tagger(text):
            tok = {'writing': word.surface}
            reading = _reading_of(word)
            if reading:
                tok['reading'] = reading
            tokens.append(tok)
        return tokens
```

### Which UniDic feature is "the reading"

UniDic's 29-field schema has two katakana reading fields that read
differently for the same word:

| Field | Index | Example (東京) | Reflects |
|---|---|---|---|
| `pron` | 9 | トーキョー | Phonetic pronunciation (vowel lengthening, devoicing, etc.) |
| `kana` | 20 | トウキョウ | Orthographic reading, spelled out as written |

Conventional furigana uses the orthographic form — nobody writes 東京's ruby
as とーきょー. `unk.dic`'s output format and most MeCab tutorials default to
`pron` (field 9), which would produce furigana with stray `ー` marks that
don't match how the word is actually spelled in kana. Field 20 was confirmed
empirically against `sys.dic` (e.g. 西東京 → pron `ニシトーキョー` vs.
kana `ニシトウキョウ`) and cross-checked against UniDic's published field
list; see `unidic-to-git.py`'s module docstring for the same table with the
pitch-accent field (`aType`, index 24) included.

### Coverage and fallback

`_reading_of` returns `None` (leaving that span unmarked, same as
`markup_sentence`'s existing behaviour) for:

- **Unknown words** — text MeCab can't match against the dictionary (numbers,
  rare proper nouns). These come back with a short feature tuple from
  `unk.dic`'s output format, with no field 20 to read.
- **Symbols and punctuation** — `kana` is the literal string `*`.

Because MeCab's surfaces are emitted in order and exactly reconstitute the
input sentence, `markup_sentence`'s left-to-right substring search always
succeeds immediately (the next token is always the head of what remains) —
unlike the old B-line-driven approach, there is no possibility of a token
being silently skipped for failing to align with the sentence text.

### Dictionary directory

`unidic-to-git.py` already downloads UniDic from NINJAL for pitch accent data
(§ pitch.db in Database.md) and, since the dicdir-extraction change described
in its module docstring, extracts the full set of files a MeCab dictionary
needs (`sys.dic`, `matrix.bin`, `char.bin`, `unk.dic`, `dicrc`) rather than
just `sys.dic`. The resulting cache directory is passed to
`gitoeba-to-sqlite.py` via `-u`/`--unidic` and used directly as MeCab's `-d`
dicdir — no separate download or model conversion needed for tokenization.

---

## 16 — Pitch accent data merging

**File:** `pitch-to-git.py`  
**Functions:** `parse_tsv`, `_parse_pitches`, `process`

Multiple pitch accent TSV sources may be supplied.  Entries for the same
`(word, reading)` pair are merged by unioning their pitch position sets.

### TSV input formats

Three-column form: `word<TAB>reading<TAB>pitches`

Two-column form (pure-kana entries): `reading<TAB>pitches` — `word` is set
equal to `reading`.

The `pitches` field accepts one or more integer positions separated by commas
or spaces.  Each position represents a pitch drop point:

- `0` — heiban (flat: LH…H throughout)
- `1` — atamadaka (drops after mora 1: HL…L)
- `N` — drops after mora N; N = mora count means odaka (LH…HL)

Katakana readings are normalised to hiragana.  Word forms are NFC-normalised.

### Merging

```python
# word → {reading → set of pitch positions}
merged = {}
for word, reading, pitches in parse_tsv(path):
    merged.setdefault(word, {}).setdefault(reading, set()).update(pitches)
```

After all files are processed, each `(word, reading)` pair is written as a
single JSON file with a sorted pitch position list, eliminating duplicates
across sources.
