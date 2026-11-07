# Manual KiCad 10 acceptance validation

## Fresh acceptance — 6 November 2026

See [1.5.20 acceptance and remaining release gates](../docs/releases/1.5.20-acceptance-2026-11-06.md).
The current macOS / KiCad 10.0.5 checkout passed 313 native tests and 60 actual
IPC artwork placement/update cases. Fresh hands-on testing corrected multiline
alignment, locked-aspect graphic sizing, Project Data readability and painted
button callbacks in Project Data/Fonts/component presets. Local PCM upgrade from
1.5.18 to 1.5.20, installed launch, PNG import, transform handles, Project Data
sync, font installation, 3D underside readability and front/back silk GerbView
inspection passed. Package/source integrity and six Gerber exports passed.
Resumed checks also passed live catalogue refresh, installed missing-font repair
(after fixing its stale preview), data backup export/core roundtrip, and actual
app Help → manual → support/privacy/terms navigation.
The follow-up also passed manual reset/restore against a disposable library,
unsafe-backup/SVG/corrupt-PNG rejection, and an actual public1.4.1 → local1.5.20
PCM update with old-artwork reopening and UUID/position/count preservation. Fixed
a false Data Health warning for valid large Google Fonts catalogues and retested
the installed app. Windows/Linux, exact reporter environment and final immutable
CI/public artifact checks remain pending. The linked report distinguishes all
coverage and exact artifact hashes; this is not complete release approval.

## App and GitHub issue review — 2 November 2026

### Follow-up hardening status

The first pass is not proof that every feature is complete or release-ready.
The follow-up exposed a Variables status-message exception, late background
callbacks touching closed dialogs, mixed appearance after a preference change,
an optional-page failure breaking Save settings, and loss of unsaved forms
when library changes rebuild the editor. Source fixes and regression checks
have been added for these paths. Font repair completion is also constrained to
its original tool so switching pages cannot change a different tool's typeface.

The broader GUI stress run exposed a native wx timer crash after repeated
window destruction. Dialog teardown now stops child preview timers as well as
dialog timers. After unlocking the Mac, the complete suite passed **294 tests**;
four repeated UI workflow suites passed **92 checks** without callback exceptions
or a native crash. The runner also correctly rejected an intentionally failing
wx callback, which would previously have printed a traceback while reporting OK.

Native visual review covered light/dark editor and Settings screens, live text
preview, compact Settings navigation, stacked font columns and a scrollable asset
preview. It caught and fixed action labels with stale widths, a preview squeezed
to a strip, unreadable native group headings in light mode, and placement readiness
not repainting after a successful preview.

A live Google Fonts download retained its licence, reopened offline and rendered
through the PCB-vector pipeline. The guarded live IPC smoke test placed a label,
reopened editable metadata and updated it in place: footprint counts were 1 → 2 → 2.
Saving the disposable board and reloading it through KiCad's native parser retained
both footprints and the updated metadata. Compilation and whitespace checks pass.

The final 1.5.20 install archive was rebuilt from the follow-up source, with ZIP
integrity, source-file inventory/content and repository metadata checksum verified.
These checks used macOS 27.2 with KiCad 10.0.5. Windows/Linux visual acceptance,
3D/GerbView orientation acceptance and the exact issue #32 KiCad 10.0.6 setup
remain release checks. This evidence does not establish that every feature on
every platform is complete or free of defects. No release was published and no
GitHub issues were closed.

### First-pass evidence

This review applies to the current development checkout, including changes
already present before the review. It does not describe a published release.
Existing work was preserved. GitHub issues were read and assessed; none were
closed or commented on remotely.

