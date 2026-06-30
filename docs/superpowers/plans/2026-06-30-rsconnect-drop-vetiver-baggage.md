# rsconnect-python: drop vetiver test baggage, adopt with-connect — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all vetiver-specific test code from rsconnect-python, re-home its own `system caches` integration test onto `posit-dev/with-connect`, and relabel the `deploy_python_fastapi` compatibility shim instead of removing it.

**Architecture:** `with-connect` boots a licensed Connect container and yields an admin API key. rsconnect's only Connect integration test (`test_main_system_caches.py`) needs two privilege levels, so a fixture creates a non-admin publisher user via the admin key at runtime; the cache-manipulation commands target the `with-connect` container by id. The vetiver↔Connect tests move entirely to the vetiver repo.

**Tech Stack:** Python, pytest, Click, Docker, `uv`/`uvx`, GitHub Actions, `just`.

## Global Constraints

- Pin `with-connect` to commit `0783dabdd24e360e985a4588ce1239c3dc31c542` (no release tags exist yet). Verify at execution time with `gh api repos/posit-dev/with-connect/commits/main -q .sha`.
- `with-connect` exposes only `CONNECT_SERVER` + `CONNECT_API_KEY` to a wrapped command; in **start-only** mode (no `command`) the Action also outputs `CONTAINER_ID`. The `system caches` test needs the container id, so it runs in start-only mode.
- The `actions.py` shim (`deploy_python_fastapi` → `deploy_app` → `validate_*`, lines ~281–442) is **kept**. Do not delete it. Do not alter the active `validate_*` in `bundle.py`.
- A valid `rstudio-connect.lic` must be present in the repo root for local runs; CI passes it via the `RSC_LICENSE` secret.
- Keep CI green at every commit: re-home `test_main_system_caches.py` (Tasks 1–3) **before** deleting `vetiver-testing/` (Task 5).

---

### Task 1: Spike — establish the with-connect publisher-user + container-exec mechanism

This is a discovery task. `test_main_system_caches.py` asserts that an **admin** can list/delete caches and a **non-admin publisher** is denied. `with-connect` only provides the admin key and runs a plain `docker` container (no `docker compose`). This task pins down, against a live `with-connect` Connect, exactly how to (a) create a publisher user + its API key from the admin key, and (b) run the cache-setup commands inside the container.

**Files:**
- Create (temporary): `scratch_spike.py` (deleted at end of task)

- [ ] **Step 1: Start Connect in start-only mode and capture the container id + creds**

Run:
```bash
eval "$(uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect)"
echo "server=$CONNECT_SERVER container=$(docker ps --filter ancestor --format '{{.ID}}' | head -1)"
docker ps --format '{{.ID}}\t{{.Image}}' | grep -i connect
```
Expected: `CONNECT_SERVER` and `CONNECT_API_KEY` are exported; one running Connect container is listed. Record its container id.

- [ ] **Step 2: Confirm cache-dir manipulation works via `docker exec` (not `docker compose exec`)**

Run (substitute the container id from Step 1 for `$CID`):
```bash
docker exec -u rstudio-connect -T $CID mkdir -p /data/python-environments/_packages_cache/pip/1.2.3
docker exec -u rstudio-connect -T $CID [ -d /data/python-environments/_packages_cache/pip/1.2.3 ] && echo "CACHE_OK"
```
Expected: prints `CACHE_OK`. (If `-u rstudio-connect` is rejected, record the correct user; the with-connect image may differ from `rstudio/rstudio-connect`.)

- [ ] **Step 3: Determine how to create a publisher user + API key from the admin key**

Write `scratch_spike.py` and try the rsconnect-native client first (no new deps):

```python
import os
from rsconnect.api import RSConnectServer, RSConnectClient

server = RSConnectServer(url=os.environ["CONNECT_SERVER"], api_key=os.environ["CONNECT_API_KEY"])
client = RSConnectClient(server)

# Probe: what does the admin identity look like, and can we create a user?
print("me:", client.me())
resp = client._server.handle_bad_response  # noqa  (inspect available methods)
print([m for m in dir(client) if "user" in m.lower() or "key" in m.lower()])
```

Run: `uvx --with . python scratch_spike.py`
Expected: prints the admin identity and the available user/key methods.

