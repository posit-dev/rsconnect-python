# uv-native Tooling Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Docker (for Python environments), `make`, `setuptools`/`setuptools_scm`, and `black`+`flake8` with an astral-native toolchain: `uv_build` backend, `uv` multi-version testing, a `Justfile`, and `ruff` (keeping `pyright`).

**Architecture:** `pyproject.toml` becomes the version source of truth (static, bumped with `uv version`); dev tooling moves to PEP 735 `[dependency-groups]` so it stays out of published wheel metadata; tests run on uv-provided interpreters; a `Justfile` holds task definitions; CI uses `astral-sh/setup-uv` + `just`. The Connect-*server* Docker setups (`docker-compose.yml`, `vetiver-testing/`, `integration-testing/`) are intentionally kept — uv cannot run the Connect product.

**Tech Stack:** uv (≥0.9, `uv_build` backend), just, ruff, pyright, pytest, mkdocs, GitHub Actions.

## Global Constraints

- `requires-python = ">=3.8"`; the test matrix covers 3.8, 3.9, 3.10, 3.11, 3.12, 3.13.
- Build backend pin: `uv_build>=0.9.0,<0.10.0`. CI must use a uv that provides `uv version` (≥ 0.9), pinned via `astral-sh/setup-uv` `version: ">=0.9.0"`.
- Committed version is `1.29.1.dev0` (a `.dev` suffix — never a plain released version). This keeps `Version(VERSION).is_devrelease == True` so `rsconnect/version_check.py` suppresses the update-nag in dev, and cannot collide with the published `1.29.0`.
- Flat layout: `[tool.uv.build-backend]` must set **both** `module-name = "rsconnect"` and `module-root = ""`.
- ruff: `line-length = 120`; `select = ["E","F","W"]`; `ignore = ["E203","E231","E302"]` (these are E-codes that `select=["E"]` enables; the old flake8 ignored them for formatter compatibility — omitting them is a bug).
- pyright stays **advisory** (non-blocking) in `just lint`, matching today's Makefile `-` prefix.
- Dev tooling (`ruff`, `pyright`, `twine`, `pytest`, mkdocs, …) lives in `[dependency-groups]`, NOT `[project.optional-dependencies]`. Only genuine runtime features (`keyring`, `snowflake`, `mcp`) remain extras.
- Out of scope / unchanged: `docker-compose.yml`, `vetiver-testing/`, `integration-testing/`, and the committed `requirements.txt`.

---

## File Structure

| File | Responsibility | Action |
| --- | --- | --- |
| `pyproject.toml` | build backend, static version, dependency-groups, ruff config | Modify |
| `rsconnect/__init__.py` | resolve `VERSION` via `importlib.metadata` | Modify |
| `rsconnect/version.py` | setuptools_scm-generated version (gitignored) | Delete |
| `.gitignore` | drop the `version.py` line | Modify |
| `uv.lock` | reproducible resolution across 3.8–3.13 | Regenerate + commit |
| `scripts/temporary-rename` → `scripts/prepare-build` | dual-name build prep | Rename |
| `scripts/runtests` | single source of pytest args | Keep (reused by `just`) |
| `scripts/build-image` | Docker image build | Delete |
| `Justfile` | task runner (replaces Makefile) | Create |
| `Makefile` | old task runner | Delete |
| `Dockerfile`, `docs/Dockerfile` | Python-env / docs images | Delete |
| `setup.py` | empty setuptools stub | Delete |
| `.github/workflows/main.yml` | CI: test/dist/docs/integration | Modify |
| `.github/workflows/preview-docs.yml` | CI: PR doc previews | Modify |
| `CONTRIBUTING.md` | dev setup, lint, versioning docs | Modify |
| `CLAUDE.md` | Releasing + dev-command sections | Modify |

---

## Task 1: Migrate `pyproject.toml`, version plumbing, and lockfile

