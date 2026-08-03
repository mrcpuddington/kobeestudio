# Changelog

## 1.3.0 — 2026-08-04

- Migrated the plugin entry point and board-placement adapter to KiCad's supported IPC API while keeping 1.2.x artwork editable.
- Added optional underlines beneath main label text, exported as real KiCad geometry for filled, inverted, outline and container-free labels.
- Added forward-slash and backslash shortcuts to the label character controls.
- Added optional human-readable text beneath QR codes and Code 128 barcodes. The displayed line is editable independently from the encoded payload.
- Adopted the package identifier `com.github.mrcpuddington.kobeestudio`.
- Rebuilt the PCM archive around the official IPC package layout, with the plugin manifest directly under `plugins/`, a 64 × 64 catalog icon, bundled licences and KiCad schema-valid metadata.
- Completed IPC create, reopen, update and undo testing on KiCad 10 for macOS. Windows IPC validation remains a follow-up before the official Plugin and Content Manager submission.

## 1.2.1 — 2026-08-03

- Added an always-visible **Need help?** button in the top-right of the editor. It opens the Kobee Studio documentation hub for installation help, tutorials and tool guides without interrupting the artwork workflow.

## 1.2.0 — 2026-08-03

- Made every new artwork mode begin with a useful, renderable starting design instead of an empty or invalid configuration. The 2.54 mm header tool now starts with four `Pin 1`–`Pin 4` labels, vertical orientation, pins on the left and a continuous plug opening.
- Reordered the workspace so **Artwork type** comes before layer choice, and made the advanced-settings switch permanently available above the scrolling settings area.
- Clarified that each placed artwork item belongs to one KiCad layer. To use matching artwork on another layer, duplicate the item and change its layer rather than accidentally emitting it on every layer.
- Validated the KiCad 10 release workflow on both macOS and Windows. Linux testing remains the next platform-compatibility task.

## 1.1.0 — 2026-08-03

This release is mostly about making it easier to build more complete board graphics without making the editor harder to use.

- Added component callouts for common passive sizes, LEDs, tactile switches and custom component envelopes. The component stays clear while the label, icon and container are built around it.
- Added vertical and horizontal component arrays for repeated LEDs or other parts, with editable spacing and one label per component.
- Added title-and-subtitle labels, with the subtitle following the main typeface by default and an optional typeface override when a different look is wanted.
- Reworked the editor into a calmer workspace with a live preview, always-visible layer choice, a scrollable settings area and basic/advanced controls.
- Simplified the tactile-switch callout to one clean rounded enclosure rather than separate cut-outs around the legs.
- Added an editable Kobee Studio showcase board and refreshed the repository artwork to cover labels, symbols, component callouts, connector overlays, QR codes, barcodes and multilayer graphics.
- Kept the existing label, symbol, header, QR and barcode workflows intact while making new artwork start from the everyday label tool.

## 1.0.0 — 2026-08-02

- Released the first packaged Kobee Studio milestone for KiCad 10, tested on macOS with Windows and Linux validation still planned.
- Added parametric labels with filled, inverted, and outline appearances; asymmetric padding; rounded, pill, pointer, flag, tab, chamfer, hexagon, and independently styled ends.
- Added searchable libraries of common PCB labels and original electrical, warning, control, interface, and polarity symbols, including standalone icon artwork.
- Added configurable single-row 2.54 mm header overlays with per-pin labels, four orientations, detailed connector/text spacing, optional openings, and independent long-edge styles.
- Added QR Code and Code 128 generation with payload validation, fabrication-aware sizing, protected quiet zones, compact barcode defaults, rounded QR frames, adjustable extra frame spacing, and optional knockout footer text.
- Fixed icon-and-text assembly alignment, font sizing/spacing, inverted artwork knockout geometry, bottom-side mirroring, live-preview painting, editor reopening, and growing-dialog layout issues.
- Added KiCad footprint parsing, six-layer Gerber export, geometry, settings, picker, icon-complexity, QR, barcode, and pin-header regression coverage.
- Bundled the pure-Python runtime dependencies and retained all upstream licences and KiBuzzard attribution for a self-contained PCM installation.

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

- Added the first usable Silk Studio controls to the Kobee Studio dialog, including every first-generation parametric shape, inverted and outline styles, padding, borders, corner radius, feature size, and direction.
- Added a single-row 2.54 mm pin-header label tool with 1–40 pins, one label per pin, horizontal/vertical orientation, configurable pin-1 end, four rail sides, and an optional pin-1 marker.
- Added independent connector clearance, label padding, and leading/trailing padding controls so larger sockets, shrouds, and plug bodies can reserve more space than an ordinary header.
- Added a shared millimetre artwork renderer and KiCad footprint writer so preview and exported geometry use the same vectors.
- Added versioned pin-header edit data, pin-1 placement anchoring, preview-only clearance guides, and compatibility loading for existing KiBuzzard labels.
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

- Started Kobee Studio as a maintained fork of KiBuzzard, with original-author attribution retained.
- Added explicit front and bottom output choices for silkscreen, copper, and solder mask.
- Generated bottom labels as B.Cu-owned footprints with a single mirror transform on their selected B.\* layer.
- Rebuilt the macOS preview renderer with deterministic sizing, buffered painting, and a separate bottom-view caption strip.
- Replaced clipboard/simulated-paste placement with direct KiCad board insertion for KiCad 10.0.x.
- Added diagnostics, source-level regression tests, macOS development-install instructions, PCM metadata, and a release checklist.
