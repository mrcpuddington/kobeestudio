# Manual KiCad 10 acceptance validation

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
9. Run **Add Kobee Designator to Selected Footprint**. Confirm it opens Board Tools → Designators without another popup, keeps reference text read-only in the main window, and updates the live preview as layout, font, symbol, shape, appearance, border, radius, and four padding values change. Change the KiCad selection while Kobee Studio remains open and confirm the reference/preview updates automatically. Confirm **Apply designators** remains visible in every Designators section. Switch to **Whole board** and confirm the first eligible reference is previewed. Test front and bottom references with rotated native fields. Run it twice and confirm the existing Kobee designator updates without duplication. Repeat in bulk mode. Undo once to restore native references and again to remove the verified generated artwork.
10. Confirm **Variables** is the final Labels tab. Load a project whose `.kicad_pro` contains externally supplied `text_variables`, insert several `${NAME}` expressions into a multi-line global and project template, and confirm the preview shows the current resolved values. Place the label and inspect it in KiCad: the stored footprint text must still contain the raw `${NAME}` expressions, update when the project variables change, and mirror correctly on B.SilkS. Reopen and update the label, then back up and restore the library and confirm both templates return.