This is the coupled core: switching to `uv_build` requires a static version, and every `uv run` performs an implicit build. The whole transformation lands as one deliverable so the repo is never half-migrated.

**Files:**
- Modify: `pyproject.toml`
- Modify: `rsconnect/__init__.py`
- Delete: `rsconnect/version.py`
- Modify: `.gitignore`
- Regenerate: `uv.lock`

**Interfaces:**
- Produces: `rsconnect.VERSION: str` (resolved at runtime via `importlib.metadata`); dependency group `test` and `docs`; runtime extras `keyring`, `snowflake`, `mcp`; build backend `uv_build` with `module-name = "rsconnect"`, `module-root = ""`.

- [ ] **Step 1: Replace `pyproject.toml` with the migrated version**

Write the full file:

```toml
[project]
name = "rsconnect_python"
description = "The Posit Connect command-line interface."

authors = [{ name = "Posit, PBC", email = "rsconnect@posit.co" }]
license = { file = "LICENSE.md" }
readme = { file = "README.md", content-type = "text/markdown" }
requires-python = ">=3.8"
version = "1.29.1.dev0"

dependencies = [
    "typing-extensions>=4.8.0",
    "pip>=10.0.0",
    "uv>=0.9.0",
    "semver>=2.0.0,<4.0.0",
    "pyjwt>=2.4.0",
    "click>=8.0.0",
    "packaging>=20.0",
    "toml>=0.10; python_version < '3.11'",
]

[project.scripts]
rsconnect = "rsconnect.main:cli"

[project.optional-dependencies]
keyring = ["keyring>=23.0.0"]
snowflake = ["snowflake-cli"]
mcp = ["fastmcp==2.12.4; python_version >= '3.10'"]

[dependency-groups]
test = [
    "coverage",
    "httpretty",
    "ipykernel",
    "nbconvert",
    "pytest",
    "pytest-cov",
    "twine",
    "types-Flask",
    "ruff",
    "pyright",
    "fastmcp==2.12.4; python_version >= '3.10'",
]
docs = [
    "mkdocs-material",
    "mkdocs-click",
    "pymdown-extensions",
    "mkdocs-macros-plugin",
]

[project.urls]
Repository = "http://github.com/posit-dev/rsconnect-python"
Documentation = "https://docs.posit.co/rsconnect-python"

[build-system]
requires = ["uv_build>=0.9.0,<0.10.0"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "rsconnect"
module-root = ""

[tool.ruff]
line-length = 120
extend-exclude = ["my-shiny-app", "rsconnect-build", "rsconnect-build-test", "integration", "vetiver-testing"]

[tool.ruff.lint]
select = ["E", "F", "W"]
ignore = ["E203", "E231", "E302"]
per-file-ignores = { "tests/test_metadata.py" = ["E501"] }

[tool.coverage.run]
omit = ["tests/*"]

[tool.pytest.ini_options]
markers = ["vetiver: tests for vetiver"]
addopts = """
    --ignore=tests/testdata
"""

[tool.pyright]
typeCheckingMode = "strict"
reportPrivateUsage = "none"
reportUnnecessaryIsInstance = "none"
reportUnnecessaryComparison = "none"
```

Removed vs. the old file: `dynamic = ["version"]`, the `test`/`docs` entries under `[project.optional-dependencies]`, `[build-system]` setuptools requires, `[tool.distutils.bdist_wheel]`, `[tool.black]`, `[tool.flake8]`, `[tool.setuptools]`, `[tool.setuptools_scm]`, `[tool.setuptools.package-data]`.

- [ ] **Step 2: Rewrite `rsconnect/__init__.py` to resolve VERSION from installed metadata**

Replace the entire file with:

```python
from importlib.metadata import PackageNotFoundError, version


def _resolve_version() -> str:
    for distribution in ("rsconnect_python", "rsconnect"):
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    return "NOTSET"


VERSION = _resolve_version()
```

