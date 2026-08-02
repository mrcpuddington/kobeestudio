# Runtime vendor bundle

Kobee Studio vendors the small runtime parts of FontTools and svg2mod required
to convert fonts into KiCad geometry. They are kept here rather than mixed into
the Studio code so the dependency boundary is explicit and the package does not
depend on a separate Python installation.

- `fontTools/` — FontTools runtime package. Licence: `licenses/fonttools-LICENSE`.
- `svg2mod/` — svg2mod runtime package. Licence: `licenses/svg2mod-LICENSE`.

Only runtime source is included; the upstream projects' documentation, tests,
examples, and development tooling are intentionally not shipped.
