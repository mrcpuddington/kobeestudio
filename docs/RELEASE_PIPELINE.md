# Kobee Studio release pipeline

This document describes how Kobee Studio moves from a code change to a tested
beta and then to a stable release.

The source repository is the home for code, tests, and GitHub Actions. The
separate `mrcpuddington-kicad-repository` contains the generated
`repository.json` and `packages.json` files that KiCad reads.

## The flow

```text
Feature branch
    ↓ pull request
Validation workflow
    ↓ merge
main
    ↓ manually run Publish workflow
Testing GitHub Release + testing PCM repository
    ↓ install and test
Production approval
    ↓ manually run or promote
Stable GitHub Release + stable PCM repository
```

## Local development

Local builds are for fast iteration and private testing:

```bash
python3 pcm/build.py
```

The generated package is in `pcm/build/`. Install it in KiCad with **Plugin
and Content Manager → Install from File**.

Local builds do not publish anything and do not change GitHub releases.

## Package authority

Packages are built by GitHub Actions from an explicit source revision. Testers
install the testing-stream package from PCM or its release asset; they do not
need to build an install ZIP locally.

## Validation workflow

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main` and
`UI2.0`. It:

1. Checks out the commit.
2. Sets up Python 3.11.
3. Runs the complete test suite with wxPython under Xvfb.
4. Builds the PCM ZIP.
5. Verifies that the ZIP metadata matches the source metadata.
6. Uploads the ZIP as a short-lived Actions artifact.

This workflow never creates a GitHub Release and never updates a PCM
repository.

## Publishing a beta

Before publishing, update the selected source ref with the intended numeric
PCM version and set its metadata status to `testing`. KiCad requires a numeric
`major.minor.patch` PCM version; it does not accept a SemVer suffix in the PCM
metadata.

Open **Actions → Publish Kobee Studio package → Run workflow** and enter:

- `source_ref`: the exact branch, tag or commit to test;
- `channel`: `testing`;
- `release_tag`: for example `v1.4.0-beta.1`;
- `release_name`: an optional friendly title.

The worker checks out that exact ref, runs the tests, builds the ZIP, validates
the version/status, prepares an official KiCad metadata draft as an Actions
artifact, creates a GitHub pre-release with the ZIP attached, and updates the
`testing` branch of the PCM catalogue. It uses the curated notes from
`docs/releases/<version>-notes.md` when present, otherwise generated notes.

The testing PCM repository is intended for invited testers or for your own
KiCad installation. Add its `repository.json` URL to KiCad, refresh PCM, and
install or update Kobee Studio from that channel.

## Promoting to stable

Stable publication is deliberately separate from beta publication. After the
beta has been tested:

1. Update the release source ref so its PCM metadata says `status: stable`.
2. Run the same workflow with `channel: stable`.
3. Select the `production` environment when GitHub requests approval.
4. Approve only after the beta has passed manual testing.
5. The worker creates or updates the non-prerelease GitHub Release and uploads
   the stable ZIP.
6. The worker updates the `main` branch of the PCM repository with the
   generated metadata.

The `production` environment must be configured in the GitHub repository
settings with required reviewers. Without that environment configuration, the
workflow cannot provide a meaningful production approval gate.

## Repository layout

The recommended final arrangement is:

```text
mrcpuddington/kobeestudio
  Source code
  pcm/build.py
  .github/workflows/ci.yml
  .github/workflows/publish.yml

mrcpuddington/kobeestudio-pcm
  repository.json
  packages.json
  testing/    (optional separate testing endpoint)
```

The distribution repository is intentionally separate from the source tree:
it contains generated catalogue data, not hand-edited plugin code. The publish
worker checks out the correct branch, writes both catalogue files, and pushes
the generated update.

## Why the worker is the release authority

Local builds remain useful during development, but official packages should be
built by Actions because the worker:

- starts from an explicit commit or tag;
- runs the same checks every time;
- creates the ZIP and checksum consistently;
- attaches the exact artifact to the GitHub Release; and
- pauses stable publication behind a production approval.

Do not manually rebuild a different ZIP after approving a beta. Promote the
tested commit and artifact through the release process so the package tested
by you is the package users receive.

## First-time GitHub setup

1. Add the workflows in this repository.
2. Create GitHub Actions environments named `testing` and `production`.
3. Configure required reviewers for `production`.
4. Create a fine-grained GitHub token with Contents read/write access only to
   `mrcpuddington/mrcpuddington-kicad-repository`.
5. Add it to the source repository as the Actions secret
   `PCM_REPOSITORY_TOKEN`.
6. Add the testing repository URL to your KiCad installation.
7. Run a beta publication and test installation/update manually.
8. Run a stable publication only after the beta is accepted.

The publish worker now handles GitHub Release creation, ZIP upload, and the
matching testing/stable PCM catalogue update.

## Updating the official KiCad catalog

The custom PCM catalog above and KiCad's default catalog are separate delivery
routes. The official catalog currently includes Kobee Studio 1.4.1, 1.4.0 and
1.3.4. Submit an update to
[`kicad/addons/metadata`](https://gitlab.com/kicad/addons/metadata), changing
`packages/com.github.mrcpuddington.kobeestudio/metadata.json`. Preserve existing
versions and their checksums. The public-facing `kicad/addons/repository` is
generated; it is not the merge-request target.

Use the [1.5.20 preparation checklist](releases/1.5.20-preparation.md) for the
current testing candidate. A metadata draft does not publish a package, submit
a GitLab merge request or approve a release.

After publishing the intended artifact, download that exact ZIP and run:

```bash
python3 tools/prepare_kicad_submission.py \
  --archive /path/to/Kobee-Studio-1.5.20-pcm.zip \
  --release-tag v1.5.20-beta.1 \
  --verify-download
```

The default output is `pcm/build/official-submission/`. It contains the package
path to copy into a GitLab fork, a merge-request draft, the upstream snapshot and
a readiness record. Offline preparation can use `--upstream-metadata <file>`;
refresh upstream before submission. Without `--verify-download`, the readiness
record explicitly leaves public availability unverified. A failed verification
returns a nonzero exit status and leaves the draft marked unverified.

Run the official repository's validator, push the metadata-only branch to your
fork, and install/update from its temporary PCM repository. Then submit the
merge request. For stable distribution, finish the manual acceptance checks,
prepare the stable package and use its exact `v1.5.20` tag and checksum. Do this
before adding 1.5.20 to the official catalog: published archives are immutable,
and the preparation tool refuses to replace an existing upstream version with
different bytes. Rebuilding in Actions can change the ZIP checksum, so always
regenerate the submission from the actual released file.

See the [official submission/update guide](https://dev-docs.kicad.org/en/addons/)
and [repository workflow](https://gitlab.com/kicad/addons/metadata/-/blob/main/README.md).
