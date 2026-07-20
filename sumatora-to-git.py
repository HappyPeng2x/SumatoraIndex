#!/usr/bin/env python3
"""Export sumatora.db word entries as git-friendly, rendering-ready JSON.

Reuses the same forms/furigana/sense-tag/restriction/example assembly
sumatora-render-entry.py already implements against the schema-v2 tables,
but writes structured JSON instead of a terminal card, split by language the
same way gitmdict is:

    entries/{shard}/{seq}.json              language-neutral: forms with
                                             furigana, sense-group tags,
                                             per-sense applicable-forms and
                                             Japanese example text/furigana,
                                             alternate-forms table
    translations/{lang}/{shard}/{seq}.json  per language: glosses per sense
                                             and example translations

shard = seq // SHARD_SIZE, matching gitmdict's own convention -- seq (the
JMdict sequence number, Entry.source_key) is used as the filename rather
than the internal entry_id, so files line up 1:1 with gitmdict's.

Usage:
    sumatora-to-git.py -d sumatora.db -o <output dir> [--lang eng --lang fre ...]

With no --lang given, exports every language present in SenseGloss.
"""

import argparse
import json
import os
import sqlite3

SHARD_SIZE = 10000


def word_entries(conn):
    return [r[0] for r in conn.execute(
        "SELECT entry_id FROM Entry WHERE entry_type = 'word' ORDER BY entry_id").fetchall()]


def visible_forms(conn, entry_id):
    cols = ('form_id', 'ord', 'form_type', 'text', 'reading', 'is_primary', 'is_common', 'score')
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM EntryForm WHERE entry_id = ? AND is_search_only = 0 ORDER BY ord",
        (entry_id,)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def furigana_segments(conn, form_id):
    return [{'base': b, 'ruby': r} for b, r in conn.execute(
        "SELECT base, ruby FROM FormFuriganaSegment WHERE form_id = ? ORDER BY ord",
        (form_id,)).fetchall()]


def build_forms_json(conn, forms):
    out = []
    for f in forms:
        entry = {
            'text': f['text'],
            'type': f['form_type'],
            'reading': f['reading'],
            'isPrimary': bool(f['is_primary']),
            'isCommon': bool(f['is_common']),
        }
        segs = furigana_segments(conn, f['form_id'])
        if segs:
            entry['furigana'] = segs
        out.append(entry)
    return out


def sense_group_tags(conn, sense_group_id):
    return [{'category': c, 'code': code, 'label': label} for c, code, label in conn.execute(
        "SELECT t.category, t.code, t.label FROM SenseGroupTag sgt JOIN Tag t ON t.tag_id = sgt.tag_id "
        "WHERE sgt.sense_group_id = ? ORDER BY t.category, t.sort_order",
        (sense_group_id,)).fetchall()]


def applies_to_forms(conn, sense_id):
    return [text for (text,) in conn.execute(
        "SELECT ef.text FROM SenseAppliesToForm s JOIN EntryForm ef ON ef.form_id = s.form_id "
        "WHERE s.sense_id = ?", (sense_id,)).fetchall()]


def example_for_sense(conn, entry_id, sense_id, first_sense_id):
    """Tatoeba example linked to this sense (see sumatora-render-entry.py's
    example_for_sense for the same first-sense fallback rationale)."""
    row = conn.execute(
        "SELECT ee.example_id FROM EntryExample ee "
        "WHERE ee.entry_id = ? AND (ee.sense_id = ? OR (ee.sense_id IS NULL AND ? = ?)) "
        "ORDER BY ee.sense_id IS NULL, ee.ord LIMIT 1",
        (entry_id, sense_id, sense_id, first_sense_id)).fetchone()
    return row[0] if row else None


def example_japanese(conn, example_id):
    segs = conn.execute(
        "SELECT base, ruby FROM ExampleSegment WHERE example_id = ? ORDER BY ord",
        (example_id,)).fetchall()
    if not segs:
        return None
    return {
        'text': ''.join(base for base, _ in segs),
        'segments': [{'base': b, 'ruby': r} for b, r in segs],
    }


def example_translation(conn, example_id, lang):
    row = conn.execute(
        "SELECT translation FROM Example WHERE example_id = ? AND lang = ?",
        (example_id, lang)).fetchone()
    return row[0] if row else None


def build_forms_table_json(forms):
    writing = [f for f in forms if f['form_type'] == 'writing']
    reading_only = [f for f in forms if f['form_type'] == 'reading']

    columns, seen = [], set()
    for f in writing:
        if f['text'] not in seen:
            seen.add(f['text'])
            columns.append(f['text'])

    bridging_readings = {f['reading'] for f in writing if f['reading']}
    reading_ord = {}
    for f in writing:
        if f['reading']:
            reading_ord[f['reading']] = min(reading_ord.get(f['reading'], f['ord']), f['ord'])
    rows = sorted(bridging_readings, key=lambda r: reading_ord[r])

    nokanji = sorted(
        (f['text'] for f in reading_only if f['text'] not in bridging_readings),
        key=lambda t: next(f['ord'] for f in reading_only if f['text'] == t),
    )

    def badge(f):
        if f is None:
            return None
        if f['is_primary']:
            return 'primary'
        if f['score'] < 0:
            return 'rare'
        return 'common'

    cell = {(f['reading'], f['text']): f for f in writing}
    cells = {
        reading: {col: badge(cell.get((reading, col))) for col in columns}
        for reading in rows
    }
    if len(columns) <= 1 and len(rows) <= 1 and not nokanji:
        return None  # trivial one-cell matrix, same omission rule as the terminal renderer
    return {'columns': columns, 'rows': rows, 'cells': cells, 'nokanji': nokanji}


