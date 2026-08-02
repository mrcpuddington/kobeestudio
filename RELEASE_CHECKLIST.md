# Kobee Studio release checklist

- [ ] Run the automated test suite using the intended KiCad embedded Python.
- [ ] Install from a clean checkout through a symbolic link and refresh plugins.
- [ ] Verify Kobee Studio appears in PCB Editor’s External Plugins menu and opens without traceback.
- [ ] Create and place `FRONT`, `BOTTOM`, `ABC123`, and `R2D7` on F/B Silkscreen, F/B Copper, and F/B Mask.
- [ ] Confirm every B.* label is bottom-owned and needs no manual `F` flip.
- [ ] Inspect both board sides and the underside in KiCad 3D Viewer; `R2D7` must be readable from below.
- [ ] Confirm mask labels produce intentional openings and copper labels pass the intended DRC/manufacturing rules.
- [ ] Export all six supported Gerbers and review them in GerbView; preserve the evidence with the release notes.
- [ ] Check plain, background-tag/inverted-background, inline formatting, fonts, height, width, alignment, and edit flows.
- [ ] Check every Silk Studio shape in inverted and outline modes, including padding, border, radius, feature-size, direction, and all independent square/rounded end combinations.
- [ ] Check all 16 built-in icons left/right of text and icon-only, including **No container** bare symbols, automatic/explicit icon height, gap, inverted fill, outline, and all six layers. Confirm Input and Output point in opposite directions and both DC polarity diagrams are correct.
- [ ] Search and filter both visual asset pickers; confirm every thumbnail appears and selecting Custom text or No symbol clears only the intended catalog choice.
- [ ] Select representative quick labels from every category, edit their suggested text/icon independently, place them, and reopen them with the same settings.
- [ ] Place and reopen a four-pin 2.54 mm header rail in all four orientations/sides; confirm pin-1 anchoring, optional marker, exact pitch, non-exported guides, and independently square/rounded pin-side and label-side long edges.
- [ ] Confirm header openings can be none, continuous, or individual; verify continuous width/end extension, plot-time silkscreen subtraction for **None**, and mandatory copper clearance.
- [ ] Confirm errors are shown in the dialog and diagnostics do not expose private paths.
- [ ] Retain MIT, GPL-2.0, FontTools, svg2mod, Buzzard, and Greg Davill attribution in the release archive.
- [ ] Validate the PCM archive and metadata, then publish only after a maintainer explicitly approves release distribution.
