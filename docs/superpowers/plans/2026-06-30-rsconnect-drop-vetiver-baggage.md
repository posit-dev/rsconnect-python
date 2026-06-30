# rsconnect-python: drop vetiver test baggage, adopt with-connect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all *vetiver-specific* test code from rsconnect-python, re-home its own `system caches` integration test onto `posit-dev/with-connect`, and relabel the `deploy_python_fastapi` compatibility shim instead of removing it.

**Architecture:** `with-connect` boots a licensed Connect container and (in start-only mode) yields an admin API key + the container id. rsconnect's only Connect integration test (`test_main_system_caches.py`) asserts an admin can list/delete caches and a **non-admin publisher is denied (403)**, so it genuinely needs two privilege levels. Since Connect has no public "admin mints another user's key" endpoint, we keep a **minimal** Connect test bootstrap — a password-auth `gcfg` passed via the Action's `config-file` input, a `useradd` of one publisher inside the container, and a small helper that mints that publisher's key via Connect's signup/session flow. This replaces the old `docker-compose` + multi-user `vetiver-testing/` harness with `with-connect` + a slim, de-vetivered config. The vetiver↔Connect tests move entirely to the vetiver repo.

**Tech Stack:** Python, pytest, Click, Docker, `uv`, GitHub Actions, `just`.

## Global Constraints

- Pin `with-connect` to commit `0783dabdd24e360e985a4588ce1239c3dc31c542` (no release tags exist yet). Verify at execution time with `gh api repos/posit-dev/with-connect/commits/main -q .sha`.
- **Confirmed `with-connect` Action API** (verified against `action.yml@main`): inputs include `license`, `version`, `config-file`, `env`, `command`, `stop`; in **start-only** mode (no `command`) it sets outputs `CONNECT_SERVER`, `CONNECT_API_KEY`, `CONTAINER_ID`. The `system caches` job uses start-only mode and runs `pytest` as a normal `uv run` step (so the "`pytest` not found inside a wrapped `with-connect -- pytest`" gotcha does not apply here).
- The container runs via plain `docker` (no `docker compose`). Cache-dir setup uses `docker exec <CONTAINER_ID> ...`, not `docker compose exec`.
- The `actions.py` shim (`deploy_python_fastapi` → `deploy_app` → `validate_*`, lines ~281–442) is **kept**. Do not delete it. Do not alter the active `validate_*` in `bundle.py`.
- `pins` is **not** a dependency of rsconnect-python. The old key-mint used `pins.rsconnect.api._HackyConnect`. The publisher-key helper here should prefer a small self-contained raw-HTTP reproduction; only if that proves too fiddly, add `pins` as a **test-only** dependency (Task 1 decides).
- A valid `rstudio-connect.lic` must be present in the repo root for local runs; CI passes it via the `RSC_LICENSE` secret.
- Keep CI green at every commit: re-home `test_main_system_caches.py` and stand up its new CI job (Tasks 1–3) **before** deleting `vetiver-testing/` (Task 5).

---

### Task 1: Spike — gcfg + JWT-bootstrap coexistence and publisher-key minting

Discovery task (no production commit). Resolve, against a live `with-connect` Connect, the exact mechanism the dependent tasks consume. Record findings in the task notes; Tasks 2–3 are written against them.

**Files:**
- Create (temporary, for the spike only): `scratch/` artifacts you delete at the end. A candidate `tests/connect/rstudio-connect.gcfg` you iterate on (kept if it works — see Task 2).

Base the candidate gcfg on the old `vetiver-testing/setup-rsconnect/rstudio-connect.gcfg` but **drop the `[Python]` section** (its image-specific executable paths won't match the with-connect image, and the system-caches test runs no Python content). Keep PAM auth and `DefaultUserRole = publisher`:

```ini
[Server]
DataDir = /data
Address = http://localhost:3939

[HTTP]
Listen = :3939

[Authentication]
Provider = pam

[Authorization]
DefaultUserRole = publisher

[Logging]
ServiceLog = STDOUT
```

- [ ] **Step 1: Confirm with-connect's JWT bootstrap coexists with the PAM gcfg**

Start Connect with the candidate config (start-only). Use the CLI's `--config` (the CLI equivalent of the Action's `config-file`):
```bash
eval "$(uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --config tests/connect/rstudio-connect.gcfg)"
echo "server=$CONNECT_SERVER key set=${CONNECT_API_KEY:+yes}"
CID=$(docker ps --format '{{.ID}}' --filter status=running | head -1); echo "container=$CID"
curl -fsS -H "Authorization: Key $CONNECT_API_KEY" "$CONNECT_SERVER/__api__/v1/user" && echo OK
```
Expected: with-connect still bootstraps an admin key (its JWT bootstrap is provider-independent) and the admin `GET /v1/user` returns 200. If bootstrap fails under PAM auth, record that — it means the gcfg must also keep whatever provider with-connect's default uses; iterate the gcfg minimally until both bootstrap and PAM login work.

