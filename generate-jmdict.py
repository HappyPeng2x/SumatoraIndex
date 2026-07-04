#!/usr/bin/env python3
"""Generate gitjidic2 then gitmdict, satisfying the kanjidic2 → jmdict dependency.

Runs kanjidic2-to-git.py first (idempotent — skips download if cached), then
jmdict-to-git.py with --kanjidic2 pointing at the freshly written gitjidic2
directory so the informed furigana solver is active.

Usage:
    generate-jmdict.py -o <gitmdict output dir>
                       [--kanjidic2-dir <gitjidic2 dir>]   default: ~/Code/gitjidic2
                       [--cache <cache dir>]                default: ~/.cache

Downloads are cached; delete the cache files to force a fresh download.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KANJIDIC2_DIR = os.path.expanduser('~/Code/gitjidic2')
DEFAULT_CACHE_DIR = os.path.expanduser('~/.cache')

HELP = (
    'usage: generate-jmdict.py -o <gitmdict dir> '
    '[--kanjidic2-dir <gitjidic2 dir>] [--kanjidic2-db <output dir>] '
    '[--cache <cache dir>]'
)


def run(*args):
    cmd = [sys.executable] + [str(a) for a in args]
    print('==> ' + ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main(argv):
    output_dir = ''
    kanjidic2_dir = DEFAULT_KANJIDIC2_DIR
    kanjidic2_db_dir = None
    cache_dir = DEFAULT_CACHE_DIR
    try:
        opts, _ = getopt.getopt(
            argv, 'ho:',
            ['odir=', 'kanjidic2-dir=', 'kanjidic2-db=', 'cache='],
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
        elif opt == '--kanjidic2-dir':
            kanjidic2_dir = arg
        elif opt == '--kanjidic2-db':
            kanjidic2_db_dir = arg
        elif opt == '--cache':
            cache_dir = arg

    if not output_dir:
        print(HELP)
        sys.exit(2)

    kanjidic2_cache = os.path.join(cache_dir, 'kanjidic2')
    jmdict_cache = os.path.join(cache_dir, 'jmdict')

    kanjidic2_script = os.path.join(SCRIPT_DIR, 'kanjidic2-to-git.py')
    jmdict_script = os.path.join(SCRIPT_DIR, 'jmdict-to-git.py')
    gitjidic2_sqlite_script = os.path.join(SCRIPT_DIR, 'gitjidic2-to-sqlite.py')

    print('--- Step 1: kanjidic2 ---', flush=True)
    run(kanjidic2_script,
        '-o', kanjidic2_dir,
        '--cache', kanjidic2_cache)

    print('--- Step 2: jmdict (informed furigana) ---', flush=True)
    run(jmdict_script,
        '-o', output_dir,
        '--kanjidic2', kanjidic2_dir,
        '--cache', jmdict_cache)

    if kanjidic2_db_dir:
        print('--- Step 3: kanjidic2.db ---', flush=True)
        run(gitjidic2_sqlite_script,
            '-i', kanjidic2_dir,
            '-o', kanjidic2_db_dir)

    print('Done.', flush=True)


if __name__ == '__main__':
    main(sys.argv[1:])
