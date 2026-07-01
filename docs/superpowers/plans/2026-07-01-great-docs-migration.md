# great-docs Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mkdocs/Material documentation toolchain with great-docs (Quarto-based) while preserving the `docs.posit.co/rsconnect-python` S3 site, CLI-reference + narrative + changelog scope, and PR previews.

**Architecture:** great-docs reads `great-docs.yml`, auto-discovers the Click CLI from `rsconnect.main`, auto-generates a changelog from GitHub Releases, and builds a static site to `great-docs/_site/`. CI keeps syncing that directory to the existing S3 buckets. A one-time script backfills the empty GitHub Release bodies from the existing `CHANGELOG.md` so the auto-changelog has full history. Narrative pages become `.qmd`.

**Tech Stack:** great-docs, Quarto CLI, uv, GitHub Actions, AWS S3, `gh` CLI, pytest.

## Global Constraints

- Hosting stays on **S3** (`s3://rstudio-connect-downloads/connect/rsconnect-python/latest/docs/` and `s3://docs.rstudio.com/rsconnect-python/`); great-docs replaces only the build step.
- Site scope: CLI reference + narrative guides + changelog. **No Python API reference.**
- **Single-version** site (one "latest"), matching current promotion-on-tag behavior.
- great-docs output directory is `great-docs/_site/` (all S3/preview paths point here, not `site/`).
- great-docs requires **Python ≥3.11 and the Quarto CLI**; the package itself still supports Python ≥3.8. Run great-docs via `uv run --python 3.12 --with great-docs ...` so its Python floor never conflicts with the project's `requires-python = ">=3.8"`.
- Repository URL for the auto-changelog comes from `pyproject.toml` `[project.urls] Repository`.
- Git tags have **no `v` prefix** (e.g. `1.29.0`). CHANGELOG version headers are `## [X.Y.Z] - YYYY-MM-DD`.

---

## File Structure

- `docs/superpowers/spikes/2026-07-01-great-docs-findings.md` — spike outcomes (Task 1).
- `scripts/backfill_release_notes.py` — CHANGELOG → GitHub Releases backfill (Tasks 2–3).
- `tests/test_backfill_release_notes.py` — parser unit tests (Task 2).
- `great-docs.yml` — great-docs config (Task 4).
- `great-docs/user_guide/*.qmd` — migrated narrative pages (Task 5). Exact directory confirmed by Task 1.
- `great-docs/_variables.yml` (generated at build) — version substitution (Tasks 5, 7).
- `pyproject.toml` — drop the `docs` dependency group (Task 4).
- `justfile` — `docs`/`docs-serve`/`clean` and S3 recipes retargeted (Task 7).
- `.github/workflows/main.yml`, `.github/workflows/preview-docs.yml` — Quarto install + path changes (Task 7).
- Removed in Task 8: `mkdocs.yml`, `docs/commands/`, `docs/overrides/`, `docs/css/`, `docs/requirements.txt`, `docs/index.md`, `docs/deploying.md`, `docs/programmatic-provisioning.md`, `docs/server-administration.md`, `docs/.gitignore`.

---

## Task 1: Spike — validate great-docs feasibility

Exploratory task. Produces a findings note that greenlights Tasks 4–8 or records required deviations. Work on a throwaway branch; nothing here needs to merge except the findings note.

**Files:**
- Create: `docs/superpowers/spikes/2026-07-01-great-docs-findings.md`

**Interfaces:**
- Produces: confirmed values for downstream tasks — (a) how to disable the API reference in `great-docs.yml`; (b) the source-content directory great-docs expects (assumed `great-docs/user_guide/`); (c) the working version-substitution mechanism (assumed Quarto `_variables.yml` + `{{< var rsconnect_python.version >}}`); (d) whether GTM can be injected; (e) that `great-docs build` emits to `great-docs/_site/`.

- [ ] **Step 1: Scaffold a throwaway great-docs project in a scratch dir**

