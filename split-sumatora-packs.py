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
