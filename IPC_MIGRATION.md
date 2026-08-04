# IPC migration

Kobee Studio 1.2.x used KiCad's SWIG ActionPlugin interface. Kobee Studio 1.3
is the stable successor built on KiCad's supported IPC plugin API, which is
available in KiCad 9 and 10 and planned to replace SWIG in KiCad 11.

## Current milestone — connection foundation

- [x] Keep the current SWIG plugin and its packaged release untouched.
- [x] Add an IPC `plugin.json` action manifest and declared runtime dependencies.
- [x] Add a small IPC session boundary that connects using KiCad-provided socket
  and token environment variables.
- [x] Verify the API can read the active board, selection and create a single
  undoable transaction boundary.
- [x] Convert generated filled and outlined artwork into IPC footprint polygons.
- [x] Carry Kobee Studio edit metadata in a hidden footprint field.
- [x] Open selected IPC artwork in the existing editor and update it in place.
- [x] Open and replace selected 1.2.x SWIG artwork through IPC without losing
  its saved settings, position, or orientation.
- [x] Complete live macOS create, reopen, update and undo-transaction testing
  against KiCad 10.0.4 using the self-contained development install.
- [x] Build a schema-valid IPC PCM archive with the identifier
  `com.github.mrcpuddington.kobeestudio`.
- [ ] Repeat the live IPC regression on KiCad 10 for Windows.

## Migration shape

The geometry engine, asset libraries, QR/barcode generation, artwork document
format, and most of the editor UI remain shared. The migration replaces only
the KiCad-facing adapter currently in
`kobeestudio/integration/kicad_compatibility.py`.

IPC artwork is created in one board transaction, so placing or updating a
Kobee Studio item remains a single Undo operation. The 1.3.1 PCM is the stable
IPC release. Complete Windows IPC validation remains on the roadmap before the
official KiCad package-repository submission.

## Test path

For manual work, install `ipc_plugin/` as a KiCad IPC plugin directory. KiCad
creates a per-plugin virtual environment, installs `requirements.txt`, then
launches `kobeestudio_ipc.py` with `KICAD_API_SOCKET` and `KICAD_API_TOKEN`.
The `tools/ipc_smoke_test.py` development helper can exercise create and update
against a disposable board through an explicitly selected PCB Editor socket.

Run `python3 pcm/build.py` to create the installable
`pcm/build/Kobee-Studio-1.3.1-pcm.zip` archive. It contains the IPC manifest,
application source, dependency declarations, icons and licences and can be installed with
KiCad's **Plugin and Content Manager → Install from File…** command.
