# Kobee Studio versioning

This project uses two related version labels:

1. A KiCad PCM version, which must be numeric and use the format `major.minor.patch`.
2. A human-readable GitHub release tag, which may use normal Semantic Versioning.

KiCad PCM does not accept versions such as `1.4.0-beta.1` or `1.3.4.1` in the
package metadata. The PCM version must contain three numeric components.

## Release standard

Stable releases use the same version in all locations:

```text
PCM version: 1.4.0
PCM status:  stable
Git tag:     v1.4.0
```

Testing releases use the target release number in PCM and identify beta
iterations in the GitHub tag:

```text
PCM version: 1.4.2
PCM status:  testing
Git tag:     v1.4.2-beta.1
```

Subsequent beta tags are:

```text
v1.4.2-beta.1
v1.4.2-beta.2
```

For local or manual beta testing, each beta can be installed from its GitHub
release asset or from the locally generated ZIP. For automatic PCM updates
between iterations, use a separate testing repository and an increasing
numeric build scheme; do not add SemVer suffixes to the PCM version.

The automated catalogue now retains every published numeric version. A new
numeric version is appended to the catalogue, while rerunning an identical
version replaces only that version's asset metadata.

## Version locations in this repository

Until the build process is automated further, keep these values synchronized:

- `kobeestudio/version.py` — version embedded in generated artwork and plugin
  information.
- `pcm/metadata_template.json` — version and status read by KiCad PCM.
- Version assertions in `tests/` — expected metadata values.

The archive filename is generated from the version in
`pcm/metadata_template.json`.

## Building locally

Run:

```bash
python3 pcm/build.py
```

The script recreates `pcm/build/` and produces:

```text
pcm/build/Kobee-Studio-<pcm-version>-pcm.zip
pcm/build/metadata.json
```

The generated files are build artifacts and are ignored by Git. Install the ZIP
through KiCad's Plugin and Content Manager using **Install from File**.

## Release checklist

1. Update the version and status in the files listed above.
2. Run the focused tests.
3. Build the PCM ZIP with `python3 pcm/build.py`.
4. Verify the ZIP metadata and checksum.
5. Create a GitHub release using the matching tag.
6. Mark beta releases as GitHub pre-releases and PCM versions as `testing`.
7. Mark the final release as stable in both GitHub and PCM metadata.

## References

- [KiCad Addon and PCM documentation](https://dev-docs.kicad.org/en/addons/index.html)
- [Bouni's KiCad repository example](https://raw.githubusercontent.com/Bouni/bouni-kicad-repository/main/packages.json)
