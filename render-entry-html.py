#!/usr/bin/env python3
"""Render gitender JSON entries as standalone HTML cards, using Jitendex's
actual class vocabulary and stylesheet (jitendex.css + common.css), copied
in directly rather than reimplemented.

Jitendex (https://jitendex.org/) is CC BY-SA 4.0 -- "You are free to use,
modify, and redistribute Jitendex files under the terms of the Creative
Commons Attribution-ShareAlike License (V4.0)" (c) 2025 Stephen Kraus, see
https://jitendex.org/pages/legal.html -- so its CSS can be used directly
here rather than reimplemented, matching this repo's own CC BY-SA 4.0
license. (The AGPLv3 COPYING in Jitendex's GitHub repo covers a separate,
still-unfinished C# build-pipeline rewrite, not the distributed dictionary
files this script's markup is styled against.)

This implements the subset of Jitendex's card layout the gitender JSON
actually carries data for: headline + furigana + priority marker, tag-group
containers (part-of-speech/misc/field/dialect), numbered sense lists with
the real circled-digit list markers, glosses, linked example sentences, and
the alternate-forms matrix. It does not implement pieces gitender has no
data for yet: cross-references/antonyms, lang-source, pitch accent/audio,
and embedded graphics.

Reads gitender's entries/{shard}/{seq}.json (language-neutral) and
translations/{lang}/{shard}/{seq}.json (glosses), and writes one HTML file
per entry to <output>/{lang}/{shard}/{seq}.html, plus the shared
common.css/jitendex.css at the output root.

Point -o at a gitenderml checkout root directly (not a subdirectory) -- the
rendered HTML is large enough (roughly doubling gitender's own size) that
it's kept in its own repository rather than nested inside gitender, so
anyone who only wants the JSON data isn't forced to pull it too.

Usage:
    render-entry-html.py -i <gitender dir> -o <gitenderml dir> [--lang eng --lang fre ...]
    render-entry-html.py ... --jitendex-css <dir containing jitendex.css/common.css>
"""

import argparse
import html
import json
import os
import shutil

SHARD_SIZE = 10000
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_JITENDEX_CSS = os.path.join(_SCRIPT_DIR, 'vendor', 'jitendex')

# Sequential Unicode "circled digit" block covers 1-20 (U+2460..U+2473),
# matching Jitendex's own per-<li> `style="list-style-type: '①'"` marker
# trick; anything past that (rare -- a handful of very common verbs) falls
# back to a plain parenthesized number rather than reaching into the
# scattered higher circled-number blocks.
_CIRCLED_START = 0x2460
_CIRCLED_MAX = 20

_TAG_CONTAINER_ORDER = ['pos', 'field', 'dialect', 'misc']
_TAG_CONTAINER_CLASS = {
    'pos': 'part-of-speech-container',
    'misc': 'misc-container',
    'field': 'field-container',
    'dialect': 'dialect-container',
}
_TAG_INFO_CLASS = {
    'pos': 'part-of-speech-info',
    'misc': 'misc-info',
    'field': 'field-info',
    'dialect': 'dialect-info',
}

# sumatora-to-git.py's own best-effort mapping onto Jitendex's tiered form
# badges (see that script's build_forms_table_json) -- JMdict has no native
# irr/old/out distinction the way Jitendex's own source data does, so only
# the pri/valid/rare tiers are ever produced.
_FORM_BADGE_CLASS = {'primary': 'form-pri', 'common': 'form-valid', 'rare': 'form-rare'}


def circled_number(n):
    if 1 <= n <= _CIRCLED_MAX:
        return chr(_CIRCLED_START + n - 1)
    return f'({n})'


def esc(s):
    return html.escape(s, quote=False)


def render_ruby(segments):
    parts = []
    for seg in segments:
        base = esc(seg['base'])
        if seg.get('ruby'):
            parts.append(f'<ruby>{base}<rt>{esc(seg["ruby"])}</rt></ruby>')
        else:
            parts.append(base)
    return ''.join(parts)


