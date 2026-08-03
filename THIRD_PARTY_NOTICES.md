# Third-party notices

Kobee Studio is distributed under GPL-2.0 because the packaged plugin directly uses the GPL-2.0 svg2mod runtime. It is also a substantial evolution of **[KiBuzzard](https://github.com/gregdavill/KiBuzzard)**, originally created by Greg Davill. The font-to-vector renderer and base dialog began in that project; their source provenance is retained in comments and commit history.

The following runtime dependencies are bundled because KiCad plugins cannot
assume a separate system Python environment:

- **FontTools**, under the MIT Licence — see
  [`kobeestudio/vendor/licenses/fonttools-LICENSE`](kobeestudio/vendor/licenses/fonttools-LICENSE).
- **svg2mod**, under GPL-2.0 — see
  [`kobeestudio/vendor/licenses/svg2mod-LICENSE`](kobeestudio/vendor/licenses/svg2mod-LICENSE).
- **KiBuzzard**, under the MIT Licence — see
  [`kobeestudio/vendor/licenses/kiBuzzard-LICENSE`](kobeestudio/vendor/licenses/kiBuzzard-LICENSE).
- **qrcode 8.2**, under the BSD Licence — see
  [`kobeestudio/vendor/licenses/qrcode-LICENSE`](kobeestudio/vendor/licenses/qrcode-LICENSE).
- **python-barcode 0.16.1**, under the MIT Licence — see
  [`kobeestudio/vendor/licenses/python-barcode-LICENSE`](kobeestudio/vendor/licenses/python-barcode-LICENSE).

The included FreddySpark, Ubuntu Mono, and M+ typefaces remain credited to
their respective creators in the project history and are retained solely for
the same bundled-font functionality provided by the original plugin.