```bash
git checkout -b spike/great-docs
uv run --python 3.12 --with great-docs great-docs config
```
Expected: a starter `great-docs.yml` is written listing all documented options. Read it to locate the keys for CLI, changelog, reference, user-guide dir, and analytics.

- [ ] **Step 2: Probe CLI-only build with the API reference disabled**

Edit `great-docs.yml` to enable the CLI, enable the changelog, and disable/omit the API reference. Then:
```bash
uv run --python 3.12 --with great-docs great-docs build
ls great-docs/_site/
```
Record in the findings note: the exact YAML that disables the reference, whether the build succeeds with no reference, and whether the 16 `rsconnect` subcommands are auto-discovered from `rsconnect.main`. If the reference cannot be disabled, record the fallback (accept a minimal auto-reference) per the spec.

- [ ] **Step 3: Probe version substitution**

Create `great-docs/_variables.yml` with `rsconnect_python:\n  version: "9.9.9"` and put `{{< var rsconnect_python.version >}}` in a test page under the user-guide dir. Build and grep the output HTML for `9.9.9`. Record whether Quarto var substitution works within the great-docs source layout; if not, record the fallback (build-time `sed` replacement in the `docs` recipe).

- [ ] **Step 4: Probe GTM/analytics injection**

Search the `great-docs config` output and great-docs docs for an analytics/head-include key. Attempt to inject `GTM-KHBDBW7`. Record whether it is supported, and if not, the fallback decision (Quarto-native `google-analytics` vs. a custom head include vs. dropping GTM).

- [ ] **Step 5: Write the findings note and clean up**

Write `docs/superpowers/spikes/2026-07-01-great-docs-findings.md` capturing the confirmed values (a)–(e) above with the exact YAML snippets. Then:
```bash
git checkout .   # discard scratch config
git switch -c feat/great-docs-migration main
git add docs/superpowers/spikes/2026-07-01-great-docs-findings.md
git commit -m "docs: record great-docs spike findings"
```
Expected: findings note committed on the migration branch; scratch artifacts discarded.

---

## Task 2: Changelog backfill parser

**Files:**
- Create: `scripts/backfill_release_notes.py`
- Test: `tests/test_backfill_release_notes.py`

**Interfaces:**
- Produces: `parse_changelog(text: str) -> dict[str, str]` — maps each released version (e.g. `"1.29.0"`) to its release-notes body (markdown). Excludes the `Unreleased` section and the trailing link-reference definitions. Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill_release_notes.py
from scripts.backfill_release_notes import parse_changelog

SAMPLE = """# Changelog

Some preamble.

## Unreleased

- unreleased thing

## [1.29.0] - 2026-04-29

- Added `rsconnect deploy nodejs` command.

### Added

- `rsconnect content get-lockfile` command.

## [1.28.2] - 2025-12-05

### Fixed

- Corrected Changelog.

[Unreleased]: https://github.com/posit-dev/rsconnect-python/compare/1.5.0...HEAD
[1.5.0]: https://github.com/posit-dev/rsconnect-python/releases/tag/1.5.0
"""


def test_parse_changelog_extracts_versions_only():
    entries = parse_changelog(SAMPLE)
    assert set(entries) == {"1.29.0", "1.28.2"}


def test_parse_changelog_excludes_unreleased_and_link_refs():
    entries = parse_changelog(SAMPLE)
    assert "unreleased thing" not in "".join(entries.values())
    assert "compare/1.5.0" not in "".join(entries.values())


def test_parse_changelog_keeps_body_and_subsections():
    entries = parse_changelog(SAMPLE)
    assert "deploy nodejs" in entries["1.29.0"]
    assert "### Added" in entries["1.29.0"]
    assert "get-lockfile" in entries["1.29.0"]
    assert entries["1.28.2"].startswith("### Fixed")


