# Feature foundations

SVG symbols, custom assets, profiles, and measurement preferences are standard
Kobee Studio functionality. The testing-stream package exposes them by default;
there is no runtime environment flag to enable them.

## Storage layout

Install-owned data is read-only and replaced during updates:

```text
kobeestudio/resources/
  symbols/<category>/<symbol_slug>--<variant>.svg
  labels/*.json
```

The SVGs in `kobeestudio/resources/symbols/` are the bundled source assets.
There is no SVG regeneration step in the repository, so contributor SVG work
cannot be overwritten by packaging.

Instance-wide user data is outside the installed plugin:

```text
<user data>/Kobee Studio/
  preferences.json
  assets/v1/<namespace>/<upload-id>/
    asset.svg
    metadata.json
  labels/v1/items/<quick-label-id>.json
  profiles/v1/<module>/
    default.json
    items/<profile-id>.json
```

Project-only uploads use the same asset schema at:

```text
<project directory>/.kobeestudio/assets/v1/...
```

Project-only quick labels similarly live at
`<project directory>/.kobeestudio/labels/v1/items/`. The whole instance-wide
folder is a portable data library: Settings → **Library** exports it as a
small ZIP. Restoring an archive explicitly replaces the current portable
library after a warning, so a new machine can receive an exact backup. It
includes preferences, profiles, custom SVGs, and quick labels; installed
package files are intentionally excluded.

The split means plugin updates can replace bundled content without touching
uploads or profiles. Each uploaded asset and profile has its own metadata file,
and writes are staged then atomically renamed, so a partial write cannot damage
the rest of a catalog.

## Symbol identity and variants

A bundled symbol has a stable ID such as `builtin.ground`. `default` and
`rounded` are variants of that ID rather than unrelated picker entries.
Custom symbols use an immutable `custom.<uuid>` ID. Upload another SVG with that
ID and a different variant name to extend its variant family.

The initial shipped convention is **default** plus **rounded** where an
alternative is supplied. The picker exposes a Variant selector and then shows
one card per symbol family for that selected variant. Uploads deliberately offer only
these two variants for now; a future variant class is a renderer/UI feature,
not a free-form user field. There is no separate variant editor: use
**Uploads → Symbols → Add variant** on the selected symbol family.

See [Custom symbol authoring](custom-symbol-authoring.md) for the supported
SVG profile, Inkscape setup, visual-weight guidance, and normal Difference
workflows for hollow-circle symbols.

Linked label JSON references both `symbol_id` and `symbol_variant`. This keeps a
premade label stable when more variants are added later.

## Upload service

`SvgAssetStore` is namespace-based. The `symbols` namespace performs both the
generic SVG safety checks and PCB-symbol renderability checks. Future namespaces
can retain safe vector features that the current PCB polygon renderer does not
yet consume. Uploads reject active content, external/embedded resources, XML
entities, excessive sizes, and unsafe paths. Deletion resolves a catalog entry
and atomically moves only its UUID directory before removal.

## Units and profiles

Geometry and serialized artwork remain in millimetres. `MeasurementUnit` only
converts values at input/display boundaries, preventing existing projects from
changing dimensions when a preference changes.

Profiles are module-scoped. The module IDs are `labels`, `pin_headers`,
`component_callouts`, `component_arrays`, and `machine_codes`. A profile stores
that module's settings plus one optional default pointer. Existing artwork
always uses its embedded settings; a module default is considered only for new
artwork.

Application-wide display units and appearance live in the separate versioned
`preferences.json`. Keeping them out of design profiles prevents applying a
label preset from unexpectedly changing the whole editor.

## Settings UI

The editor header opens **Settings**, with five pages:

- **General** manages system/light/dark appearance and millimetre/mil display.
- **Profiles and defaults** saves, updates, recalls, defaults, clears defaults,
  and deletes settings independently for each artwork module.
- **Uploads** manages update-safe global or project-only SVGs. The app asks for
  a display name, category, and variant, then owns the internal filename and
  stable ID. Select a family and use **Add variant** for names such as
  `rounded`.
- **Uploads** has sub-tabs for SVG symbols and quick labels. Symbol variants
  are managed on a selected family with `default` and `rounded` as the two
  supported variant classes.
- **Library** has Backup & reset and Bundled visibility sub-tabs.
- **About & help** is a top-level Settings tab.
  Hide rules are stored in `preferences.json`, so an update never resets them;
  hiding a symbol does not hide a linked quick label. Reset requires a typed
  confirmation and removes mutable library content only, returning to shipped
  defaults.