| Issue | Development status and evidence |
| --- | --- |
| [#10 Fonts](https://github.com/mrcpuddington/kobeestudio/issues/10) | Existing system-font activation and Google Fonts library reviewed. Offline catalog, font install/repair/cache and glyph coverage tests pass. Fixed the single-row catalog layout and added keyboard list navigation. Live download, licence retention and offline rendering verified locally; cross-platform release acceptance remains. |
| [#12 SVG import](https://github.com/mrcpuddington/kobeestudio/issues/12) | Existing project/personal SVG libraries, sizing, transforms and embedded fallback pass automated checks. Preview now catches missing-file errors before placement. |
| [#15 Underline/overline](https://github.com/mrcpuddington/kobeestudio/issues/15) | Added independent full-text overline controls with physical gap/thickness, alongside underline. Optional text formatting supports `~{RESET}` and `!{text}` for scoped lines. Geometry, padding and knockout tests pass. |
| [#16 Placement origin](https://github.com/mrcpuddington/kobeestudio/issues/16) | Added all nine anchors under Typography, an origin marker in preview, saved settings and consistent IPC/serialized offsets. Tested front/back anchors and text changes. |
| [#19 SVG catalog](https://github.com/mrcpuddington/kobeestudio/issues/19) | Existing SVG discovery, stable legacy IDs, variants, metadata, search and compatibility tests pass. Fixed loss of an icon's variant during container layout. |
| [#28 Position-edit freeze](https://github.com/mrcpuddington/kobeestudio/issues/28) | Reproduced a native-edit stall using an inverted 32-pin overlay with 3,912 polygons. Exact region compaction reduces the same artwork to 379 polygons. Native properties edits then complete promptly; saving and reloading preserves all 379 shapes and X=104 mm. Also fixed zero-sized hidden fields that independently prevented native properties from saving. Reporter/platform confirmation remains needed. |
| [#29 Rectangular header cutout](https://github.com/mrcpuddington/kobeestudio/issues/29) | Existing pill, rounded rectangle and square rectangle cutouts reviewed. Geometry tests pass; the live 32-pin stress case used a rectangular opening. |
| [#30 Subscript/superscript](https://github.com/mrcpuddington/kobeestudio/issues/30) | Added opt-in KiCad-style `D_{0}` and `V^{2}` formatting, nested groups, escaping and actionable malformed-group errors. Plain labels retain literal characters while formatting is disabled. |
| [#32 Placement crash](https://github.com/mrcpuddington/kobeestudio/issues/32) | The supplied log fails in `_eeschema`'s `API_HANDLER_EDITOR::checkForBusy` during BeginCommit, before artwork creation. Added a pre-write guard for KiCad 10.0.0–10.0.6 with an open schematic, plus no-handler and failed-query tests. See the [upstream fix](https://gitlab.com/kicad/code/kicad/-/commit/bdcb150903658e2c8f91b8862f87d950b35c0d1f). The reporter's exact macOS 27 / KiCad 10.0.6 setup was not available. |

Other reviewed flows include all artwork tools, empty graphics, invalid/recovered
input, cached previews, target layers, family navigation, Settings, profiles,
project data, asset libraries and transactional board cleanup. Settings scroll
when needed; the editor's 760×600 minimum keeps navigation and layer choices in
bounds. Cleanup failures restore local wrappers as well as requesting rollback.

Run the complete suite using `python tools/run_tests.py` with the IPC requirements
installed and wxPython available. On macOS use KiCad's bundled Python. Linux CI
uses `xvfb-run`, a virtual environment with system wxPython, and the same runner.
Both validation and publishing workflows now run the full suite.
First-pass local result: **280 tests passed**, including native wrappers, KiCad file
parsing, all supported output-layer Gerbers, geometry coverage and GUI workflows.
The 1.5.20 PCM archive built successfully; ZIP integrity, metadata and the
complete source-file inventory were verified.

Native checks used a disposable ten-layer board with KiCad 10.0.5 on macOS:
placement → editable metadata → in-place update → native X-position edit → save
→ KiCad parser reload. No existing user board was used. Cross-platform visual
acceptance and the exact crash reporter environment remain release checks.

## Release acceptance procedure

Run this against the development install on macOS and Windows before claiming KiCad 10 compatibility.

1. Open a saved board in KiCad 10 PCB Editor and run **Kobee Studio: Create PCB Artwork** from **Tools → External Plugins**.
2. Place `FRONT`, `BOTTOM`, `ABC123`, and `R2D7` on each of F/B Silkscreen, F/B Copper, and F/B Solder Mask.
3. Every bottom choice must show the mirrored front-view preview with its caption below the artwork; do not press `F` after placement.
4. Inspect footprint properties: front labels must be F.Cu-owned and bottom labels B.Cu-owned. Every graphic must remain on its selected output layer.
5. Switch to the board underside and open the 3D Viewer from below. Each bottom `R2D7` must read normally.
6. Confirm F/B Mask labels create intentional solder-mask openings and F/B Copper labels behave as filled copper geometry.
7. Export all six Gerbers, then inspect them in GerbView. Confirm each asymmetric bottom label is the expected mirror from the front.

## Silk Studio and 2.54 mm header pass

1. In **Label** mode, place `R2D7` as plain text and as every available shape. Check both **Inverted fill** and **Outline**, including a visibly thick border and an intentionally oversized corner radius. For **Independent ends**, check square→square, square→rounded, rounded→square, and rounded→rounded.
2. Confirm changing top/right/bottom/left padding moves the text correctly and does not change the requested outside width of an outlined shape.
3. Search and filter quick labels and symbols, checking that every visible card has a preview. Confirm suggested text/icon can still be edited independently. Check all 16 icons on the left, right, and by themselves; **No container + Icon only** must place a bare symbol with no surrounding artwork. Confirm Input and Output point in opposite directions, both DC polarity diagrams are correct, and the standalone `+`/`−` symbols have square layout bounds. Verify automatic (`0`) and explicit icon heights, icon gap, inverted fill, outline, and reopening a placed icon label.
4. In **2.54 mm Pin Header** mode, choose four pins and enter `VCC`, `GND`, `SDA`, and `SCL` on separate lines. Place examples with pins on the top, bottom, left, and right.
5. Align pin 1 of the generated footprint over pin 1 of a real 1x4 2.54 mm connector. Every dashed preview guide should land on one connector pin and no dashed guide should be exported.
6. Repeat with pin 1 at the opposite end and on a bottom layer. Do not manually flip the result.
7. Check all three **Opening** modes. For **None**, export once with **Subtract soldermask from silkscreen** disabled and once enabled, then confirm the enabled Gerber is clipped at the connector's mask openings. Check continuous width/end extension against a larger shrouded plug, and individual openings against ordinary pins.
8. Confirm choosing copper output changes **None** to a continuous opening and that no copper shape joins separate connector pins.
9. Check the optional pin-1 marker, enclosure end padding, inverted/outline appearances, and editing a placed header footprint back through Kobee Studio. For **Independent long edges**, verify square/rounded combinations affect the pair of corners along the pin side and the pair along the label side—not the pin-1 and far ends—and that Radius controls how subtle the rounding is.

For a command-line export after saving `acceptance.kicad_pcb`:

```sh
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb export gerbers \
  --layers F.SilkS,B.SilkS,F.Cu,B.Cu,F.Mask,B.Mask \
  --output gerbers acceptance.kicad_pcb
```

Record KiCad version, operating-system version, generated Gerbers, and screenshots in the release evidence. This test is deliberately manual because correct 3D and Gerber viewing orientation is a visual acceptance criterion.

## Feature-expansion acceptance pass

Run every item once on macOS and once on Windows with KiCad 10.

1. Resize Kobee Studio from its minimum size to a maximized window on every Labels, Graphics, Codes, Board Tools, and Settings page. Confirm cards reflow without duplicated native controls. Scroll with the pointer over every numeric field; the page or preview may scroll/zoom, but the number must never change.
2. In Settings → Fonts, search the bundled offline catalog, select several families/faces, and confirm the editable PCB-vector sample changes without slowing catalog scrolling. Re-select a cached face offline, then install Regular and Italic faces, close KiCad, disconnect the network, and reopen Kobee Studio. Generate text with both installed faces. Remove one font file manually, confirm Settings marks it missing, then use **Redownload missing** and verify saved artwork still uses the same face. Check that `LICENSE.txt` exists beside the restored font.
3. Upload representative Illustrator and Inkscape SVGs containing paths, shapes, nested transforms, fills, strokes, and both even-odd and nonzero holes. Confirm scripts, external images, filters, masks, SVG text, and embedded raster data are rejected with an actionable message.
4. Convert a transparent PNG. Exercise threshold, inversion, alpha cutoff, crop, smoothing, despeckle, and width. Save it, choose **Edit PNG trace…**, change the settings, and confirm the same library asset updates rather than creating a duplicate.
5. Place an imported graphic and use all four resize handles, the rotation handle, and body dragging. Repeat after rotating and mirroring it and on B.SilkS. Reopen the generated footprint, modify it, and confirm its UUID and board position are retained.
6. Create global and project component presets, edit and delete them, then use each in Component Callout and Component Array. Reopen placed artwork and confirm the embedded dimensions survive after deleting the source preset.
7. Generate Connector Overlays at every standard pitch and at custom 0.50 mm and 20.00 mm boundaries. Confirm the displayed maximum label height updates while typing a custom pitch and that switching between millimetres and mils preserves the physical pitch.
8. Select ordinary, locked, and Kobee-generated footprints. Run each External Plugin cleanup action and each Board Tools selected/whole-board action. Confirm counts, both-side silkscreen removal, preservation of pads/copper/mask/fabrication/courtyard/3D data and semantic field values, and exactly one KiCad undo step.
9. Run **Add Kobee Designator to Selected Footprint**. Confirm it opens Board Tools → Designators without another popup, keeps reference text read-only in the main window, and updates the live preview as layout, font, symbol, shape, appearance, border, radius, and four padding values change. Verify **Reference layout** can add a detail line below each reference, and that left/centre/right alignment, title/detail typography, line spacing, and title/detail gap all update the preview. With a symbol, verify inline left/right and stacked above/below positions. Change the KiCad selection while Kobee Studio remains open and confirm the reference/preview updates automatically. Confirm **Apply designators** remains visible in every Designators section. Switch to **Whole board** and confirm the first eligible reference is previewed. Test front and bottom references with rotated native fields. Move a generated Kobee designator independently of its source footprint, then rerun it and confirm the existing movable Kobee footprint updates without duplication or losing its manual position. Repeat in bulk mode. One undo must restore the native reference and remove the generated replacement labels together.
10. Confirm **Variables** is the final Labels tab. Load a project whose `.kicad_pro` contains externally supplied `text_variables`, insert several `${NAME}` expressions into a multi-line global and project template, and confirm the preview shows the current resolved values. Place a filled/inverted variable label and inspect it in KiCad: it must use the same knockout container geometry as a normal label. Change a project value, reopen the label, and confirm Update re-renders its current resolved value. Back up and restore the library and confirm both templates return.
