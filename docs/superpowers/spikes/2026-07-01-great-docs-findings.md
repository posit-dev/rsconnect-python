# great-docs spike findings — 2026-07-01

Validated great-docs against the real rsconnect-python package (via a scratch project + the
installed package). Results gate/adjust plan Tasks 4–8.

## ✅ CLI-only build works; Python API reference can be suppressed

Config that builds CLI + user-guide + changelog with **no Python API reference**:

```yaml
display_name: rsconnect-python
cli:
  enabled: true
  module: rsconnect.main
reference: []          # empty explicit sections => no auto Python API reference
changelog:
  enabled: true
```

`reference: []` produced **zero** non-CLI reference pages. Build emitted 87–88 HTML pages.

## ✅ CLI auto-discovery from `rsconnect.main` is rich

great-docs generated `reference/cli/<command>.qmd` for every command **plus per-content-type
subcommands** (e.g. `reference/cli/deploy/{quarto,notebook,...}.qmd`,
`reference/cli/write_manifest/{flask,dash,voila,api,nodejs,gradio,fastapi,pyproject,notebook,panel}.qmd`).
Cosmetic: Click warns "parameter --verbose/-v used more than once" — originates in rsconnect's
CLI, not great-docs; harmless.

## Content location (corrects the plan)

- `user_guide/` lives at the **project root** by default (NOT `great-docs/user_guide/`). Override
  with the `user_guide:` key if needed.
- great-docs renders into a **managed `great-docs/` working directory** and writes output to
  **`great-docs/_site/`**. It also generates `great-docs/_quarto.yml`, `great-docs/index.qmd`,
  `great-docs/scripts/post-render.py`, `great-docs/_package_meta.json`, `skill.md`, etc.
  All generated/managed paths must be git-ignored.

## Build recipe (corrects the plan's `uv run --with` approach)

The `uv run --python 3.12 --with great-docs` ephemeral approach **fails**: Quarto's post-render
hook (`great-docs/scripts/post-render.py`) runs under an interpreter that must have `pygments`
AND `great_docs` importable, and the ephemeral env is not the interpreter Quarto uses.

**Working recipe:** a dedicated venv (Python 3.12) with `great-docs`, `pygments`, and the project
installed, run **activated** so `python3` on PATH is that venv:

```bash
uv venv --python 3.12 .venv-docs
uv pip install --python .venv-docs great-docs pygments .   # "." installs rsconnect
source .venv-docs/bin/activate
great-docs build      # -> great-docs/_site/
```

- `pygments` must be installed explicitly (declared great-docs dep, but the post-render subprocess
  needs it on the active interpreter).
- A non-`.venv` name (`.venv-docs`) works when **activated**, so it won't clobber the dev/test
  `.venv`. (great-docs only auto-detects `.venv`/`venv` in the project root for `QUARTO_PYTHON`;
  otherwise it uses its own `sys.executable`, which the activated venv satisfies.)
- Requires-python note: installing into a 3.12 venv via `uv pip install` avoids the dependency-group
  resolution conflict between the project (`>=3.8`) and great-docs (`>=3.11`).

## ❌ Version substitution has no clean mechanism

`_variables.yml` at the project root is NOT picked up (Quarto renders in the managed `great-docs/`
dir; the root variables file never reaches it). The literal `{{< var ... >}}` token survives in
output. **great-docs auto-detects the package version (1.29.0) and injects version badges**, so the
version is already displayed. Options for the inline "Generated from rsconnect-python X" line:
(a) drop it (redundant with the auto version badge), or (b) post-build `sed` over
`great-docs/_site/**/*.html` replacing a sentinel token.

## ✅ GTM/analytics via `include_in_header` (Quarto includes)

great-docs has no dedicated analytics key, and `site:` keys are whitelisted (theme, toc, toc-depth,
toc-title, show_dates, date_format, show_author, show_security) so nesting includes under `site:`
does NOT work. BUT great-docs supports a **top-level `include_in_header`** key that it merges into
Quarto's `format.html.include-in-header` (core.py:11247–11250; config.py:1205). Accepts an inline
`text:` block or a `file:` entry. Verified: an inline GTM `<script>` snippet was injected into the
`<head>` of **all 88 pages**:

```yaml
include_in_header:
  - text: |
      <!-- Google Tag Manager -->
      <script>...GTM-KHBDBW7...</script>
```

This is the clean, config-based path — no post-build HTML mutation needed for analytics. (Note:
`include_in_header` is head-only; the GTM `<noscript>` body iframe has no config hook, but the head
script is the functional part for JS-enabled clients.)

## Net gate result

Feasible. The scope-defining assumptions hold (CLI-only, S3 output dir, single version). Two
cosmetic/outward-facing items (version line, GTM) lack config hooks and need a post-build step or a
drop decision — escalated to the user before Tasks 5–7.
