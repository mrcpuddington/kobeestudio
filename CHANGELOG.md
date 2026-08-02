# Changelog

## 0.4.0-dev — 2026-08-02

- Renamed the product to **Kobee Studio** across the KiCad plugin, dialog,
  package metadata, generated footprints, documentation, and release package.
- Removed the `legacy/` tree. The renderer, base dialog, fonts, and necessary
  FontTools/svg2mod runtime source now live in clear current module boundaries;
  unneeded upstream documentation, tests, examples, tooling, and stale assets
  are no longer shipped.
- Added a dedicated third-party notice file and retained the FontTools and
  svg2mod licences alongside their runtime source.

## 0.3.0-dev — 2026-08-02

- Added the first usable Silk Studio controls to the KiBeezard dialog, including every first-generation parametric shape, inverted and outline styles, padding, borders, corner radius, feature size, and direction.
- Added a single-row 2.54 mm pin-header label tool with 1–40 pins, one label per pin, horizontal/vertical orientation, configurable pin-1 end, four rail sides, and an optional pin-1 marker.
- Added independent connector clearance, label padding, and leading/trailing padding controls so larger sockets, shrouds, and plug bodies can reserve more space than an ordinary header.
- Added a shared millimetre artwork renderer and KiCad footprint writer so preview and exported geometry use the same vectors.
- Added versioned pin-header edit data, pin-1 placement anchoring, preview-only clearance guides, and compatibility loading for existing KiBuzzard/KiBeezard labels.
- Added geometry, mirroring, parser, payload, and six-layer Gerber coverage for the new Studio label and header paths.
- Corrected Studio font scaling so the requested capital height is the actual generated height in millimetres, and changed the default text padding to a compact KiBuzzard-like 0.4 mm horizontal / 0.2 mm vertical margin.
- Reworked header blocks as one enclosure around the connector and labels: pins can sit on any side, text aligns away from the pins, horizontal labels rotate 90 degrees, and the adjustable plug envelope becomes a real artwork knockout.
- Replaced fragile multi-hole polygon bridges with compact, nested knockout geometry that preserves letters, counters, and connector openings in KiCad's renderer.
- Made header openings optional and selectable as none, one continuous plug opening, or individual pin openings, with adjustable width and continuous end extension. Copper output automatically requires an opening to prevent accidental pin shorts.
- Added **Independent ends** for ordinary labels and **Independent long edges** for header enclosures. A header can make the two pin-side corners and two label-side corners square or subtly rounded in any combination, using the configured corner radius instead of an oversized end cap. Inverted-fill and outline appearances work with every combination.
- Added 16 original PCB-safe built-in icons spanning electrical, polarity, control, warning, indicator, battery, and button symbols, with left, right, icon-only, inverted, outline, and bare-symbol layouts. Input and Output use deliberately opposite arrow directions.
- Added DC centre-negative and negative-polarity symbols, rebuilt the warning triangle with rounded fabrication-safe strokes, corrected the positive symbol to a square `+`, and removed the airflow symbol.
- Added 58 quick labels across power, test, programming, interfaces, signals, and controls. Searchable, categorised visual pickers now preview every quick label and symbol instead of presenting long dropdowns.
- Changed new-label defaults to 1.2 mm text, 0.5 mm vertical padding, and 1.2 mm horizontal padding.
- Promoted the six output layers into an always-visible selector and hid shape parameters that do not apply to the current selection.
- Expanded independently styled label ends with Square, Rounded, Chamfered, Point, and Notch choices.
- Changed the visual asset picker to a compact, high-contrast, single-column list that opens at the top and scrolls vertically without duplicate captions.

## 0.2.0-dev — 2026-08-02

- Added an immutable, versioned Silk Studio composition document with text, icon, shape, guide, and group objects.
- Added deterministic JSON round trips and validation for layers, references, groups, typography, padding, and style values.
- Added a KiCad-independent parametric geometry engine for rectangles, rounded rectangles, pills, pointers, flags, tabs, chamfers, and hexagons.
- Added configurable asymmetric padding, borders, radius clamping, filled/outlined/inverted modes, content measurement, placement, and front-view bottom mirroring.
- Embedded the new composition document alongside legacy settings in generated footprints so the current editor stays compatible during migration.
- Preserved and tagged the working `v0.1.0-dev` baseline before beginning the Silk Studio core.

## 0.1.0-dev — 2026-08-02

- Started KiBeezard as a maintained fork of KiBuzzard, with original-author attribution retained.
- Added explicit front and bottom output choices for silkscreen, copper, and solder mask.
- Generated bottom labels as B.Cu-owned footprints with a single mirror transform on their selected B.* layer.
- Rebuilt the macOS preview renderer with deterministic sizing, buffered painting, and a separate bottom-view caption strip.
- Replaced clipboard/simulated-paste placement with direct KiCad board insertion for KiCad 10.0.x.
- Added diagnostics, source-level regression tests, macOS development-install instructions, PCM metadata, and a release checklist.