Decision point — pick the simplest mechanism that works against this Connect:
  1. **rsconnect client / raw REST**: `POST {server}/__api__/v1/users` to create a publisher, then mint a key. Verify the endpoint and key-creation route actually exist on this image.
  2. **Custom gcfg via the Action's `config-file`**: if API-driven user creation is not supported by with-connect's default auth provider, supply a minimal `rstudio-connect.gcfg` (password auth) plus a startup user, mirroring the old `vetiver-testing` setup but passed through `with-connect`'s `config-file` input.

Record the working approach (exact REST calls or the gcfg + the publisher key retrieval) in the task notes — Task 2 consumes it.

- [ ] **Step 4: Tear down and clean up**

Run:
```bash
uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --stop
rm -f scratch_spike.py
```
Expected: container stops; scratch file removed. **No commit** (spike produces notes only).

---

### Task 2: Refactor `test_main_system_caches.py` onto env creds + a publisher fixture

**Files:**
- Modify: `tests/test_main_system_caches.py`

**Interfaces:**
- Consumes (from env): `CONNECT_SERVER`, `CONNECT_API_KEY` (admin), `CONNECT_CONTAINER` (container id from with-connect start-only mode).
- Consumes (from Task 1): the verified publisher-user creation mechanism.
- Produces: a `publisher_key` fixture; no dependency on `vetiver-testing/rsconnect_api_keys.json` or `docker compose`.

- [ ] **Step 1: Replace the module header (creds, container ref, docker commands)**

Replace lines 1–47 (imports through `apply_common_args`) of `tests/test_main_system_caches.py` with:

```python
import os
import unittest
from os import system

from click.testing import CliRunner

from rsconnect.main import cli

CONNECT_SERVER = os.environ.get("CONNECT_SERVER", "http://localhost:3939")
ADMIN_KEY = os.environ.get("CONNECT_API_KEY")
CONTAINER = os.environ.get("CONNECT_CONTAINER", "")
CONNECT_CACHE_DIR = "/data/python-environments/_packages_cache"

_EXEC = f"docker exec -u rstudio-connect -T {CONTAINER}"
ADD_CACHE_COMMAND = f"{_EXEC} mkdir -p {CONNECT_CACHE_DIR}/pip/1.2.3"
RM_CACHE_COMMAND = f"{_EXEC} rm -Rf {CONNECT_CACHE_DIR}/pip/1.2.3"
# The following returns int(0) if dir exists, else nonzero.
CACHE_EXISTS_COMMAND = f"{_EXEC} [ -d {CONNECT_CACHE_DIR}/pip/1.2.3 ]"


def rsconnect_service_running():
    if not CONTAINER:
        return False
    return system(f"docker inspect -f '{{{{.State.Running}}}}' {CONTAINER}") == 0


def cache_dir_exists():
    return system(CACHE_EXISTS_COMMAND) == 0


def make_publisher_key():
    """Create a non-admin publisher user via the admin key and return its API key.

    Implementation comes from Task 1's verified mechanism. Replace the body below
    with the exact calls confirmed in the spike.
    """
    from rsconnect.api import RSConnectClient, RSConnectServer  # local import

    server = RSConnectServer(url=CONNECT_SERVER, api_key=ADMIN_KEY)
    client = RSConnectClient(server)
    # <-- insert the verified create-publisher-and-mint-key calls here -->
    raise NotImplementedError("fill from Task 1 spike result")


def apply_common_args(args: list, server=None, key=None, insecure=True):
    if server:
        args.extend(["-s", server])
    if key:
        args.extend(["-k", key])
    if insecure:
        args.extend(["--insecure"])
```

> Note: the `make_publisher_key` body is the single point that depends on the Task 1 spike. Everything else is final. Do not leave `NotImplementedError` in the committed version — Step 2 fills it.

- [ ] **Step 2: Fill `make_publisher_key` with the verified mechanism and add a module-level publisher key**

Using the approach confirmed in Task 1, implement `make_publisher_key()` so it returns a usable publisher API key, then add below `apply_common_args`:

```python
PUBLISHER_KEY = make_publisher_key() if ADMIN_KEY else None
```

Replace every `get_key("admin")` with `ADMIN_KEY` and every `get_key("susan")` with `PUBLISHER_KEY` in the test methods (lines ~67, 82, 109, 122, 137). Delete the old `get_key`, `CONNECT_KEYS_JSON`, and the `SERVICE_RUNNING_COMMAND` constant.

- [ ] **Step 3: Verify the refactored test passes under with-connect start-only mode**

