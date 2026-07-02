# Sumatora Index

Database generator for the Android application [Sumatora Dictionary](https://github.com/HappyPeng2x/SumatoraDictionary).

As of v0.5.0 the pipeline is split into two steps with a git-friendly JSON intermediate repository ([gitmdict](https://github.com/HappyPeng2x/gitmdict)).

## Pipeline

### Step 1 — XML → JSON git repository

```
python3 xml-to-git.py -i <JMdict file> -o <gitmdict directory>
```

Parses the JMdict XML file and writes one JSON file per dictionary entry and one per entry/language into a local git repository. The resulting repository can be pushed to GitHub (see [HappyPeng2x/gitmdict](https://github.com/HappyPeng2x/gitmdict)).

Requires: `lxml`

### Step 2 — JSON git repository → SQLite

```
python3 git-to-sqlite.py -i <gitmdict directory> -o <output directory>
```

Reads the JSON files from the gitmdict repository and produces the same SQLite databases used by Sumatora Dictionary:

- `jmdict.db` — entries, FTS index, entity table
- `<lang>.db` — per-language translation tables with FTS index (eng, ger, dut, fre, rus, hun, spa, slv, swe)

Requires: no third-party dependencies beyond the Python standard library.

### Legacy single-pass script

```
python3 sumatora-index.py -i <JMdict file> -o <output directory>
```

The original single-pass XML → SQLite script. Requires `libxml2` Python bindings and `romkan`.

## Database releases

Pre-built SQLite databases are published as GitHub release assets on this repository. Release tags follow the pattern:

```
v{format}-{date}
```

- **`{format}`** — zero-padded integer that increments whenever the SQLite schema or stored data format changes in a way that requires the consumer (Sumatora Dictionary) to be updated. The current format is **`v01`**.
- **`{date}`** — ISO 8601 date (YYYY-MM-DD) of the JMdict snapshot used to build the databases.

Example: `v01-2026-07-02` is the first release using format v01, built from the JMdict data of 2026-07-02.

When the format number changes, the previous release series becomes incompatible with older app versions. The date component alone changing means only dictionary content was updated; no app update is required.

## Input

Download [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) in XML format and gunzip before processing.

## License

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

See the [LICENSE](LICENSE) file for details.

## Credits

- [JMdict](https://www.edrdg.org/jmdict/j_jmdict.html) — property of James William BREEN and [The Electronic Dictionary Research and Development Group](https://www.edrdg.org/), used in conformance with the Group's [licence](https://www.edrdg.org/edrdg/licence.html) (Creative Commons Attribution-ShareAlike 4.0 International)
