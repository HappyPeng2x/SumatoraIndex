#!/usr/bin/env python3
"""Build schema-v2 pitch rows in sumatora.db from a gitch JSON repository."""

__author__ = "Nicolas Centa"
__license__ = "GPLv3"
__version__ = "0.1.0"

import getopt
import json
import os
import sys

import sumatora_schema
from sumatora_common import iter_json_files


def _form_matches(conn, word, reading):
    """Yield (form_id, confidence) for exact word+reading and reading fallback hits."""
    seen = set()
    for (form_id,) in conn.execute(
        "SELECT f.form_id FROM EntryForm f JOIN Entry e ON e.entry_id = f.entry_id "
        "WHERE e.entry_type = 'word' AND f.form_type = 'writing' "
        "AND f.text = ? AND f.reading = ?",
        (word, reading),
    ):
        seen.add(form_id)
        yield form_id, 'exact'

    for (form_id,) in conn.execute(
        "SELECT f.form_id FROM EntryForm f JOIN Entry e ON e.entry_id = f.entry_id "
        "WHERE e.entry_type = 'word' AND f.form_type = 'reading' AND f.text = ?",
        (reading,),
    ):
        if form_id not in seen:
            seen.add(form_id)
            confidence = 'exact' if word == reading else 'reading_fallback'
            yield form_id, confidence


def process(gitch_dir, db_path):
    conn = sumatora_schema.open_or_init_db(db_path)
    c = conn.cursor()
    src = sumatora_schema.source_id(conn, 'pitch')

    entries_dir = os.path.join(gitch_dir, 'entries')
    pitch_count = pattern_count = link_count = 0

    for path in iter_json_files(entries_dir):
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        word = data.get('word')
        if not word:
            continue
        for item in data.get('readings', []):
            reading = item.get('reading')
            pitches = item.get('pitches')
            if not reading or pitches is None:
                continue

            c.execute(
                'INSERT OR IGNORE INTO PitchAccent (word, reading, source_id) VALUES (?, ?, ?)',
                (word, reading, src),
            )
            pitch_id = c.execute(
                'SELECT pitch_id FROM PitchAccent WHERE word = ? AND reading = ? AND source_id = ?',
                (word, reading, src),
            ).fetchone()[0]
            c.execute('DELETE FROM PitchPattern WHERE pitch_id = ?', (pitch_id,))
            for ord_, position in enumerate(sorted(set(int(p) for p in pitches))):
                c.execute(
                    'INSERT INTO PitchPattern (pitch_id, ord, position) VALUES (?, ?, ?)',
                    (pitch_id, ord_, position),
                )
                pattern_count += 1

            for form_id, confidence in _form_matches(conn, word, reading):
                c.execute(
                    'INSERT OR REPLACE INTO FormPitch (form_id, pitch_id, confidence) '
                    'VALUES (?, ?, ?)',
                    (form_id, pitch_id, confidence),
                )
                link_count += 1

            pitch_count += 1
            if pitch_count % 10000 == 0:
                print(f'  {pitch_count} pitch accents inserted...', flush=True)

    sumatora_schema.set_build_metadata(
        conn,
        pitch_accent_count=str(pitch_count),
        pitch_pattern_count=str(pattern_count),
        pitch_form_link_count=str(link_count),
    )
    conn.commit()
    conn.close()
    print(f'Done: {pitch_count} pitch accents, {link_count} form links -> {db_path}', flush=True)


HELP = 'usage: pitch-to-sumatora-db.py -i <gitch directory> -d <sumatora.db path>'


def main(argv):
    gitch_dir = ''
    db_path = ''
    try:
        opts, _ = getopt.getopt(argv, 'hi:d:', ['idir=', 'db='])
    except getopt.GetoptError:
        print(HELP)
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print(HELP)
            sys.exit()
        elif opt in ('-i', '--idir'):
            gitch_dir = arg
        elif opt in ('-d', '--db'):
            db_path = arg
    if not gitch_dir or not db_path:
        print(HELP)
        sys.exit(2)
    process(gitch_dir, db_path)


if __name__ == '__main__':
    main(sys.argv[1:])
