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

## Task 4: great-docs scaffolding & config

**Files:**
- Create: `great-docs.yml`
- Modify: `pyproject.toml` (remove the `docs` dependency group)

**Interfaces:**
- Consumes: spike-confirmed keys from Task 1 (reference-disable YAML, user-guide dir, analytics support).
- Produces: a `great-docs.yml` that builds a CLI + changelog site (no API reference) to `great-docs/_site/`, consumed by Tasks 5–7.

- [ ] **Step 1: Write `great-docs.yml`**

Use the keys confirmed in Task 1's findings note. Baseline (adjust key names to the findings):

```yaml
# great-docs.yml
site:
  title: rsconnect-python
cli:
  enabled: true
  module: rsconnect.main
changelog:
  enabled: true
  max_releases: 100
reference:
  enabled: false        # per Task 1 findings; if unsupported, use the recorded fallback
user_guide: great-docs/user_guide
homepage: user_guide
```

- [ ] **Step 2: Remove the mkdocs `docs` dependency group**

Delete the `docs = [...]` block from `[dependency-groups]` in `pyproject.toml` (great-docs runs via `uv run --with great-docs`, not the group). Leave `[project.urls] Repository` intact — the auto-changelog needs it.

Confirm the block removed:
```bash
grep -n "mkdocs" pyproject.toml
```
Expected: no output.

- [ ] **Step 3: Build to verify the config is valid**

Run:
```bash
uv run --python 3.12 --with great-docs great-docs build
```
Expected: build succeeds; `great-docs/_site/index.html` exists, a CLI reference page exists, and a Changelog page renders with the backfilled history from Task 3.

- [ ] **Step 4: Ignore generated build artifacts**

Create/replace `.gitignore` entries so the generated site and Quarto internals are not committed:
```bash
printf '_site/\n.quarto/\n_quarto.yml\n_variables.yml\n' > great-docs/.gitignore
```
(Adjust to the actual generated-file set observed in Step 3.)

- [ ] **Step 5: Commit**

```bash
git add great-docs.yml great-docs/.gitignore pyproject.toml
git commit -m "build: add great-docs config, drop mkdocs deps"
```

---

## Task 5: Migrate narrative content to `.qmd`

The four narrative pages are plain markdown; the only mkdocs-specific construct across all of them is the single `{{ rsconnect_python.version }}` macro in `deploying.md`. Migration is: move to the great-docs user-guide dir as `.qmd`, and convert that one macro to the spike-confirmed substitution mechanism. Page prose is preserved verbatim otherwise.

**Files:**
- Create: `great-docs/user_guide/index.qmd`, `deploying.qmd`, `programmatic-provisioning.qmd`, `server-administration.qmd` (from the matching `docs/*.md`)
- Create: `great-docs/_variables.yml` (checked-in placeholder; regenerated at build in Task 7)

**Interfaces:**
- Consumes: `great-docs.yml` `user_guide` path (Task 4); version-substitution mechanism (Task 1).
- Produces: rendered user-guide pages consumed by the build in Tasks 7–8.

- [ ] **Step 1: Copy the four pages into the user-guide dir as `.qmd`**

```bash
mkdir -p great-docs/user_guide
for f in index deploying programmatic-provisioning server-administration; do
  cp "docs/$f.md" "great-docs/user_guide/$f.qmd"
done
```

- [ ] **Step 2: Convert the version macro in `deploying.qmd`**

