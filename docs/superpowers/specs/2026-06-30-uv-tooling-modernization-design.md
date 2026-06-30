# uv-native tooling modernization

**Date:** 2026-06-30
**Status:** Approved design (v2 — reconciled after dual review)

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
- CI workflow updates to use `uv` / `just` (`main.yml`, `preview-docs.yml`;
  `snyk.yml` reviewed for impact).
- Delete now-dead Docker and build artifacts.

### Out of scope (stays on Docker)
- `docker-compose.yml` + `vetiver-testing/` — spins up a real Connect server
  for the `dev`/`dev-stop` helpers and the `test-dev-connect` CI job.
- `integration-testing/` — Connect server + bats client integration suite.
- `requirements.txt` — see "requirements.txt has three consumers" note below;
  the hand-maintained file is left as-is.

## Background: how Docker is used today

1. **Multi-version Python testing** (`Makefile` `image-%`/`test-%`/`RUNNER`,
   `Dockerfile`, `scripts/build-image`): builds a `python:X-slim` image per
   version and runs tests inside. CI already bypasses this — when
   `GITHUB_RUN_ID` is set, `RUNNER` collapses to `bash -c`. So this path is
   effectively local-dev only. **Replaceable by uv.**
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

- Flat layout (`rsconnect/` at repo root). Set **both** keys explicitly so the
  backend neither assumes a `src/` layout nor packages sibling directories:
  ```toml
  [tool.uv.build-backend]
  module-name = "rsconnect"
  module-root = ""
  ```
- `rsconnect/py.typed` and `rsconnect/quickstart/templates/**/*` live under the
  module and should be included automatically. **This is not taken on faith** —
  see "Migration verification" for a mandatory wheel-contents check, promoted to
  a CI step. The explicit `[tool.setuptools] packages = [...]` and
  `[tool.setuptools.package-data]` blocks are removed.
- Delete `setup.py` (an empty `setup()` stub).
- Remove `[tool.distutils.bdist_wheel] universal = true`. That legacy setting
  produced the `py2.py3-none-any` wheel tag; `uv_build` emits `py3-none-any`.
  The only hardcoded reference to the old filename is `Makefile` `BDIST_WHEEL`,
  which is deleted with the Makefile (see §F for the CI consumer of the wheel).

**Dual-name publishing** (`rsconnect_python` and `rsconnect`) is preserved. The
existing `scripts/temporary-rename` uv inline-script rewrites `project.name`
from the `PACKAGE_NAME` env var before the build; renamed to
`scripts/prepare-build` for clarity. `just dist` runs `scripts/prepare-build`
then `uv build`. **Note:** this script runs only in disposable CI checkouts;
never run it against a tracked tree (it rewrites `pyproject.toml` via
`toml.dump`, which does not preserve comments/key order). `uv build` reads
`pyproject.toml`, not `uv.lock`, so the transient name/lock mismatch does not
fail the build — verified as part of migration.

### B. Versioning

The version's source of truth moves from the git tag to `pyproject.toml`.

**Committed value is `1.29.1.dev0`, not `1.29.0`.** This is the single most
important correction from review and fixes two problems at once:

1. **No PyPI collision.** `1.29.0` is already published. Committing a released
   version on `main` means every build between releases produces an artifact
   labeled as an existing release; a tag build that forgets to bump would have
   `pypa/gh-action-pypi-publish` reject it as a duplicate. A `.dev0` suffix
   cannot collide with any published release.
2. **Dev-nag stays suppressed.** `rsconnect/version_check.py:124` gates the
   "a newer version is available" network check on
   `_is_dev_version(VERSION)` → `Version(VERSION).is_devrelease`. With
   `setuptools_scm`, editable installs reported `…devN+gHASH` (a dev release),
   so the nag never fired during local dev or tests. `1.29.1.dev0` keeps
   `is_devrelease == True`; a plain `1.29.0` would arm the nag (and its PyPI
   fetch) on every developer's machine and in test runs.

Release flow (update `CLAUDE.md` "Releasing" and `CONTRIBUTING.md"`):
```
uv version --bump stable        # 1.29.1.dev0 => 1.29.1
git commit -am 'Release 1.29.1'
git tag -a 1.29.1 -m 'Release 1.29.1'
git push --tags
# after release, re-arm dev on main:
uv version 1.29.2.dev0
git commit -am 'Begin 1.29.2 development'
```

