#!/usr/bin/env python3
"""Gzip installable packs, checksum them, and render dictionaries.xml.

Consumes the output of split-sumatora-packs.py (schema-v2.md packs under a
directory) and produces:

  - one gzip-compressed copy of each pack under --release-dir, named
    exactly as it should appear as a GitHub Release asset (<pack>.db.gz)
  - a dictionaries.xml manifest in the shape SumatoraDictionary's
    BaseDictionaryObject.fromXML / RemoteManifestFetcher already parse: one
    <repository version=".." date=".."> with a <dictionary> child per pack
    (uri, type, description, lang, sha256).

See release-pipeline.md for the full design (why this lives in
SumatoraIndex, the version/date bootstrap, and how the workflow uses this
script).

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.
"""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import argparse
import gzip
import hashlib
import os
import shutil
import sys
from xml.etree import ElementTree as ET
from xml.dom import minidom

# Native-language display names for gloss packs, matching the names already
# used in the bundled app/src/main/assets/dictionaries.xml, so a rebuilt
# manifest reads identically for languages the app already knows about.
_GLOSS_NATIVE_NAMES = {
    'eng': 'English', 'ger': 'Deutsch', 'rus': 'русский язык',
    'spa': 'Español', 'dut': 'Nederlands', 'hun': 'Magyar nyelv',
    'swe': 'Svenska', 'fre': 'Français', 'slv': 'Slovenski jezik',
}

# English display names for example-sentence packs, matching the bundled
# manifest's "<Language> examples" convention. Falls back to the bare code
# for any language not listed here (e.g. a newly-added Tatoeba language)
# rather than failing the build.
_EXAMPLE_LANG_NAMES = {
    'eng': 'English', 'fre': 'French', 'ger': 'German', 'rus': 'Russian',
    'spa': 'Spanish', 'dut': 'Dutch', 'hun': 'Hungarian', 'swe': 'Swedish',
    'slv': 'Slovenian', 'acm': 'Iraqi Arabic', 'afr': 'Afrikaans',
    'ara': 'Arabic', 'baq': 'Basque', 'bel': 'Belarusian', 'ber': 'Berber',
    'bul': 'Bulgarian', 'bur': 'Burmese', 'cat': 'Catalan', 'ceb': 'Cebuano',
    'cmn': 'Mandarin Chinese', 'cor': 'Cornish', 'cze': 'Czech',
    'dan': 'Danish', 'dtp': 'Dusun', 'epo': 'Esperanto', 'est': 'Estonian',
    'fin': 'Finnish', 'fry': 'Frisian', 'heb': 'Hebrew', 'hin': 'Hindi',
    'hrv': 'Croatian', 'hsb': 'Upper Sorbian', 'ice': 'Icelandic',
    'ido': 'Ido', 'ind': 'Indonesian', 'ita': 'Italian', 'jbo': 'Lojban',
    'jpn': 'Japanese', 'kab': 'Kabyle', 'khm': 'Khmer', 'kor': 'Korean',
    'kzj': 'Coastal Kadazan', 'lat': 'Latin', 'lfn': 'Lingua Franca Nova',
    'lit': 'Lithuanian', 'lvs': 'Latvian', 'lzh': 'Literary Chinese',
    'mar': 'Marathi', 'mfa': 'Kelantan-Pattani Malay', 'mon': 'Mongolian',
    'nds': 'Low German', 'nob': 'Norwegian Bokmål', 'npi': 'Nepali',
    'oci': 'Occitan', 'pes': 'Iranian Persian', 'pol': 'Polish',
    'por': 'Portuguese', 'rum': 'Romanian', 'slo': 'Slovak',
    'tat': 'Tatar', 'tgl': 'Tagalog', 'tha': 'Thai', 'tlh': 'Klingon',
    'tok': 'Toki Pona', 'tur': 'Turkish', 'uig': 'Uyghur',
    'ukr': 'Ukrainian', 'vie': 'Vietnamese', 'wuu': 'Wu Chinese',
    'yid': 'Yiddish', 'yue': 'Cantonese', 'zsm': 'Malay',
}


def _pack_metadata(filename):
    """Return (type, lang, description) for a sumatora_*.db pack filename."""
    name = filename[len('sumatora_'):-len('.db')]

    if name == 'core':
        return 'core', '', 'Index'
    if name == 'kanji':
        return 'kanji', '', 'Kanji data'
    if name == 'pitch':
        return 'pitch', '', 'Pitch accent'
    if name == 'search_suffix':
        return 'suffix', '', 'Substring search'
    if name == 'names':
        return 'names', '', 'Proper names (JMnedict)'
    if name.startswith('gloss_'):
        lang = name[len('gloss_'):]
        return 'gloss', lang, _GLOSS_NATIVE_NAMES.get(lang, lang)
    if name.startswith('examples_'):
        lang = name[len('examples_'):]
        return 'tatoeba', lang, f'{_EXAMPLE_LANG_NAMES.get(lang, lang)} examples'
    raise ValueError(f'unrecognized pack filename: {filename}')