def render_headline(entry):
    forms = entry['forms']
    writing = [f for f in forms if f['type'] == 'writing']
    head = max(writing, key=lambda f: (f['isCommon'],), default=None) if writing else None
    if head is None:
        head = next((f for f in forms if f['type'] == 'reading' and f['isPrimary']), forms[0])
    is_common = any(f['isCommon'] for f in forms)

    text = render_ruby(head['furigana']) if head.get('furigana') else esc(head['text'])
    priority_class = ' priority' if is_common else ' no-furigana' if not head.get('furigana') else ''
    priority_symbol = (
        '<span class="priority-symbol" title="high priority entry">★</span>' if is_common else ''
    )
    return (
        f'<div class="headline{priority_class}">'
        f'<span class="headword" lang="ja">{text}</span>{priority_symbol}'
        f'</div>'
    )


def render_tag_containers(tags):
    by_category = {}
    for t in tags:
        by_category.setdefault(t['category'], []).append(t)
    out = []
    for cat in _TAG_CONTAINER_ORDER:
        items = by_category.get(cat)
        if not items:
            continue
        chips = ''.join(
            f'<span class="tag {_TAG_INFO_CLASS[cat]}" data-code="{esc(t["code"])}" '
            f'title="{esc(t["label"])}">{esc(t["code"])}</span>'
            for t in items
        )
        out.append(f'<div class="{_TAG_CONTAINER_CLASS[cat]}">{chips}</div>')
    return ''.join(out)


def render_example(example, translation):
    ja = f'<div class="ex-sent-ja" lang="ja">{render_ruby(example["segments"])}</div>'
    en = f'<div class="ex-sent-en"><span class="ex-sent-en-content">{esc(translation)}</span></div>' \
        if translation else ''
    return f'<div class="extra-box ex-sent">{ja}{en}</div>'


def render_sense(sense, glosses, example_translations):
    number = circled_number(sense['number'])
    restriction = ''
    if sense.get('appliesToForms'):
        forms_str = '・'.join(esc(t) for t in sense['appliesToForms'])
        restriction = f'<span class="reference-label">{forms_str} only</span>'

    gloss_items = ''.join(f'<li class="gloss">{esc(g)}</li>' for g in glosses) or \
        '<li class="gloss">(no translation yet)</li>'

    extra = ''
    if sense.get('example'):
        translation = example_translations.get(str(sense['number']))
        extra = f'<div class="extra-info">{render_example(sense["example"], translation)}</div>'

    return (
        f"<li class=\"sense\" style=\"list-style-type: '{number}';\">"
        f'{restriction}<ul class="glossary">{gloss_items}</ul>{extra}'
        f'</li>'
    )


def render_sense_groups(entry, translation):
    sense_by_number = {}
    if translation:
        for s in translation['senses']:
            sense_by_number[s['number']] = s['glosses']
    example_translations = (translation or {}).get('exampleTranslations', {})

    total_senses = sum(len(g['senses']) for g in entry['senseGroups'])
    group_count = len(entry['senseGroups'])

    groups_html = []
    for group in entry['senseGroups']:
        tags_html = render_tag_containers(group['tags'])
        senses_html = ''.join(
            render_sense(s, sense_by_number.get(s['number'], []), example_translations)
            for s in group['senses']
        )
        groups_html.append(
            f'<li class="sense-group">{tags_html}<ol class="sense-list">{senses_html}</ol></li>')

    return (
        f'<ul class="sense-groups" data-sense-count="{total_senses}" '
        f'data-sense-group-count="{group_count}">{"".join(groups_html)}</ul>'
    )