`rsconnect/__init__.py` resolves the runtime `VERSION` from installed package
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
- **CI guard (tag builds):** the `distributions` job asserts the pushed tag
  equals `uv version --short` and fails the release if they diverge — restoring
  the tag↔version coupling that `setuptools_scm` enforced structurally.

**Behavior change (accepted):** untagged commits report `1.29.1.dev0` rather
than a unique `…devN+gHASH` string. The `+gHASH` commit identifier and
auto-incrementing `devN` are lost; `is_devrelease` semantics are preserved.

### C. Lint/format → `ruff` (keep `pyright`)

`ruff` replaces both `black` (formatter) and `flake8` (linter). `pyright`
remains for type checking (strict mode, unchanged config).

- Remove `[tool.black]` and `[tool.flake8]`. Add:
  ```toml
  [tool.ruff]
  line-length = 120
  extend-exclude = ["my-shiny-app", "rsconnect-build", "rsconnect-build-test", "integration", "vetiver-testing"]

  [tool.ruff.lint]
  select = ["E", "F", "W"]
  ignore = ["E203", "E231", "E302"]
  per-file-ignores = { "tests/test_metadata.py" = ["E501"] }
  ```
- **`ignore = ["E203","E231","E302"]` is required, not optional.** These are
  pycodestyle E-codes that `select = ["E"]` enables; the old `flake8` config
  `extend_ignore`d them for black compatibility. Omitting them would surface new
  findings the formatter is responsible for. (Correcting a false claim in v1
  that they were "not in the selected set.")
- `extend-exclude` replaces the old `flake8` `exclude` list so `ruff check .`
  does not descend into scratch/sibling dirs that flake8 skipped. `ruff` also
  respects `.gitignore` by default.
- Lint scope **broadens** to the whole tree (`ruff check .`), which now includes
  `tests/` — the old Makefile linted `rsconnect/` and `tests/` separately, so
  coverage is preserved and slightly extended.
- `[project.optional-dependencies].test`: remove `black==24.3.0`, `flake8`,
  `flake8-pyproject`, `setuptools`, `setuptools_scm`; add `ruff`. Keep
  `pyright`, `pytest`, `pytest-cov`, `coverage`, `httpretty`, `ipykernel`,
  `nbconvert`, `twine`, `types-Flask`, and the `fastmcp` marker.

A one-time `ruff format .` pass is applied as a **dedicated commit**, separate
from logic changes. See "Migration verification" for the pre-commit diff check
that bounds the churn.

### D. Multi-version testing via uv

Tests run against uv-provided interpreters — no Docker images:

```
uv run --python <X> --extra test ./scripts/runtests
```

`scripts/runtests` is **kept** as the single source of truth for pytest args
(`-vv --cov=rsconnect --cov-report=term --cov-report=html --cov-report=xml
./tests/`) and exports `CONNECT_CONTENT_BUILD_DIR=rsconnect-build-test`. `uv`
fetches each interpreter (python-build-standalone) for 3.8–3.13. `CONNECT_SERVER`
/ `CONNECT_API_KEY` are inherited from the environment when present (integration
jobs).

`scripts/build-image` is deleted (Docker-only). The Makefile `image-%` /
`RUNNER` machinery is deleted.

