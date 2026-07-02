# Furigana Algorithm

This document describes how the indexer computes per-character furigana (ruby
text) for JMdict kanji headwords, and what would be needed to improve accuracy
with Kanjidic2.

---

## Output format

Furigana is stored in bracket notation inside each element of the `kanji` array
in the entry JSON:

```
食[た]べ物[もの]
難[むずか]しい
東京湾[とうきょうわん]
```

Rules:
- Kana characters pass through unchanged (no brackets).
- Each kanji run is immediately followed by `[reading]`.
- A consecutive block of kanji without intervening kana gets a single bracket
  spanning the whole block (see *Limitations* below).
- Pure-kana kanji elements (e.g. `食べもの`) receive furigana only over their
  kanji characters: `食[た]べもの`.
- `null` is stored when a kanji element contains no kanji characters at all.

---

## Algorithm (ignorant — no external dictionary)

Input: `(kanji_form, reading)`, e.g. `("食べ物", "たべもの")`.

### Step 1 — Normalise

Convert the reading to hiragana (katakana → hiragana via codepoint shift,
`ー` preserved).  The kanji form is kept as-is but also normalised internally
for matching.

### Step 2 — Segment

Split the kanji form into alternating runs:

- **Kana run** — one or more consecutive non-kanji characters (hiragana,
  katakana, okurigana, punctuation, etc.).
- **Kanji run** — one or more consecutive CJK characters.

Example: `食べ物` → `[kanji:"食", kana:"べ", kanji:"物"]`

### Step 3 — Assign readings left to right

Maintain a cursor `pos` into the (normalised) reading string.

**Kana run** — the run must match the reading at `pos` directly.  Advance
`pos` by the run's length.  If there is a mismatch the algorithm falls back to
whole-word bracketing (see *Failure*).

**Kanji run** — look ahead for the first kana run that follows.  Find that
kana string inside `reading[pos:]`; everything before it is the kanji run's
reading.  Advance `pos` past the kanji reading; the kana run will consume its
own characters in the next iteration.

If no kana run follows (the kanji run ends the word), all remaining reading
characters are assigned to it.

### Step 4 — Validate

After all segments are processed `pos` must equal the total reading length.
Otherwise the segmentation is inconsistent and the algorithm falls back.

### Failure / fallback

Any of the following cause a whole-word block bracket:

- A kana run in the form does not match the reading at the current position.
- The next-kana anchor string is not found in the remaining reading.
- A kanji run would be assigned an empty reading.
- `pos` does not reach the end of the reading after all segments.

Fallback result: `kanji_form[reading_hira]`, e.g. `東京湾[とうきょうわん]`.

### Examples

| Kanji form | Reading | Result |
|---|---|---|
| `食べ物` | `たべもの` | `食[た]べ物[もの]` |
| `難しい` | `むずかしい` | `難[むずか]しい` |
| `真っ青` | `まっさお` | `真[ま]っ青[さお]` |
| `お化け` | `おばけ` | `お化[ば]け` |
| `掻っ攫う` | `かっさらう` | `掻[か]っ攫[さら]う` |
| `毒を以て毒を制す` | `どくをもってどくをせいす` | `毒[どく]を以[もっ]て毒[どく]を制[せい]す` |
| `好き者が嫌い` | `すきものがきらい` | `好[す]き者[もの]が嫌[きら]い` |

### Limitations

**Consecutive kanji blocks** — when two or more kanji appear without an
intervening kana, the algorithm has no anchor to split the reading per
character.  The entire block receives one bracket:

| Kanji form | Reading | Result |
|---|---|---|
| `東京湾` | `とうきょうわん` | `東京湾[とうきょうわん]` |
| `日本語` | `にほんご` | `日本語[にほんご]` |
| `勉強` | `べんきょう` | `勉強[べんきょう]` |
| `御姉さん` | `おねえさん` | `御姉[おねえ]さん` |

This is the same output Jitendex produces through its "lazy ignorant" solver
when no per-character knowledge is available.

---

## Future enhancement — Kanjidic2

Kanjidic2 maps each kanji character to its on-yomi and kun-yomi readings.
With this knowledge, consecutive kanji blocks can be split per character.

### How Jitendex uses it

Jitendex (`Source/Furigana/`) loads Kanjidic2-derived readings into an
in-memory `Knowledge` object before processing JMdict.  The `InformedAlgorithm`
then resolves single kanji characters against their known readings instead of
relying on kana anchors:

- `東[とう]`, `京[きょう]`, `湾[わん]` are each looked up and matched
  against the remaining reading — producing `東[とう]京[きょう]湾[わん]`
  instead of the block bracket.

Jitendex also stores per-compound readings for repeated-use subwords, enabling
correct handling of irregular compound readings.

### What the indexer would need

1. **Download and parse `kanjidic2.xml`** — extract `<reading r_type="ja_on">`
   and `<reading r_type="ja_kun">` for each kanji entry.

2. **Build a lookup table** `{char → [hiragana_readings]}`.  Kun-yomi readings
   often include okurigana separated by `.` (e.g. `おく.る`); strip the suffix
   part, keeping only the prefix.  Strip the okurigana suffix separator.

3. **Enhanced kanji-run resolution** — for a kanji run `A₁A₂…Aₙ` with total
   reading `R`:
   - Try all ways to partition `R` into `n` non-empty parts.
   - Accept a partition only if each part is a known reading of the
     corresponding kanji.
   - If exactly one valid partition exists, use it; otherwise keep the block
     bracket.

4. **Integrate into `jmdict-to-git.py`** — pass the knowledge table to
   `compute_furigana` as an optional parameter; the rest of the algorithm
   (segment parsing, kana pass-through, single-kanji anchoring) is unchanged.

The lookup table for all kanji in Kanjidic2 fits comfortably in memory
(~13 000 entries), so no additional infrastructure is required.
