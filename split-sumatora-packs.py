#!/usr/bin/env python3
"""Split a schema-v2 sumatora.db into installable pack databases.

This is intentionally a release-pack step over an already validated monolithic
v2 database. It preserves table definitions/indexes by copying the source DB,
then pruning each copy to the pack boundary and VACUUMing.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import os
import shutil
import sqlite3
import sys


HELP = (
    'usage: split-sumatora-packs.py -i <sumatora.db> -o <output directory> '
    '[--lang <code>] [--all-languages]'
)

# WebSearchPrefixTop materializes only prefixes broad enough to make a live
# FTS5 scan expensive over HTTP range requests: those with more raw candidate
# entries than _PREFIX_TOP_THRESHOLD, for prefix lengths 1.._PREFIX_TOP_MAX_LEN
# of either script. Each materialized (script, prefix, priority_class) group
# is capped to its top _PREFIX_TOP_CAP rows (already sorted in Android tier
# order) -- comfortably above MAX_ONLINE_RESULTS (54 in the PWA) plus the
# runtime's over-fetch margin for entries already consumed by the exact-match
# tier. See split-sumatora-packs.py's _web_search() and Database.md.
_PREFIX_TOP_THRESHOLD = 50
_PREFIX_TOP_CAP = 80
_PREFIX_TOP_MAX_LEN = 8

_DROP_CORE = (
    'PitchPattern', 'FormPitch', 'PitchAccent',
    'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
    'EntryExample', 'ExampleSegment', 'Example',
    'SearchSuffix',
    'NameTranslation',
)

_DROP_GLOSS = (
    'SearchSuffix',
    'PitchPattern', 'FormPitch', 'PitchAccent',
    'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
    'EntryExample', 'ExampleSegment', 'Example',
    'NameTranslation',
    'SearchTermFts', 'SearchTerm',
    'FormFuriganaSegment', 'FormTag', 'EntryForm', 'EntryTag',
    'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
    'SenseGroupTag', 'SenseGroup', 'FormRule', 'DeinflectionRule',
    'Entry',
)

_DROP_NAMES = (
    'SearchSuffix',
    'GlossSearchFts', 'SenseGloss',
    'PitchPattern', 'FormPitch', 'PitchAccent',
    'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
    'EntryExample', 'ExampleSegment', 'Example',
    'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
    'SenseGroupTag', 'Sense', 'SenseGroup', 'FormRule',
    'DeinflectionRule',
)

_DROP_SUFFIX = tuple(
    t for t in (
        'GlossSearchFts', 'SenseGloss',
        'PitchPattern', 'FormPitch', 'PitchAccent',
        'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
        'EntryExample', 'ExampleSegment', 'Example',
        'NameTranslation',
        'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
        'SenseGroupTag', 'Sense', 'SenseGroup', 'FormRule',
        'DeinflectionRule', 'FormFuriganaSegment', 'FormTag', 'EntryTag',
    )
)

_DROP_PITCH = (
    'SearchSuffix', 'GlossSearchFts', 'SenseGloss',
    'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
    'EntryExample', 'ExampleSegment', 'Example',
    'NameTranslation',
    'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
    'SenseGroupTag', 'Sense', 'SenseGroup', 'FormRule',
    'DeinflectionRule', 'FormFuriganaSegment', 'FormTag', 'EntryTag',
    'SearchTermFts', 'SearchTerm',
)

_DROP_KANJI = (
    'SearchSuffix', 'GlossSearchFts', 'SenseGloss',
    'PitchPattern', 'FormPitch', 'PitchAccent',
    'EntryExample', 'ExampleSegment', 'Example',
    'NameTranslation',
    'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
    'SenseGroupTag', 'Sense', 'SenseGroup', 'FormRule',
    'DeinflectionRule', 'FormFuriganaSegment', 'FormTag', 'EntryTag',
)

_DROP_EXAMPLES = (
    'SearchSuffix', 'GlossSearchFts', 'SenseGloss',
    'PitchPattern', 'FormPitch', 'PitchAccent',
    'KanjiMeaning', 'KanjiReading', 'KanjiEntry',
    'NameTranslation',
    'SenseReference', 'SenseAppliesToForm', 'SenseLanguageSource', 'SenseNote',
    'SenseGroupTag', 'Sense', 'SenseGroup', 'FormRule',
    'DeinflectionRule', 'FormFuriganaSegment', 'FormTag', 'EntryTag',
    'SearchTermFts', 'SearchTerm', 'EntryForm', 'Entry',
)


def _connect(path):
    conn = sqlite3.connect(path)
    conn.execute('PRAGMA foreign_keys = OFF')
    return conn


def _drop_tables(conn, names):
    for name in names:
        conn.execute(f'DROP TABLE IF EXISTS {name}')


def _vacuum(conn):
    conn.commit()
    conn.execute('VACUUM')
    conn.commit()


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.unlink(dst)
    shutil.copy2(src, dst)


def _rebuild_search_fts(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'SearchTermFts'").fetchone():
        conn.execute("INSERT INTO SearchTermFts(SearchTermFts) VALUES ('rebuild')")


def _web_search(src, out_dir):
    """Build the small, range-request-friendly index used by the PWA."""
    path = os.path.join(out_dir, 'sumatora_web_search.db')
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(path):
        os.unlink(path)

    conn = sqlite3.connect(path)
    try:
        # Larger pages reduce HTTP round trips while remaining small enough
        # for random cold reads. Prefix indexes deliberately trade file size
        # for latency on the common one-to-four-character web queries.
        conn.execute('PRAGMA page_size = 16384')
        conn.execute('PRAGMA journal_mode = OFF')
        conn.execute('PRAGMA synchronous = OFF')
        conn.executescript(
            """
            CREATE TABLE WebSearchResult (
                search_id  INTEGER PRIMARY KEY,
                source_key INTEGER NOT NULL,
                entry_id   INTEGER NOT NULL,
                script_order INTEGER NOT NULL,
                priority   INTEGER NOT NULL,
                entry_score INTEGER NOT NULL
            );

            -- Some prefixes (either script, any length) match thousands of
            -- entries -- one-character kana prefixes average 3000+
            -- candidates, but so do a handful of common single kanji and
            -- even some 3-character kana prefixes. FTS5 must enumerate every
            -- posting for a prefix before it can rank them, which is cheap
            -- locally but causes hundreds of HTTP range reads online. This
            -- covering table pre-ranks exactly the prefixes broad enough to
            -- need it -- selected by candidate count, not by prefix length
            -- or script -- in Android's tier order, so a query can stop
            -- after one indexed seek instead of sorting the whole posting
            -- list.
            CREATE TABLE WebSearchPrefixTop (
                script_order   INTEGER NOT NULL,
                prefix         TEXT NOT NULL,
                priority_class INTEGER NOT NULL,
                entry_score    INTEGER NOT NULL,
                entry_id       INTEGER NOT NULL,
                source_key     INTEGER NOT NULL,
                PRIMARY KEY (
                    script_order, prefix, priority_class,
                    entry_score DESC, entry_id, source_key
                )
            ) WITHOUT ROWID;

            CREATE VIRTUAL TABLE WebSearchFts USING fts5(
                normalized,
                content='',
                columnsize=0,
                detail=column,
                prefix='1 2 3 4'
            );
            """
        )
        conn.execute('ATTACH DATABASE ? AS source', (src,))
        source_filter = """
            FROM source.SearchTerm AS st
            JOIN source.Entry AS e ON e.entry_id = st.entry_id
            WHERE e.entry_type = 'word'
              AND st.script IN ('writing', 'kana', 'romaji')
        """
        conn.execute(
            """
            INSERT INTO WebSearchResult(
                search_id, source_key, entry_id, script_order, priority, entry_score
            )
            SELECT st.search_id, CAST(e.source_key AS INTEGER), e.entry_id,
                   CASE st.script WHEN 'writing' THEN 0 WHEN 'kana' THEN 1 ELSE 2 END,
                   st.priority, e.score
            """ + source_filter
        )
        conn.execute(
            """
            INSERT INTO WebSearchFts(rowid, normalized)
            SELECT st.search_id, st.normalized
            """ + source_filter
        )
        # WebSearchFts's tokenizer splits on internal separators (e.g. the
        # middle dot in "アーリー・アメリカン"), so a MATCH query can match a
        # later token that a naive substr(normalized, 1, n) prefix would
        # never see. fts5vocab's 'instance' mode reads the index's own
        # token->rowid postings directly, so prefixes generated from it are
        # guaranteed to agree with what MATCH actually finds at query time --
        # unlike re-deriving tokenization rules by hand, which would have to
        # track FTS5's tokenizer exactly to stay correct.
        conn.execute(
            "CREATE VIRTUAL TABLE temp.web_search_vocab "
            "USING fts5vocab('main', 'WebSearchFts', 'instance')"
        )
        conn.execute(
            f"""
            INSERT INTO WebSearchPrefixTop(
                script_order, prefix, priority_class, entry_score, entry_id, source_key
            )
            SELECT script_order, prefix, priority_class, entry_score, entry_id, source_key
            FROM (
                SELECT
                    dedup.*,
                    COUNT(*) OVER (
                        PARTITION BY script_order, prefix, priority_class
                    ) AS group_size,
                    ROW_NUMBER() OVER (
                        PARTITION BY script_order, prefix, priority_class
                        ORDER BY entry_score DESC, entry_id
                    ) AS rn
                FROM (
                    SELECT
                        wr.script_order AS script_order,
                        substr(v.term, 1, lengths.n) AS prefix,
                        CASE WHEN MAX(wr.priority) > 0 THEN 1 ELSE 0 END AS priority_class,
                        wr.entry_score AS entry_score, wr.entry_id AS entry_id,
                        wr.source_key AS source_key
                    FROM temp.web_search_vocab AS v
                    JOIN WebSearchResult AS wr ON wr.search_id = v.doc
                    JOIN (
                        SELECT 1 AS n
                        {''.join(f' UNION ALL SELECT {n}' for n in range(2, _PREFIX_TOP_MAX_LEN + 1))}
                    ) AS lengths
                    WHERE length(v.term) >= lengths.n
                    GROUP BY wr.script_order, prefix, wr.entry_id
                ) AS dedup
            )
            WHERE group_size > {_PREFIX_TOP_THRESHOLD} AND rn <= {_PREFIX_TOP_CAP}
            """
        )
        conn.execute('DROP TABLE temp.web_search_vocab')
        conn.execute("INSERT INTO WebSearchFts(WebSearchFts) VALUES ('optimize')")
        conn.commit()
        conn.execute('DETACH DATABASE source')
        conn.execute('PRAGMA user_version = 2')
        conn.commit()
        conn.execute('VACUUM')
        conn.commit()
    finally:
        conn.close()


def _rebuild_gloss_fts(conn):
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'GlossSearchFts'").fetchone():
        conn.execute("INSERT INTO GlossSearchFts(GlossSearchFts) VALUES ('rebuild')")


def _delete_entries_not(conn, entry_type):
    conn.execute(
        'DELETE FROM Entry WHERE entry_type != ?',
        (entry_type,),
    )
    conn.execute(
        'DELETE FROM EntryForm WHERE entry_id NOT IN (SELECT entry_id FROM Entry)'
    )
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'SearchTerm'").fetchone():
        conn.execute(
            'DELETE FROM SearchTerm WHERE entry_id NOT IN (SELECT entry_id FROM Entry)'
        )
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'EntryTag'").fetchone():
        conn.execute(
            'DELETE FROM EntryTag WHERE entry_id NOT IN (SELECT entry_id FROM Entry)'
        )
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'FormTag'").fetchone():
        conn.execute(
            'DELETE FROM FormTag WHERE form_id NOT IN (SELECT form_id FROM EntryForm)'
        )
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'FormFuriganaSegment'").fetchone():
        conn.execute(
            'DELETE FROM FormFuriganaSegment WHERE form_id NOT IN (SELECT form_id FROM EntryForm)'
        )


def _core(src, out_dir):
    path = os.path.join(out_dir, 'sumatora_core.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_CORE)
    conn.execute('DROP TABLE IF EXISTS GlossSearchFts')
    conn.execute('DELETE FROM SenseGloss')
    _delete_entries_not(conn, 'word')
    conn.execute(
        'DELETE FROM Sense WHERE entry_id NOT IN (SELECT entry_id FROM Entry)'
    )
    conn.execute(
        'DELETE FROM SenseGroup WHERE entry_id NOT IN (SELECT entry_id FROM Entry)'
    )
    conn.execute(
        'DELETE FROM SenseGroupTag WHERE sense_group_id NOT IN '
        '(SELECT sense_group_id FROM SenseGroup)'
    )
    conn.execute(
        'DELETE FROM SenseReference WHERE sense_id NOT IN (SELECT sense_id FROM Sense)'
    )
    conn.execute(
        'DELETE FROM SenseAppliesToForm WHERE sense_id NOT IN (SELECT sense_id FROM Sense)'
    )
    conn.execute(
        'DELETE FROM SenseLanguageSource WHERE sense_id NOT IN (SELECT sense_id FROM Sense)'
    )
    conn.execute(
        'DELETE FROM SenseNote WHERE sense_id NOT IN (SELECT sense_id FROM Sense)'
    )
    conn.execute(
        'DELETE FROM FormRule WHERE form_id NOT IN (SELECT form_id FROM EntryForm)'
    )
    _rebuild_search_fts(conn)
    _vacuum(conn)
    conn.close()


def _gloss(src, out_dir, lang):
    path = os.path.join(out_dir, f'sumatora_gloss_{lang}.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_GLOSS)
    conn.execute('DELETE FROM SenseGloss WHERE lang != ?', (lang,))
    conn.execute(
        'DELETE FROM Sense WHERE sense_id NOT IN (SELECT DISTINCT sense_id FROM SenseGloss)'
    )
    _rebuild_gloss_fts(conn)
    _vacuum(conn)
    conn.close()


def _names(src, out_dir):
    path = os.path.join(out_dir, 'sumatora_names.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_NAMES)
    _delete_entries_not(conn, 'name')
    _rebuild_search_fts(conn)
    _vacuum(conn)
    conn.close()


def _suffix(src, out_dir):
    path = os.path.join(out_dir, 'sumatora_search_suffix.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_SUFFIX)
    conn.execute(
        "DELETE FROM SearchTerm WHERE entry_id NOT IN "
        "(SELECT entry_id FROM Entry WHERE entry_type = 'word')"
    )
    _delete_entries_not(conn, 'word')
    conn.execute('DROP TABLE IF EXISTS SearchTermFts')
    _vacuum(conn)
    conn.close()


def _pitch(src, out_dir):
    path = os.path.join(out_dir, 'sumatora_pitch.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_PITCH)
    conn.execute(
        'DELETE FROM Entry WHERE entry_id NOT IN '
        '(SELECT f.entry_id FROM EntryForm f JOIN FormPitch fp ON fp.form_id = f.form_id)'
    )
    conn.execute(
        'DELETE FROM EntryForm WHERE form_id NOT IN (SELECT form_id FROM FormPitch)'
    )
    _vacuum(conn)
    conn.close()


def _kanji(src, out_dir):
    path = os.path.join(out_dir, 'sumatora_kanji.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_KANJI)
    _delete_entries_not(conn, 'kanji')
    _rebuild_search_fts(conn)
    _vacuum(conn)
    conn.close()


def _examples(src, out_dir, lang):
    path = os.path.join(out_dir, f'sumatora_examples_{lang}.db')
    _copy(src, path)
    conn = _connect(path)
    _drop_tables(conn, _DROP_EXAMPLES)
    conn.execute('DELETE FROM Example WHERE lang != ?', (lang,))
    conn.execute(
        'DELETE FROM EntryExample WHERE example_id NOT IN (SELECT example_id FROM Example)'
    )
    conn.execute(
        'DELETE FROM ExampleSegment WHERE example_id NOT IN (SELECT example_id FROM Example)'
    )
    _vacuum(conn)
    conn.close()


def _langs(conn, table, column='lang'):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone():
        return []
    return [r[0] for r in conn.execute(f'SELECT DISTINCT {column} FROM {table} ORDER BY {column}')]


def split(src, out_dir, requested_langs, all_languages):
    os.makedirs(out_dir, exist_ok=True)
    with sqlite3.connect(src) as conn:
        gloss_langs = _langs(conn, 'SenseGloss')
        example_langs = _langs(conn, 'Example')
    if not all_languages:
        wanted = set(requested_langs or ['eng'])
        gloss_langs = [lang for lang in gloss_langs if lang in wanted]
        example_langs = [lang for lang in example_langs if lang in wanted]

    print('core', flush=True)
    _core(src, out_dir)
    print('web search', flush=True)
    _web_search(src, out_dir)
    print('names', flush=True)
    _names(src, out_dir)
    print('suffix', flush=True)
    _suffix(src, out_dir)
    print('pitch', flush=True)
    _pitch(src, out_dir)
    print('kanji', flush=True)
    _kanji(src, out_dir)

    for lang in gloss_langs:
        print(f'gloss {lang}', flush=True)
        _gloss(src, out_dir, lang)
    for lang in example_langs:
        print(f'examples {lang}', flush=True)
        _examples(src, out_dir, lang)


def main(argv):
    src = ''
    out_dir = ''
    langs = []
    all_languages = False
    try:
        opts, _ = getopt.getopt(
            argv, 'hi:o:l:', ['input=', 'output=', 'lang=', 'all-languages'],
        )
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--input'):
            src = arg
        elif opt in ('-o', '--output'):
            out_dir = arg
        elif opt in ('-l', '--lang'):
            langs.append(arg)
        elif opt == '--all-languages':
            all_languages = True
    if not src or not out_dir:
        print(HELP)
        sys.exit(2)
    split(src, out_dir, langs, all_languages)


if __name__ == '__main__':
    main(sys.argv[1:])