Replace the mkdocs macro with the Quarto var (per Task 1 findings). In `great-docs/user_guide/deploying.qmd`, change:
```
Generated from <code>rsconnect-python {{ rsconnect_python.version }}</code>
```
to:
```
Generated from <code>rsconnect-python {{< var rsconnect_python.version >}}</code>
```
(If Task 1 recorded the `sed` fallback instead, leave a literal placeholder token here and note it for Task 7's build recipe.)

- [ ] **Step 3: Add a checked-in `_variables.yml`**

```bash
printf 'rsconnect_python:\n  version: "dev"\n' > great-docs/_variables.yml
```
(Task 7 overwrites this at build time with the real version. `dev` is the local-build fallback.)

- [ ] **Step 4: Add page ordering/titles if required by great-docs**

If the findings note shows great-docs orders user-guide pages by front matter or a nav key, add a `title:` (and `order:`) front-matter block to each `.qmd` matching the current mkdocs nav labels: `Getting Started` (index), `Programmatic Provisioning`, `Deploying Content`, `Server Administration`. Otherwise skip.

- [ ] **Step 5: Build and verify pages + substitution render**

Run:
```bash
uv run --python 3.12 --with great-docs great-docs build
grep -rl "rsconnect-python dev" great-docs/_site/ || echo "MISSING version substitution"
```
Expected: build succeeds; all four pages present in `great-docs/_site/`; the version string resolved to `dev` (not the literal `{{ ... }}`).

- [ ] **Step 6: Commit**

```bash
git add great-docs/user_guide great-docs/_variables.yml
git commit -m "docs: migrate narrative pages to great-docs qmd"
```

---

## Task 6: Branding & analytics

**Files:**
- Create: `great-docs/` asset files (logo, favicon, custom CSS) as the findings note dictates
- Modify: `great-docs.yml` (theme/branding/analytics keys)

**Interfaces:**
- Consumes: analytics support finding (Task 1); existing assets under `docs/images/` and `docs/css/custom.css`.
- Produces: a branded site with GTM (or the recorded analytics fallback).

- [ ] **Step 1: Copy brand assets into the great-docs project**

```bash
mkdir -p great-docs/assets
cp docs/images/iconPositConnect.svg docs/images/favicon.ico great-docs/assets/
cp docs/css/custom.css great-docs/assets/custom.css
```

- [ ] **Step 2: Wire logo, favicon, and CSS into `great-docs.yml`**

Add the theme keys confirmed in Task 1 (logo, favicon, extra CSS) pointing at `great-docs/assets/`. Keep it minimal — only what maps to the current Material config (Posit logo, favicon, custom CSS).

- [ ] **Step 3: Configure analytics**

Add GTM (`GTM-KHBDBW7`) via the analytics/head-include key from Task 1. If GTM injection is unsupported, apply the recorded fallback (Quarto-native `google-analytics`, or omit with a note).

- [ ] **Step 4: Build and verify branding + analytics**

Run:
```bash
uv run --python 3.12 --with great-docs great-docs build
grep -rl "GTM-KHBDBW7" great-docs/_site/ || echo "analytics not injected (check fallback)"
```
Expected: build succeeds; logo/favicon present in output; analytics snippet present (or fallback confirmed per findings).

- [ ] **Step 5: Commit**

```bash
git add great-docs.yml great-docs/assets
git commit -m "docs: port Posit branding and analytics to great-docs"
```

---

## Task 7: Build tooling & CI

**Files:**
- Modify: `justfile` (`docs`, `docs-serve`, `clean`, `sync-latest-docs-to-s3`, `promote-docs-in-s3`)
- Modify: `.github/workflows/main.yml` (docs job)
- Modify: `.github/workflows/preview-docs.yml`

**Interfaces:**
- Consumes: build command and `_variables.yml` mechanism (Tasks 1, 5); output dir `great-docs/_site/`.
- Produces: CI that builds with great-docs and syncs `great-docs/_site/` to the existing S3 buckets and PR previews.

- [ ] **Step 1: Update the `docs` and `docs-serve` recipes**

Replace the mkdocs recipes in `justfile`:
```make
# Build the documentation site
docs:
    printf 'rsconnect_python:\n  version: "%s"\n' "$(uv version --short)" > great-docs/_variables.yml
    uv run --python 3.12 --with great-docs great-docs build

# Serve the documentation with live reload
docs-serve:
    printf 'rsconnect_python:\n  version: "%s"\n' "$(uv version --short)" > great-docs/_variables.yml
    uv run --python 3.12 --with great-docs great-docs preview
```
(If Task 1 recorded the `sed` fallback for version substitution, replace the `_variables.yml` line with the recorded substitution command. If great-docs has no `preview` subcommand, use `great-docs build` + a static server per the findings.)

- [ ] **Step 2: Retarget the S3 and clean recipes**

In `justfile`, change `site/` → `great-docs/_site/` in both S3 recipes, and update `clean` to remove `great-docs/_site`:
```make
clean:
    rm -rf .coverage .pytest_cache build dist htmlcov rsconnect_python.egg-info rsconnect.egg-info great-docs/_site

sync-latest-docs-to-s3:
    aws s3 sync --acl bucket-owner-full-control --cache-control max-age=0 great-docs/_site/ s3://rstudio-connect-downloads/connect/rsconnect-python/latest/docs/

promote-docs-in-s3:
    aws s3 sync --delete --acl bucket-owner-full-control --cache-control max-age=300 great-docs/_site/ s3://docs.rstudio.com/rsconnect-python/
```

- [ ] **Step 3: Verify the recipe end-to-end locally**

Run:
```bash
just docs
ls great-docs/_site/index.html
grep -rl "rsconnect-python $(uv version --short)" great-docs/_site/ || echo "MISSING version"
```
Expected: build succeeds; index exists; the real project version (not `dev`) appears in the output.

- [ ] **Step 4: Add Quarto to the `docs` CI job**

In `.github/workflows/main.yml`, in the `docs` job, add the Quarto setup action before `build docs` (after the `setup-just` step):
```yaml
    - uses: quarto-dev/quarto-actions/setup@v2
```
The `run: just docs` step is unchanged; the S3 sync/promote steps now push `great-docs/_site/` via the updated recipes (no YAML path change needed since they call `just`).

- [ ] **Step 5: Update the PR preview workflow**

In `.github/workflows/preview-docs.yml`: add the Quarto setup step before `Install and Build`, and change `source-dir: ./site/` to `source-dir: ./great-docs/_site/`:
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

- In the Documentation commands section, replace the mkdocs `just docs`/`docs-serve` descriptions with the great-docs equivalents (note: requires Quarto CLI; runs via `uv run --with great-docs`).
- In the Releasing section, update the changelog guidance: release notes are now authored in the GitHub Release (source of truth for the published changelog); `docs/CHANGELOG.md` retains only the `Unreleased` section for in-flight work. Reference `scripts/backfill_release_notes.py` as the one-time migration.

- [ ] **Step 4: Full build + parity check**

Run:
```bash
just docs
```
Then verify against this checklist (manually open `great-docs/_site/`):
- All four narrative pages present with correct titles.
- All 16 CLI commands documented (add, bootstrap, content, deploy, details, environment, info, integration, list, login, logout, quickstart, remove, system, version, write-manifest).
- Changelog page shows full history from the backfilled Releases.
- Version string resolves to the real version in `deploying`.
- Posit logo/favicon present; analytics present (or fallback confirmed).

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
