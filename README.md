# Kobee Studio

![Kobee bee](kibeezard/resources/kobee-bee.png)

> Friendly, flexible PCB artwork for KiCad. 🐝

Hi — I’m [Corey Busuttil](https://www.coreybusuttil.com). I run
[Kobee](https://www.kobee.com.au), and Kobee Studio is the tool I wanted when
making a board: quick little labels when that is all you need, but enough care
and control to build a proper, consistent visual system when the project calls
for it.

Kobee Studio evolved from **KiBuzzard**, created by Greg Davill. It keeps the
excellent font-to-vector foundation that made KiBuzzard so useful, while taking
the product in a broader direction: labels, symbols, connector callouts, and
eventually a more complete PCB artwork studio.

## What works today

Kobee Studio runs in **KiCad 10 on macOS**. It creates ordinary, editable
footprints on the board — there is no footprint library to configure.

- Text labels with practical `1.2 mm` default text height and compact padding.
- Labels on one chosen front or bottom silkscreen, copper, or solder-mask layer.
- Rectangle, rounded rectangle, pill, pointer, flag, tab, chamfer, and hexagon
  containers, with fill, outline, borders, radius, and independent end styles.
- Searchable quick labels and 16 original PCB-safe icons, including ground,
  power, test point, input/output, warning, LED, battery, and polarity symbols.
- Bare icons as well as icon-and-label artwork.
- 2.54 mm single-row header blocks with per-pin labels, configurable plug space,
  optional openings, pin-side layout, and independently styled long edges.

Windows testing is planned next, still for KiCad 10. Until it is completed,
this is a development build rather than a broad compatibility promise.

## Roadmap

The detail lives in [ROADMAP.md](ROADMAP.md), with the build order in
[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md). The short version is:

### Likely next

- [x] Parametric labels, icons, quick-label picker, and 2.54 mm header blocks.
- [ ] Saved user and project style presets, including a Kobee preset.
- [ ] More icons and labels shaped by real board-design use.
- [ ] Dual-row headers, connector callouts, and pinout tables.
- [ ] SVG artwork import, QR codes, batch generation, and templates.
- [ ] Windows and Linux validation for KiCad 10.
- [ ] A release through KiCad’s Plugin and Content Manager.

### Further out

- [ ] A full Silk Studio canvas with objects, layers, history, and reusable
  design-system templates.
- [ ] Automatic placement that understands pads, tracks, board edges, and
  existing artwork.
- [ ] Board-wide typography and artwork consistency checks.
- [ ] Net-aware copper artwork and schematic-aware callouts.

## A few useful details

Choose **Label** for normal artwork, then choose a shape and fill or outline.
**Independent ends** lets the left and right ends be square, rounded,
chamfered, pointed, or notched independently. The live preview and exported
footprint use the same geometry.

The searchable **Quick labels** and **Symbols** controls open visual pickers;
they are deliberately not long dropdown lists. Icons may sit beside text or be
used on their own with **No container + Icon only**.

Choose **2.54 mm Pin Header** for a single-row connector overlay. A row with
pins on the left is laid out as outer padding → pin/plug space → gap →
right-aligned labels → outer padding; the other sides rotate or mirror this
relationship. The artwork is an overlay only and never replaces or changes the
electrical connector footprint.

For silkscreen, **None** is the default opening mode. KiCad can remove silk
where no solder mask exists if the project’s Gerber plot option enables it.
Copper header blocks always require an opening so the enclosure cannot join
connector pins together.

## Install Kobee Studio — KiCad 10

Kobee Studio is a KiCad plugin, not a footprint library. The intended public
path will be a signed, versioned `Kobee-Studio-x.y.z-pcm.zip` download from the
[GitHub Releases page](https://github.com/mrcpuddington/kibeezard/releases).

When a release is available:

1. Download the PCM ZIP without unzipping it.
2. In KiCad PCB Editor, open **Plugin and Content Manager**.
3. Choose **Install from File…**, select the ZIP, and approve the install.
4. Open **Tools → External Plugins → Kobee Studio: Create PCB Artwork**.

### Manual install — current source or development build

This is the KiBuzzard-compatible fallback for people testing a newer build.
In KiCad’s Python/Scripting Console, run:

```python
import pcbnew
print(*pcbnew.PLUGIN_DIRECTORIES_SEARCH, sep="\n")
```

Choose a writable user plugin directory from that list, then use one of these:

```sh
# Git — easiest way to update later
git clone https://github.com/mrcpuddington/kibeezard.git "PLUGIN_DIRECTORY/kibeezard"

# Existing local checkout — best for contributors
ln -s "$(pwd)" "PLUGIN_DIRECTORY/kibeezard"
```

Or download GitHub’s **Source code (zip)** archive, unzip it, and move its
top-level folder to `PLUGIN_DIRECTORY/kibeezard`. The on-disk `kibeezard`
folder is the stable Python plugin module used by KiCad; the product itself is
Kobee Studio. Refresh plugins or restart PCB Editor afterwards.

To update a Git checkout, run:

```sh
git -C "PLUGIN_DIRECTORY/kibeezard" pull
```

## Repository layout

- `kibeezard/core/` — composition documents, shapes, artwork, and output.
- `kibeezard/rendering/` — the retained font-to-vector renderer.
- `kibeezard/fonts/` — bundled typefaces used by the renderer.
- `kibeezard/ui/` — the Kobee Studio wxPython interface and its base dialog.
- `kibeezard/vendor/` — only the FontTools and svg2mod runtime source required
  by the plugin; upstream docs, tests, and development tooling are excluded.
- `tests/` — repeatable generation and geometry checks.

There is intentionally no `legacy/` directory. The small pieces Kobee Studio
still relies on were brought into the current rendering, UI-base, font, and
vendor boundaries, with their licences retained.

## Testing

Run the automated checks with KiCad’s embedded Python:

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3.9 -m unittest discover -s tests -v
```

Manual checks are in [tests/MANUAL_VALIDATION.md](tests/MANUAL_VALIDATION.md).
`python3 pcm/build.py` creates a local PCM-shaped archive in `build/`; it is
not a public release package yet.

## Thank you

Kobee Studio stands on some genuinely great work:

- **Greg Davill**, for creating KiBuzzard and making beautiful custom
  silkscreen practical in KiCad.
- **SparkFun**, for the original [Buzzard](https://github.com/sparkfunX/Buzzard)
  project that inspired the renderer.
- The people behind [Interactive HTML BOM](https://github.com/openscopeproject/InteractiveHtmlBom),
  whose KiCad plugin and wx dialog ideas shaped the original experience.
- The [FontTools](https://github.com/fonttools/fonttools) and
  [svg2mod](https://github.com/svg2mod/svg2mod) contributors.

Thank you to everyone who used KiBuzzard, reported issues, shared boards, and
kept this kind of small, joyful tool alive. Licence and attribution details are
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
