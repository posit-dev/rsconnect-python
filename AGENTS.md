# AGENTS.md

This file provides guidance to coding agents when working with code in this repository.

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

### Building Distribution
```bash
# Build wheel distribution
just dist

# Install built package
just install
```

## Code Style

- `ruff format` (120-character lines) and `ruff check` are enforced in CI. `tests/test_metadata.py` is exempt from the line-length rule.
- Pyright runs in strict mode (`typeCheckingMode = "strict"`). It is advisory and doesn't fail `just lint`.
- Support Python 3.11+ (see ADR-0001). The CLI Python and the content Python are separate: all of `rsconnect/` runs on the CLI Python, including `subprocesses/inspect_environment.py`, which only shells out to the content Python for its version and packages.
- Import typing features from `typing`, never `typing_extensions`. It's installed in dev environments through other tools, but it's not a runtime dependency, so imports pass tests and then fail for users.
- Use `TypedDict` for structured dictionaries such as API responses and manifest data.

## Important Patterns

- Raise `RSConnectException` for user-facing operational errors, with a message that says what went wrong and how to fix it.
- Wrap CLI steps in `cli_feedback()` (in `actions.py`) for consistent OK/ERROR output.
- Log user-visible progress with `logger.info()` and diagnostics with `logger.debug()`. `log.py` also defines a `VERBOSE` level between the two.
- Use Click's `echo()` / `secho()` for console output.
- `AppModes` in `models.py` is the canonical list of content types; a manifest must declare the right one.

## Testing

- Tests in `tests/` mirror the module names (`test_bundle.py`, `test_api.py`, ...). Shared fixtures are in `conftest.py`; sample content is in `tests/testdata/`.
- Mock HTTP with `httpretty`. Use temporary directories for anything that writes files.
- Integration tests against a live Connect server run only when `CONNECT_SERVER` and `CONNECT_API_KEY` are set. Unset them if unrelated tests fail unexpectedly.

## More guidance

- `docs/agents/architecture.md`: module map, deployment targets, and the deployment flow. Read it before changing `api.py`, `bundle.py`, or deployment commands.
- `CONTRIBUTING.md`: contributor workflow, testing against Connect, and the release process.

## Issues and domain docs

- **Issues**: tracked in GitHub Issues on posit-dev/rsconnect-python via the `gh` CLI. See `docs/agents/issue-tracker.md`.
- **Triage labels**: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.
- **Domain docs**: one root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.
