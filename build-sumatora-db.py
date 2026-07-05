#!/usr/bin/env python3
"""Orchestrate the schema-v2 (see schema-v2.md) Sumatora dictionary build pipeline.

This is the v2 counterpart of generate-jmdict.py. Stage 1 (the git-friendly JSON
repos) is unchanged and shared with the v1 pipeline. Stage 2 is replaced: instead
of writing jmdict.db / {lang}.db / kanjidic2.db / pitch.db / examples_{lang}.db,
everything is compiled into a single normalized sumatora.db (schema-v2.md "Option A").

Dependency graph (→ = depends on):

    kanjidic2-to-git.py         →  gitjidic2/
    jmnedict-to-git.py          →  gitnedict/
    jmdict-to-git.py            →  gitmdict/       (uses gitjidic2/ for informed furigana)
    unidic-to-git.py            →  gitch/          (also leaves a MeCab dicdir in the
                                                      unidic cache dir, used below)
    [pitch-to-git.py]           →  gitch/          (curated TSV; overwrites UniDic for same words)

    kanjidic2-to-sumatora-db.py →  sumatora.db (KanjiEntry/KanjiReading/KanjiMeaning)
    jmnedict-to-sumatora-db.py  →  sumatora.db (Entry(name)/EntryForm/NameTranslation/...)
    jmdict-to-sumatora-db.py    →  sumatora.db (Entry(word)/EntryForm/Sense/.../SearchTerm)
    pitch-to-sumatora-db.py     →  sumatora.db (PitchAccent/PitchPattern/FormPitch;
                                                  needs EntryForm from jmdict step)
    [gitoeba-to-sumatora-db.py] →  sumatora.db (Example/ExampleSegment/EntryExample;
                                                  needs SearchTerm/EntryForm from jmdict step)

Steps in brackets are optional and only execute when their prerequisite data
is present.

Usage:
    build-sumatora-db.py -o <sqlite output dir>
        [--gitjidic2  <dir>]   intermediate kanjidic2 JSON repo  (default: ~/Code/gitjidic2)
        [--gitmdict   <dir>]   intermediate jmdict JSON repo      (default: ~/Code/gitmdict)
        [--gitnedict  <dir>]   intermediate jmnedict JSON repo    (default: ~/Code/gitnedict)
        [--gitch      <dir>]   intermediate pitch JSON repo       (default: ~/Code/gitch)
        [--pitch-dir  <dir>]   directory scanned for *.tsv pitch files (default: ~/Code/pitch)
        [--pitch-tsv  <file>]  repeatable; explicit pitch TSV file (overrides --pitch-dir scan)
        [--gitoeba    <dir>]   Tatoeba JSON corpus                (default: ~/Code/gitoeba)
        [--cache      <dir>]   download cache root                (default: ~/.cache)
        [--skip-stage1]        reuse existing JSON repos instead of re-running
                                kanjidic2-to-git.py / jmnedict-to-git.py / jmdict-to-git.py /
                                unidic-to-git.py / pitch-to-git.py
        [--split-packs]        also write installable pack DBs under <output>/packs
        [--pack-lang <code>]   repeatable pack language (default: eng)
        [--all-pack-languages] split every language present in the monolithic DB

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import glob
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HELP = (
    'usage: build-sumatora-db.py -o <sqlite output dir>\n'
    '    [--gitjidic2  <dir>]   default: ~/Code/gitjidic2\n'
    '    [--gitmdict   <dir>]   default: ~/Code/gitmdict\n'
    '    [--gitnedict  <dir>]   default: ~/Code/gitnedict\n'
    '    [--gitch      <dir>]   default: ~/Code/gitch\n'
    '    [--pitch-dir  <dir>]   default: ~/Code/pitch  (scanned for *.tsv)\n'
    '    [--pitch-tsv  <file>]  repeatable; explicit pitch TSV (overrides --pitch-dir)\n'
    '    [--gitoeba    <dir>]   default: ~/Code/gitoeba\n'
    '    [--cache      <dir>]   default: ~/.cache\n'
    '    [--skip-stage1]        reuse existing JSON repos, skip *-to-git.py steps\n'
    '    [--split-packs]        also write installable pack DBs under <output>/packs\n'
    '    [--pack-lang <code>]   repeatable pack language (default: eng)\n'
    '    [--all-pack-languages] split every language present in the monolithic DB'
)


def script(name):
    return os.path.join(SCRIPT_DIR, name)


def run(*args):
    cmd = [sys.executable] + [str(a) for a in args]
    print('==> ' + ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main(argv):
    output_dir    = ''
    gitjidic2_dir = os.path.expanduser('~/Code/gitjidic2')
    gitmdict_dir  = os.path.expanduser('~/Code/gitmdict')
    gitnedict_dir = os.path.expanduser('~/Code/gitnedict')
    gitch_dir     = os.path.expanduser('~/Code/gitch')
    pitch_dir     = os.path.expanduser('~/Code/pitch')
    gitoeba_dir   = os.path.expanduser('~/Code/gitoeba')
    pitch_tsvs    = []
    cache_dir     = os.path.expanduser('~/.cache')
    skip_stage1   = False
    split_packs   = False
    pack_langs    = []
    all_pack_langs = False

    try:
        opts, _ = getopt.getopt(
            argv, 'ho:',
            ['odir=', 'gitjidic2=', 'gitmdict=', 'gitnedict=', 'gitch=',
             'pitch-dir=', 'gitoeba=', 'pitch-tsv=', 'cache=', 'skip-stage1',
             'split-packs', 'pack-lang=', 'all-pack-languages'],
        )
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)

    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-o', '--odir'):
            output_dir = arg
        elif opt == '--gitjidic2':
            gitjidic2_dir = arg
        elif opt == '--gitmdict':
            gitmdict_dir = arg
        elif opt == '--gitnedict':
            gitnedict_dir = arg
        elif opt == '--gitch':
            gitch_dir = arg
        elif opt == '--pitch-dir':
            pitch_dir = arg
        elif opt == '--gitoeba':
            gitoeba_dir = arg
        elif opt == '--pitch-tsv':
            pitch_tsvs.append(arg)
        elif opt == '--cache':
            cache_dir = arg
        elif opt == '--skip-stage1':
            skip_stage1 = True
        elif opt == '--split-packs':
            split_packs = True
        elif opt == '--pack-lang':
            pack_langs.append(arg)
        elif opt == '--all-pack-languages':
            all_pack_langs = True

    if not output_dir:
        print(HELP)
        sys.exit(2)

    kanjidic2_cache = os.path.join(cache_dir, 'kanjidic2')
    jmnedict_cache  = os.path.join(cache_dir, 'jmnedict')
    jmdict_cache    = os.path.join(cache_dir, 'jmdict')
    unidic_cache    = os.path.join(cache_dir, 'unidic')

    # ------------------------------------------------------------------
    # Stage 1 — build JSON repos (git-friendly intermediate data, shared with v1)
    # ------------------------------------------------------------------

    if skip_stage1:
        print('--- Stage 1 skipped (--skip-stage1): reusing existing JSON repos ---',
              flush=True)
    else:
        print('--- Step 1: kanjidic2-to-git ---', flush=True)
        run(script('kanjidic2-to-git.py'),
            '-o', gitjidic2_dir,
            '--cache', kanjidic2_cache)

        print('--- Step 2: jmnedict-to-git (informed furigana) ---', flush=True)
        run(script('jmnedict-to-git.py'),
            '-o', gitnedict_dir,
            '--kanjidic2', gitjidic2_dir,
            '--cache', jmnedict_cache)

        print('--- Step 3: jmdict-to-git (informed furigana) ---', flush=True)
        run(script('jmdict-to-git.py'),
            '-o', gitmdict_dir,
            '--kanjidic2', gitjidic2_dir,
            '--cache', jmdict_cache)

        print('--- Step 4: unidic-to-git ---', flush=True)
        run(script('unidic-to-git.py'), '-o', gitch_dir, '--cache', unidic_cache)

        if not pitch_tsvs and os.path.isdir(pitch_dir):
            pitch_tsvs = sorted(glob.glob(os.path.join(pitch_dir, '*.tsv')))

        if pitch_tsvs:
            print('--- Step 5: pitch-to-git (overwrites UniDic for curated words) ---',
                  flush=True)
            pitch_args = [script('pitch-to-git.py')]
            for tsv in pitch_tsvs:
                pitch_args += ['-i', tsv]
            pitch_args += ['-o', gitch_dir]
            run(*pitch_args)
        else:
            print(f'--- Step 5: pitch-to-git skipped (no *.tsv in {pitch_dir}) ---', flush=True)

    # ------------------------------------------------------------------
    # Stage 2 — compile JSON repos into one normalized sumatora.db
    # ------------------------------------------------------------------

    os.makedirs(output_dir, exist_ok=True)
    sumatora_db = os.path.join(output_dir, 'sumatora.db')
    if os.path.exists(sumatora_db):
        os.unlink(sumatora_db)

    print('--- Step 6: kanjidic2-to-sumatora-db ---', flush=True)
    run(script('kanjidic2-to-sumatora-db.py'),
        '-i', gitjidic2_dir,
        '-d', sumatora_db)

    print('--- Step 7: jmnedict-to-sumatora-db ---', flush=True)
    run(script('jmnedict-to-sumatora-db.py'),
        '-i', gitnedict_dir,
        '-d', sumatora_db)

    print('--- Step 8: jmdict-to-sumatora-db ---', flush=True)
    run(script('jmdict-to-sumatora-db.py'),
        '-i', gitmdict_dir,
        '-d', sumatora_db)

    print('--- Step 9: pitch-to-sumatora-db ---', flush=True)
    run(script('pitch-to-sumatora-db.py'),
        '-i', gitch_dir,
        '-d', sumatora_db)

    if os.path.isdir(gitoeba_dir):
        print('--- Step 10: gitoeba-to-sumatora-db ---', flush=True)
        run(script('gitoeba-to-sumatora-db.py'),
            '-i', gitoeba_dir,
            '-u', unidic_cache,
            '-d', sumatora_db)
    else:
        print(f'--- Step 10: gitoeba-to-sumatora-db skipped ({gitoeba_dir} not found) ---',
              flush=True)

    if split_packs:
        print('--- Step 11: split-sumatora-packs ---', flush=True)
        run(script('split-sumatora-packs.py'),
            '-i', sumatora_db,
            '-o', os.path.join(output_dir, 'packs'),
            *(['--all-languages'] if all_pack_langs else
              [x for lang in (pack_langs or ['eng']) for x in ('--lang', lang)]))

    print('Done.', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
