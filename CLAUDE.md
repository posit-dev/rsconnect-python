# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rsconnect-python is the Posit Connect command-line interface for deploying Python content (Shiny apps, Quarto documents, APIs, Jupyter notebooks, etc.) to Posit Connect servers. The tool handles bundling content, managing credentials, and orchestrating deployments.

## Development Commands

### Environment Setup
```bash
# Install the project plus dev tooling
# `uv` provisions the interpreter and resolves the `test` dependency group
uv sync --group test

# Run the CLI from your working tree
uv run rsconnect version
```

### Testing
```bash
# Run tests with the default Python (3.13)
just test

# Run tests with a specific Python version (uv fetches it if needed)
just test 3.12

# Run tests across all supported Python versions
just all-tests

# Run single test file
uv run pytest tests/test_bundle.py

# Run single test
uv run pytest tests/test_bundle.py::test_function_name
```

### Linting and Formatting
```bash
# Auto-format and apply fixes
just fmt

# Run all linters (ruff format --check, ruff check, pyright)
just lint
```

### Documentation
```bash
# Build documentation
just docs

# Serve documentation locally (with live reload)
just docs-serve
```

Docs are built with [great-docs](https://github.com/posit-dev/great-docs) (Quarto-based), not
mkdocs. Requires the **Quarto CLI** to be installed. `just docs` provisions an isolated
`.venv-docs` (Python 3.12) with `uv venv`/`uv pip install`, then runs `great-docs build` inside
that venv — it does **not** use `uv run --with`, because Quarto's post-render hook must execute
under the same interpreter that has `great_docs`/`pygments` importable. Output is written to
`great-docs/_site/` (git-ignored, along with `.venv-docs/`). Narrative pages live in
`user_guide/*.qmd`; CLI reference pages are auto-generated from `rsconnect.main`.

### Building Distribution
```bash
# Build wheel distribution
just dist

# Install built package
just install
```

## Code Architecture

### Core Modules

**main.py** - CLI entry point using Click framework. Defines all commands (deploy, add, list, etc.) and option parsing. Commands delegate to action functions.

**api.py** - HTTP client for Posit Connect API. Key classes:
- `RSConnectServer` - represents a Connect server (URL, API key, certificates)
- `RSConnectClient` - low-level HTTP operations
- `RSConnectExecutor` - high-level deployment operations (deploy_bundle, wait_for_task, etc.)
- `SPCSConnectServer` - specialized server for Snowflake deployments

**actions.py & actions_content.py** - High-level deployment orchestration:
- `actions.py` - deployment workflows (test connections, create bundles, validate Quarto)
- `actions_content.py` - content management (list, search, build history, download bundles)

**bundle.py** - Content bundling and manifest generation. Creates tar.gz bundles containing:
- Application files
- `manifest.json` describing app mode, entry point, dependencies
- Environment snapshot (requirements.txt or environment.yml)

Functions named `make_*_bundle()` for different content types (api, html, notebook, tensorflow, voila, quarto).

**models.py** - Data structures:
- `AppMode` - represents content types (shiny, quarto-shiny, jupyter-static, python-api, etc.)
- `AppModes` - registry of all supported app modes with lookup functions
- TypedDict models for API responses (ContentItemV1, TaskStatusV1, etc.)

**metadata.py** - Persistent storage of configuration:
- `ServerStore` - saved server credentials (stored in `~/.rsconnect-python/`)
- `AppStore` - deployment history per directory (stored in local `rsconnect-python/` subdirs)

**environment.py** - Python dependency detection:
- Inspects virtual environments, conda environments, or current Python
- Generates requirements files for reproducible deployments
- Runs inspection in subprocess for isolation

### Deployment Flow

1. **Validate** - Check server connection, validate content files
2. **Bundle** - Create manifest.json, snapshot dependencies, tar content files
3. **Upload** - POST bundle to `/v1/content` or existing content GUID
4. **Deploy** - Server extracts bundle, starts deployment task
5. **Wait** - Poll task status until COMPLETE or ERROR
6. **Store** - Save deployment metadata to local AppStore

### App Modes

Different content types have different app modes (defined in models.py):
- `python-shiny` - Shiny for Python apps
- `quarto-shiny` - Quarto documents with Shiny runtime
- `jupyter-static` - Rendered Jupyter notebooks
- `python-api` - FastAPI, Flask APIs
- `python-dash` - Plotly Dash apps
- `python-streamlit` - Streamlit apps
- `python-holoviz-panel` - HoloViz Panel apps
- etc.

The app mode determines how Connect runs the content. Manifests must specify the correct mode.

## Testing

### Test Structure
- Unit tests in `tests/` mirror module structure (`test_bundle.py`, `test_api.py`, etc.)
- Uses `pytest` with `httpretty` for mocking HTTP requests
- `conftest.py` defines shared fixtures

### Key Test Patterns
- Mock HTTP responses with `httpretty` decorators
- Use temporary directories for file operations
- Test fixtures in `tests/testdata/` for sample content
- `test_metadata.py` has long lines that exceed the default line length limit

### CI/CD
- GitHub Actions workflow in `.github/workflows/main.yml`
- Tests run on Python 3.8-3.13 across ubuntu/macos/windows
- Linting enforced on all PRs
- Coverage reported on Python 3.8 PRs

## Code Style

### Python Standards
- `ruff format` for formatting (120 char line length)
- `ruff check` for linting (enforced in CI)
- Pyright for type checking (advisory; does not fail `just lint`)
- Python 3.8+ compatibility (use `typing_extensions` for newer types)

### Type Annotations
- Strict type checking enabled (`typeCheckingMode = "strict"`)
- Use `TypedDict` for structured dictionaries (API responses, manifest data)
- Import from `typing_extensions` for Python 3.8-3.10 compatibility
- `py.typed` marker indicates typed package

## Important Patterns

### Error Handling
- Raise `RSConnectException` for operational errors (user-facing)
- Include helpful error messages with context
- Use `cli_feedback()` context manager for OK/ERROR output

### Logging
- Logger in `log.py` with custom VERBOSE level between INFO and DEBUG
- Use `logger.info()` for user-visible progress
- Use `logger.debug()` for detailed diagnostics
- Console output uses Click's `echo()` and `secho()` for colors

### Manifest Generation
- Every deployment requires a `manifest.json` describing the content
- Manifests include file checksums, app mode, entry point, dependencies
- Different manifest generators for different content types

### Server Communication
- All API calls go through `RSConnectClient` in api.py
- Handle non-JSON responses and network errors gracefully
- Retry logic built into executor methods
- Support for certificate validation with custom CA bundles

## Releasing

- Version is a static field in `pyproject.toml`, managed with `uv version`.
- `main` carries a `.dev` version (e.g. `1.29.1.dev0`).
- Release notes are now authored directly in the GitHub Release for each tag — that's the source
  of truth for the published changelog (great-docs renders it into the docs changelog page).
  `docs/CHANGELOG.md` only retains the `Unreleased` section for in-flight work; update it before
  cutting a release, then clear it back to an empty `Unreleased` section afterward.
- `scripts/backfill_release_notes.py` is the one-time migration that ported historical
  `docs/CHANGELOG.md` entries into existing GitHub Releases. Run it dry-run first
  (`uv run scripts/backfill_release_notes.py`) to review the plan, then `--apply` to write it.
  It should not need to run again once history is migrated.
- Cut a release: `uv version --bump stable`, commit, `git tag -a 1.2.3 -m 'Release 1.2.3'`, push the tag.
- The `distributions` CI job asserts the tag matches the `pyproject.toml` version, then builds and publishes to PyPI.
- After releasing, bump `main` back to the next `.dev` version with `uv version <next>.dev0`.

## Special Integrations

### Quarto
- Quarto support requires quarto CLI installed
- `actions.py` has `quarto_inspect()` for introspecting projects
- Special handling for Quarto projects with Shiny runtime

### Snowflake
- Special deployment path for Snowflake Snowpark
- `SPCSConnectServer` class for Snowflake-specific authentication
- JWT generation in `snowflake.py`
