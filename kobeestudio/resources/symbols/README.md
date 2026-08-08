# Bundled symbol contract

Kobee Studio discovers bundled symbols from this directory. No Python catalog
entry is required.

Use this path and filename convention:

```text
symbols/<category>/<symbol_slug>--<variant>.svg
```

All three names must use lowercase ASCII letters, numbers, and underscores.
Examples:

```text
symbols/electrical/ground--default.svg
symbols/electrical/ground--rounded.svg
symbols/direction/input--straight.svg
```

The stable symbol ID is `builtin.<symbol_slug>`. The suffix identifies its
variant; every symbol should provide `default`. Add a short SVG `<title>` for
the picker display name. The category display name is inferred from the
directory.

Symbols must be self-contained, filled vector geometry with a finite viewBox.
Convert strokes and text to filled paths before contributing. Scripts,
external references, embedded images, event handlers, DTDs, and entities are
rejected. Paths must be closed. Compound holes must first be converted into
separate, fabrication-safe filled regions (segmented rings are one reliable
option), because PCB polygon boundaries do not preserve SVG fill rules. Keep
artwork centred where practical and avoid unnecessarily dense paths because the
output becomes PCB polygons.

Run the catalog tests before opening a pull request:

```sh
python3 -m unittest tests.test_svg_symbols
```

`tools/export_builtin_symbols.py` documents how the initial SVG migration was
created from the legacy Python catalog. The checked-in SVGs—not that export
script—are the source of truth for this development system.