- [ ] **Step 2: Create the publisher PAM user inside the container**

```bash
docker exec -u root "$CID" bash -lc 'useradd -m -s /bin/bash susan && echo "susan:susan" | chpasswd && id susan'
```
Expected: prints `uid=...(susan)`. (If `-u root` or `useradd` is unavailable on the with-connect image, record the correct path — e.g. a different base image user or a pre-seeded user via the gcfg.)

- [ ] **Step 3: Mint susan's API key (the crux)**

First try a **raw-HTTP** reproduction of the old `_HackyConnect` flow (login as susan via the password provider, then create an API key through the session), e.g. probing:
```bash
# Inspect the login + key-create endpoints the web UI uses:
curl -i -X POST "$CONNECT_SERVER/__login__" -H 'Content-Type: application/json' -d '{"username":"susan","password":"susan"}'
# then, with the returned session cookie, POST to the api-keys creation endpoint
```
Record the exact endpoints, payloads, and cookie handling that yield a working publisher key (verify by calling `GET /v1/user` with it and seeing a non-admin role). If reproducing the session/login flow proves too fiddly to be maintainable, fall back to adding `pins` as a **test-only** dependency and reusing `pins.rsconnect.api._HackyConnect` (which the old `dump_api_keys.py` used). Decide and record which approach Task 2 will implement.

- [ ] **Step 4: Confirm cache-dir manipulation via `docker exec`**

```bash
docker exec -u rstudio-connect "$CID" mkdir -p /data/python-environments/_packages_cache/pip/1.2.3
docker exec -u rstudio-connect "$CID" sh -c '[ -d /data/python-environments/_packages_cache/pip/1.2.3 ] && echo CACHE_OK'
```
Expected: prints `CACHE_OK`. Record the correct exec user if `rstudio-connect` is wrong for this image.

- [ ] **Step 5: Tear down**

```bash
uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --stop "$CID"
```
Keep the working `tests/connect/rstudio-connect.gcfg`; delete any other scratch. **No production commit** — write the resolved mechanism (gcfg contents, useradd command, exact key-mint approach, exec user) into the task notes for Tasks 2–3.

---

### Task 2: Re-home `test_main_system_caches.py` onto env creds + a publisher fixture

**Files:**
- Modify: `tests/test_main_system_caches.py`
- Create: `tests/connect/rstudio-connect.gcfg` (the validated gcfg from Task 1)
- Create: `tests/connect/bootstrap.py` (publisher useradd + key-mint helper), OR add `pins` as a test-only dep in `pyproject.toml` if Task 1 chose that fallback.

**Interfaces:**
- Consumes (from env): `CONNECT_SERVER`, `CONNECT_API_KEY` (admin), `CONNECT_CONTAINER` (container id).
- Consumes (from Task 1): the validated gcfg, the useradd command, and the exact publisher-key-mint mechanism + exec user.
- Produces: a `publisher_key` fixture; no dependency on `vetiver-testing/rsconnect_api_keys.json` or `docker compose`.

- [ ] **Step 1: Add the key-mint helper**

Create `tests/connect/bootstrap.py` implementing `make_publisher_key(server_url, container_id) -> str` using the EXACT mechanism Task 1 validated: `docker exec` the `useradd` for `susan`, then mint and return her API key (raw-HTTP session flow, or `_HackyConnect` if that was the chosen fallback). Keep it small and self-contained.

- [ ] **Step 2: Rewrite the module header of `tests/test_main_system_caches.py`**

Replace lines 1–47 (imports through `apply_common_args`) with creds-from-env + `docker exec <CONTAINER_ID>` cache commands + the publisher fixture wiring:

