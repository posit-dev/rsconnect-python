"""File selection for bundling, honoring ``.posit/publish`` config ``files``.

Two selectors, one matching engine (:mod:`pathspec`, ``gitwildmatch``):

- :func:`select_config_files` -- an **allowlist**. A config's ``files`` are
  gitignore-syntax patterns with include/exclude *inverted*: a matching pattern
  *includes* a path, a ``!``-prefixed pattern *excludes* it, and
  :data:`STANDARD_EXCLUSIONS` are appended so they always win (last-match-wins).
  This mirrors Posit Publisher's bundler (``extensions/vscode/src/bundler/
  collect.ts``).
- :func:`select_default_files` -- a **denylist** used when no config applies:
  everything except paths ignored by ``.gitignore`` (project root plus nested)
  and the hardcoded :data:`directories_ignore_list`.

Both return sorted, project-relative, forward-slash paths, so downstream
bundling code treats the two cases identically.
"""

from __future__ import annotations

import os
import typing
import warnings

import pathspec

from ..bundle import directories_ignore_list


def _compile(lines: typing.Sequence[str]) -> pathspec.PathSpec:
    """Compile gitignore-style ``lines`` into a spec.

    ``gitwildmatch`` is the pattern-factory name available across the whole
    supported ``pathspec`` range; newer releases deprecate the alias in favor of
    ``gitignore`` but keep it working, so we silence that one warning here rather
    than raise the version floor.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", "GitWildMatchPattern", DeprecationWarning)
        return pathspec.PathSpec.from_lines("gitwildmatch", list(lines))


# Always appended after a config's user patterns. Because resolution is
# last-match-wins, these exclusions always take precedence. Ported verbatim from
# Publisher's ``STANDARD_EXCLUSIONS`` (collect.ts); each is a ``!`` exclusion.
STANDARD_EXCLUSIONS: typing.List[str] = [
    # From rsconnect-python
    "!.Rproj.user/",
    "!.git/",
    "!.svn/",
    "!__pycache__/",
    "!packrat/",
    "!rsconnect-python/",
    "!rsconnect/",
    # From rsconnect
    "!.DS_Store",
    "!.Rhistory",
    "!.quarto/",
    "!*.Rproj",
    "!.rscignore",
    "!*_cache/",
    # Other
    "!.ipynb_checkpoints/",
    # Exclude existing manifest.json; we will create one.
    "!manifest.json",
    # renv library cannot be included
    "!renv/library",
    "!renv/sandbox",
    "!renv/staging",
    # node_modules shouldn't be deployed and can be very large
    "!node_modules/",
]

# Relative paths (under a candidate directory) whose presence marks the directory
# as a Python virtual environment; such directories are skipped entirely, matching
# Publisher's ``isPythonEnvironmentDir``.
_PYTHON_BIN_PATHS = [
    os.path.join("bin", "python"),
    os.path.join("bin", "python3"),
    os.path.join("Scripts", "python.exe"),
    os.path.join("Scripts", "python3.exe"),
]


def _is_python_environment_dir(abs_dir: str) -> bool:
    return any(os.path.isfile(os.path.join(abs_dir, bin_path)) for bin_path in _PYTHON_BIN_PATHS)


def _is_renv_library_dir(rel_dir: str) -> bool:
    parts = rel_dir.split("/")
    return len(parts) >= 2 and parts[-2] == "renv" and parts[-1] in ("library", "sandbox", "staging")


def _rel_posix(base_dir: str, abs_path: str) -> str:
    """Project-relative, forward-slash path (``pathspec`` wants POSIX separators)."""
    return os.path.relpath(abs_path, base_dir).replace(os.sep, "/")


def _walk(
    directory: str,
    keep_file: typing.Callable[[str], bool],
    prune_dir: typing.Callable[[str], bool],
) -> typing.List[str]:
    """Walk ``directory`` collecting project-relative files.

    ``keep_file(rel)`` decides whether a file is included. ``prune_dir(rel)``
    decides whether a directory subtree is skipped entirely (for performance and
    to match Publisher's directory-level exclusion). Python virtualenv and renv
    library directories are always pruned.
    """
    results: typing.List[str] = []
    for cur_dir, dir_names, file_names in os.walk(directory):
        # Prune subdirectories in place so os.walk does not descend into them.
        kept_dirs: typing.List[str] = []
        for name in dir_names:
            abs_sub = os.path.join(cur_dir, name)
            rel_sub = _rel_posix(directory, abs_sub)
            if prune_dir(rel_sub):
                continue
            if _is_python_environment_dir(abs_sub) or _is_renv_library_dir(rel_sub):
                continue
            kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in file_names:
            rel = _rel_posix(directory, os.path.join(cur_dir, name))
            if keep_file(rel):
                results.append(rel)
    return sorted(results)


def select_config_files(directory: str, config_files: typing.Sequence[str]) -> typing.List[str]:
    """Return the files under ``directory`` selected by a config's ``files``.

    ``config_files`` are Publisher-style include patterns. A file is selected
    only when its last matching pattern is an include (``STANDARD_EXCLUSIONS`` are
    appended and win ties). Directories are pruned only when explicitly excluded,
    so an include deeper in an otherwise-unmatched directory is still found.
    """
    spec = _compile(list(config_files) + STANDARD_EXCLUSIONS)

    def keep_file(rel: str) -> bool:
        return spec.check_file(rel).include is True

    def prune_dir(rel: str) -> bool:
        # Prune only definitively-excluded directories; an unmatched directory
        # may still contain files that match an include pattern.
        return spec.check_file(rel + "/").include is False

    return _walk(directory, keep_file, prune_dir)


def _gitignore_spec(directory: str) -> pathspec.PathSpec:
    """A gitignore-style denylist: nested ``.gitignore`` files + hardcoded dirs.

    Patterns from a nested ``.gitignore`` are anchored to that file's directory
    (matching git), so ``build/`` in ``sub/.gitignore`` becomes ``/sub/build/``.
    """
    lines: typing.List[str] = list(directories_ignore_list)
    for cur_dir, _, file_names in os.walk(directory):
        if ".gitignore" not in file_names:
            continue
        rel_dir = _rel_posix(directory, cur_dir)
        prefix = "" if rel_dir == "." else rel_dir + "/"
        try:
            with open(os.path.join(cur_dir, ".gitignore"), "r", encoding="utf-8") as handle:
                raw_lines = handle.read().splitlines()
        except OSError:
            continue
        for raw in raw_lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(raw)
                continue
            negated = stripped.startswith("!")
            body = stripped[1:] if negated else stripped
            # A rooted (contains a non-trailing slash) pattern is relative to the
            # .gitignore's directory; anchor it. An unrooted pattern matches at any
            # depth below that directory, so prefix it with "**/".
            if body.startswith("/"):
                anchored = prefix + body.lstrip("/")
            elif "/" in body.rstrip("/"):
                anchored = prefix + body
            else:
                anchored = prefix + "**/" + body if prefix else body
            lines.append(("!" if negated else "") + anchored)
    return _compile(lines)


def select_default_files(directory: str) -> typing.List[str]:
    """Return every file under ``directory`` that is not gitignored.

    Used when no ``.posit/publish`` config applies. Honors ``.gitignore`` (root
    and nested) plus the hardcoded :data:`directories_ignore_list`.
    """
    spec = _gitignore_spec(directory)

    def keep_file(rel: str) -> bool:
        return not spec.match_file(rel)

    def prune_dir(rel: str) -> bool:
        return spec.match_file(rel + "/")

    return _walk(directory, keep_file, prune_dir)
