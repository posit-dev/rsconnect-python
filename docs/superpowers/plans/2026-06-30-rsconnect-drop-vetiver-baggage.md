# rsconnect-python: drop vetiver test baggage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all vetiver-specific test code from rsconnect-python, convert its own `system caches` integration test to an offline `httpretty`-mocked unit test (no live Connect), drop the now-empty `test-dev-connect` CI job and the bespoke Connect harness, and relabel the `deploy_python_fastapi` compatibility shim instead of removing it.

**Architecture:** rsconnect's `system caches list/delete` CLI commands are thin wrappers over `GET`/`DELETE v1/system/caches/runtime`. Connect's *permission enforcement* on that endpoint (admin allowed; publisher/viewer/anon → 403) is already fully covered upstream in `connect/test/api/tests/test_system_caches_runtime.py`, so rsconnect does not need a live Connect or a second user to re-test it. Instead rsconnect tests its own CLI layer — command wiring, required-flag validation, output formatting, and error surfacing — with `httpretty`, the repo's established HTTP-mocking approach. This removes rsconnect's need for `with-connect` entirely.

**Tech Stack:** Python, pytest, Click (`CliRunner`), httpretty.

## Global Constraints

- **No live Connect / no `with-connect` for rsconnect.** Every test in this plan runs offline; the plan is executable without a license or Docker.
- The `system caches` CLI hits `v1/system/caches/runtime` (`rsconnect/api.py:982-988`); mocks must target that path. The CLI builds an `RSConnectExecutor(...).validate_server()` first, so the mock must also satisfy server validation — mirror the httpretty server setup already used in `tests/test_main_content.py` / `tests/test_main_integration.py`.
- Connect permission enforcement is relied upon from upstream `connect/test/api/tests/test_system_caches_runtime.py` (already covers all four roles for these endpoints). Do not re-test enforcement against a live server here.
- The `actions.py` shim (`deploy_python_fastapi` → `deploy_app` → `validate_*`, lines ~281–442) is **kept**. Do not delete it. Do not alter the active `validate_*` in `bundle.py`.
- This branch is based on `uv-tooling-modernization` (its exact-block edits target that branch's `Justfile`/`main.yml`/`conftest.py`), not `main`.
- Keep CI green at every commit: rewrite `test_main_system_caches.py` (Task 1) and remove the job that depended on the old harness (Task 3) **before** deleting `vetiver-testing/` (Task 4).

---

### Task 1: Rewrite `test_main_system_caches.py` as an httpretty-mocked unit test

**Files:**
- Modify: `tests/test_main_system_caches.py` (full rewrite — remove all live-Connect/docker/JSON-key machinery)

**Interfaces:**
- Consumes: nothing external (fully mocked).
- Produces: an offline test module that runs in the default `pytest ./tests/` suite (no marker, no skip guard).

- [ ] **Step 1: Study the existing CLI-against-mocked-Connect pattern**

Read `tests/test_main_content.py` (and `tests/test_main_integration.py`) for how a `CliRunner().invoke(cli, ...)` flow is run against an `httpretty`-mocked Connect, specifically how server validation is satisfied (the endpoints `RSConnectExecutor.validate_server()` calls — typically the server settings + current-user/verify endpoints). Reuse that exact setup so the executor validates without a real server. Identify the helper or the set of `register_uri` calls needed and report them in your report.

- [ ] **Step 2: Write the mocked tests**

Replace the entire contents of `tests/test_main_system_caches.py`. Keep the four behaviors the old test covered, now mocked (no `admin`/`susan` users, no docker, no JSON keys). Use the repo's `@httpretty.activate(verbose=True, allow_net_connect=False)` style and `CliRunner`. The endpoint is `v1/system/caches/runtime`.

Cover:
1. **`list` happy path** — register `GET v1/system/caches/runtime` returning a caches payload (e.g. `{"caches": [{"language": "Python", "version": "1.2.3", "image_name": "Local"}]}`); invoke `system caches list`; assert exit 0 and that stdout JSON matches.
2. **`delete` happy path** — register `DELETE v1/system/caches/runtime` returning success; invoke `system caches delete --language Python --version 1.2.3 --image-name Local`; assert exit 0.
3. **required-flag validation** — invoke `system caches delete` with no flags (and with only `--language`); assert exit code 2 and the `Missing option '--language' / '-l'` / `--version` messages. (No server interaction occurs; flag parsing fails first — these may not even need httpretty.)
4. **permission surfacing** — register the cache endpoint to return `403` with Connect's permission-denied body; invoke the command; assert exit code 1 and that the output contains the permission-denied message. This replaces the old live "publisher is denied" assertion: it verifies the CLI *surfaces* a 403, while Connect's actual enforcement is covered upstream.

Mirror `tests/test_main_content.py` for the server-validation `register_uri` calls and for `apply_common_args`-style `-s`/`-k`/`--insecure` argument wiring (keep a local `apply_common_args` helper or inline the args).

- [ ] **Step 3: Run the test offline**

Run: `uv run pytest tests/test_main_system_caches.py -v`
Expected: all cases PASS with no network access (httpretty `allow_net_connect=False`) and no Docker.

- [ ] **Step 4: Confirm it is collected by the default suite**

Run: `uv run pytest --collect-only -q tests/test_main_system_caches.py`
Expected: the new tests are collected with no special marker or `--vetiver`/live-Connect skip. (It will now run as part of `scripts/runtests` on every PR.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_main_system_caches.py
git commit -m "test: cover system caches CLI with httpretty mocks instead of a live Connect"
```

---

### Task 2: Remove the `--vetiver` marker plumbing and the vetiver test

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

### Task 3: Remove the `test-dev-connect` CI job

**Files:**
- Modify: `.github/workflows/main.yml` (delete the `test-dev-connect` job, lines ~183–211)

The job existed only to run the vetiver test and the old live `test_main_system_caches.py`. With the vetiver test deleted (Task 2) and system caches now an offline unit test that runs in the normal suite (Task 1), the job has nothing left to do.

- [ ] **Step 1: Delete the entire `test-dev-connect` job**

Remove the job block (from `  test-dev-connect:` through its final `uv run --no-sync pytest --vetiver -m 'vetiver'` line). Do not add a replacement. The mocked `test_main_system_caches.py` now runs in the standard test job via `scripts/runtests`.

- [ ] **Step 2: Confirm no other job references the deleted job or the harness**

Run: `grep -n "test-dev-connect\|vetiver\|just dev\|docker compose" .github/workflows/main.yml`
Expected: no hits (or only unrelated ones you can explain). Confirm no `needs:` in another job points at `test-dev-connect`.

- [ ] **Step 3: Lint the workflow YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/main.yml'))"`
Expected: no output (valid YAML).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/main.yml
git commit -m "ci: drop test-dev-connect job (system caches now mocked, vetiver test removed)"
```

---

### Task 4: Delete the bespoke vetiver harness (vetiver-testing, docker-compose, Justfile dev recipes)

**Files:**
- Delete: `vetiver-testing/` (entire directory)
- Delete: `docker-compose.yml` (root)
- Modify: `Justfile` (remove `dev` and `dev-stop` recipes)

With no live Connect test remaining in rsconnect, none of this has a consumer.

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

Run: `uv run pytest -q`
Expected: PASS (the full offline suite, now including the mocked `test_main_system_caches.py`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove vetiver test harness and root docker-compose"
```

---

### Task 5: Relabel the `actions.py` compatibility shim

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

## Why no live Connect / no with-connect for rsconnect

The earlier draft of this plan kept a live Connect test (with a gcfg + `useradd` + key-mint helper) to exercise the publisher-denied path. Investigation showed that path re-tests *Connect's* permission enforcement, which is already covered upstream in `connect/test/api/tests/test_system_caches_runtime.py` for all four roles on the same `v1/system/caches/runtime` endpoint. rsconnect's job is to test its CLI wiring, which `httpretty` mocks do offline. This deletes the spike, the gcfg/helper, and the with-connect CI job, and moves system-caches coverage into the default per-PR suite. (vetiver-python, by contrast, genuinely deploys a model and serves predictions, so it keeps a live `with-connect` test — see rstudio/vetiver-python#242.)

## Self-Review notes

- Every task is offline and locally verifiable (no license/Docker).
- Task 1 preserves the CLI behaviors the old test covered (list, delete, required-flag validation, 403 surfacing) via mocks; real enforcement is covered upstream.
- Ordering keeps CI green: system-caches rewritten (Task 1) and the dependent job removed (Task 3) before the harness is deleted (Task 4).
- The shim is relabeled, never removed (Task 5); `bundle.py` validate functions untouched except as an explicit import in the optional cleanup.
- No external action pin, no with-connect dependency anywhere in this plan.