```python
import os
import unittest
from os import system

from click.testing import CliRunner

from rsconnect.main import cli
from tests.connect.bootstrap import make_publisher_key

CONNECT_SERVER = os.environ.get("CONNECT_SERVER", "http://localhost:3939")
ADMIN_KEY = os.environ.get("CONNECT_API_KEY")
CONTAINER = os.environ.get("CONNECT_CONTAINER", "")
CONNECT_CACHE_DIR = "/data/python-environments/_packages_cache"

_EXEC = f"docker exec -u rstudio-connect {CONTAINER}"
ADD_CACHE_COMMAND = f"{_EXEC} mkdir -p {CONNECT_CACHE_DIR}/pip/1.2.3"
RM_CACHE_COMMAND = f"{_EXEC} rm -Rf {CONNECT_CACHE_DIR}/pip/1.2.3"
CACHE_EXISTS_COMMAND = f"{_EXEC} sh -c '[ -d {CONNECT_CACHE_DIR}/pip/1.2.3 ]'"


def rsconnect_service_running():
    if not CONTAINER:
        return False
    return system(f"docker inspect -f '{{{{.State.Running}}}}' {CONTAINER}") == 0


def cache_dir_exists():
    return system(CACHE_EXISTS_COMMAND) == 0


PUBLISHER_KEY = (
    make_publisher_key(CONNECT_SERVER, CONTAINER) if (ADMIN_KEY and CONTAINER) else None
)


def apply_common_args(args: list, server=None, key=None, insecure=True):
    if server:
        args.extend(["-s", server])
    if key:
        args.extend(["-k", key])
    if insecure:
        args.extend(["--insecure"])
```

> Use `-u rstudio-connect`/exec user exactly as Task 1 confirmed. If Task 1 found minting must happen lazily (not at import), move the `make_publisher_key` call into a module-scoped pytest fixture instead of a module constant.

- [ ] **Step 3: Swap the key lookups in the test bodies**

Replace each `get_key("admin")` with `ADMIN_KEY` and each `get_key("susan")` with `PUBLISHER_KEY` (lines ~67, 82, 109, 122, 137). Delete the old `get_key`, `CONNECT_KEYS_JSON`, and `SERVICE_RUNNING_COMMAND`.

- [ ] **Step 4: Verify locally under with-connect start-only mode**

```bash
eval "$(uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --config tests/connect/rstudio-connect.gcfg)"
export CONNECT_CONTAINER="$(docker ps --format '{{.ID}}' --filter status=running | head -1)"
uv run --no-sync pytest tests/test_main_system_caches.py -v
uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --stop "$CONNECT_CONTAINER"
```
Expected: PASS — admin list/delete exit 0; publisher list/delete exit 1 with "You don't have permission to perform this operation."

- [ ] **Step 5: Commit**

```bash
git add tests/test_main_system_caches.py tests/connect/rstudio-connect.gcfg tests/connect/bootstrap.py
git commit -m "test: run system-caches integration test via with-connect with a slim publisher bootstrap"
```

---

### Task 3: Replace the `test-dev-connect` CI job with an rsconnect-own with-connect job

**Files:**
- Modify: `.github/workflows/main.yml` (the `test-dev-connect` job, lines ~183–211)

**Interfaces:**
- Consumes: `secrets.RSC_LICENSE`; the refactored `test_main_system_caches.py` + `tests/connect/` from Task 2.
- Produces: a job running only rsconnect's own integration test, no vetiver install, no `docker compose`/`just dev`.

- [ ] **Step 1: Replace the entire `test-dev-connect` job**

```yaml
  test-system-caches:
    name: "Integration tests against dev Connect"
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v6
        with:
          version: ">=0.9.0"
      - name: Install dependencies
        run: uv sync --python 3.12 --group test
      - name: Start Connect
        id: connect
        uses: posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542
        with:
          license: ${{ secrets.RSC_LICENSE }}
          config-file: tests/connect/rstudio-connect.gcfg
      - name: Run system caches tests
        run: uv run --no-sync pytest tests/test_main_system_caches.py
        env:
          CONNECT_SERVER: ${{ steps.connect.outputs.CONNECT_SERVER }}
          CONNECT_API_KEY: ${{ steps.connect.outputs.CONNECT_API_KEY }}
          CONNECT_CONTAINER: ${{ steps.connect.outputs.CONTAINER_ID }}
      - name: Get logs on failure
        if: ${{ failure() }}
        run: docker logs ${{ steps.connect.outputs.CONTAINER_ID }}
      - name: Stop Connect
        if: always()
        uses: posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542
        with:
          license: ${{ secrets.RSC_LICENSE }}
          stop: ${{ steps.connect.outputs.CONTAINER_ID }}
```

