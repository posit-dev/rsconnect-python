# Domain Docs

How the engineering skills should use rsconnect-python's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root: the project's vocabulary.
- **`docs/adr/`**: architecture decision records. Read the ones that touch the area you're about to work in.

If either doesn't exist yet, **proceed silently**. Don't flag the absence or suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them when a term or decision actually gets resolved.

## Layout

This is a single-context repo: one Python package (`rsconnect/`), one glossary, one ADR folder.

```
/
├── AGENTS.md
├── GLOSSARY.md
├── docs/
│   ├── adr/          ← decision records (excluded from the MkDocs site)
│   ├── agents/       ← skill configuration (excluded from the MkDocs site)
│   └── *.md          ← public user docs, published by MkDocs
└── rsconnect/
```

`docs/adr/` and `docs/agents/` are listed under `exclude_docs` in `mkdocs.yml`. Anything else added under `docs/` is published to the public documentation site, so keep internal notes in those two folders.

## Where the vocabulary already lives

Until `GLOSSARY.md` covers a term, these are the authoritative sources:

- **`rsconnect/models.py`**: `AppModes` is the canonical list of content types. Use the mode's name string (`python-shiny`, `quarto-static`, `jupyter-voila`) when naming a content type, not a framework nickname.
- **`rsconnect/api.py`**: the deployment targets (`RSConnectServer` for Posit Connect, `SPCSConnectServer` for Connect on Snowflake, `ShinyappsServer`, `ConnectCloudServer`). Say which target you mean; "server" alone is ambiguous.
- **`rsconnect/metadata.py`**: `ServerStore` (saved server credentials) and `AppStore` (per-directory deployment records).
- **Public docs under `docs/`**: the user-facing wording for CLI concepts. Issue titles and user-visible messages should match it.

Terms that are easy to blur and worth pinning down in the glossary when they come up: *content* vs. *app*, *bundle* vs. *manifest*, *deployment* vs. *content build*, and *environment* (local Python environment vs. Connect execution environment).

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, say so explicitly rather than silently overriding it:

> _Contradicts ADR-0003 (keep Python 3.8 support), but worth reopening because…_
