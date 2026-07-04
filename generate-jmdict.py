#!/usr/bin/env python3
"""Orchestrate the full Sumatora dictionary build pipeline.

Runs all pipeline steps in dependency order, producing the complete set of
SQLite databases from downloadable and user-supplied source data.

Dependency graph (→ = depends on):

    kanjidic2-to-git.py    →  gitjidic2/
    jmnedict-to-git.py     →  gitnedict/
    jmdict-to-git.py       →  gitmdict/       (uses gitjidic2/ for informed furigana)
    unidic-to-git.py       →  gitch/          (UniDic pitch from installed pip package)
    [pitch-to-git.py]      →  gitch/          (curated TSV; overwrites UniDic for same words)
    gitjidic2-to-sqlite.py →  kanjidic2.db
    gitmdict-to-sqlite.py  →  jmdict.db, {lang}.db  (uses gitnedict/ for proper names)
    gitch-to-sqlite.py     →  pitch.db
    [gitoeba-to-sqlite.py] →  examples_{lang}.db    (when --gitoeba dir exists)

Steps in brackets are optional and only execute when their prerequisite data
is present.

Usage:
    generate-jmdict.py -o <sqlite output dir>
        [--gitjidic2  <dir>]   intermediate kanjidic2 JSON repo  (default: ~/Code/gitjidic2)
        [--gitmdict   <dir>]   intermediate jmdict JSON repo      (default: ~/Code/gitmdict)
        [--gitnedict  <dir>]   intermediate jmnedict JSON repo    (default: ~/Code/gitnedict)
        [--gitch      <dir>]   intermediate pitch JSON repo       (default: ~/Code/gitch)
        [--pitch-dir  <dir>]   directory scanned for *.tsv pitch files (default: ~/Code/pitch)
        [--pitch-tsv  <file>]  repeatable; explicit pitch TSV file (overrides --pitch-dir scan)
        [--gitoeba    <dir>]   Tatoeba JSON corpus                (default: ~/Code/gitoeba)
        [--cache      <dir>]   download cache root                (default: ~/.cache)

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.3.0"

import getopt
import glob
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HELP = (
    'usage: generate-jmdict.py -o <sqlite output dir>\n'
    '    [--gitjidic2  <dir>]   default: ~/Code/gitjidic2\n'
    '    [--gitmdict   <dir>]   default: ~/Code/gitmdict\n'
    '    [--gitnedict  <dir>]   default: ~/Code/gitnedict\n'
    '    [--gitch      <dir>]   default: ~/Code/gitch\n'
    '    [--pitch-dir  <dir>]   default: ~/Code/pitch  (scanned for *.tsv)\n'
    '    [--pitch-tsv  <file>]  repeatable; explicit pitch TSV (overrides --pitch-dir)\n'
    '    [--gitoeba    <dir>]   default: ~/Code/gitoeba\n'
    '    [--cache      <dir>]   default: ~/.cache'
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

    try:
        opts, _ = getopt.getopt(
            argv, 'ho:',
            ['odir=', 'gitjidic2=', 'gitmdict=', 'gitnedict=', 'gitch=',
             'pitch-dir=', 'gitoeba=', 'pitch-tsv=', 'cache='],
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

    if not output_dir:
        print(HELP)
        sys.exit(2)

    kanjidic2_cache = os.path.join(cache_dir, 'kanjidic2')
    jmnedict_cache  = os.path.join(cache_dir, 'jmnedict')
    jmdict_cache    = os.path.join(cache_dir, 'jmdict')

    # ------------------------------------------------------------------
    # Stage 1 — build JSON repos (git-friendly intermediate data)
    # ------------------------------------------------------------------

    print('--- Step 1: kanjidic2-to-git ---', flush=True)
    run(script('kanjidic2-to-git.py'),
        '-o', gitjidic2_dir,
        '--cache', kanjidic2_cache)

    print('--- Step 2: jmnedict-to-git ---', flush=True)
    run(script('jmnedict-to-git.py'),
        '-o', gitnedict_dir,
        '--cache', jmnedict_cache)

    print('--- Step 3: jmdict-to-git (informed furigana) ---', flush=True)
    run(script('jmdict-to-git.py'),
        '-o', gitmdict_dir,
        '--kanjidic2', gitjidic2_dir,
        '--cache', jmdict_cache)

    print('--- Step 4: unidic-to-git ---', flush=True)
    run(script('unidic-to-git.py'), '-o', gitch_dir)

    if not pitch_tsvs and os.path.isdir(pitch_dir):
        pitch_tsvs = sorted(glob.glob(os.path.join(pitch_dir, '*.tsv')))

    if pitch_tsvs:
        print('--- Step 5: pitch-to-git (overwrites UniDic for curated words) ---', flush=True)
        pitch_args = [script('pitch-to-git.py')]
        for tsv in pitch_tsvs:
            pitch_args += ['-i', tsv]
        pitch_args += ['-o', gitch_dir]
        run(*pitch_args)
    else:
        print(f'--- Step 5: pitch-to-git skipped (no *.tsv in {pitch_dir}) ---', flush=True)

    # ------------------------------------------------------------------
    # Stage 2 — compile JSON repos to SQLite
    # ------------------------------------------------------------------

    print('--- Step 6: gitjidic2-to-sqlite ---', flush=True)
    run(script('gitjidic2-to-sqlite.py'),
        '-i', gitjidic2_dir,
        '-o', output_dir)

    print('--- Step 7: gitmdict-to-sqlite ---', flush=True)
    run(script('gitmdict-to-sqlite.py'),
        '-i', gitmdict_dir,
        '--nedict', gitnedict_dir,
        '-o', output_dir)

    print('--- Step 8: gitch-to-sqlite ---', flush=True)
    run(script('gitch-to-sqlite.py'),
        '-i', gitch_dir,
        '-o', output_dir)

    if os.path.isdir(gitoeba_dir):
        jmdict_path = os.path.join(output_dir, 'jmdict.db')
        print('--- Step 9: gitoeba-to-sqlite ---', flush=True)
        run(script('gitoeba-to-sqlite.py'),
            '-i', gitoeba_dir,
            '-j', jmdict_path,
            '-o', output_dir)
    else:
        print(f'--- Step 9: gitoeba-to-sqlite skipped ({gitoeba_dir} not found) ---',
              flush=True)

    print('Done.', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
