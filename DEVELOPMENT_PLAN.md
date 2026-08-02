# Kobee Studio internal development plan

This is the working plan for growing Kobee Studio into a complete PCB artwork tool. The order matters: we should build one reusable composition engine and put every higher-level workflow on top of it.

## Product and engineering rules

- Keep a single user-selected output layer as the default.
- Keep geometry generation independent from KiCad and wxPython.
- Treat the current KiBuzzard-derived renderer as a compatibility backend, not the future data model.
- Store editable designs as versioned, serialisable parameters.
- Make every geometry feature testable without opening the GUI.
- Add the GUI only after the underlying model and renderer are covered.
- Preserve original credits, bundled licences, and asset attribution.
- Prefer deliberate manufacturing warnings over silently changing user artwork.

## Milestone 0 — checkpoint the working baseline

Goal: preserve the stable KiCad 10/macOS work before the larger refactor begins.

- [ ] Finish the six-layer live placement checks.
- [ ] Inspect bottom orientation, 3D view, mask openings, copper, and all six Gerbers.
- [x] Commit and push the current `0.1.0-dev` checkpoint.
- [x] Tag the stable compatibility baseline before changing the geometry model.

Acceptance: the current single-label workflow is recoverable and remains covered while the new engine is developed.

## Milestone 1 — composition document model

Goal: represent a design as objects rather than special-case dialog fields.

Initial object types:

- `TextObject`
- `IconObject`
- `ShapeObject`
- `GroupObject`
- `GuideObject` for non-exported pin/pad guides

Shared document settings:

- Output layer and board side
- Anchor and origin
- Width, height, rotation, and alignment
- Fill, border, padding, and corner radius
- Typography and icon settings
- Schema version and generator version

Work:

- [x] Define immutable core data models.
- [x] Define a versioned JSON serialisation format.
- [x] Add load/save/round-trip tests.
- [x] Add an adapter from current dialog settings into the new document.
- [x] Embed the new document alongside legacy settings so generated footprints can be reopened during migration.

Acceptance: a document can be created, serialised, restored, and rendered without importing `pcbnew` or creating a wx application.

## Milestone 2 — parametric shape and style engine

Goal: deliver the shared geometry needed by the first visible upgrades.

Build in this order:

1. Rectangle.
2. Rounded rectangle.
3. Fully rounded pill.
4. Outline/border geometry.
5. Independent horizontal and vertical padding.
6. Filled and inverted variants.
7. Pointer, flag, tab, chamfer, and hexagon shapes.

Work:

- [x] Create pure geometry functions for every first-generation shape.
- [x] Define deterministic radius clamping when the requested radius is too large.
- [x] Add border thickness without changing the requested outer dimensions.
- [x] Add content-box measurement for text and icons.
- [x] Test small sizes, multiline content, front/back mirroring, and all supported layers.

Acceptance: the same document produces stable preview and footprint geometry, and existing plain/tag labels still render through a compatibility adapter.

## Milestone 3 — presets and project styles

Goal: prove that the new engine can create reusable design systems.

- [ ] Define preset inheritance and override rules.
- [ ] Store global presets in the Kobee Studio configuration directory.
- [ ] Support a project-local preset file suitable for source control.
- [ ] Add import/export with schema migration.
- [ ] Create first-party Plain, Rounded, Pill, Warning, Power, Interface, Test Point, and Kobee presets.
- [ ] Add preset preview thumbnails generated from the real renderer.

Acceptance: changing a named preset updates its preview predictably, and a preset file can be shared with another checkout.

## Milestone 4 — 2.54 mm pin-header label block

Goal: ship the first workflow that is substantially more capable than KiBuzzard.

### First version scope

- Single-row `1xN` headers.
- Fixed 2.54 mm pitch.
- User-selected pin count.
- One editable label per pin.
- Horizontal or vertical row orientation.
- Configurable pin-1 end.
- Label rail above, below, left, or right of the pin row.
- User-selected layer and shape/style parameters; named presets will plug into this in Milestone 3.
- Configurable pad-clearance diameter and outer padding.
- Pin-1-centred placement anchor.
- Adjustable connector clearance for larger sockets, shrouds, and plug bodies.

### Geometry model

For pin index `i`, the pin centre is placed at `i × 2.54 mm` along the row axis. The preview shows non-exported pad-clearance guides around those centres. The exported artwork contains:

- A block or rail sized from the first and last pin centres.
- One label cell aligned with every pin centre.
- Clearance around the physical pad row.
- Extra space on the selected label side.
- Leading and trailing padding beyond the end pins.
- Optional pin-1 marker.