> The publisher `useradd` runs inside `make_publisher_key` (Task 2) via `docker exec`, so no separate CI step is needed for it. If Task 1 found `useradd` must run as a distinct step (e.g. timing/permissions), add a `docker exec` step between Start and the test, using `${{ steps.connect.outputs.CONTAINER_ID }}`.

- [ ] **Step 2: Lint the workflow YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/main.yml'))"`
Expected: no output (valid YAML).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/main.yml
git commit -m "ci: run system-caches integration test via with-connect; drop vetiver job"
```

---

### Task 4: Remove the `--vetiver` marker plumbing and the vetiver test

**Files:**
- Modify: `conftest.py`
- Delete: `tests/test_vetiver_pins.py`
- Modify: `pyproject.toml` (markers + ruff exclude)

- [ ] **Step 1: Remove the vetiver option/marker logic from `conftest.py`**

Delete these three functions from `conftest.py`:

```python
def pytest_addoption(parser):
    parser.addoption("--vetiver", action="store_true", default=False, help="run vetiver tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "vetiver: test for vetiver interaction")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--vetiver"):
        return
    skip_vetiver = pytest.mark.skip(reason="need --vetiver option to run")
    for item in items:
        if "vetiver" in item.keywords:
            item.add_marker(skip_vetiver)
```

The remaining `conftest.py` keeps the `CONNECT_CONTENT_BUILD_DIR` setup. The `import pytest` line is now unused — remove it too.

- [ ] **Step 2: Delete the vetiver integration test**

Run: `git rm tests/test_vetiver_pins.py`

- [ ] **Step 3: Remove the `vetiver` marker and the `vetiver-testing` ruff exclude from `pyproject.toml`**

Change line ~74:

```toml
markers = ["vetiver: tests for vetiver"]
```

to an empty list if it becomes empty:

```toml
markers = []
```

And in the ruff `extend-exclude` (line ~63), drop `"vetiver-testing"`:

```toml
extend-exclude = ["my-shiny-app", "rsconnect-build", "rsconnect-build-test", "integration", "tests/testdata"]
```

- [ ] **Step 4: Verify collection has no orphaned marker references**

Run: `uv run pytest --collect-only -q 2>&1 | tail -5`
Expected: collection succeeds with no `PytestUnknownMarkWarning: vetiver` and no error about a missing `--vetiver` option.

- [ ] **Step 5: Commit**

```bash
git add conftest.py pyproject.toml
git commit -m "test: drop --vetiver marker plumbing and test_vetiver_pins"
```

---

### Task 5: Delete the bespoke vetiver harness (vetiver-testing, docker-compose, Justfile dev recipes)

**Files:**
- Delete: `vetiver-testing/` (entire directory)
- Delete: `docker-compose.yml` (root)
- Modify: `Justfile` (remove `dev` and `dev-stop` recipes)

> The de-vetivered `tests/connect/` gcfg + helper from Task 2 are the replacement; this task removes only the old vetiver-named harness.

- [ ] **Step 1: Confirm nothing still references these paths**

Run:
```bash
grep -rn "vetiver-testing\|rsconnect_api_keys\|docker compose\|docker-compose" \
  --include='*.py' --include='*.yml' --include='*.yaml' Justfile conftest.py . \
  | grep -v 'docs/superpowers' | grep -v 'integration-testing/'
```
Expected: no hits outside `docs/superpowers/` and the unrelated `integration-testing/` tree.

- [ ] **Step 2: Remove the `dev` and `dev-stop` recipes from `Justfile`**

Delete these two recipes:

```just
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
```

- [ ] **Step 3: Delete the directories**

```bash
git rm -r vetiver-testing
git rm docker-compose.yml
```

- [ ] **Step 4: Verify the unit suite and `just` recipes are intact**

Run: `just --list`
Expected: lists recipes with no `dev`/`dev-stop`, no parse error.

Run: `uv run pytest -q -k "not system_caches"`
Expected: PASS (the offline unit suite is unaffected).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove vetiver test harness and root docker-compose"
```

---

