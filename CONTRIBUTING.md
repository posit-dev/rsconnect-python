# Contributing to `rsconnect-python`

This project aims to uphold Python [community norms](https://www.python.org/psf/conduct/) and make use of [recommended
tooling](https://packaging.python.org/guides/tool-recommendations/).

To get started, you'll want to:
- install [`uv`](https://docs.astral.sh/uv/) and [`just`](https://github.com/casey/just)
- clone the repo
- run `uv sync --group test` to provision the interpreter and install all dependencies
- validate your build environment with some sample commands

We use [`uv`](https://docs.astral.sh/uv/) to manage environments and
[`just`](https://github.com/casey/just) as the task runner. Install both, then:

```bash
# Clone the repo
cd ~/dev
git clone https://github.com/posit-dev/rsconnect-python.git
cd rsconnect-python
# Create the environment and install the project plus dev tooling.
# `uv` provisions the interpreter and resolves the `test` dependency group.
uv sync --group test
# Run the CLI from your working tree:
uv run rsconnect version
```

## Workflow

### Linting

```bash
just lint
```

This runs `ruff format --check`, `ruff check`, and `pyright`. `pyright` is
advisory (it does not fail the command); ruff is enforced. Auto-format and
apply fixes with:

```bash
just fmt
```

### Testing

```bash
# run the tests on the default Python (3.13)
just test

# run tests with a specific Python version (uv fetches it if needed)
just test 3.12

# run tests across all supported Python versions
just all-tests
```

The test suite includes integration tests that require a running Posit Connect
server. These tests are skipped automatically unless the `CONNECT_SERVER` and
`CONNECT_API_KEY` environment variables are set. If you have these variables in
your environment from other work and see unexpected test failures, unset them:

```bash
unset CONNECT_SERVER CONNECT_API_KEY
```

## Proposing Change

Any and all proposed changes are expected to be made via [pull
request](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests).

### Testing Against Connect

Prior to merging, we run tests against the dev version of Connect using the `rsconnect-python-tests-at-night` workflow
in the Connect repository. To test a feature branch:

1. Navigate to the `rsconnect-python-tests-at-night` workflow in the Connect repository
2. Trigger it manually via workflow_dispatch
3. Specify your `rsconnect-python` branch/ref in the dropdown

## Versioning and Releasing

The version is a static field in `pyproject.toml`, managed with
[`uv version`](https://docs.astral.sh/uv/guides/package/#updating-your-version).
`main` always carries a `.dev` version (e.g. `1.29.1.dev0`) so development
builds are marked as pre-releases and never collide with a published release.

`main` is a protected branch, so direct pushes are rejected. Releases go
through a Release PR; only the tag is pushed directly (tags are not
protected).

### Open the Release PR

Increment the version and update CHANGELOG.md. The changelog must be updated
before _EACH_ release, even beta releases.

```bash
# Drop the .dev suffix to cut the release (e.g. 1.29.1.dev0 -> 1.29.1)
VERSION="$(uv version --bump stable --dry-run --short)"  # use "--bump minor" if there are new features
git checkout -b "release-$VERSION" main
uv version "$VERSION"
sed -i "s/^## Unreleased/## [$VERSION] - $(date +%Y-%m-%d)/" docs/CHANGELOG.md
git commit -am "Release $VERSION"
git push -u origin "release-$VERSION"
gh pr create --title "Release $VERSION" --body "Release $VERSION"
```

### Merge the Release PR, then Tag main

After the PR is approved and merged, tag the merge commit on `main`.
Do NOT tag your local release branch: squash-merging rewrites the SHA.

```bash
git checkout main && git pull
VERSION="$(uv version --short)"  # sanity check: must be the release version
git tag -a "$VERSION" -m "Release $VERSION"
git push origin "$VERSION"
```

On the tag push, the `distributions` job asserts the tag equals the
`pyproject.toml` version, builds `rsconnect_python` and `rsconnect`, and
publishes to [PyPI](https://pypi.org/project/rsconnect-python/#history) and the
GitHub releases page.

### Re-arm development

After releasing, re-arm development on `main` with a second PR that adds
back the `Unreleased` section to CHANGELOG.md and moves to a development
version

```bash
VERSION="$(uv version --bump patch --bump dev --dry-run --short)"  # e.g. 1.29.1 -> 1.29.2.dev1
git checkout -b "rearm-$VERSION" main
sed -i '0,/^## \[/s//## Unreleased\n\n&/' docs/CHANGELOG.md
uv version "$VERSION"
git commit -am "Begin $VERSION development"
git push -u origin "rearm-$VERSION"
gh pr create --title "Begin $VERSION development" --body "Re-arm development after release"
```

> **NOTE**: Pre-release versions must comply with [PEP 440](https://www.python.org/dev/peps/pep-0440/) so PyPI marks them as pre-releases. `uv version`'s `dev`/`alpha`/`beta`/`rc` bumps produce compliant strings.

## Updating rsconnect-python on conda-forge

rsconnect-python exists on conda-forge as its own [feedstock](https://github.com/conda-forge/rsconnect-python-feedstock)

Updating the package requires a fork of the repository and a [push request](https://github.com/conda-forge/rsconnect-python-feedstock#updating-rsconnect-python-feedstock).

- For new version/release, update the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file with the new version number, source url, and corresponding checksum.

- For a rebuild of the same version, increase "number" under "build" by one in the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file.

Once the proposed change is pushed, follow the checklist.
- [example PR with check list](https://github.com/conda-forge/rsconnect-python-feedstock/pull/1)

### Adding yourself as a rsconnect-python conda-forge maintainer

Add your github username under recipe-maintainers in the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file.