# Stable display order: core-ish singletons first, then gloss/tatoeba
# grouped and alphabetized by language, so the manifest diffs cleanly
# release to release instead of reordering on directory-listing order.
_TYPE_ORDER = {'core': 0, 'kanji': 1, 'pitch': 2, 'suffix': 3, 'names': 4,
               'gloss': 5, 'tatoeba': 6}


def _sort_key(pack):
    filename, (pack_type, lang, _description) = pack
    return (_TYPE_ORDER.get(pack_type, 99), lang, filename)


def _sha256_file(path):
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def gzip_and_checksum(packs_dir, release_dir):
    """Gzip every sumatora_*.db under packs_dir into release_dir.

    Returns a list of (gz_filename, pack_type, lang, description, sha256).
    """
    os.makedirs(release_dir, exist_ok=True)
    packs = []

    filenames = sorted(f for f in os.listdir(packs_dir)
                        if f.startswith('sumatora_') and f.endswith('.db'))
    for filename in filenames:
        pack_type, lang, description = _pack_metadata(filename)
        src_path = os.path.join(packs_dir, filename)
        gz_filename = filename + '.gz'
        gz_path = os.path.join(release_dir, gz_filename)

        with open(src_path, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

        sha256 = _sha256_file(gz_path)
        packs.append((gz_filename, pack_type, lang, description, sha256))
        print(f'  {filename} -> {gz_filename} ({sha256[:12]}...)', flush=True)

    packs.sort(key=lambda p: _sort_key((p[0], (p[1], p[2], p[3]))))
    return packs


def render_manifest(packs, version, date, download_base_url,
                     changelog_url=None, changelog_sha256=None):
    """Build the dictionaries.xml ElementTree for the given packs."""
    attrs = {'version': str(version), 'date': str(date)}
    if changelog_url:
        attrs['changelog'] = changelog_url
        attrs['changelog_sha256'] = changelog_sha256
    repository = ET.Element('repository', attrs)
    for gz_filename, pack_type, lang, description, sha256 in packs:
        ET.SubElement(repository, 'dictionary', {
            'uri': f'{download_base_url}/{gz_filename}',
            'type': pack_type,
            'description': description,
            'lang': lang,
            'sha256': sha256,
        })
    return repository


def write_manifest(repository, out_path):
    rough = ET.tostring(repository, encoding='unicode')
    pretty = minidom.parseString(rough).toprettyxml(indent='    ')
    # minidom always emits its own XML declaration; keep the file's declaration-free
    # style consistent with the existing bundled dictionaries.xml.
    lines = [line for line in pretty.split('\n') if line.strip()]
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines[1:]) + '\n')


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packs-dir', required=True,
                         help='directory of sumatora_*.db packs (split-sumatora-packs.py -o)')
    parser.add_argument('--release-dir', required=True,
                         help='output directory for gzip-compressed release assets')
    parser.add_argument('--version', required=True, type=int,
                         help='repository version (must exceed the previous release)')
    parser.add_argument('--date', required=True,
                         help='repository date, YYYYMMDD')
    parser.add_argument('--download-base-url', required=True,
                         help='base URL packs are downloadable from, e.g. '
                              'https://github.com/OWNER/REPO/releases/download/TAG')
    parser.add_argument('--changelog-path',
                         help='optional path to a changelog.json (build-changelog.py output) '
                              'to checksum and reference from the manifest; ignored if absent')
    parser.add_argument('-o', '--manifest', required=True,
                         help='output path for dictionaries.xml')
    args = parser.parse_args(argv)

    print(f'Gzipping and checksumming packs from {args.packs_dir}...', flush=True)
    packs = gzip_and_checksum(args.packs_dir, args.release_dir)
    if not packs:
        print(f'error: no sumatora_*.db packs found in {args.packs_dir}', file=sys.stderr)
        return 1

    changelog_url = None
    changelog_sha256 = None
    if args.changelog_path and os.path.isfile(args.changelog_path):
        changelog_sha256 = _sha256_file(args.changelog_path)
        changelog_url = f'{args.download_base_url}/changelog.json'
        print(f'  changelog.json -> ({changelog_sha256[:12]}...)', flush=True)

    repository = render_manifest(packs, args.version, args.date, args.download_base_url,
                                  changelog_url=changelog_url, changelog_sha256=changelog_sha256)
    write_manifest(repository, args.manifest)

    total_size = sum(os.path.getsize(os.path.join(args.release_dir, p[0])) for p in packs)
    print(f'Done: {len(packs)} packs, {total_size / 1_000_000:.1f}MB compressed, '
          f'version={args.version} date={args.date} -> {args.manifest}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
