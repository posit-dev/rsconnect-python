# Contributing to `rsconnect-python`

This project aims to uphold Python [community norms](https://www.python.org/psf/conduct/) and make use of [recommended
tooling](https://packaging.python.org/guides/tool-recommendations/).

## Workflow

The [`test` job in the default GitHub Actions workflow](.github/workflows/main.yml) reflects a typical set of steps for
building and testing.

## Proposing Change

Any and all proposed changes are expected to be made via [pull
request](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests/about-pull-requests).

## Versioning and Releasing

All version and release management is done via [annotated git tags](https://git-scm.com/docs/git-tag), as this is the
repo metadata used by the [`setuptools_scm`](https://github.com/pypa/setuptools_scm) package to generate the version
string provided as `rsconnect:VERSION` and output by `rsconnect version`.

To create a new release, create and push an annotated git tag:

```bash
git tag -a 1.2.3 -m 'Release 1.2.3'
git push origin 1.2.3
```

Once the tag push is received by GitHub, the relevant workflow action will be triggered and, upon successful completion,
a release will be created and published to the repository
[releases](https://github.com/rstudio/rsconnect-python/releases) and the public
[PYPI](https://pypi.org/project/rsconnect-python/#history).

> **NOTE**: Pre-releases versions must comply with [PIP 440](https://www.python.org/dev/peps/pep-0440/) in order for
> PIPY to appropriately mark them as pre-releases.
