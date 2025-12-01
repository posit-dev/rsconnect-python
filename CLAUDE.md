# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

rsconnect-python is the Posit Connect command-line interface for deploying Python content (Shiny apps, Quarto documents, APIs, Jupyter notebooks, etc.) to Posit Connect servers. The tool handles bundling content, managing credentials, and orchestrating deployments.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev dependencies
pip install -e '.[test]'
```

### Testing
```bash
# Run tests with Python 3.8 (default)
make test

# Run tests with specific Python version
make test-3.12

# Run tests across all Python versions (3.8-3.12)
make all-tests

# Run single test file
pytest tests/test_bundle.py

# Run single test
pytest tests/test_bundle.py::test_function_name

# Run tests with verbose coverage
./scripts/runtests  # Uses pytest with coverage
```

### Linting and Formatting
```bash
# Format code with black
make fmt

# Run all linters (black, flake8, pyright)
make lint

# Run individual linters
black --check --diff rsconnect/
flake8 rsconnect/
pyright rsconnect/
```

### Documentation
```bash
# Build documentation
make docs

# Serve documentation locally (with live reload)
make docs-serve
```

### Building Distribution
```bash
# Build wheel distribution
make dist

# Install built package
make install
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
- `test_metadata.py` has special flake8 exclusion for E501 (line length)

### CI/CD
- GitHub Actions workflow in `.github/workflows/main.yml`
- Tests run on Python 3.8-3.12 across ubuntu/macos/windows
- Linting enforced on all PRs
- Coverage reported on Python 3.8 PRs

## Code Style

### Python Standards
- Black formatting (120 char line length)
- Flake8 with specific ignores for Black compatibility (E203, E231, E302)
- Strict type checking with Pyright
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

- Version managed by `setuptools_scm` based on git tags
- Update CHANGELOG.md before each release (even betas)
- Create annotated tag: `git tag -a 1.2.3 -m 'Release 1.2.3'`
- Push tag triggers GitHub Actions workflow for PyPI publishing
- Pre-releases must follow PEP 440 format

## Special Integrations

### Quarto
- Quarto support requires quarto CLI installed
- `actions.py` has `quarto_inspect()` for introspecting projects
- Special handling for Quarto projects with Shiny runtime

### Snowflake
- Special deployment path for Snowflake Snowpark
- `SPCSConnectServer` class for Snowflake-specific authentication
- JWT generation in `snowflake.py`

### MCP (Model Context Protocol)
- Optional MCP support for deploying MCP servers (Python 3.10+)
- Uses `fastmcp` library when available
- See `mcp_deploy_context.py` for deployment context handling
