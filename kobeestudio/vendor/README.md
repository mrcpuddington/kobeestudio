# Runtime vendor bundle

Kobee Studio vendors the small runtime parts of FontTools and svg2mod required
to convert fonts into KiCad geometry, plus pure-Python encoders for generated
machine-readable artwork.

- `fontTools/` — FontTools runtime package. Licence: `licenses/fonttools-LICENSE`.
- `svg2mod/` — svg2mod runtime package. Licence: `licenses/svg2mod-LICENSE`.

- `qrcode/` — qrcode 8.2 QR matrix encoder. Licence: `licenses/qrcode-LICENSE`.
- `barcode/` — python-barcode 0.16.1 Code 128 encoder. Licence: `licenses/python-barcode-LICENSE`.

Only runtime source is included; the upstream projects' documentation, tests,
examples, and development tooling are intentionally not shipped.
