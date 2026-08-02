# Kobee Studio roadmap

Kobee Studio began as an evolution of KiBuzzard, but the longer-term goal is broader: a friendly PCB graphics and labelling system with a full **Silk Studio** interface.

This roadmap deliberately separates the features we expect to build from the more ambitious ideas we want to explore. It is a direction, not a promise that every item will ship in the next release.

## Foundation already underway

- [x] KiCad 10 support on macOS.
- [x] Direct placement without clipboard simulation.
- [x] User-selectable front and bottom Silkscreen, Copper, and Solder Mask output.
- [x] Correct single mirroring for bottom-side output.
- [x] Stable buffered preview and automated KiCad/Gerber regression coverage.
- [x] Maintained Kobee Studio package, documentation, attribution, and development installation flow.
- [x] Versioned Silk Studio composition documents embedded alongside legacy edit settings.
- [x] KiCad-independent geometry foundation for the first parametric label shapes.
- [x] Usable Silk Studio shape controls and single-row 2.54 mm header workflow in the main dialog.

## Likely roadmap

These are the features that fit the main Kobee Studio product and have a clear route to implementation.

### Parametric label shapes

- [x] Plain text, rectangle, rounded rectangle, and fully rounded pill.
- [x] Pointer, flag, tab, chamfered, and hexagonal label shapes.
- [x] Independent horizontal and vertical padding.
- [x] Border thickness and corner radius.
- [x] Filled, outlined, and inverted variants.
- [x] Independent square/rounded left and right ends, including mixed-end labels.
- [x] Icon-left, icon-right, and icon-only layouts, including bare icons with no container.
- [ ] Secondary-text layouts.
- [ ] Fixed-width, multiline, and alignment controls.

### Styles, presets, and design systems

- [ ] Saved user presets.
- [ ] Project-local presets that can be committed with a KiCad project.
- [ ] Named project typography and spacing settings.
- [ ] Importable and exportable preset packs.
- [ ] Compact, Standard, Large, Warning, Power, Interface, and Test Point styles.
- [ ] A first-party Kobee visual style preset.
- [ ] Bulk restyling of existing Kobee Studio labels.

### 2.54 mm pin-header label blocks

- [x] Choose the number of pins in a single 2.54 mm row.
- [x] Enter one label for every pin.
- [x] Choose horizontal or vertical connector orientation.
- [x] Choose the pin-1 end and the side of the enclosure occupied by the pins.
- [x] Calculate pin centres at an exact 2.54 mm pitch.
- [x] Reserve a configurable continuous opening around the pin row or a larger plug body.
- [x] Make the connector opening optional, continuous, or individual per pin with adjustable width and end extension.
- [x] Add the correct outer, pin-to-label, pin-1-end, and far-end padding.
- [x] Align labels away from left/right pin rows and rotate top/bottom label rows by 90 degrees.
- [x] Generate one user-selected shape as the connector enclosure, including independently square or rounded pin-side and label-side long edges.
- [x] Anchor the block at pin 1 so it drops accurately over an existing header.
- [x] Mirror bottom-layer versions exactly once.
- [x] Preserve the selected Kobee Studio layer and style parameters.
- [ ] Extend the tool to dual-row 2xN headers after the single-row workflow is proven.
- [ ] Eventually read real pad positions and dimensions from a selected connector footprint.

The generated item will be an artwork overlay, not an electrical replacement for the connector footprint. It must keep silkscreen and other artwork clear of the actual pads.

### Built-in tags and icon library

- [x] First-party 16-icon set spanning electrical, polarity, control, warning, indicator, battery, and button symbols.
- [x] First 58 quick labels across power, test, programming, interfaces, signals, and controls.
- [ ] Preloaded Power, GND, protective earth, chassis ground, and battery tags.
- [ ] USB, Ethernet, CAN, RS-485, I2C, SPI, UART, SWD, and JTAG tags.
- [ ] Input/output arrows, polarity, pin 1, ESD, high-voltage, RF, and warning symbols.
- [ ] LED, button, switch, jumper, test point, measurement, and calibration tags.
- [x] Searchable, categorised visual pickers with a rendered preview for every label and symbol.
- [ ] Favourites and recently used assets.
- [x] Original PCB-safe closed paths with no new third-party icon dependency.
- [ ] Attribution and licence metadata for any future imported icon packs.