def test_parse_changelog_strips_surrounding_blank_lines():
    entries = parse_changelog(SAMPLE)
    assert not entries["1.29.0"].startswith("\n")
    assert not entries["1.29.0"].endswith("\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group test pytest tests/test_backfill_release_notes.py -v`
Expected: FAIL — `ModuleNotFoundError` / `parse_changelog` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/backfill_release_notes.py
"""Backfill empty GitHub Release bodies from docs/CHANGELOG.md.

The GitHub Releases for this project have empty bodies; the real history
lives in docs/CHANGELOG.md (Keep a Changelog format). This one-time script
parses that file and populates each matching Release so great-docs can
generate its Changelog page from Releases.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Dict

VERSION_HEADER = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+(?:[a-z]+\d+)?)\](?: - \S+)?\s*$"
)
LINK_REF = re.compile(r"^\[[^\]]+\]:\s+https?://")


def parse_changelog(text: str) -> Dict[str, str]:
    """Split a Keep-a-Changelog document into {version: body}.

    Skips the 'Unreleased' section and trailing link-reference
    definitions. Body is the markdown between a version header and the
    next '## ' header, with surrounding blank lines stripped.
    """
    entries: Dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            entries[current] = "\n".join(buffer).strip()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            match = VERSION_HEADER.match(line)
            current = match.group("version") if match else None
            buffer = []
            continue
        if LINK_REF.match(line):
            continue
        if current is not None:
            buffer.append(line)

    flush()
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group test pytest tests/test_backfill_release_notes.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_release_notes.py tests/test_backfill_release_notes.py
git commit -m "feat: parse CHANGELOG.md into per-version release notes"
```

---

## Task 3: Changelog backfill execution

**Files:**
- Modify: `scripts/backfill_release_notes.py` (add CLI entry point around `parse_changelog`)
- Test: `tests/test_backfill_release_notes.py` (add plan-building test)

**Interfaces:**
- Consumes: `parse_changelog` from Task 2.
- Produces: `build_backfill_plan(entries, existing_tags, release_has_body) -> list[tuple[str, str]]` — the ordered `(tag, body)` edits to apply, limited to releases that exist and currently have an empty body. `main()` runs a dry-run by default and applies with `--apply`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_backfill_release_notes.py
from scripts.backfill_release_notes import build_backfill_plan


def test_build_backfill_plan_skips_missing_and_nonempty():
    entries = {"1.29.0": "body A", "1.28.2": "body B", "1.0.0": "old"}
    existing_tags = {"1.29.0", "1.28.2"}  # 1.0.0 has no release
    release_has_body = {"1.29.0": False, "1.28.2": True}  # 1.28.2 already has notes
    plan = build_backfill_plan(entries, existing_tags, release_has_body)
    assert plan == [("1.29.0", "body A")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group test pytest tests/test_backfill_release_notes.py::test_build_backfill_plan_skips_missing_and_nonempty -v`
Expected: FAIL — `build_backfill_plan` not defined.

- [ ] **Step 3: Write minimal implementation**

```python
# add to scripts/backfill_release_notes.py

def build_backfill_plan(
    entries: Dict[str, str],
    existing_tags: set[str],
    release_has_body: Dict[str, bool],
) -> list[tuple[str, str]]:
    """Return (tag, body) edits for releases that exist and are empty."""
    plan: list[tuple[str, str]] = []
    for version, body in entries.items():
        if version not in existing_tags:
            continue
        if release_has_body.get(version, False):
            continue
        plan.append((version, body))
    return plan


def _gh_releases() -> Dict[str, bool]:
    """Map existing release tag -> whether its body is non-empty."""
    out = subprocess.run(
        ["gh", "release", "list", "--limit", "500", "--json", "tagName,name"],
        check=True, capture_output=True, text=True,
    ).stdout
    import json
    result: Dict[str, bool] = {}
    for rel in json.loads(out):
        tag = rel["tagName"]
        body = subprocess.run(
            ["gh", "release", "view", tag, "--json", "body", "-q", ".body"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        result[tag] = bool(body)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("changelog", nargs="?", default="docs/CHANGELOG.md")
    parser.add_argument("--apply", action="store_true", help="Actually edit releases")
    args = parser.parse_args(argv)

    with open(args.changelog, encoding="utf-8") as handle:
        entries = parse_changelog(handle.read())

    body_by_tag = _gh_releases()
    existing = set(body_by_tag)
    plan = build_backfill_plan(entries, existing, body_by_tag)

    for tag, body in plan:
        print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {tag} ({len(body)} chars)")
        if args.apply:
            subprocess.run(
                ["gh", "release", "edit", tag, "--notes-file", "-"],
                input=body, text=True, check=True,
            )
    print(f"{len(plan)} release(s) {'updated' if args.apply else 'would be updated'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group test pytest tests/test_backfill_release_notes.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Dry-run against the real repo and spot-check**

Run: `uv run python scripts/backfill_release_notes.py`
Expected: prints `DRY-RUN: 1.29.0 (...)` etc. for the released versions present in CHANGELOG that currently have empty bodies; ends with `N release(s) would be updated.` Sanity-check N against the ~40 versioned CHANGELOG sections.

- [ ] **Step 6: Apply the backfill and verify one release**

Run:
```bash
uv run python scripts/backfill_release_notes.py --apply
gh release view 1.29.0 --json body -q '.body'
```
Expected: the apply run reports the releases updated; `gh release view 1.29.0` now shows the migrated notes (matching the `## [1.29.0]` CHANGELOG section).

- [ ] **Step 7: Commit**

```bash
git add scripts/backfill_release_notes.py tests/test_backfill_release_notes.py
git commit -m "feat: backfill GitHub Release notes from CHANGELOG"
```

---

> **SPIKE-CORRECTED (Task 1 findings, authoritative).** These tasks were rewritten after the
> spike overturned several pre-spike assumptions. Confirmed facts used below:
> - CLI-only build works with `reference: false` (boolean; suppresses the Python API reference).
>   NOTE: `reference: []` does NOT work — an empty list is falsy and falls through to full API
>   auto-discovery. Use the boolean `false`. Config keys: `display_name`, `cli.enabled`/`cli.module`,
>   `changelog.enabled`, top-level `include_in_header`.
> - `user_guide/` lives at the **project root** (not `great-docs/user_guide/`).
> - great-docs renders into a **managed `great-docs/` directory** (git-ignore it entirely) and
>   outputs `great-docs/_site/`. `great-docs.yml` (the config file) stays at the repo root and IS tracked.
> - Build requires a dedicated venv (Python 3.12) with `great-docs` + `pygments` + the project
>   installed, run **activated** (Quarto's post-render hook needs `pygments` on the active `python3`).
>   The `uv run --with great-docs` ephemeral approach does NOT work.
> - GTM analytics injects via a **top-level `include_in_header`** key (inline `text:`), verified on
>   all pages. It is NOT reachable under `site:`.
> - The inline `{{ rsconnect_python.version }}` line is **dropped** (great-docs auto-displays the
>   package version); no `_variables.yml`, no post-build substitution.

## Task 4: great-docs scaffolding & config

**Files:**
- Create: `great-docs.yml` (repo root)
- Create/modify: `.gitignore` (ignore the managed `great-docs/` dir and the docs venv)
- Modify: `pyproject.toml` (remove the mkdocs `docs` dependency group)

**Interfaces:**
- Produces: a `great-docs.yml` that builds a CLI + changelog site (no Python API reference) to
  `great-docs/_site/`, consumed by Tasks 5–7. The build recipe (venv + activate) is defined in Task 7;
  this task builds with the same recipe inline to validate config.

- [ ] **Step 1: Write `great-docs.yml`** (repo root)

```yaml
# great-docs.yml
display_name: rsconnect-python
cli:
  enabled: true
  module: rsconnect.main
reference: false           # disables auto Python API reference (CLI reference still generated). NOT `[]` — an empty list is falsy and falls through to full auto-discovery.
changelog:
  enabled: true
  max_releases: 100
```

- [ ] **Step 2: Remove the mkdocs `docs` dependency group**

Delete the `docs = [...]` block from `[dependency-groups]` in `pyproject.toml`. Do NOT add great-docs
to a dependency group: it requires Python ≥3.11 while the project is `requires-python = ">=3.8"`, so a
group would break resolution. great-docs is installed ad-hoc into a docs venv by the Task 7 recipe.
Leave `[project.urls] Repository` intact — the auto-changelog reads it.

Confirm the mkdocs block is gone:
```bash
grep -n "mkdocs" pyproject.toml
```
Expected: no output.

- [ ] **Step 3: Ignore the managed build dir and docs venv**

Append to the repo-root `.gitignore` (create the entries if absent):
```
/great-docs/
.venv-docs/
```
(`great-docs/` is regenerated on every build — `_quarto.yml`, `index.qmd`, `scripts/`, `_site/`,
`_package_meta.json`, etc. `great-docs.yml` is a file at the root and is NOT covered by `/great-docs/`.)

- [ ] **Step 4: Build to verify the config is valid**

```bash
uv venv --python 3.12 .venv-docs
uv pip install --python .venv-docs --quiet great-docs pygments .
source .venv-docs/bin/activate
great-docs build
deactivate
```
Expected: `[OK] Build complete`; `great-docs/_site/index.html` exists; CLI reference pages exist under
`great-docs/_site/reference/cli/`; a Changelog page renders (its history is populated only after the
Task 3 backfill is applied by the user — an empty/short changelog here is expected and NOT a failure).
Confirm no Python-module reference pages were generated:
```bash
find great-docs/_site -path '*reference*' -name '*.html' | grep -v '/cli/' || echo "no python API pages (correct)"
```

- [ ] **Step 5: Commit**

```bash
git add great-docs.yml pyproject.toml .gitignore
git commit -m "build: add great-docs config, drop mkdocs deps"
```

---

## Task 5: Migrate narrative content to `.qmd`

The four narrative pages are plain markdown; the only mkdocs-specific construct across all of them is
the single `{{ rsconnect_python.version }}` macro in `deploying.md`, which is **dropped** (great-docs
auto-displays the version). Migration is: move the pages to the root `user_guide/` dir as `.qmd`,
preserving prose verbatim, and remove that one macro line.

**Files:**
- Create: `user_guide/index.qmd`, `user_guide/deploying.qmd`, `user_guide/programmatic-provisioning.qmd`,
  `user_guide/server-administration.qmd` (from the matching `docs/*.md`)

**Interfaces:**
- Consumes: `great-docs.yml` (Task 4). great-docs auto-discovers `user_guide/` at the repo root.
- Produces: rendered user-guide pages consumed by the build in Tasks 7–8.

- [ ] **Step 1: Copy the four pages into the root `user_guide/` dir as `.qmd`**

```bash
mkdir -p user_guide
for f in index deploying programmatic-provisioning server-administration; do
  cp "docs/$f.md" "user_guide/$f.qmd"
done
```
(The `docs/*.md` originals are removed later, in Task 8.)

- [ ] **Step 2: Drop the version macro line in `deploying.qmd`**

In `user_guide/deploying.qmd`, remove the line containing the mkdocs macro:
```
Generated from <code>rsconnect-python {{ rsconnect_python.version }}</code>
```
Delete the whole line (and an adjacent now-orphaned blank line if it leaves one). Do not replace it —
great-docs shows the package version automatically. Confirm no macro remains:
```bash
grep -rn "rsconnect_python.version\|{{" user_guide/ || echo "no macros remain (correct)"
```

- [ ] **Step 3: Add page titles/ordering if great-docs needs them**

Build once (Step 4 recipe) and inspect the generated User Guide nav order. If pages are mis-ordered or
mis-titled, add YAML front matter (`---\ntitle: "Deploying Content"\n---`) to each `.qmd` matching the
current mkdocs nav labels: `Getting Started` (index), `Programmatic Provisioning`, `Deploying Content`,
`Server Administration`. If the auto order/titles are already correct, skip.

- [ ] **Step 4: Build and verify all four pages render**

```bash
source .venv-docs/bin/activate    # venv from Task 4
great-docs build
deactivate
for p in index deploying programmatic-provisioning server-administration; do
  ls great-docs/_site/user-guide/$p.html 2>/dev/null || echo "MISSING $p"
done
grep -rn "{{ rsconnect_python.version }}" great-docs/_site/ && echo "MACRO LEAKED" || echo "no leaked macro (correct)"
```
Expected: build succeeds; all four `user-guide/*.html` pages exist; no leaked macro token.

- [ ] **Step 5: Commit**

```bash
git add user_guide
git commit -m "docs: migrate narrative pages to great-docs qmd"
```

---

## Task 6: Branding & analytics

**Files:**
- Create: `assets/` at repo root for brand files (logo, favicon, custom CSS)
- Modify: `great-docs.yml` (logo/favicon/CSS + `include_in_header` GTM)

**Interfaces:**
- Consumes: existing assets under `docs/images/` and `docs/css/custom.css`; `great-docs.yml` from Task 4.
- Produces: a branded site with GTM injected into every page's `<head>`.

- [ ] **Step 1: Copy brand assets to a tracked `assets/` dir**

```bash
mkdir -p assets
cp docs/images/iconPositConnect.svg docs/images/favicon.ico assets/
cp docs/css/custom.css assets/custom.css
```
(Use `assets/` at the repo root — NOT under `great-docs/`, which is git-ignored and regenerated.)

- [ ] **Step 2: Wire logo/favicon/CSS into `great-docs.yml`**

Add the branding keys (see the `great-docs config` starter output for exact key shapes). Baseline:
```yaml
logo: assets/iconPositConnect.svg
```
Add favicon and custom CSS via the keys great-docs exposes for them (confirm against
`uv run --python 3.12 --with great-docs great-docs config` output; e.g. a `favicon:` key and a CSS/SCSS
include). Keep it minimal — only what maps to the current Material config (Posit logo, favicon, custom CSS).
If a key for custom CSS is not available, note it and defer; branding parity beyond the logo is
non-blocking.

- [ ] **Step 3: Inject GTM via top-level `include_in_header`**

Add to `great-docs.yml` (top level, NOT under `site:`), using the real Google Tag Manager snippet for
container `GTM-KHBDBW7`:
```yaml
include_in_header:
  - text: |
      <!-- Google Tag Manager -->
      <script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
      new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
      j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
      'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
      })(window,document,'script','dataLayer','GTM-KHBDBW7');</script>
      <!-- End Google Tag Manager -->
```

- [ ] **Step 4: Build and verify branding + analytics**

```bash
source .venv-docs/bin/activate
great-docs build
deactivate
n=$(grep -rl "GTM-KHBDBW7" great-docs/_site/ | wc -l); echo "pages with GTM: $n"
ls great-docs/_site/**/iconPositConnect.svg great-docs/_site/*iconPositConnect* 2>/dev/null || echo "check logo path in output"
```
Expected: build succeeds; GTM snippet present on all generated pages (n > 1); logo asset present in output.

- [ ] **Step 5: Commit**

```bash
git add great-docs.yml assets
git commit -m "docs: port Posit branding and GTM analytics to great-docs"
```

---

## Task 7: Build tooling & CI

**Files:**
- Modify: `justfile` (`docs`, `docs-serve`, `clean`, `sync-latest-docs-to-s3`, `promote-docs-in-s3`)
- Modify: `.github/workflows/main.yml` (docs job)
- Modify: `.github/workflows/preview-docs.yml`

**Interfaces:**
- Consumes: output dir `great-docs/_site/`; the venv build recipe validated in the spike.
- Produces: `just docs` builds via great-docs into `great-docs/_site/`; CI syncs that dir to the
  existing S3 buckets and PR previews.

- [ ] **Step 1: Replace the `docs` and `docs-serve` recipes**

The build needs an activated venv, so these must be `bash` shebang recipes (multi-line shell state).
Replace the mkdocs recipes in `justfile`:
```make
# Build the documentation site (great-docs / Quarto). Requires the Quarto CLI.
docs:
    #!/usr/bin/env bash
    set -euo pipefail
    uv venv --python 3.12 .venv-docs
    uv pip install --python .venv-docs --quiet great-docs pygments .
    source .venv-docs/bin/activate
    great-docs build

# Serve the documentation with live reload
docs-serve:
    #!/usr/bin/env bash
    set -euo pipefail
    uv venv --python 3.12 .venv-docs
    uv pip install --python .venv-docs --quiet great-docs pygments .
    source .venv-docs/bin/activate
    great-docs preview
```
(`pygments` MUST be installed explicitly — the Quarto post-render hook needs it on the active `python3`.
`.` installs the project so great-docs can import `rsconnect.main` for CLI discovery.)

- [ ] **Step 2: Retarget the S3 and clean recipes**

Change `site/` → `great-docs/_site/` in both S3 recipes and update `clean`:
```make
clean:
    rm -rf .coverage .pytest_cache build dist htmlcov rsconnect_python.egg-info rsconnect.egg-info great-docs

sync-latest-docs-to-s3:
    aws s3 sync --acl bucket-owner-full-control --cache-control max-age=0 great-docs/_site/ s3://rstudio-connect-downloads/connect/rsconnect-python/latest/docs/

promote-docs-in-s3:
    aws s3 sync --delete --acl bucket-owner-full-control --cache-control max-age=300 great-docs/_site/ s3://docs.rstudio.com/rsconnect-python/
```

- [ ] **Step 3: Verify the recipe end-to-end locally**

```bash
just docs
ls great-docs/_site/index.html
```
Expected: build succeeds; `great-docs/_site/index.html` exists.

- [ ] **Step 4: Add Quarto to the `docs` CI job**

In `.github/workflows/main.yml`, in the `docs` job, add the Quarto setup action after the `setup-just`
step and before `build docs`:
```yaml
    - uses: quarto-dev/quarto-actions/setup@v2
```
The `run: just docs` step and the S3 sync/promote steps are unchanged — the recipe now builds via
great-docs and the recipes point at `great-docs/_site/`.

- [ ] **Step 5: Update the PR preview workflow**

In `.github/workflows/preview-docs.yml`: add the Quarto setup step before `Install and Build`, and
change `source-dir: ./site/` to `source-dir: ./great-docs/_site/`:
```yaml
      - uses: quarto-dev/quarto-actions/setup@v2
```
```yaml
        with:
          source-dir: ./great-docs/_site/
```

- [ ] **Step 6: Commit**

```bash
git add justfile .github/workflows/main.yml .github/workflows/preview-docs.yml
git commit -m "build: run docs via great-docs in CI and just recipes"
```

---

## Task 8: Remove mkdocs and finalize

**Files:**
- Delete: `mkdocs.yml`, `docs/commands/`, `docs/overrides/`, `docs/css/`, `docs/requirements.txt`, `docs/.gitignore`, and the four migrated `docs/*.md` pages
- Keep: `docs/CHANGELOG.md` (retained for the `Unreleased` section and as the notes source for future releases), `docs/images/`
- Modify: `CLAUDE.md` (docs commands + changelog/release process), `docs/superpowers/spikes/2026-07-01-great-docs-findings.md` if any notes changed

**Interfaces:**
- Consumes: everything from Tasks 4–7.
- Produces: a repo with no mkdocs residue and an accurate `CLAUDE.md`.

- [ ] **Step 1: Delete mkdocs files and migrated originals**

```bash
git rm mkdocs.yml docs/requirements.txt docs/.gitignore
git rm -r docs/commands docs/overrides docs/css
git rm docs/index.md docs/deploying.md docs/programmatic-provisioning.md docs/server-administration.md
```

- [ ] **Step 2: Confirm no mkdocs references remain**

Run:
```bash
grep -rniE "mkdocs|pymdownx|mkdocs-click|mkdocs-macros" . --exclude-dir=.git --exclude-dir=great-docs/_site --exclude-dir=docs/superpowers
```
Expected: no output (or only historical mentions inside `docs/CHANGELOG.md`, which are fine).

- [ ] **Step 3: Update `CLAUDE.md`**

- In the Documentation commands section, replace the mkdocs `just docs`/`docs-serve` descriptions with the great-docs equivalents. Note: requires the **Quarto CLI**; `just docs` builds via great-docs into `great-docs/_site/` using an isolated `.venv-docs` (Python 3.12) — it does NOT use `uv run --with`.
- In the Releasing section, update the changelog guidance: release notes are now authored in the GitHub Release (source of truth for the published changelog); `docs/CHANGELOG.md` retains only the `Unreleased` section for in-flight work. Reference `scripts/backfill_release_notes.py` as the one-time migration (run its dry-run, then `--apply`).

- [ ] **Step 4: Full build + parity check**

Run:
```bash
just docs
```
Then verify against this checklist (manually open `great-docs/_site/`):
- All four narrative pages present under `user-guide/` with correct titles.
- All 16 CLI commands documented under `reference/cli/` (add, bootstrap, content, deploy, details, environment, info, integration, list, login, logout, quickstart, remove, system, version, write-manifest).
- Changelog page renders (full history appears once the user applies the Task 3 backfill; empty/short before that is expected).
- No leaked `{{ ... }}` macro token; great-docs shows the package version automatically.
- Posit logo present; GTM (`GTM-KHBDBW7`) snippet present on pages.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "build: remove mkdocs toolchain, update CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- S3 hosting preserved → Task 7 (S3 recipes retargeted, CI unchanged in intent). ✓
- CLI + narrative + changelog scope, no API reference → Tasks 4 (`reference.enabled: false`), 5 (narrative), 3/4 (changelog). ✓
- Single-version → no `versions:` key introduced. ✓
- Backfill-then-auto changelog → Tasks 2, 3, then 4 (`changelog.enabled`). ✓
- Spike-then-migrate strategy → Task 1 gates Tasks 4–8. ✓
- All narrative pages to `.qmd` → Task 5. ✓
- CLI auto-discovery from `rsconnect.main` → Tasks 1, 4. ✓
- Version substitution → Tasks 1, 5, 7. ✓
- GTM/analytics → Tasks 1, 6. ✓
- Build tooling + PR previews → Task 7. ✓
- Cutover/cleanup + CLAUDE.md → Task 8. ✓
- Risks (reference-disable, GTM, content-dir layout, URL stability) → carried into Task 1 findings with fallbacks.

**Placeholder scan:** No "TBD/TODO". The intentional spike-dependent values (exact YAML keys, analytics mechanism) are resolved in Task 1 and referenced with documented fallbacks — not silent gaps.

**Type consistency:** `parse_changelog(text) -> dict[str, str]` and `build_backfill_plan(entries, existing_tags, release_has_body) -> list[tuple[str, str]]` are used consistently across Tasks 2–3.

**Open item — URL stability:** great-docs' CLI page structure differs from the current `commands/<name>/` paths; inbound deep links may break. Enumerate broken paths during Task 8's parity check and decide whether S3 redirects are warranted (out of scope for this plan unless the check surfaces critical links).