**Dependency declaration:** test/lint/build tooling stays in
`[project.optional-dependencies].test` (consumed via `--extra test`) for this
migration, because the out-of-scope integration jobs still `pip install
'.[test]'`. Migrating to PEP 735 `[dependency-groups]` (so dev tooling is not
advertised in the published wheel's metadata) is a recommended **follow-up**,
deferred here to avoid changing the out-of-scope integration jobs' install path.

### E. Task runner → `Justfile`

`Justfile` replaces `Makefile`. Recipes (mapping the kept Make targets):

| Recipe | Behavior |
| --- | --- |
| `test py="3.13"` | `uv run --python {{py}} --extra test ./scripts/runtests` |
| `all-tests` | runs `test` for 3.8, 3.9, 3.10, 3.11, 3.12, 3.13 |
| `lint` | `uv run ruff format --check .` + `uv run ruff check .` + advisory `uv run pyright rsconnect/` (see note) |
| `fmt` | `uv run ruff format .` + `uv run ruff check --fix .` |
| `dist` | `scripts/prepare-build` + `uv build` + `uv run twine check dist/*.whl` |
| `install` | `uv pip install dist/*.whl` |
| `docs` / `docs-serve` | `VERSION=$(uv version --short) uv run mkdocs build` / `serve` |
| `version` | `uv version --short` |
| `clean` / `clean-stores` | same cleanup as Makefile |
| `dev` / `dev-stop` | **unchanged** — still `docker compose up/down` for the Connect server |
| `sync-latest-docs-to-s3` / `promote-docs-in-s3` | unchanged `aws s3 sync` (called by CI) |

**pyright failure semantics (decision):** the current Makefile runs pyright with
a leading `-` so it is **advisory** (never fails `make lint`). `just lint`
preserves this advisory behavior to avoid a surprise CI break on migration
(strict mode over a large codebase). Making pyright blocking is a deliberate
follow-up once findings are driven to zero. This is called out because v1
described pyright as "unchanged" while its failure semantics would in fact have
changed.

**`docs`/`docs-serve` set `VERSION`:** `mkdocs.yml:93` reads
`os.getenv("VERSION")`. The Makefile only set `VERSION` as a make-var (never
exported), so it was likely empty in published docs already; the `just` recipes
set it explicitly from `uv version --short` so the rendered version is correct.

Delete `Makefile`.

### F. CI updates

Audit **every** `make ` invocation across all workflows, not just `make test-X`.

**`.github/workflows/main.yml`:**

- `test-python-versions`: replace `actions/setup-python` + `pip install '.[test]'`
  + `make lint`/`make test-X` with `astral-sh/setup-uv` (pinned to a uv that
  provides `uv version`, ≥ 0.9), then `just lint` and
  `just test ${{ matrix.python-version }}`. The `GITHUB_RUN_ID` Make hack is
  gone. Coverage upload step unchanged (still reads `coverage.xml`).
- `prerelease-test`: must actually exercise prereleases. `uv run --prerelease
  allow` alone resolves against the committed `uv.lock` and tests nothing new,
  so use `uv run --upgrade --prerelease allow --extra test …` (re-resolves,
  ignoring the lock). **Preserve** the existing `make lint` and `rsconnect
  version` smoke steps (as `just lint` / `rsconnect version`), which v1 dropped.
- `distributions`: `just dist` (already uses `astral-sh/setup-uv`); keep the
  `PACKAGE_NAME` matrix and the rename step (now `scripts/prepare-build`).
  **The step that consumes `steps.create_dist.outputs.whl` must be rewritten to
  glob `dist/*.whl`** — `just` does not emit the Makefile's `::set-output
  name=whl::` value (and that syntax is deprecated in favor of `$GITHUB_OUTPUT`).
  Add the **tag↔version guard** here (§B).
- `docs`: `just docs` (already uv-based).
- `test-connect-versions` (integration, `posit-dev/with-connect@main`): **keep
  the Docker Connect server.** Do **not** run `just`/`uv run` inside the
  `with-connect` `command:` block, because that triggers an implicit
  build/resolve + interpreter fetch over the network *during* the
  integration test, and assumes `uv`/`just` are on PATH in that action's shell.
  Instead: add an explicit `astral-sh/setup-uv` + `uv sync --extra test` (or
  `uv pip install '.[test]'`) step on the runner **before** entering
  `with-connect`, and have the `command:` invoke `pytest` directly against the
  already-prepared environment.
- `test-dev-connect` (integration): keeps `docker compose`. It calls **`make
  dev`** (not `make test-X`) — swap to `just dev`. Its `pip install '.[test]'`
  + `pip freeze > requirements.txt` are left as-is (see requirements.txt note).

**`.github/workflows/preview-docs.yml`:** use `astral-sh/setup-uv` + `just docs`
(which sets `VERSION`) instead of `setup-python` + `pip install`.

**`.github/workflows/snyk.yml`:** unchanged mechanically, but in scope because
it triggers on `pyproject.toml` changes and runs `uv pip compile pyproject.toml
--output-file requirements.txt` (ephemeral, in-CI only — it does not commit the
file). After the dependency edits, snyk simply scans the new dependency set.
No action required beyond awareness.

### G. Lockfile

Commit a `uv.lock` for reproducible CI and local dev.

- **Regenerate** the lock with `uv lock` *after* the `pyproject.toml`
  dependency edits. The lock currently on disk still references `black`,
  `flake8`, and `setuptools_scm`; committing it as-is would re-pin the very
  tools being removed. Commit the regenerated lock.
- A single universal lock resolves across `requires-python >= 3.8` (3.8–3.13)
  via environment markers; note this enforces a lowest-common-denominator
  resolution (3.8 constraints can hold back newer-Python pins), unlike the old
  per-interpreter `pip install`. Acceptable.
- CI runs `uv lock --check` (or `uv run --locked`) so a stale lock fails fast.

## requirements.txt has three consumers (documented, not resolved)

`requirements.txt` is written/read by three different actors with different
expectations; this is pre-existing and **not** introduced by the migration:
1. The committed, hand-maintained file (already stale vs `pyproject.toml`),
   consumed by the integration `scripts`/`Dockerfile` path.
2. `snyk.yml` regenerates it in-CI via `uv pip compile` (ephemeral).
3. `test-dev-connect` regenerates it in-CI via `pip freeze` (ephemeral).

Reconciling these is out of scope (touches the integration suite, see `#649`).
The migration leaves the committed file alone and documents the contention so a
follow-up can address it.

## Migration verification (mandatory, before merge)

1. **Lint diff:** run `ruff check .` and a final `flake8` against the *current*
   (pre-format) tree and diff the reported codes. Confirm no new findings beyond
   the intended formatter reflow before applying `ruff format`.
2. **Format churn:** run `ruff format .` and review the diff size; it should be
   small (black-compatible at line-length 120). Land it as a dedicated commit.
3. **Wheel contents (also a CI step):** `uv build`, then `unzip -l dist/*.whl`
   and assert it **contains** `rsconnect/`, `rsconnect/py.typed`, every
   `rsconnect/quickstart/templates/**`, and **does not contain** `tests/`,
   `conftest.py`, or any sibling top-level dir.
4. **Runtime version:** install the built wheel into a clean venv and confirm
   `rsconnect version` prints the expected value and that
   `importlib.metadata.version` resolves for both `rsconnect_python` and
   `rsconnect` builds.
5. **Dev-nag:** confirm `_is_dev_version(VERSION)` is `True` in an editable
   install (so the version check stays suppressed in dev/CI).
6. **Dual-name build:** run `scripts/prepare-build` + `uv build` for both
   `PACKAGE_NAME` values and confirm `uv build` does not fail on the
   name/lock mismatch.

## Files

**Deleted:** `Dockerfile`, `scripts/build-image`, `docs/Dockerfile`,
`Makefile`, `setup.py`, `rsconnect/version.py` (+ its `.gitignore` line).

**Renamed:** `scripts/temporary-rename` → `scripts/prepare-build`.

**Kept (re-used by `just`):** `scripts/runtests`.

**Added:** `Justfile`, `uv.lock` (regenerated).

**Modified:** `pyproject.toml`, `rsconnect/__init__.py`, `.gitignore`,
`.github/workflows/main.yml`, `.github/workflows/preview-docs.yml`, `CLAUDE.md`
(Releasing + dev-command sections), `CONTRIBUTING.md` (dev setup **and** the
linting section — drop the `#774` Makefile-specific pyright note / restate for
`just lint` — **and** the full Versioning/Releasing rewrite).

**Untouched (kept on Docker):** `docker-compose.yml`, `vetiver-testing/`,
`integration-testing/`, `requirements.txt`.

## Risks / notes

- **uv_build has no dynamic/VCS version support** (confirmed against uv docs) —
  hence the committed static version. Revisit if uv adds VCS versioning.
- **Flat-layout build** is the most likely thing to get wrong: `module-name`
  and `module-root = ""` must both be set, and the wheel-contents assertion
  (verification step 3) is mandatory and promoted to CI.
- **Version/tag divergence** is now possible (it was structurally impossible
  with `setuptools_scm`); the tag↔version CI guard mitigates it.
- **Python 3.8 is EOL** but still provided by uv via python-build-standalone.
- **ruff format is ~black-compatible but not byte-identical**; bounded by
  verification step 2.
- **pyright stays advisory** in CI for now (matching today's `-` behavior);
  making it blocking is a tracked follow-up.

## Deferred follow-ups (explicitly not in this migration)
- PEP 735 `[dependency-groups]` for dev tooling (§D).
- Making `pyright` blocking in CI (§E).
- Reconciling the three `requirements.txt` consumers / integration-suite
  overhaul (`#649`).
