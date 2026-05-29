# Contributing to `rsconnect-python`

This project aims to uphold Python [community norms](https://www.python.org/psf/conduct/) and make use of [recommended
tooling](https://packaging.python.org/guides/tool-recommendations/).

To get started, you'll want to:
- clone the repo into a project directory
- setup a virtual 3.8+ python environment in the project directory
- activate that virtual environment
- install the dependencies
- validate your build environment with some sample commands

While there are several different tools and techniques you can use to accomplish the
steps listed above, the following is an example which uses `venv`.

```bash
# Clone the repo
cd ~/dev
git clone https://github.com/posit-dev/rsconnect-python.git
cd rsconnect-python
# Setup a virtual python environment
python3 -m venv .venv
# Activate the virtual environment
source .venv/bin/activate
# Install rsconnect-python with a symbolic link to the locations repository,
# meaning any changes to code in there will automatically be reflected.
# Also install dev/test dependencies.
pip install -e '.[test]'
```

## Workflow

With your venv setup and active, as described previously, running rsconnect-python using your codebase is as simple as running the `rsconnect` command from the terminal.

### Linting

```bash
make lint
```

This runs black (formatting check), flake8, and pyright.

> **NOTE**: pyright currently has known errors that are suppressed in the Makefile (see [#774](https://github.com/posit-dev/rsconnect-python/issues/774)). Until those are resolved, you can run just the enforced checks directly:
>
> ```bash
> black --check --diff rsconnect/
> flake8 rsconnect/
> flake8 tests/
> ```

To auto-format code:

```bash
make fmt
```

### Testing

```bash
# run the tests
make test

# run tests with a specific Python version
make test-3.12

# run tests across all supported Python versions
make all-tests
```

The test suite includes integration tests that require a running Posit Connect server. These tests are skipped automatically unless the `CONNECT_SERVER` and `CONNECT_API_KEY` environment variables are set. If you have these variables in your environment from other work and see unexpected test failures, unset them:

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

All version and release management is done via [annotated git tags](https://git-scm.com/docs/git-tag), as this is the
repo metadata used by the [`setuptools_scm`](https://github.com/pypa/setuptools_scm) package to generate the version
string provided as `rsconnect:VERSION` and output by `rsconnect version`.

### Update CHANGELOG.md

Before releasing, replace the `Unreleased` heading in the CHANGELOG.md with the version number and date. Update CHANGELOG.md before _EACH_ release, even beta releases, in order to avoid one commit with multiple tags (https://github.com/pypa/setuptools_scm/issues/521).

### Tagging a Release

To create a new release, create and push an annotated git tag:

```bash
git tag -a 1.2.3 -m 'Release 1.2.3'
git push origin 1.2.3
```

Once the tag push is received by GitHub, the relevant workflow action will be triggered and, upon successful completion,
a release will be created and published to the repository
[releases](https://github.com/posit-dev/rsconnect-python/releases) and the public
[PYPI](https://pypi.org/project/rsconnect-python/#history).

> **NOTE**: Pre-releases versions must comply with [PIP 440](https://www.python.org/dev/peps/pep-0440/) in order for
> PIPY to appropriately mark them as pre-releases.

## Updating rsconnect-python on conda-forge

rsconnect-python exists on conda-forge as its own [feedstock](https://github.com/conda-forge/rsconnect-python-feedstock)

Updating the package requires a fork of the repository and a [push request](https://github.com/conda-forge/rsconnect-python-feedstock#updating-rsconnect-python-feedstock).

- For new version/release, update the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file with the new version number, source url, and corresponding checksum.

- For a rebuild of the same version, increase "number" under "build" by one in the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file.

Once the proposed change is pushed, follow the checklist.
- [example PR with check list](https://github.com/conda-forge/rsconnect-python-feedstock/pull/1)

### Adding yourself as a rsconnect-python conda-forge maintainer

Add your github username under recipe-maintainers in the [meta.yaml](https://github.com/conda-forge/rsconnect-python-feedstock/blob/master/recipe/meta.yaml) file.
