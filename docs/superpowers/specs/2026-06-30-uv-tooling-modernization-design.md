# uv-native tooling modernization

**Date:** 2026-06-30
**Status:** Approved design

## Goal

Modernize the build and test infrastructure of `rsconnect-python` onto an
astral-native toolchain. Replace Docker (where it is only providing Python
environments) with `uv`, replace `make` with `just`, adopt `uv_build` as the
build backend, and replace `black` + `flake8` with `ruff`.

Docker is **not** removed where it runs the actual Posit Connect server
product — `uv` cannot run Connect.

## Scope

### In scope
- Build backend: `setuptools` + `setuptools_scm` → `uv_build`.
- Versioning: git-tag-derived (`setuptools_scm`) → static version in
  `pyproject.toml`, managed with `uv version`.
- Multi-version testing: per-version Docker images → `uv run --python <X>`.
- Task runner: `Makefile` → `Justfile`.
- Lint/format: `black` + `flake8` → `ruff` (keep `pyright` for type checking).
- CI workflow updates to use `uv` / `just`.
- Delete now-dead Docker and build artifacts.

### Out of scope (stays on Docker)
- `docker-compose.yml` + `vetiver-testing/` — spins up a real Connect server
  for the `dev`/`dev-stop` helpers and the `test-dev-connect` CI job.
- `integration-testing/` — Connect server + bats client integration suite.
- `requirements.txt` — still consumed by integration tests (see the existing
  `#649` TODO). Left untouched.

## Background: how Docker is used today

1. **Multi-version Python testing** (`Makefile` `image-%`/`test-%`/`RUNNER`,
   `Dockerfile`, `scripts/build-image`): builds a `python:X-slim` image per
   version and runs tests inside. CI already bypasses this — when
   `GITHUB_RUN_ID` is set, `RUNNER` collapses to `bash -c` and CI uses
   `actions/setup-python` + `pip install`. So this path is effectively
   local-dev only. **Replaceable by uv.**
2. **Running a Connect server** (`docker-compose.yml`, `integration-testing/`):
   runs the actual Connect product. **Not replaceable by uv. Kept.**
3. **Docs** (`docs/Dockerfile`): dead — `make docs` already uses `uv`.
   **Deleted.**

## Design

### A. Build backend → `uv_build`

`pyproject.toml` `[build-system]`:

```toml
[build-system]
requires = ["uv_build>=0.9.0,<0.10.0"]
build-backend = "uv_build"
```

- The project uses a **flat layout** (`rsconnect/` at the repo root), so the
  build backend needs `[tool.uv.build-backend] module-root = ""`.
- `rsconnect/py.typed` and `rsconnect/quickstart/templates/**/*` live under the
  module root and are therefore included in the wheel automatically. The
  explicit `[tool.setuptools] packages = [...]` and
  `[tool.setuptools.package-data]` blocks are removed.
- Delete `setup.py` (an empty `setup()` stub).
- Remove `[tool.distutils.bdist_wheel] universal = true`. That legacy setting
  produced the `py2.py3-none-any` wheel tag; `uv_build` emits `py3-none-any`.
  The release jobs upload `dist/*.whl`, so the filename change is harmless.

**Dual-name publishing** (`rsconnect_python` and `rsconnect`) is preserved. The
existing `scripts/temporary-rename` uv inline-script rewrites `project.name` in
`pyproject.toml` from the `PACKAGE_NAME` env var before the build; this still
works with `uv_build`. It is renamed to `scripts/prepare-build` for clarity.
`just dist` runs `scripts/prepare-build` and then `uv build`.

### B. Versioning

The version's source of truth moves from the git tag to `pyproject.toml`.

- Add a static `version = "1.29.0"` to `[project]` (the last released tag) and
  remove `version` from `dynamic`.
- Release flow (update the "Releasing" section of `CLAUDE.md`):
  ```
  uv version --bump patch        # 1.29.0 => 1.29.1
  git commit -am 'Release 1.29.1'
  git tag -a 1.29.1 -m 'Release 1.29.1'
  git push --tags
  ```
- `rsconnect/__init__.py` resolves the runtime `VERSION` from installed package
  metadata, trying both published distribution names:
  ```python
  from importlib.metadata import version, PackageNotFoundError

  try:
      VERSION = version("rsconnect_python")
  except PackageNotFoundError:
      try:
          VERSION = version("rsconnect")
      except PackageNotFoundError:
          VERSION = "NOTSET"
  ```
- Delete the generated `rsconnect/version.py` and its `.gitignore` entry.
- Drop `setuptools_scm` from dependencies and remove `[tool.setuptools_scm]`.

**Behavior change:** untagged commits no longer report a unique
`1.29.1.devN+gHASH` string; an editable/dev install reports the committed
version. This was accepted in design review. The release version (built wheels,
PyPI) is always correct because it is committed and bumped explicitly.

### C. Lint/format → `ruff` (keep `pyright`)

`ruff` replaces both `black` (formatter) and `flake8` (linter). `pyright`
remains for type checking (strict mode, unchanged).

- Remove `[tool.black]` and `[tool.flake8]`. Add:
  ```toml
  [tool.ruff]
  line-length = 120

  [tool.ruff.lint]
  select = ["E", "F", "W"]
  per-file-ignores = { "tests/test_metadata.py" = ["E501"] }
  ```
- The `select = ["E", "F", "W"]` set is intentionally conservative — it
  approximates today's `flake8` (pyflakes + pycodestyle errors/warnings)
  **without** enabling isort (`I`) or other rule groups, to avoid a large
  one-time import-reordering / lint diff. `ruff format` settings default to
  black-compatible behavior at `line-length = 120`, keeping the one-time
  reformatting diff minimal.
