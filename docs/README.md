# Documentation

The top-level [README.md](../README.md) becomes our documentation. GitHub
supports a very small set of admonitions. Those admonitions are rewritten into
mkdocs-style admonitions when the README is rendered for our hosted
documentation.

Write GitHub-style admonitions, which MUST have the header as a separate line
using the following syntax; the entire Markdown blockquote becomes the mkdocs
admonition.

GitHub README input:

```markdown
> **Warning**
> This is the warning text.

> **Note**
> This is the note text.
```

mkdocs output:

```markdown
!!! warning
    This is the warning text.

!!! note
    This is the note text.
```
