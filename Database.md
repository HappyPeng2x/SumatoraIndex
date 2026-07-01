# Sumatora Database Structure

Two SQLite databases are distributed per language: `jmdict.db` (shared) and `{lang}.db` (one per language, e.g. `eng.db`, `ger.db`). Both are built by `git-to-sqlite.py` from a gitmdict JSON repository.

---

## jmdict.db

### DictionaryEntry

The main entry table. One row per JMdict entry.

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER PK | JMdict sequence number |
| `readingsPrio` | TEXT | Space-separated **priority** kana readings |
| `readings` | TEXT | Space-separated non-priority kana readings |
| `writingsPrio` | TEXT | Space-separated **priority** kanji writings |
| `writings` | TEXT | Space-separated non-priority kanji writings |
| `pos` | TEXT | JSON: per-sense arrays of part-of-speech codes |
| `xref` | TEXT | JSON: per-sense arrays of cross-references |
| `ant` | TEXT | JSON: per-sense arrays of antonyms |
| `misc` | TEXT | JSON: per-sense miscellaneous info |
| `lsource` | TEXT | JSON: per-sense language source info |
| `dial` | TEXT | JSON: per-sense dialect codes |
| `s_inf` | TEXT | JSON: per-sense sense information strings |
| `field` | TEXT | JSON: per-sense field domain codes |

### DictionaryIndex (FTS5, contentless)

FTS5 virtual table used for fast reading/writing lookup. **Contentless** (`content=""`): it stores only the FTS5 token index, not the original text. Column values must be retrieved from `DictionaryEntry`.

The `rowid` of each FTS5 row equals the `seq` of the corresponding `DictionaryEntry` row, so a MATCH result can be joined directly:

```sql
SELECT DictionaryEntry.*
FROM DictionaryEntry
WHERE seq IN (SELECT rowid FROM DictionaryIndex WHERE writingsPrio MATCH ?)
```

| Column | Description |
|---|---|
| `readingsPrioKana` | Priority readings converted to katakana |
| `readingsPrioKanaParts` | Space-separated katakana suffixes of each priority reading (enables substring search) |
| `readingsKana` | Non-priority readings converted to katakana |
| `readingsKanaParts` | Katakana suffixes of non-priority readings |
| `writingsPrio` | Priority kanji writings (verbatim) |
| `writingsPrioParts` | Character suffixes of each priority writing |
| `writings` | Non-priority kanji writings |
| `writingsParts` | Character suffixes of non-priority writings |

**Suffix-parts columns** store all suffixes starting from position 1 of each token (e.g. `カタカナ` → `タカナ カナ ナ`). A `MATCH term*` on a parts column finds entries where `term` appears as a substring within the original word.

**All kana columns store katakana.** Hiragana in the source data is converted to katakana before indexing. Search queries against these columns must also be katakana.

### DictionaryEntity

JMdict XML entity definitions (e.g. `v5k` → `"Godan verb with ku ending"`).

| Column | Type | Description |
|---|---|---|
| `name` | TEXT PK | Entity code |
| `content` | TEXT | Human-readable expansion |

### DictionaryControl

Key/value metadata for the database build.

| Column | Type |
|---|---|
| `control` | TEXT PK |
| `value` | INTEGER |

---

## {lang}.db  (e.g. eng.db, ger.db)

### DictionaryTranslation

One row per sense per entry. `gloss` contains all glosses for a single sense joined with `, `.

| Column | Type | Description |
|---|---|---|
| `seq` | INTEGER | JMdict sequence number (foreign key to DictionaryEntry.seq) |
| `gloss_id` | INTEGER | Sense index within the entry (0-based) |
| `gloss` | TEXT | Comma-joined gloss strings for this sense |
| PRIMARY KEY | (seq, gloss_id) | |

### DictionaryTranslationIndex (FTS5, content table)

FTS5 virtual table backed by `DictionaryTranslation`. The `rowid` of the FTS5 row equals the `rowid` of the corresponding `DictionaryTranslation` row (the implicit SQLite rowid, not `seq`).

```sql
CREATE VIRTUAL TABLE DictionaryTranslationIndex USING fts5(gloss, content="DictionaryTranslation")
```

To find entries matching a gloss term:

```sql
SELECT dt.seq
FROM DictionaryTranslationIndex AS fts
JOIN DictionaryTranslation AS dt ON dt.rowid = fts.rowid
WHERE fts.gloss MATCH ?
```

---

## How apps consume the databases

Both the Android app and the PWA open `jmdict.db` as the main schema and ATTACH the language database:

```sql
ATTACH DATABASE '/eng.db' AS "eng"
-- then query as: jmdict.DictionaryEntry, eng.DictionaryTranslation, eng.DictionaryTranslationIndex
```

### Search strategy (priority order)

Forward search steps (stopping when enough results are found):

1. `writingsPrio MATCH term` — exact kanji, priority
2. `readingsPrioKana MATCH kata` — exact kana, priority
3. `writings MATCH term` — exact kanji, non-priority
4. `readingsKana MATCH kata` — exact kana, non-priority
5. `writingsPrio MATCH term*` — prefix kanji, priority
6. `readingsPrioKana MATCH kata*` — prefix kana, priority
7. `writings MATCH term*` — prefix kanji, non-priority
8. `readingsKana MATCH kata*` — prefix kana, non-priority
9. `writingsPrioParts MATCH term*` — substring kanji, priority
10. `readingsPrioKanaParts MATCH kata*` — substring kana, priority
11. `writingsParts MATCH term*` — substring kanji, non-priority
12. `readingsKanaParts MATCH kata*` — substring kana, non-priority
13. `DictionaryTranslationIndex.gloss MATCH term` — exact gloss
14. `DictionaryTranslationIndex.gloss MATCH term*` — prefix gloss

`kata` is the search term normalized to katakana (hiragana and rōmaji are converted before querying).

---

## Building the databases

```sh
python3 xml-to-git.py -i JMdict_e.xml -o gitmdict/
python3 git-to-sqlite.py -i gitmdict/ -o output/
```

Output: `output/jmdict.db`, `output/eng.db`, `output/ger.db`, etc.