### Artwork and generated content

- [ ] SVG import with scale, rotation, crop, and alignment.
- [ ] Stroke-to-path conversion and curve simplification.
- [ ] Minimum-feature and malformed-path warnings.
- [x] QR Codes and Code 128 barcodes with payload validation, quiet zones, compact sizing, rounded QR frames, and optional knockout footer text.
- [ ] Configurable QR error-correction level and additional barcode symbologies.
- [ ] Data Matrix and serial-number markings.
- [ ] Connector callouts, pinout tables, and test-point legends.
- [ ] CSV and pasted-table batch generation.
- [ ] Revision, date, URL, and project-field templates.

### Layer and manufacturing support

- [ ] Layer-aware preview colours and explanations.
- [ ] Silkscreen clearance checks around pads and board edges.
- [ ] Copper feature-size and clearance warnings.
- [ ] Solder-mask opening warnings and previews.
- [ ] F/B Fabrication and paired User-layer artwork.
- [ ] Explicit composite recipes such as exposed copper plus matching mask opening.
- [ ] Keep single-layer output as the default; composite output must always be deliberately selected.
- [ ] A dedicated courtyard-envelope tool rather than unrestricted decorative courtyard artwork.

### Silk Studio interface

- [ ] Large live composition canvas.
- [ ] Asset and template browser.
- [ ] Object/layer list and properties inspector.
- [ ] Preset manager and project style editor.
- [ ] Connector-callout and batch-generation workflows.
- [ ] Undo/history and non-destructive editing.
- [ ] Board-manufacturing preview and front/back viewing modes.
- [ ] Keyboard-friendly search and placement.

### Compatibility and release work

- [ ] Dependable editing of existing Kobee Studio and compatible KiBuzzard labels.
- [ ] KiCad 10 testing and documentation on Windows.
- [ ] KiCad 10 testing on Linux.
- [ ] Plugin and Content Manager packaging.
- [ ] Stable project/preset file format with migrations.
- [ ] Gradual move from the legacy SWIG boundary toward KiCad's IPC API.

## Experimental and further-out ideas

These ideas are exciting, but they depend on the core document, style, and board-integration work being solid first.

- [ ] Automatically find unlabeled connectors, switches, LEDs, and test points.
- [ ] Generate a complete board legend from footprints, pads, nets, and project fields.
- [ ] Automatically place labels while avoiding pads, vias, tracks, courtyards, existing artwork, and board edges.
- [ ] Route leader lines from callouts to pins or components.
- [ ] Create net-aware copper artwork that can intentionally connect to GND or another selected net.
- [ ] Live-sync smart labels when connector pins, net names, or project fields change.
- [ ] Audit an entire board for typography, spacing, naming, and visual-style consistency.
- [ ] Apply a complete board-branding theme with one previewable operation.
- [ ] Compare two revisions and highlight changed labels or callouts.
- [ ] Simulate common board-house feature limits with selectable manufacturing profiles.
- [ ] Support community icon, style, and template packs.
- [ ] Build procedural PCB patterns, badges, borders, and decorative fills.
- [ ] Add schematic-aware callouts when KiCad's integration surface supports the required data reliably.
- [ ] Offer an assisted layout mode that proposes several label arrangements for the user to approve.

## A note on courtyard artwork

Courtyard layers have real placement and clearance meaning in KiCad. Kobee Studio should therefore generate courtyard geometry only through a dedicated envelope tool with clear warnings. Decorative documentation belongs on Fabrication or User layers instead.

## What comes first

The first large milestone is the parametric shape/style engine. Rounded labels, pills, presets, the Kobee style, pin-header blocks, icons, templates, and Silk Studio all depend on that shared foundation.
