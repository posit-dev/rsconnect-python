# rsconnect-python task runner. Run `just --list` to see recipes.

python_versions := "3.8 3.9 3.10 3.11 3.12 3.13"

# Run the test suite against a single Python version (default 3.13)
# Invoke via `bash` so the recipe works on Windows, where uv cannot spawn the
# shebang script directly (os error 193).
test py="3.13":
    uv run --python {{py}} --group test bash ./scripts/runtests

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
    find . -type d \( -name "rsconnect-python" -o -name "rsconnect_python-*" \) -exec rm -rf {} +

# Sync latest docs to S3 (CI)
sync-latest-docs-to-s3:
    aws s3 sync --acl bucket-owner-full-control --cache-control max-age=0 site/ s3://rstudio-connect-downloads/connect/rsconnect-python/latest/docs/

# Promote docs in S3 (CI)
promote-docs-in-s3:
    aws s3 sync --delete --acl bucket-owner-full-control --cache-control max-age=300 site/ s3://docs.rstudio.com/rsconnect-python/
