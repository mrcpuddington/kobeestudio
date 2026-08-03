# IPC migration

Kobee Studio 1.2.x uses KiCad's SWIG ActionPlugin interface. It remains the
released path for KiCad 10. This branch develops the successor against KiCad's
supported IPC plugin API, which is available in KiCad 9 and 10 and planned to
replace SWIG in KiCad 11.

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
- [ ] Repeat the live IPC regression on KiCad 10 for Windows.

## Migration shape

The geometry engine, asset libraries, QR/barcode generation, artwork document
format, and most of the editor UI remain shared. The migration replaces only
the KiCad-facing adapter currently in
`kobeestudio/integration/kicad_compatibility.py`.

IPC artwork will be created in one board transaction, so placing or updating a
Kobee Studio item remains a single Undo operation. Until placement and editing
are fully covered by regression tests on KiCad 10 for macOS and Windows, the
IPC scaffold is deliberately excluded from PCM release packages.

## Test path

For manual work, install `ipc_plugin/` as a KiCad IPC plugin directory. KiCad
creates a per-plugin virtual environment, installs `requirements.txt`, then
launches `kobeestudio_ipc.py` with `KICAD_API_SOCKET` and `KICAD_API_TOKEN`.
The `tools/ipc_smoke_test.py` development helper can exercise create and update
against a disposable board through an explicitly selected PCB Editor socket.

Run `python ipc_plugin/build.py` to create a self-contained development plugin
directory and ZIP under the ignored `ipc_plugin/build/` directory. The build
contains the application source and licences, so it does not depend on a local
repository checkout when installed into KiCad's user plugin directory.