- The old `black`-compat `flake8` ignores (`E203`, `E231`, `E302`) are no
  longer needed: `ruff format` owns whitespace/blank-line formatting, and those
  codes are not in the selected lint set.
- `[project.optional-dependencies].test`: remove `black==24.3.0`, `flake8`,
  `flake8-pyproject`; add `ruff`. Keep `pyright`, `pytest`, `pytest-cov`,
  `coverage`, `httpretty`, `ipykernel`, `nbconvert`, `twine`, `types-Flask`,
  and the `fastmcp` marker. (`setuptools`/`setuptools_scm` are removed.)

A one-time `ruff format .` pass is applied as part of the migration so the tree
is clean under the new formatter.

### D. Multi-version testing via uv

Tests run directly against uv-provided interpreters — no Docker images:

```
uv run --python <X> --extra test pytest -vv \
    --cov=rsconnect --cov-report=term --cov-report=html --cov-report=xml ./tests/
```

`uv` fetches each interpreter (python-build-standalone) for 3.8–3.13. The test
recipe also exports `CONNECT_CONTENT_BUILD_DIR=rsconnect-build-test` (as the
Makefile `TEST_ENV` did) and inherits `CONNECT_SERVER` / `CONNECT_API_KEY` from
the environment when present (used by the integration jobs).

Delete `Dockerfile`, `scripts/build-image`, and the Makefile `image-%` /
`RUNNER` machinery.

### E. Task runner → `Justfile`

`Justfile` replaces `Makefile`. Recipes (mapping the kept Make targets):

| Recipe | Behavior |
| --- | --- |
| `test py="3.13"` | `uv run --python {{py}} --extra test pytest …` (+ `CONNECT_CONTENT_BUILD_DIR`) |
| `all-tests` | runs `test` for 3.8, 3.9, 3.10, 3.11, 3.12, 3.13 |
| `lint` | `uv run ruff format --check .` + `uv run ruff check .` + `uv run pyright rsconnect/` |
| `fmt` | `uv run ruff format .` + `uv run ruff check --fix .` |
| `dist` | `scripts/prepare-build` + `uv build` + `uv run twine check dist/*.whl` |
| `install` | install the built wheel |
| `docs` / `docs-serve` | `uv run mkdocs build` / `serve` (unchanged from today) |
| `version` | `uv version --short` |
| `clean` / `clean-stores` | same cleanup as Makefile |
| `dev` / `dev-stop` | **unchanged** — still `docker compose up/down` for the Connect server |
| `sync-latest-docs-to-s3` / `promote-docs-in-s3` | unchanged `aws s3 sync` (called by CI) |

Delete `Makefile`.

### F. CI updates

**`.github/workflows/main.yml`:**

- `test-python-versions`: replace `actions/setup-python` + `pip install '.[test]'`
  + `make lint` / `make test-X` with `astral-sh/setup-uv`, then `just lint` and
  `just test ${{ matrix.python-version }}`. The `GITHUB_RUN_ID` Make hack is
  gone. Coverage upload step unchanged (still reads `coverage.xml`).
- `prerelease-test`: `uv run --prerelease allow --extra test` for install/test.
- `distributions`: `just dist` (already uses `astral-sh/setup-uv`); keep the
  `PACKAGE_NAME` matrix and the rename step (now `scripts/prepare-build`).
- `docs`: `just docs` (already uv-based).
- `test-connect-versions` and `test-dev-connect` (integration): **keep the
  Docker Connect server**. Only swap `make test-X` → `just test X` and add
  `astral-sh/setup-uv`. `test-dev-connect` continues to use `docker compose`
  and `pip freeze > requirements.txt` for its integration setup.

**`.github/workflows/preview-docs.yml`:** use `astral-sh/setup-uv` + `just docs`
(or `uv run mkdocs build`) instead of `setup-python` + `pip install`.

### G. Lockfile

Commit a `uv.lock` for reproducible CI and local dev. It must resolve across
`requires-python >= 3.8` (3.8–3.13); a single lock covers the matrix.

## Files

**Deleted:** `Dockerfile`, `scripts/build-image`, `docs/Dockerfile`,
`Makefile`, `setup.py`, `rsconnect/version.py` (+ its `.gitignore` line).

**Renamed:** `scripts/temporary-rename` → `scripts/prepare-build`.

**Added:** `Justfile`, `uv.lock`.

**Modified:** `pyproject.toml`, `rsconnect/__init__.py`, `.gitignore`,
`.github/workflows/main.yml`, `.github/workflows/preview-docs.yml`, `CLAUDE.md`
(Releasing + dev-command sections), `CONTRIBUTING.md` (dev setup instructions).

**Untouched (kept on Docker):** `docker-compose.yml`, `vetiver-testing/`,
`integration-testing/`, `requirements.txt`.

## Risks / notes

- **uv_build has no dynamic/VCS version support.** Confirmed against the uv
  build-backend docs; this is why versioning moves to a committed static value.
  If uv adds VCS versioning later, this can be revisited.
- **Python 3.8 is EOL** but still provided by uv via python-build-standalone;
  the test matrix continues to cover it.
- **ruff format is ~black-compatible but not byte-identical**; expect a small
  one-time formatting diff, applied as a dedicated commit. The conservative
  lint `select` avoids a large lint/import-ordering diff.
- **Flat-layout build:** `module-root = ""` is required; without it `uv_build`
  assumes a `src/` layout and the wheel will be empty/wrong. This is the most
  likely thing to get wrong — verify the built wheel contains `rsconnect/`,
  `py.typed`, and the quickstart templates.