The generator must not create or alter electrical pads. It produces a separate artwork footprint that the user aligns over an existing connector.

### Data model

- `pin_count`
- `pitch_mm` defaulting to `2.54`
- `pin_labels[]`
- `orientation`
- `pin1_end`
- `label_side`
- `pad_clearance_mm`
- `leading_padding_mm`
- `trailing_padding_mm`
- `label_padding_mm`
- `shape` and versioned style parameters (with `shape_preset` added after Milestone 3)
- `output_layer`

### Required tests

- [x] Exact 2.54 mm centre-to-centre spacing.
- [x] Correct overall bounds for 1, 2, 3, 8, 10, and 20 pins.
- [x] Label count must match pin count.
- [x] No exported silkscreen geometry enters configured pad-clearance areas.
- [x] Correct rail-side padding in every orientation.
- [x] Pin-1 anchor remains stable when labels or styles change.
- [x] Bottom output is exactly one X mirror of front output.
- [x] Serialisation round trip preserves all labels and layout settings.
- [x] Generated footprint parses and exports through KiCad 10 on all six supported layers.

### Follow-on versions

- [ ] Dual-row `2xN` headers.
- [ ] Other common pitches such as 1.27 mm and 2.00 mm.
- [ ] Read pitch, pad centres, orientation, and pad dimensions from a selected footprint.
- [ ] Populate labels from pad numbers, net names, or a pasted table.
- [ ] Connector templates for JST, terminal blocks, debug headers, and common modules.

Acceptance: a user can enter an eight-pin header, provide eight labels, place the generated block with its pin-1 anchor, and have every label and clearance align to the existing 2.54 mm row on either board side.

## Milestone 5 — built-in tags and icons

Goal: make common labels available without drawing or importing anything.

- [x] Define the icon asset format and metadata schema.
- [x] Create a curated first-party electrical symbol set.
- [ ] Evaluate and import an attributed subset of a permissively licensed icon library.
- [x] Use closed, fabrication-friendly polygon paths without runtime SVG dependencies.
- [x] Add searchable categories and rendered asset previews.
- [ ] Add favourites and recent assets.
- [x] Create the first 58 preloaded Power, GND, interface, warning, test, and control labels.
- [x] Test every bundled icon through composition, parser, layer, and 3D-render paths.

Acceptance: bundled assets render consistently on front/back Silkscreen, Copper, and Mask without unsupported SVG features.

## Milestone 6 — SVG, codes, and batch generation

- [ ] Sanitised SVG import.
- [ ] QR and Data Matrix objects with quiet-zone and module-size checks.
- [ ] CSV/pasted-table batch generation.
- [ ] Revision, serial-number, connector, and test-point templates.
- [ ] Export selected designs as a reusable footprint library.

Acceptance: imported/generated content uses the same composition, style, preview, and manufacturing-validation path as normal labels.

## Milestone 7 — Silk Studio shell

- [ ] Asset/template browser.
- [ ] Composition canvas.
- [ ] Object list and inspector.
- [ ] Preset and project-style manager.
- [ ] Header/callout and batch workflows.
- [ ] Undo/history.
- [ ] Front/back and manufacturing previews.

Acceptance: the existing quick-label flow remains available, while complex documents can be built without exposing raw geometry parameters.

## Milestone 8 — board-aware automation and IPC

- [ ] Add a KiCad IPC integration adapter alongside the KiCad 10 compatibility path.
- [ ] Read selected footprints, pads, board edges, courtyards, and existing graphics.
- [ ] Generate connector labels from actual pad positions and net names.
- [ ] Add collision detection and placement suggestions.
- [ ] Add board-wide typography/style audit and bulk updates.

Acceptance: automation proposes changes for user approval and never silently moves or rewrites unrelated board items.

## What we start with

After checkpointing `0.1.0-dev`, start with these tasks only:

1. Define the composition document and JSON schema.
2. Implement rectangle, rounded rectangle, and pill geometry.
3. Implement padding, border thickness, and radius rules.
4. Add Plain, Rounded, Pill, and Kobee presets.
5. Build the single-row 2.54 mm pin-header generator against that engine.
6. Add its pin-centre, clearance, mirroring, serialisation, and KiCad export tests.

Do not begin the full Silk Studio shell, automatic placement, or large icon library until those six steps are working. They are the smallest foundation that supports nearly every likely roadmap item.