(Single assignment avoids pyright's `reportConstantRedefinition`; both published distribution names are tried.)

- [ ] **Step 3: Delete the generated version file and its gitignore entry**

`rsconnect/version.py` is gitignored (untracked), so a plain filesystem delete is enough:

```bash
rm -f rsconnect/version.py
```

Then edit `.gitignore` and delete line 23 (`/rsconnect/version.py`).

- [ ] **Step 4: Regenerate the lockfile**

The on-disk `uv.lock` (if present) still pins `black`/`flake8`/`setuptools_scm`. Regenerate it against the new `pyproject.toml`:

Run: `uv lock`
Expected: completes; `uv.lock` no longer contains `setuptools-scm`, `black`, or `flake8`. Verify:

Run: `grep -E "name = \"(black|flake8|setuptools-scm)\"" uv.lock; echo "exit:$?"`
Expected: no matches, `exit:1`.

- [ ] **Step 5: Verify the project builds and the wheel contents are correct**

Run: `uv build`
Expected: produces `dist/rsconnect_python-1.29.1.dev0-py3-none-any.whl` and a `.tar.gz` sdist.

Run: `unzip -l dist/*.whl`
Expected: the listing **contains** `rsconnect/__init__.py`, `rsconnect/py.typed`, and files under `rsconnect/quickstart/templates/` (e.g. `…/shiny/app.py`); it **does not contain** `tests/`, `conftest.py`, `integration/`, or any sibling top-level directory.

If `py.typed` or the templates are missing, the flat-layout config is wrong — confirm `module-root = ""` and `module-name = "rsconnect"` are set; uv_build includes all non-excluded files under the module by default, so a missing file usually means the module root resolved incorrectly. Do not proceed until the wheel is correct.

- [ ] **Step 6: Verify runtime version resolution and dev-release detection**

Run: `uv run --no-project --with dist/*.whl rsconnect version`
Expected: prints `1.29.1.dev0`.

Run: `uv run --group test python -c "from rsconnect import VERSION; from packaging.version import Version; print(VERSION, Version(VERSION).is_devrelease)"`
Expected: `1.29.1.dev0 True` (confirms the update-nag stays suppressed in dev).

- [ ] **Step 7: Run the test suite under uv**

Run: `uv run --group test pytest -q`
Expected: the suite passes (same result set as before the migration). Integration tests that need `CONNECT_SERVER`/`CONNECT_API_KEY` self-skip when those are unset.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml rsconnect/__init__.py .gitignore uv.lock
git commit -m "build: migrate to uv_build backend with static versioning and dependency-groups"
```

(`rsconnect/version.py` was untracked, so there is nothing to `git rm`.)

---

## Task 2: One-time `ruff format` + lint reconciliation

ruff is configured (Task 1) but the tree has not been reformatted. This task bounds and lands the formatting churn as its own commit, separate from logic.

**Files:**
- Modify: any files ruff reformats (formatting only — no logic changes)

- [ ] **Step 1: Confirm the lint diff is acceptable before formatting**

Run: `uv run --group test ruff check .`
Expected: review the findings. Any **new** lint errors (beyond line-length/whitespace that the formatter will fix) must be triaged here — fix genuine issues, or if a rule is too aggressive vs. the old flake8 set, reconcile by adjusting `[tool.ruff.lint] ignore` (document why). Do not blanket-ignore real findings.

- [ ] **Step 2: Apply the formatter**

Run: `uv run --group test ruff format .`
Expected: reports the number of reformatted files. The diff should be modest (ruff format is black-compatible at line-length 120).

- [ ] **Step 3: Apply safe lint autofixes**

Run: `uv run --group test ruff check --fix .`
Expected: applies import/whitespace fixes; re-run `ruff check .` and confirm it now passes.

- [ ] **Step 4: Verify formatting check and tests are green**

Run: `uv run --group test ruff format --check . && uv run --group test ruff check .`
Expected: both pass with no output / "All checks passed".

Run: `uv run --group test pytest -q`
Expected: still passes (formatting must not change behavior).

- [ ] **Step 5: Commit (formatting isolated)**

```bash
git add -A
git commit -m "style: apply ruff format and lint fixes"
```

---

## Task 3: Rename `scripts/temporary-rename` → `scripts/prepare-build`; delete `scripts/build-image`

**Files:**
- Rename: `scripts/temporary-rename` → `scripts/prepare-build`
- Delete: `scripts/build-image`

**Interfaces:**
- Produces: `scripts/prepare-build` — a uv inline-script that, when `PACKAGE_NAME` is set, rewrites `[project].name` in `pyproject.toml`. Invoked by `just dist` and the `distributions` CI job. Runs only in disposable CI checkouts.

- [ ] **Step 1: Rename the script**

```bash
git mv scripts/temporary-rename scripts/prepare-build
```

- [ ] **Step 2: Delete the Docker image build script**

```bash
git rm scripts/build-image
```

- [ ] **Step 3: Verify `prepare-build` still runs and is a no-op without PACKAGE_NAME**

Run: `./scripts/prepare-build && git diff --quiet pyproject.toml && echo "unchanged"`
Expected: `unchanged` (no `PACKAGE_NAME` set → script leaves `pyproject.toml` alone).

- [ ] **Step 4: Verify the rename path works (in a throwaway check)**

Run: `cp pyproject.toml /tmp/pyproject.bak && PACKAGE_NAME=rsconnect ./scripts/prepare-build && grep '^name = ' pyproject.toml`
Expected: `name = "rsconnect"`.

Restore: `mv /tmp/pyproject.bak pyproject.toml`
Expected: working tree clean again (`git diff --quiet pyproject.toml`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: rename build prep script, drop docker image script"
```

---

## Task 4: Add `Justfile`; delete `Makefile`, `Dockerfile`, `docs/Dockerfile`, `setup.py`

**Files:**
- Create: `Justfile`
- Delete: `Makefile`, `Dockerfile`, `docs/Dockerfile`, `setup.py`

**Interfaces:**
- Consumes: dependency groups `test`/`docs` (Task 1), `scripts/prepare-build` (Task 3), `scripts/runtests`.
- Produces: recipes `test`, `all-tests`, `lint`, `fmt`, `dist`, `install`, `docs`, `docs-serve`, `version`, `clean`, `clean-stores`, `dev`, `dev-stop`, `sync-latest-docs-to-s3`, `promote-docs-in-s3` (consumed by CI in Tasks 5–6).

- [ ] **Step 1: Create the `Justfile`**

```just
# rsconnect-python task runner. Run `just --list` to see recipes.

python_versions := "3.8 3.9 3.10 3.11 3.12 3.13"

# Run the test suite against a single Python version (default 3.13)
test py="3.13":
    uv run --python {{py}} --group test ./scripts/runtests

# Run the test suite against all supported Python versions
all-tests:
    #!/usr/bin/env bash
    set -euo pipefail
    for v in {{python_versions}}; do
        echo "== Python $v =="
        uv run --python "$v" --group test ./scripts/runtests
    done

# Check formatting and lint (pyright is advisory / non-blocking)
lint:
    uv run --group test ruff format --check .
    uv run --group test ruff check .
    -uv run --group test pyright rsconnect/

# Auto-format and apply lint fixes
fmt:
    uv run --group test ruff format .
    uv run --group test ruff check --fix .

# Build wheel + sdist for the current PACKAGE_NAME and validate them
dist:
    ./scripts/prepare-build
    uv build
    uv run --group test twine check dist/*

# Install the most recently built wheel into the active environment
install:
    uv pip install dist/*.whl

# Print the current version
version:
    uv version --short

# Build the documentation site
docs:
    VERSION=$(uv version --short) uv run --group docs mkdocs build

# Serve the documentation with live reload
docs-serve:
    VERSION=$(uv version --short) uv run --group docs mkdocs serve

# Remove build/test artifacts
clean:
    rm -rf .coverage .pytest_cache build dist htmlcov rsconnect_python.egg-info rsconnect.egg-info site

# Remove local rsconnect store directories
clean-stores:
    #!/usr/bin/env bash
    set -euo pipefail
    find . -name "rsconnect-python" -o -name "rsconnect_python-*" -o -name "rsconnect-*" | xargs rm -rf

# Start a local Connect server for development (Docker; not replaced by uv)
dev:
    docker compose up -d
    sleep 30
    docker compose exec -T rsconnect bash < vetiver-testing/setup-rsconnect/add-users.sh
    uv run python vetiver-testing/setup-rsconnect/dump_api_keys.py vetiver-testing/rsconnect_api_keys.json

# Stop the local Connect server
dev-stop:
    docker compose down
    rm -f vetiver-testing/rsconnect_api_keys.json

# Sync latest docs to S3 (CI)
sync-latest-docs-to-s3:
    aws s3 sync --acl bucket-owner-full-control --cache-control max-age=0 site/ s3://rstudio-connect-downloads/connect/rsconnect-python/latest/docs/

# Promote docs in S3 (CI)
promote-docs-in-s3:
    aws s3 sync --delete --acl bucket-owner-full-control --cache-control max-age=300 site/ s3://docs.rstudio.com/rsconnect-python/
```

- [ ] **Step 2: Delete the Makefile and dead Docker/build files**

```bash
git rm Makefile Dockerfile docs/Dockerfile setup.py
```

- [ ] **Step 3: Verify recipes resolve and lint works**

Run: `just --list`
Expected: lists every recipe above without parse errors.

Run: `just lint`
Expected: ruff format-check and check pass; pyright runs and, even if it reports findings, does **not** fail the recipe (advisory `-` prefix). The recipe exits 0.

- [ ] **Step 4: Verify the test recipe runs on a single version**

Run: `just test 3.12`
Expected: uv fetches Python 3.12 if needed and the suite passes.

- [ ] **Step 5: Verify the dist recipe builds and validates**

Run: `just clean && just dist`
Expected: builds wheel + sdist into `dist/` and `twine check` reports `PASSED` for both.

- [ ] **Step 6: Commit**

```bash
git add Justfile
git add -A
git commit -m "build: replace Makefile with Justfile; remove docker/setuptools build files"
```

---

## Task 5: Update `.github/workflows/main.yml`

Audit **every** `make ` invocation, not just `make test-X`. Replace `actions/setup-python`+`pip` with `astral-sh/setup-uv`+`just`. Keep the Connect-server Docker in the integration jobs, but do not run `uv`/`just` *inside* `with-connect` (pre-sync on the runner, run `pytest` directly there).

**Files:**
- Modify: `.github/workflows/main.yml`

**Interfaces:**
- Consumes: `just` recipes (Task 4), dependency group `test`, `scripts/prepare-build`, `scripts/runtests`.

- [ ] **Step 1: Replace `.github/workflows/main.yml` with the migrated workflow**

```yaml
name: main
on:
  push:
    branches: [main]
    tags: ['*']
  schedule:
  - cron: "0 09 * * *" # Runs 11 AM UTC == 2 AM PDT
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  id-token: write
  contents: write
  pull-requests: write

jobs:
  test-python-versions:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest]
        python-version: ['3.8', '3.9', '3.10', '3.11', '3.12', '3.13']
        include:
        - os: macos-latest
          python-version: '3.13'
        - os: windows-latest
          python-version: '3.13'
    runs-on: ${{ matrix.os }}
    name: test (py${{ matrix.python-version }} ${{ matrix.os }})
    steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - uses: astral-sh/setup-uv@v6
      with:
        version: ">=0.9.0"
    - uses: extractions/setup-just@v3
    # Fail fast if uv.lock has drifted from pyproject.toml.
    - run: uv lock --locked
    - run: just lint
    - run: uv run --python ${{ matrix.python-version }} --group test rsconnect version
    - run: just test ${{ matrix.python-version }}
    - if: github.event_name == 'pull_request' && matrix.python-version == '3.8'
      uses: orgoro/coverage@v3
      with:
        coverageFile: coverage.xml
        token: ${{ secrets.GITHUB_TOKEN }}

  prerelease-test:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - uses: astral-sh/setup-uv@v6
      with:
        version: ">=0.9.0"
    - uses: extractions/setup-just@v3
    - run: just lint
    # --upgrade forces a fresh resolve (ignoring the lock) so prereleases are
    # actually exercised; plain `--prerelease allow` against the lock is a no-op.
    - run: uv run --upgrade --prerelease allow --group test rsconnect version
    - run: uv run --python 3.8 --upgrade --prerelease allow --group test ./scripts/runtests

  distributions:
    needs: test-python-versions
    strategy:
      matrix:
        package_name: ["rsconnect_python", "rsconnect"]
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - uses: astral-sh/setup-uv@v6
      with:
        version: ">=0.9.0"
    - uses: extractions/setup-just@v3
    - run: uv sync --group test
    - name: assert tag matches pyproject version
      if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags')
      run: |
        tag="${GITHUB_REF_NAME}"
        ver="$(uv version --short)"
        if [ "$tag" != "$ver" ]; then
          echo "::error::tag '$tag' does not match pyproject version '$ver'"
          exit 1
        fi
    - run: just dist
      env:
        PACKAGE_NAME: ${{ matrix.package_name }}
    - name: smoke test the built wheel
      run: |
        WHL=$(ls dist/*.whl | head -1)
        uv run --no-project --with "$WHL" rsconnect version
        uv run --no-project --with "$WHL" rsconnect --help
    - name: create github release
      uses: softprops/action-gh-release@v2
      if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags') && matrix.package_name == 'rsconnect_python'
      with:
        files: |
          dist/*.whl
        token: ${{ secrets.GITHUB_TOKEN }}
    - if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags')
      uses: pypa/gh-action-pypi-publish@release/v1

  docs:
    needs: test-python-versions
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v6
      with:
        fetch-depth: 0
    - uses: astral-sh/setup-uv@v6
      with:
        version: ">=0.9.0"
    - uses: extractions/setup-just@v3
    - name: build docs
      run: just docs
    - uses: actions/upload-artifact@v5
      with:
        name: docs
        path: site/
    - uses: aws-actions/configure-aws-credentials@v4
      id: creds
      with:
        role-to-assume: ${{ secrets.AWS_ROLE_TO_ASSUME }}
        aws-region: ${{ secrets.AWS_REGION }}
    - if: github.event_name == 'push' && github.ref == 'refs/heads/main'
      run: just sync-latest-docs-to-s3
    - if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags')
      uses: aws-actions/configure-aws-credentials@v4
      with:
        role-to-assume: ${{ secrets.DOCS_AWS_ROLE }}
        aws-region: us-east-1
    - if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags')
      run: just promote-docs-in-s3

  test-connect-versions:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        version:
          - "preview"   # nightly pre-release build of Connect
          - "release"   # special value that always points to the latest Connect release
          - "2025.09.0" # jammy
          - "2025.03.0" # jammy
          - "2024.09.0" # jammy
          - "2024.03.0" # jammy
          - "2023.09.0" # jammy
          - "2023.03.0" # bionic
          - "2022.10.0" # bionic
    name: Integration tests against Connect ${{ matrix.version }}
    env:
      python-version: '3.13'
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v6
        with:
          version: ">=0.9.0"
      # Prepare the environment on the runner BEFORE entering with-connect, so
      # no build/resolve/interpreter-fetch happens over the network mid-test.
      - run: uv sync --python ${{ env.python-version }} --group test
      - run: uv run --no-sync rsconnect version
      - name: Run integration tests
        uses: posit-dev/with-connect@main
        with:
          version: ${{ matrix.version }}
          # License file valid until 2026-12-05
          license: ${{ secrets.CONNECT_LICENSE_FILE }}
          command: |
            uv run --no-sync --group test ./scripts/runtests

  test-dev-connect:
    name: "Integration tests against dev Connect"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v6
        with:
          version: ">=0.9.0"
      - uses: extractions/setup-just@v3
      - name: Install dependencies
        run: |
          uv sync --python 3.12 --group test
          uv pip install -r vetiver-testing/vetiver-requirements.txt
      - name: Run Posit Connect
        run: |
          docker compose up --build -d
          uv pip freeze > requirements.txt
          just dev
        env:
          RSC_LICENSE: ${{ secrets.RSC_LICENSE }}
          GITHUB_TOKEN: ${{secrets.GITHUB_TOKEN}}
      - name: Get logs in case of failure
        run: |
          docker compose logs rsconnect
        if: ${{ failure() }}
      - name: Run tests
        run: |
          uv run --no-sync pytest tests/test_main_system_caches.py
          uv run --no-sync pytest -m 'vetiver'
```

- [ ] **Step 2: Validate the workflow YAML parses**

Run: `uv run --no-project --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/main.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Confirm no `make` references remain**

Run: `grep -n "make " .github/workflows/main.yml; echo "exit:$?"`
Expected: no matches, `exit:1`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/main.yml
git commit -m "ci: run main workflow on uv + just"
```

---

## Task 6: Update `.github/workflows/preview-docs.yml`

**Files:**
- Modify: `.github/workflows/preview-docs.yml`

- [ ] **Step 1: Replace the workflow**

```yaml
name: preview docs

on:
  pull_request:
    types:
      - opened
      - reopened
      - synchronize
      - closed
  workflow_dispatch:

concurrency: preview-${{ github.ref }}

jobs:
  deploy-preview:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          version: ">=0.9.0"

      - uses: extractions/setup-just@v3

      - name: Install and Build
        if: github.event.action != 'closed' # skip the build if the PR has been closed
        run: just docs

      - name: Deploy preview
        uses: rossjrw/pr-preview-action@v1
        with:
          source-dir: ./site/
```

- [ ] **Step 2: Validate YAML and confirm no pip/setup-python**

Run: `uv run --no-project --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/preview-docs.yml')); print('ok')"`
Expected: `ok`.

Run: `grep -nE "setup-python|pip install" .github/workflows/preview-docs.yml; echo "exit:$?"`
Expected: no matches, `exit:1`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/preview-docs.yml
git commit -m "ci: build doc previews with uv + just"
```

---

## Task 7: Update contributor & release documentation

**Files:**
- Modify: `CONTRIBUTING.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the dev-setup block in `CONTRIBUTING.md`**

Replace lines 13–29 (the `venv` example ending in `pip install -e '.[test]'`) with:

````markdown
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
````

- [ ] **Step 2: Rewrite the Linting and Testing sections in `CONTRIBUTING.md`**

Replace lines 35–74 (from `### Linting` through the `unset CONNECT_SERVER CONNECT_API_KEY` block) with:

````markdown
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
````

(The old `#774` note about pyright being suppressed "in the Makefile" is dropped; pyright is advisory in `just lint` instead.)

- [ ] **Step 3: Rewrite the "Versioning and Releasing" section in `CONTRIBUTING.md`**

Replace lines 90–115 (from `## Versioning and Releasing` through the PEP 440 NOTE) with:

````markdown
## Versioning and Releasing

The version is a static field in `pyproject.toml`, managed with
[`uv version`](https://docs.astral.sh/uv/guides/package/#updating-your-version).
`main` always carries a `.dev` version (e.g. `1.29.1.dev0`) so development
builds are marked as pre-releases and never collide with a published release.

### Update CHANGELOG.md

Before releasing, replace the `Unreleased` heading in CHANGELOG.md with the
version number and date. Update CHANGELOG.md before _EACH_ release, even beta
releases.

### Tagging a Release

```bash
# Drop the .dev suffix to cut the release (e.g. 1.29.1.dev0 -> 1.29.1)
uv version --bump stable
git commit -am 'Release 1.29.1'
git tag -a 1.29.1 -m 'Release 1.29.1'
git push origin main 1.29.1
```

On a tag push, the `distributions` job asserts the tag equals the
`pyproject.toml` version, builds `rsconnect_python` and `rsconnect`, and
publishes to [PyPI](https://pypi.org/project/rsconnect-python/#history) and the
GitHub releases page. After releasing, re-arm development on `main`:

```bash
uv version 1.29.2.dev0
git commit -am 'Begin 1.29.2 development'
git push origin main
```

> **NOTE**: Pre-release versions must comply with [PEP 440](https://www.python.org/dev/peps/pep-0440/) so PyPI marks them as pre-releases. `uv version`'s `dev`/`alpha`/`beta`/`rc` bumps produce compliant strings.
````

- [ ] **Step 4: Update `CLAUDE.md` development commands**

In `CLAUDE.md`, replace the "Environment Setup", "Testing", "Linting and Formatting", "Documentation", and "Building Distribution" command blocks so they use `uv`/`just` (e.g. `uv sync --group test`, `just test`, `just test 3.12`, `just all-tests`, `just lint`, `just fmt`, `just docs`, `just docs-serve`, `just dist`, `just install`). Replace the entire "## Releasing" section with:

````markdown
## Releasing

- Version is a static field in `pyproject.toml`, managed with `uv version`.
- `main` carries a `.dev` version (e.g. `1.29.1.dev0`).
- Update CHANGELOG.md before each release (even betas).
- Cut a release: `uv version --bump stable`, commit, `git tag -a 1.2.3 -m 'Release 1.2.3'`, push the tag.
- The `distributions` CI job asserts the tag matches the `pyproject.toml` version, then builds and publishes to PyPI.
- After releasing, bump `main` back to the next `.dev` version with `uv version <next>.dev0`.
````

Also update the "Code Style" section's references to `black`/`flake8` to read `ruff` (format + check) and note pyright is advisory.

- [ ] **Step 5: Verify no stale tool references remain in the docs**

Run: `grep -nE "setuptools_scm|\bblack\b|flake8|make (test|lint|fmt|docs|dist|all-tests)" CONTRIBUTING.md CLAUDE.md; echo "exit:$?"`
Expected: no matches, `exit:1`.

- [ ] **Step 6: Commit**

```bash
git add CONTRIBUTING.md CLAUDE.md
git commit -m "docs: update contributor and release docs for uv/just/ruff"
```

---

## Final verification (run after all tasks)

- [ ] `just lint` passes (ruff enforced, pyright advisory).
- [ ] `just test 3.8` and `just test 3.13` pass.
- [ ] `just clean && just dist` builds wheel + sdist; `unzip -l dist/*.whl` contains `rsconnect/py.typed` and `rsconnect/quickstart/templates/**`, and excludes `tests/`/`conftest.py`.
- [ ] `uv run --no-project --with dist/*.whl rsconnect version` prints `1.29.1.dev0`.
- [ ] `grep -rnE "setuptools_scm|flake8|\bblack\b" pyproject.toml Makefile 2>/dev/null` finds nothing (Makefile is gone; pyproject is clean).
- [ ] No `Dockerfile`, `docs/Dockerfile`, `Makefile`, `setup.py`, or `rsconnect/version.py` remain; `docker-compose.yml`, `vetiver-testing/`, `integration-testing/`, and `requirements.txt` are untouched.
- [ ] `git grep -n "make " -- .github/workflows` returns nothing.

## Deferred follow-ups (NOT in this plan)
- Make `pyright` blocking in CI once findings reach zero.
- Reconcile the three `requirements.txt` writers / integration-suite overhaul (`#649`).