### Task 6: Relabel the `actions.py` compatibility shim

**Files:**
- Modify: `rsconnect/actions.py` (comment block markers at lines ~281–285 and ~441–442; optional `validate_*` swap)

**Interfaces:**
- Produces: no behavior change for callers; `deploy_python_fastapi`/`deploy_app` remain importable with identical signatures.

- [ ] **Step 1: Rewrite the opening block comment**

Replace lines ~281–285:

```python
# START: The following deprecated functions are here only for the vetiver-python
# package.
# Some the code in this section has `pyright: ignore` comments, because this
# deprecated code which will be removed in the future.
# ===============================================================================
```

with:

```python
# START: Compatibility entry point used by the vetiver-python package.
# vetiver's `deploy_connect` calls `deploy_python_fastapi` (below), which routes
# through `deploy_app` and the local `validate_*` helpers. This is a supported
# shim; keep these signatures stable. The `pyright: ignore` comments remain
# because the kwargs-forwarding style predates strict typing.
# ===============================================================================
```

- [ ] **Step 2: Rewrite the closing block comment**

Replace lines ~441–442:

```python
# ===============================================================================
# END deprecated functions for the vetiver-python package
# ===============================================================================
```

with:

```python
# ===============================================================================
# END compatibility entry point for the vetiver-python package
# ===============================================================================
```

- [ ] **Step 3 (optional cleanup): Stop emitting spurious deprecation warnings on vetiver deploys**

`deploy_app` calls the local `validate_entry_point`/`validate_extra_files`, which each emit a `DeprecationWarning`. Point it at the active `bundle.py` versions instead. At the top of `actions.py`, confirm/add:

```python
from .bundle import validate_entry_point as _validate_entry_point
from .bundle import validate_extra_files as _validate_extra_files
```

Then in `deploy_app` change lines ~361–362:

```python
    kwargs["entry_point"] = entry_point = validate_entry_point(entry_point, directory)  # pyright: ignore
    kwargs["extra_files"] = extra_files = validate_extra_files(directory, extra_files)  # pyright: ignore
```

to:

```python
    kwargs["entry_point"] = entry_point = _validate_entry_point(entry_point, directory)  # pyright: ignore
    kwargs["extra_files"] = extra_files = _validate_extra_files(directory, extra_files)  # pyright: ignore
```

Confirm the `bundle.py` signatures match: `validate_entry_point(entry_point, directory)` and `validate_extra_files(directory, extra_files)`. If `bundle.py`'s `validate_extra_files` requires an extra `use_abspath` argument, pass its default explicitly.

- [ ] **Step 4: Verify the shim still imports and lints**

```bash
uv run python -c "from rsconnect.actions import deploy_python_fastapi, deploy_app; print('ok')"
just lint
```
Expected: prints `ok`; `just lint` passes.

- [ ] **Step 5: Commit**

```bash
git add rsconnect/actions.py
git commit -m "docs: relabel deploy_python_fastapi as supported vetiver compat shim"
```

---

## Notes carried from the vetiver-python implementation

- The vetiver side is done (PR rstudio/vetiver-python#242). It confirmed `with-connect`'s default Connect (v2026.x) + current FastAPI/pydantic require a Content-Type header (fixed in vetiver), used `content_list()` (not `content_search`), and validated the Action's start-only outputs.
- This plan's branch is based on `uv-tooling-modernization` (its exact-block edits target that branch's `Justfile`/`main.yml`/`conftest.py`), not `main`.

## Self-Review notes

- Spec "rsconnect-python changes" → Task 1 (spike) + Task 2 (re-home test, gcfg+helper) + Task 3 (own CI job) cover keeping `test_main_system_caches.py`; Tasks 4–5 cover all deletions; Task 6 covers the relabel.
- The genuinely uncertain pieces (gcfg/JWT coexistence, publisher-key mint, exec user) are isolated to Task 1; Task 2/3 consume its validated outputs. No fabricated key-mint code is committed before the spike confirms it.
- Ordering keeps CI green: the system-caches test is re-homed + its CI job stood up (Tasks 2–3) before `vetiver-testing/` is deleted (Task 5).
- The shim is relabeled, never removed (Task 6); `bundle.py` validate functions untouched except as an explicit import in the optional cleanup.
- `with-connect` SHA `0783dabdd24e360e985a4588ce1239c3dc31c542` used identically across Tasks 1–3.
