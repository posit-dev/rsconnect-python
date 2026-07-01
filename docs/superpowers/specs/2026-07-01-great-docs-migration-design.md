# Migrate rsconnect-python docs from mkdocs to great-docs

**Date:** 2026-07-01
**Status:** Approved for planning

## Goal

Replace the mkdocs/Material documentation toolchain with
[great-docs](https://posit-dev.github.io/great-docs/) (a Quarto-based framework)
while preserving the site's current audience-facing behavior.

Preserve:

- Canonical URL `docs.posit.co/rsconnect-python` via **S3 hosting** with
  tag-based promotion (great-docs replaces only the build step; CI keeps syncing
  the built directory to S3).
- Current site **scope**: CLI reference + narrative guides + changelog. **No
  Python API reference** — the public contract is the CLI, not rsconnect's
  importable internals.
- **Single-version** behavior (one "latest" site), matching today's
  promotion-on-tag model.
- **PR previews**.

Change:

- Changelog moves to great-docs' **auto-generated-from-GitHub-Releases** model,
  after a one-time backfill of Release bodies from the existing `CHANGELOG.md`.

Strategy: **spike to de-risk, then a single cutover PR** (chosen over big-bang
and parallel dual-build).

## Current state (baseline)

- `mkdocs.yml` — Material theme, `docs/overrides/` header/footer partials, custom
  CSS, Posit logos, Google Tag Manager analytics (`GTM-KHBDBW7`).
- Narrative content (markdown): `docs/index.md`,
  `docs/programmatic-provisioning.md`, `docs/deploying.md`,
  `docs/server-administration.md`.
- CLI reference: 16 stub files in `docs/commands/*.md`, each a
  `::: mkdocs-click` directive pointing at command objects in `rsconnect.main`.
- `mkdocs-macros` injects `{{ rsconnect_python.version }}` (from a `VERSION` env
  var) into `deploying.md`.
- `docs/CHANGELOG.md` maintained by hand (Keep-a-Changelog format, 40+ versioned
  sections plus an `## Unreleased` section); treated as release source of truth.
- Builds to `site/`, deployed to S3; promoted on tag. PR previews via
  `pr-preview-action` publishing `./site/`.
- Markdown extensions in use: admonitions, `pymdownx.tabbed`, snippets, mermaid,
  footnotes, magiclink, keys.

### great-docs facts established during research

- Quarto-based, Python ≥3.11, **requires the Quarto CLI installed**.
- Config in `great-docs.yml` at project root; **auto-generates `_quarto.yml`**
  (do not hand-edit — overwritten each build).
- CLI docs: `cli: enabled: true`; auto-discovers the Click group.
  `rsconnect.main` is a standard discovery location.
- Changelog auto-generated from GitHub Releases (`changelog.enabled`, default on);
  reads repo URL from `pyproject.toml` `[project.urls] Repository`.
- Output directory is `great-docs/_site/`. Deployment to **S3 is explicitly
  supported** (sync that directory).
- Build/preview via the `great-docs` CLI (`great-docs build`,
  `great-docs setup-github-pages`; preview via build + open).
- **Empty Release bodies today:** all ~89 tags (back to `1.5.0b1`, 2020) have no
  notes. The real history lives entirely in `CHANGELOG.md`.

## Phases

### Phase 0 — Spike (throwaway branch)

Validate load-bearing unknowns against the real package before committing to the
rewrite. Produces a short findings note that either greenlights Phase 2 or flags
required design changes.

1. Can great-docs build **CLI-only** with the API reference disabled/absent?
   (Biggest unknown — great-docs is primarily an API-doc generator.) Fallback:
   accept a minimal auto-generated reference, or revisit scope.
2. Does CLI auto-discovery of `rsconnect.main`'s Click group produce acceptable
   output for all 16 commands?
3. Can GTM analytics (`GTM-KHBDBW7`) be injected given great-docs owns
   `_quarto.yml`?
4. What is the Quarto/great-docs equivalent for the `{{ rsconnect_python.version }}`
   substitution used in `deploying.md`?
5. Confirm `great-docs/_site/` output syncs to S3 cleanly.

### Phase 1 — Changelog backfill (independent, reversible)

One-time script:

- Parse `docs/CHANGELOG.md` by `## [X.Y.Z] - YYYY-MM-DD` section.
- Map each section to its matching git tag (`X.Y.Z`); handle `bN` prereleases.
- Populate each empty GitHub Release body via `gh release edit <tag> --notes-file -`.
- Verify a sample of releases renders correctly.

Leaves the `## Unreleased` block in `CHANGELOG.md` (GitHub Releases can't
represent an untagged section). Going forward, release notes are authored in the
GitHub Release; update `CLAUDE.md`'s release section to reflect the shifted
source of truth. This phase is reversible (touches only Release notes, not
artifacts) and can run before or in parallel with the site work.

### Phase 2 — great-docs scaffolding

- Add `great-docs.yml`: CLI enabled, changelog enabled (auto), API reference
  disabled, homepage + user-guide layout, Posit branding.
- Swap the `docs` dependency group in `pyproject.toml`: remove mkdocs packages,
  add `great-docs`.
- Add Quarto CLI to the docs CI job.
- Confirm `_quarto.yml` is generated and git-ignored.
- Resolve exact source-content layout great-docs expects (`great-docs/` dir vs
  root `user_guide/`) — informed by Phase 0.

### Phase 3 — Content migration

- **Narrative → `.qmd` (all pages, uniformly):** `index.qmd`,
  `programmatic-provisioning.qmd`, `deploying.qmd`, `server-administration.qmd`.
  No `.md` carve-out — uniform `.qmd` enables executable examples, version
  substitution, and future version fences without a later format migration.
  Convert mkdocs-isms to Quarto equivalents: admonitions → callouts,
  `pymdownx.tabbed` → tabsets, snippets → includes, mermaid (native),
  footnotes/magiclink.
- **CLI reference:** delete the 16 `docs/commands/*.md` mkdocs-click stubs;
  great-docs generates this section.
- **Branding:** port Posit logos, favicon, custom CSS, and footer/header intent
  into great-docs theming config; drop `docs/overrides/`.
- **Changelog:** rendered via auto-changelog (Phase 1 makes the history
  complete).

### Phase 4 — Build tooling & CI

- `justfile`: `docs` / `docs-serve` → `great-docs build` / preview; S3 sync
  recipes retarget `site/` → `great-docs/_site/`.
- `.github/workflows/main.yml` docs job: install Quarto, run `just docs`;
  sync/promote steps unchanged in intent, pointed at the new path.
- `.github/workflows/preview-docs.yml`: point `source-dir` at
  `great-docs/_site/`.
- Update or remove `docs/requirements.txt` (superseded by the dependency group).

### Phase 5 — Cutover & cleanup

- Remove `mkdocs.yml`, mkdocs dependencies, `docs/overrides/`, and the
  mkdocs-click command stubs.
- Update `CLAUDE.md` (docs commands, changelog/release process).
- Verify built-site parity before merge (see Validation).

## Risks / open questions carried into the plan

- **API-reference-disable feasibility** (Phase 0 gate) — the biggest unknown,
  given great-docs' purpose.
- **GTM injection** — if unsupported, decide between Quarto-native Google
  Analytics or a custom head include if great-docs exposes one.
- **Content dir layout** — exactly where great-docs expects source, resolved in
  Phase 0/2.
- **URL/anchor stability** — great-docs' CLI page structure differs from the
  current per-command nav; existing deep links (e.g. `commands/deploy/`) may
  change. Enumerate any inbound links that break and decide whether redirects
  are needed.

## Validation / testing

- Phase 0 spike findings note.
- Local `great-docs build` producing a complete `great-docs/_site/`.
- Manual parity checklist: all narrative pages present; all 16 CLI commands
  documented; changelog history complete; `{{ version }}` substitution resolves;
  Posit branding present; GTM/analytics firing.
- PR-preview visual check before the S3 cutover.