def build_entry_json(conn, entry_id, seq):
    forms = visible_forms(conn, entry_id)
    senses = conn.execute(
        "SELECT sense_id, sense_group_id, ord FROM Sense WHERE entry_id = ? ORDER BY ord",
        (entry_id,)).fetchall()
    first_sense_id = senses[0][0] if senses else None

    sense_groups = {}
    order = []
    example_ids = {}
    for sense_id, sense_group_id, ord_ in senses:
        display_number = conn.execute(
            "SELECT display_number FROM Sense WHERE sense_id = ?", (sense_id,)).fetchone()[0] or (ord_ + 1)
        if sense_group_id not in sense_groups:
            sense_groups[sense_group_id] = {
                'tags': sense_group_tags(conn, sense_group_id),
                'senses': [],
            }
            order.append(sense_group_id)
        example_id = example_for_sense(conn, entry_id, sense_id, first_sense_id)
        sense_entry = {'number': display_number, 'senseId': sense_id}
        forms_restriction = applies_to_forms(conn, sense_id)
        if forms_restriction:
            sense_entry['appliesToForms'] = forms_restriction
        if example_id is not None:
            example_ids[display_number] = example_id
            ja = example_japanese(conn, example_id)
            if ja:
                sense_entry['example'] = ja
        sense_groups[sense_group_id]['senses'].append(sense_entry)

    return {
        'seq': seq,
        'entry_id': entry_id,
        'forms': build_forms_json(conn, forms),
        'senseGroups': [sense_groups[g] for g in order],
        'formsTable': build_forms_table_json(forms),
    }, example_ids


def build_translation_json(conn, entry_id, seq, lang, example_ids):
    senses = conn.execute(
        "SELECT sense_id, ord FROM Sense WHERE entry_id = ? ORDER BY ord", (entry_id,)).fetchall()
    sense_out = []
    has_any_gloss = False
    for sense_id, ord_ in senses:
        display_number = conn.execute(
            "SELECT display_number FROM Sense WHERE sense_id = ?", (sense_id,)).fetchone()[0] or (ord_ + 1)
        glosses = [g for (g,) in conn.execute(
            "SELECT text FROM SenseGloss WHERE sense_id = ? AND lang = ? AND gloss_type = 'main' ORDER BY ord",
            (sense_id, lang)).fetchall()]
        if glosses:
            has_any_gloss = True
        sense_out.append({'number': display_number, 'glosses': glosses})

    if not has_any_gloss:
        return None

    example_translations = {}
    for number, example_id in example_ids.items():
        text = example_translation(conn, example_id, lang)
        if text:
            example_translations[str(number)] = text

    result = {'seq': seq, 'lang': lang, 'senses': sense_out}
    if example_translations:
        result['exampleTranslations'] = example_translations
    return result


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    os.replace(tmp, path)


def process(db_path, output_dir, langs, limit=None):
    conn = sqlite3.connect(db_path)
    if not langs:
        langs = sorted(r[0] for r in conn.execute("SELECT DISTINCT lang FROM SenseGloss").fetchall())
    print(f'  Exporting languages: {", ".join(langs)}', flush=True)

    entry_ids = word_entries(conn)
    if limit is not None:
        entry_ids = entry_ids[:limit]
    print(f'  {len(entry_ids)} word entries', flush=True)

    count = 0
    for entry_id in entry_ids:
        seq = int(conn.execute(
            "SELECT source_key FROM Entry WHERE entry_id = ?", (entry_id,)).fetchone()[0])
        shard = seq // SHARD_SIZE

        entry_json, example_ids = build_entry_json(conn, entry_id, seq)
        write_json(os.path.join(output_dir, 'entries', str(shard), f'{seq}.json'), entry_json)

        for lang in langs:
            translation = build_translation_json(conn, entry_id, seq, lang, example_ids)
            if translation is not None:
                write_json(
                    os.path.join(output_dir, 'translations', lang, str(shard), f'{seq}.json'),
                    translation)

        count += 1
        if count % 20000 == 0:
            print(f'  {count} entries exported…', flush=True)

    print(f'Done: {count} entries exported -> {output_dir}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-d', '--db', required=True, help='path to sumatora.db')
    parser.add_argument('-o', '--output', required=True, help='output directory (git repo root)')
    parser.add_argument('--lang', action='append', default=[],
                         help='language to export (repeatable; default: all languages in SenseGloss)')
    parser.add_argument('--limit', type=int, default=None, help='only export the first N entries (testing)')
    args = parser.parse_args()
    process(args.db, args.output, args.lang, args.limit)


if __name__ == '__main__':
    main()