Run:
```bash
eval "$(uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect)"
export CONNECT_CONTAINER="$(docker ps --format '{{.ID}}' --filter status=running | head -1)"
uv run --no-sync pytest tests/test_main_system_caches.py -v
uvx --from git+https://github.com/posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542 with-connect --stop
```
Expected: PASS — admin list/delete succeed (exit 0), publisher list/delete are denied (exit 1, "You don't have permission to perform this operation.").

- [ ] **Step 4: Commit**

```bash
git add tests/test_main_system_caches.py
git commit -m "test: run system-caches integration test via with-connect, create publisher at runtime"
```

---

### Task 3: Replace the `test-dev-connect` CI job with an rsconnect-own with-connect job

**Files:**
- Modify: `.github/workflows/main.yml` (the `test-dev-connect` job, lines ~183–211)

**Interfaces:**
- Consumes: `secrets.RSC_LICENSE`; the refactored `test_main_system_caches.py` from Task 2.
- Produces: a job that runs only rsconnect's own integration test, with no vetiver install and no `docker compose`/`just dev`.

- [ ] **Step 1: Replace the entire `test-dev-connect` job**

Replace the job (from `  test-dev-connect:` through the final `uv run --no-sync pytest --vetiver -m 'vetiver'` line) with:

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
      - name: Run system caches tests
        run: uv run --no-sync pytest tests/test_main_system_caches.py
        env:
          CONNECT_SERVER: ${{ steps.connect.outputs.CONNECT_SERVER }}
          CONNECT_API_KEY: ${{ steps.connect.outputs.CONNECT_API_KEY }}
          CONNECT_CONTAINER: ${{ steps.connect.outputs.CONTAINER_ID }}
      - name: Stop Connect
        if: always()
        uses: posit-dev/with-connect@0783dabdd24e360e985a4588ce1239c3dc31c542
        with:
          license: ${{ secrets.RSC_LICENSE }}
          stop: ${{ steps.connect.outputs.CONTAINER_ID }}
```

> If the spike (Task 1) determined a custom gcfg is required to support publisher-user creation, add `config-file: <path>` to the `Start Connect` step and commit that gcfg alongside the test.

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

If `markers` is the only key that becomes empty, replace with an empty list:

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

### Task 5: Delete the bespoke harness (vetiver-testing, docker-compose, Justfile dev recipes)

**Files:**
- Delete: `vetiver-testing/` (entire directory)
- Delete: `docker-compose.yml` (root)
- Modify: `Justfile` (remove `dev` and `dev-stop` recipes)

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

Run:
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

`deploy_app` currently calls the local `validate_entry_point`/`validate_extra_files`, which each emit a `DeprecationWarning`. Point it at the active `bundle.py` versions instead. At the top of `actions.py`, confirm/add the import:

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

Confirm the `bundle.py` signatures match: `validate_entry_point(entry_point, directory)` and `validate_extra_files(directory, extra_files)`. If the `bundle.py` `validate_extra_files` requires the extra `use_abspath` argument, pass its default explicitly.

- [ ] **Step 4: Verify the shim still imports and lints**

Run:
```bash
uv run python -c "from rsconnect.actions import deploy_python_fastapi, deploy_app; print('ok')"
just lint
```
Expected: prints `ok`; `just lint` passes (ruff format check + ruff check).

- [ ] **Step 5: Commit**

```bash
git add rsconnect/actions.py
git commit -m "docs: relabel deploy_python_fastapi as supported vetiver compat shim"
```

---

## Self-Review notes

- Spec "rsconnect-python changes" → Task 1 (spike) + Task 2 (re-home test) + Task 3 (own CI job) cover keeping `test_main_system_caches.py`; Task 4–5 cover all deletions; Task 6 covers the relabel.
- The one genuinely uncertain piece (creating a publisher user / exec-ing the container under `with-connect`) is isolated to Task 1 and the `make_publisher_key` body in Task 2; everything else is concrete.
- Ordering keeps CI green: the system-caches test is re-homed (Tasks 2–3) before `vetiver-testing/` is deleted (Task 5).
- The `actions.py` shim is relabeled, never removed (Task 6); `bundle.py` validate functions are untouched except as an explicit import in the optional cleanup.
- `with-connect` SHA `0783dabdd24e360e985a4588ce1239c3dc31c542` is used identically across Tasks 1–3.
