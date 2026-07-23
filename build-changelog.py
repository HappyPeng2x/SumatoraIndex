#!/usr/bin/env python3
"""Build changelog.json from the stage-1 repo diffs captured during sync.

sync-stage1-repo.sh (when given DIFF_OUT) writes `git diff --cached
--name-status` between the previous release's stage-1 snapshot and this
release's freshly generated one -- an exact, free add/modify/delete diff, no
extra downloads or diffing logic needed. This script reads those diff files
and turns the raw paths into a per-category, per-language JSON changelog the
app can show as "recent updates". See changelog-pipeline.md for the full
design.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"

import argparse
import json
import os
import re
import sys

_STATUS_BUCKET = {'A': 'added', 'M': 'modified', 'D': 'removed'}

_ENTRIES_RE = re.compile(r'^entries/[^/]+/([^/]+)\.json$')
_SENTENCES_RE = re.compile(r'^sentences/[^/]+/([^/]+)\.json$')
_CHARACTERS_RE = re.compile(r'^characters/[^/]+/([^/]+)\.json$')
_TRANSLATIONS_RE = re.compile(r'^translations/([^/]+)/[^/]+/([^/]+)\.json$')


def _diff_lines(diffs_dir, repo_name):
    """Yield (bucket, path) from <diffs_dir>/<repo_name>.diff.

    A missing file means the sync step for that repo didn't run (no PAT
    configured) or found no changes -- not an error, just nothing to report.
    """
    diff_path = os.path.join(diffs_dir, f'{repo_name}.diff')
    if not os.path.isfile(diff_path):
        return
    with open(diff_path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line:
                continue
            status, _, filepath = line.partition('\t')
            bucket = _STATUS_BUCKET.get(status[0])
            if bucket is None:
                continue
            yield bucket, filepath


def _bucket(changelog, *keys):
    node = changelog
    for key in keys:
        node = node.setdefault(key, {})
    node.setdefault('added', [])
    node.setdefault('modified', [])
    node.setdefault('removed', [])
    return node


def _process_gitmdict(diffs_dir, changelog):
    for status, filepath in _diff_lines(diffs_dir, 'gitmdict'):
        m = _ENTRIES_RE.match(filepath)
        if m:
            _bucket(changelog, 'jmdict', 'entries')[status].append(int(m.group(1)))
            continue
        m = _TRANSLATIONS_RE.match(filepath)
        if m:
            lang, seq = m.groups()
            _bucket(changelog, 'jmdict', 'translations', lang)[status].append(int(seq))


def _process_gitnedict(diffs_dir, changelog):
    for status, filepath in _diff_lines(diffs_dir, 'gitnedict'):
        m = _ENTRIES_RE.match(filepath)
        if m:
            _bucket(changelog, 'jmnedict', 'entries')[status].append(int(m.group(1)))


def _process_gitjidic2(diffs_dir, changelog):
    for status, filepath in _diff_lines(diffs_dir, 'gitjidic2'):
        m = _CHARACTERS_RE.match(filepath)
        if m:
            char = chr(int(m.group(1), 16))
            _bucket(changelog, 'kanjidic2', 'characters')[status].append(char)


def _process_gitoeba(diffs_dir, changelog):
    for status, filepath in _diff_lines(diffs_dir, 'gitoeba'):
        m = _SENTENCES_RE.match(filepath)
        if m:
            _bucket(changelog, 'tatoeba', 'sentences')[status].append(int(m.group(1)))
            continue
        m = _TRANSLATIONS_RE.match(filepath)
        if m:
            lang, sid = m.groups()
            _bucket(changelog, 'tatoeba', 'translations', lang)[status].append(int(sid))


def _process_gitch(diffs_dir, changelog):
    # gitch holds both UniDic and pitch-accent data at the same paths (pitch
    # overwrites UniDic entries at build time), so this is the sole source
    # for the "pitch" category. '_' undoes the '/'->'_' filename-safety
    # encoding unidic-to-git.py/pitch-to-git.py apply when writing headwords
    # that contain a literal '/' (e.g. okurigana alternatives).
    for status, filepath in _diff_lines(diffs_dir, 'gitch'):
        m = _ENTRIES_RE.match(filepath)
        if m:
            word = m.group(1).replace('_', '/')
            _bucket(changelog, 'pitch', 'entries')[status].append(word)


def _sort_buckets(node):
    for value in node.values():
        if isinstance(value, dict):
            _sort_buckets(value)
        elif isinstance(value, list):
            value.sort()


def build_changelog(diffs_dir, version, previous_version, date):
    changelog = {
        'version': version,
        'previous_version': previous_version,
        'date': date,
    }
    _process_gitmdict(diffs_dir, changelog)
    _process_gitnedict(diffs_dir, changelog)
    _process_gitjidic2(diffs_dir, changelog)
    _process_gitoeba(diffs_dir, changelog)
    _process_gitch(diffs_dir, changelog)
    _sort_buckets(changelog)
    return changelog


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diffs-dir', required=True,
                         help='directory of <repo>.diff files written by sync-stage1-repo.sh '
                              '(DIFF_OUT); a missing <repo>.diff means no changes for that repo')
    parser.add_argument('--version', required=True, type=int,
                         help='repository version this changelog documents')
    parser.add_argument('--previous-version', required=True, type=int,
                         help='repository version being compared against')
    parser.add_argument('--date', required=True, help='repository date, YYYYMMDD')
    parser.add_argument('-o', '--output', required=True, help='output path for changelog.json')
    args = parser.parse_args(argv)

    changelog = build_changelog(args.diffs_dir, args.version, args.previous_version, args.date)

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(changelog, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')

    print(f'Wrote {args.output} (v{args.previous_version} -> v{args.version})', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