def render_forms_table(forms_table):
    if not forms_table:
        return ''
    columns = forms_table['columns']
    rows = forms_table['rows']
    nokanji = forms_table['nokanji']
    cells = forms_table['cells']

    header = '<tr class="forms-header-row"><th></th>' + \
        ''.join(f'<th lang="ja">{esc(c)}</th>' for c in columns)
    if nokanji:
        header += '<th>∅</th>'
    header += '</tr>'

    def badge_cell(badge):
        if not badge:
            return '<td></td>'
        cls = _FORM_BADGE_CLASS.get(badge, 'form-valid')
        return f'<td class="{cls}"><span></span></td>'

    body_rows = []
    for reading in rows:
        cells_html = ''.join(badge_cell(cells[reading][c]) for c in columns)
        if nokanji:
            cells_html += '<td></td>'
        body_rows.append(f'<tr class="forms-body-row"><th lang="ja">{esc(reading)}</th>{cells_html}</tr>')
    for text in nokanji:
        cells_html = '<td></td>' * len(columns) + badge_cell('common')
        body_rows.append(f'<tr class="forms-body-row"><th lang="ja">{esc(text)}</th>{cells_html}</tr>')

    return f'<table class="forms"><thead>{header}</thead><tbody>{"".join(body_rows)}</tbody></table>'


def render_entry_html(entry, translation, lang):
    headline = render_headline(entry)
    sense_groups = render_sense_groups(entry, translation)
    forms_table = render_forms_table(entry.get('formsTable'))
    title = entry['forms'][0]['text'] if entry['forms'] else entry['seq']

    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Sumatora ({esc(lang)})</title>
<link rel="stylesheet" href="../../common.css">
<link rel="stylesheet" href="../../jitendex.css">
</head>
<body>
<article class="sumatora-entry">
{headline}
{sense_groups}
{forms_table}
<div class="entry-footnotes">
Source: JMdict/EDRDG (CC BY-SA 4.0). Example sentences: Tatoeba Project (CC BY 2.0 FR).
Card style: Jitendex (CC BY-SA 4.0), &copy; Stephen Kraus.
</div>
</article>
</body>
</html>
'''


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def process(input_dir, output_dir, langs, jitendex_css_dir):
    os.makedirs(output_dir, exist_ok=True)
    for name in ('common.css', 'jitendex.css'):
        shutil.copy(os.path.join(jitendex_css_dir, name), os.path.join(output_dir, name))

    entries_dir = os.path.join(input_dir, 'entries')
    count = 0
    for shard_name in sorted(os.listdir(entries_dir), key=lambda s: int(s)):
        shard_dir = os.path.join(entries_dir, shard_name)
        for name in sorted(os.listdir(shard_dir)):
            if not name.endswith('.json'):
                continue
            seq = name[:-5]
            entry = load_json(os.path.join(shard_dir, name))
            for lang in langs:
                translation_path = os.path.join(
                    input_dir, 'translations', lang, shard_name, name)
                if not os.path.exists(translation_path):
                    # No gloss data at all for this (entry, lang) -- skip rather
                    # than emit a card whose every sense reads "no translation
                    # yet", which for a low-coverage language would be nearly
                    # all of gitender's 217,974 entries for no reader benefit.
                    continue
                translation = load_json(translation_path)
                out_path = os.path.join(output_dir, lang, shard_name, f'{seq}.html')
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, 'w', encoding='utf-8') as f:
                    f.write(render_entry_html(entry, translation, lang))
            count += 1
            if count % 20000 == 0:
                print(f'  {count} entries rendered…', flush=True)
    print(f'Done: {count} entries rendered -> {output_dir}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-i', '--input', required=True, help='gitender directory')
    parser.add_argument('-o', '--output', required=True, help='output directory')
    parser.add_argument('--lang', action='append', default=[],
                         help='language to render (repeatable; default: eng)')
    parser.add_argument('--jitendex-css', default=_DEFAULT_JITENDEX_CSS,
                         help='directory containing jitendex.css and common.css '
                              '(default: vendor/jitendex next to this script)')
    args = parser.parse_args()
    process(args.input, args.output, args.lang or ['eng'], args.jitendex_css)


if __name__ == '__main__':
    main()
