# Jitendex CSS

`common.css` and `jitendex.css` are copied unmodified from the [Jitendex](https://jitendex.org/) MDict
distribution, &copy; 2025 Stephen Kraus, licensed
[Creative Commons Attribution-ShareAlike 4.0 International](https://jitendex.org/pages/legal.html)
(CC BY-SA 4.0) -- "You are free to use, modify, and redistribute Jitendex files under the terms of the
Creative Commons Attribution-ShareAlike License (V4.0)".

Used by `render-entry-html.py` to style rendered entry cards (see that script and the
[gitenderml](https://github.com/HappyPeng2x/gitenderml) repository it publishes to). Bundled here,
rather than read from a local Jitendex checkout, so the release workflow doesn't depend on anything
outside this repository. Not modified from the upstream files -- if Jitendex updates its stylesheet,
re-copy both files here rather than hand-editing.
