""":func:`select_config_files` -- bundling driven by ``.posit/publish`` ``files``.

A config's ``files`` are gitignore-syntax patterns with include/exclude
*inverted*: a matching pattern *includes* a path, a ``!``-prefixed pattern
*excludes* it, and :data:`STANDARD_EXCLUSIONS` are appended so they always win
(last-match-wins). Matching uses :mod:`pathspec` (``gitwildmatch``). This mirrors
Posit Publisher's bundler (``extensions/vscode/src/bundler/collect.ts``).

Returns sorted, project-relative, forward-slash paths.

There is deliberately no ``.gitignore``-based selector here. When no config
applies, bundling keeps its long-standing whole-tree walk (see
``bundle.create_file_list``), which applies only the built-in
``directories_ignore_list``. Reusing ``.gitignore`` would be wrong for rendered
content: a Quarto project's HTML output is routinely gitignored precisely because
it should not be committed, yet it is exactly what needs to be deployed. Narrowing
the default set is a separate, larger decision than ``.posit`` interop.
"""

from __future__ import annotations

import os
import typing
import warnings

import pathspec


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
