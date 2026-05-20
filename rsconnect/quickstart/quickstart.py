"""
rsconnect quickstart: scaffold a deployable Posit Connect project.

This module is the deep boundary for the ``rsconnect quickstart`` command.
It owns the whole scaffolding flow: pre-flight checks, template rendering,
``pyproject.toml`` generation, ``uv``-based venv population, atomic rollback
on failure, and the post-scaffold console output.

Public entrypoint: :func:`run_quickstart`. Callers (the Click command in
``rsconnect/main.py``) should not need to import anything else from this
module.

See ``docs/commands/quickstart.md`` for the user-facing command reference.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import pkgutil
import re
import shutil
import string
import subprocess
import sys
import typing

import click

from ..exception import RSConnectException


# Supported CLI ``<type>`` values. Each entry MUST match an existing
# ``rsconnect deploy <type>`` subcommand: a project scaffolded by
# ``rsconnect quickstart <type>`` must be deployable with either
# ``rsconnect deploy <type>`` or ``rsconnect deploy pyproject``. Adding a
# type here without a matching ``deploy`` subcommand breaks that promise.
# ``flask`` is an alias for ``api``; both share the same scaffold and the
# ``python-api`` app mode.
# ``quarto`` selects ``quarto-static``; ``quarto-shiny`` is exposed as its
# own CLI type so the user-visible vocabulary matches Connect's two distinct
# app modes (``quarto-static`` and ``quarto-shiny``) rather than splitting
# one app-mode dimension into a separate flag.
SUPPORTED_APP_TYPES: typing.Tuple[str, ...] = (
    "streamlit",
    "shiny",
    "fastapi",
    "api",
    "flask",
    "notebook",
    "voila",
    "quarto",
    "quarto-shiny",
)


# Project name rule: lowercase ASCII letter start, only lowercase letters /
# digits / underscores, no trailing underscore. Underscores (not hyphens) so the name
# is a valid Python package identifier — fastapi/api scaffolds materialize a
# ``<name>/<name>/__init__.py`` package, which only works with importable
# names. The optional middle-and-end group keeps the rule satisfiable by
# single-letter names such as ``"a"``.
_project_name_pattern = re.compile(r"^[a-z]([a-z0-9_]*[a-z0-9])?$")
_PROJECT_NAME_RULE = (
    "Project name must start with a lowercase ASCII letter, contain only "
    "lowercase letters, digits, and underscores, and not end with an underscore."
)


def run_quickstart(
    app_type: str,
    name: str,
    *,
    cwd: typing.Optional[pathlib.Path] = None,
) -> pathlib.Path:
    """Scaffold a new Connect project of ``app_type`` named ``name``.

    Returns the absolute path to the created project directory on success.
    Raises :class:`rsconnect.exception.RSConnectException` on any pre-flight
    or scaffold failure. On failure the partially-created directory is
    removed so the caller sees "all or nothing."

    :param str app_type: one of the supported CLI types.
    :param str name: project name; must satisfy the project-name rule above.
    :param pathlib.Path cwd: override the working directory (testing hook);
        defaults to :func:`pathlib.Path.cwd`.
    """
    cwd = (cwd or pathlib.Path.cwd()).resolve()

    # Pre-flight checks. Each helper raises ``RSConnectException``
    # with an actionable message; nothing on disk is mutated until every
    # check has passed. Type validation now lives in Click's argument
    # parser (see ``rsconnect/main.py``), so it has already passed before
    # we get here.
    _require_uv_on_path()
    _validate_project_name(name)
    target = cwd / name
    _require_target_does_not_exist(target)
    _require_cwd_writable(cwd)

    # Resolve the per-mode template once. Pre-flight already validated
    # ``app_type`` via Click's ``Choice``; ``lookup_template`` is defensive
    # for direct API callers only.
    spec = lookup_template(app_type)

    # Atomicity: after ``mkdir`` succeeds, any failure in the rest of the
    # pipeline must remove ``./<name>/`` so the user sees "all or nothing."
    # ``BaseException`` catches ``KeyboardInterrupt`` too (a Ctrl-C
    # mid-``uv sync`` is the most likely real-world failure mode).
    target.mkdir()
    try:
        _scaffold(target, name=name, spec=spec)
        _install_venv(target)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise

    # Summary runs after success - cosmetic stdout failures (e.g. a
    # BrokenPipeError when piping to ``head``) must not invalidate the
    # on-disk project. The README carries the same two commands, so the
    # user can recover them even if this echo fails.
    _emit_summary(target, name=name, spec=spec)
    return target


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _require_uv_on_path() -> None:
    if shutil.which("uv") is None:
        # ``uv>=0.9.0`` is a declared dependency of rsconnect-python, so a
        # missing ``uv`` on PATH typically means the install environment is
        # broken. The message names both fixes a user can take.
        raise RSConnectException(
            "'uv' was not found on PATH. It ships with rsconnect-python; "
            "try reinstalling (pip install --force-reinstall rsconnect-python) "
            "or install uv manually from https://github.com/astral-sh/uv"
        )


def _validate_project_name(name: str) -> None:
    if not _project_name_pattern.match(name):
        raise RSConnectException(f"Invalid project name {name!r}. {_PROJECT_NAME_RULE}")


def _require_target_does_not_exist(target: pathlib.Path) -> None:
    if target.exists():
        raise RSConnectException(
            f"Target directory {target} already exists. Use a different name or remove the existing directory."
        )


def _require_cwd_writable(cwd: pathlib.Path) -> None:
    if not os.access(cwd, os.W_OK):
        raise RSConnectException(
            f"Current working directory {cwd} is not writable. "
            "Change to a writable directory or adjust its permissions."
        )


# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------
#
# The registry is the single source of truth that ties together what each
# supported mode produces: the canonical Connect ``app_mode`` written to
# ``[tool.rsconnect]``, the entrypoint form, the local-run command
# documented in the post-scaffold stdout and the README, the minimum
# dependencies for the hello-world, and the source files the per-mode
# template materializes.
#
# Adding a future supported mode is a registry insertion plus dropping a
# directory under ``rsconnect/quickstart/templates/<mode>/``; no pre-flight,
# pyproject-writer, or post-output code needs to change.


@dataclasses.dataclass(frozen=True)
class FileSpec:
    """One per-mode template file to materialize in the scaffolded project.

    :param str name: filename relative to the project root. The literal
        token ``{name}`` (if present) is substituted with the project name
        at scaffold time, which is how fastapi/api modes produce a nested
        ``<name>/<name>/`` Python package layout.
    :param str template: path to the template body under
        ``rsconnect/quickstart/templates/``, loaded via
        :func:`pkgutil.get_data`. Template files use the ``.tmpl`` suffix
        to signal "needs substitution before becoming a usable artifact"
        and to prevent accidental Python import of files that may not be
        valid source on their own. The single token ``{name}`` in the body
        is substituted with the project name via
        ``str.replace("{name}", name)``; no other interpolation runs, so
        templates carrying literal braces (e.g. ``notebook.ipynb`` JSON)
        are unaffected.
    """

    name: str
    template: str


@dataclasses.dataclass(frozen=True)
class TemplateSpec:
    """Per-resolved-mode scaffold contract.

    Resolved means the CLI ``app_type`` has already been mapped to one
    entry; the dataclass itself does not know about CLI aliases (e.g.
    ``flask`` -> ``api``).

    The mode's Connect identity (``app_mode``, ``entrypoint``, runtime
    ``dependencies``) lives in ``pyproject_template`` rather than as
    dataclass fields: that template file is the single source of truth
    for what ends up in the generated ``pyproject.toml``.

    :param str pyproject_template: path under ``rsconnect/quickstart/templates/``
        of the per-mode ``pyproject.toml`` template. Substituted via
        :class:`string.Template` against ``$name`` and ``$requires_python``.
    :param str readme_template: path under ``rsconnect/quickstart/templates/``
        of the per-mode ``README.md`` template. Substituted via
        :class:`string.Template` against ``$name``.
    :param tuple local_run_command: argv form of the documented local-run
        command, used by the post-scaffold stdout summary. Tokens containing
        ``"$name"`` are substituted at scaffold time.
    :param tuple source_files: per-mode template files to materialize. Each
        entry's body and ``name`` are loaded and substituted via
        :class:`string.Template` against ``$name``.
    :param tuple notes: optional user-facing trailing lines for the
        post-scaffold stdout output (e.g. "Quarto must be installed
        separately"). Empty for modes whose hello-world has no external
        tooling prerequisite. The README template owns its own copy of any
        notes a user should see on disk.
    """

    pyproject_template: str
    readme_template: str
    local_run_command: typing.Tuple[str, ...]
    source_files: typing.Tuple[FileSpec, ...]
    notes: typing.Tuple[str, ...] = ()


# Registry key: the resolved CLI ``app_type`` (``flask`` resolves to
# ``api`` before lookup; see :func:`lookup_template`). Deferred modes
# (dash, gradio, panel, bokeh) are intentionally absent.
_QUARTO_INSTALL_NOTE = "Quarto must be installed separately: https://quarto.org"

_REGISTRY: typing.Mapping[str, TemplateSpec] = {
    "streamlit": TemplateSpec(
        pyproject_template="streamlit/pyproject.toml.tmpl",
        readme_template="streamlit/README.md.tmpl",
        local_run_command=("uv", "run", "streamlit", "run", "app.py"),
        source_files=(FileSpec(name="app.py", template="streamlit/app.py.tmpl"),),
    ),
    "shiny": TemplateSpec(
        pyproject_template="shiny/pyproject.toml.tmpl",
        readme_template="shiny/README.md.tmpl",
        local_run_command=("uv", "run", "shiny", "run", "app.py"),
        source_files=(FileSpec(name="app.py", template="shiny/app.py.tmpl"),),
    ),
    # fastapi/api produce a nested ``<name>/<name>/`` package so the
    # documented ``python -m <name>`` local-run command resolves cleanly
    # and ``from .app import create_app`` relative imports work.
    "fastapi": TemplateSpec(
        pyproject_template="fastapi/pyproject.toml.tmpl",
        readme_template="fastapi/README.md.tmpl",
        local_run_command=("uv", "run", "python", "-m", "$name"),
        source_files=(
            FileSpec(name="$name/__init__.py", template="fastapi/__init__.py.tmpl"),
            FileSpec(name="$name/__main__.py", template="fastapi/__main__.py.tmpl"),
            FileSpec(name="$name/__connect__.py", template="fastapi/__connect__.py.tmpl"),
            FileSpec(name="$name/app.py", template="fastapi/app.py.tmpl"),
        ),
    ),
    "api": TemplateSpec(
        pyproject_template="api/pyproject.toml.tmpl",
        readme_template="api/README.md.tmpl",
        local_run_command=("uv", "run", "python", "-m", "$name"),
        source_files=(
            FileSpec(name="$name/__init__.py", template="api/__init__.py.tmpl"),
            FileSpec(name="$name/__main__.py", template="api/__main__.py.tmpl"),
            FileSpec(name="$name/__connect__.py", template="api/__connect__.py.tmpl"),
            FileSpec(name="$name/app.py", template="api/app.py.tmpl"),
        ),
    ),
    # notebook and voila share the same notebook body; they differ in
    # ``pyproject_template`` (app_mode + dependencies) and local-run command.
    "notebook": TemplateSpec(
        pyproject_template="notebook/pyproject.toml.tmpl",
        readme_template="notebook/README.md.tmpl",
        local_run_command=("uv", "run", "jupyter", "lab", "notebook.ipynb"),
        source_files=(FileSpec(name="notebook.ipynb", template="notebook/notebook.ipynb.tmpl"),),
    ),
    "voila": TemplateSpec(
        pyproject_template="voila/pyproject.toml.tmpl",
        readme_template="voila/README.md.tmpl",
        local_run_command=("uv", "run", "voila", "notebook.ipynb"),
        source_files=(FileSpec(name="notebook.ipynb", template="notebook/notebook.ipynb.tmpl"),),
    ),
    "quarto": TemplateSpec(
        pyproject_template="quarto/pyproject.toml.tmpl",
        readme_template="quarto/README.md.tmpl",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        source_files=(FileSpec(name="report.qmd", template="quarto/report.qmd.tmpl"),),
        notes=(_QUARTO_INSTALL_NOTE,),
    ),
    "quarto-shiny": TemplateSpec(
        pyproject_template="quarto/pyproject_shiny.toml.tmpl",
        readme_template="quarto/README_shiny.md.tmpl",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        source_files=(FileSpec(name="report.qmd", template="quarto/report_shiny.qmd.tmpl"),),
        notes=(_QUARTO_INSTALL_NOTE,),
    ),
}


def lookup_template(app_type: str) -> TemplateSpec:
    """Resolve the :class:`TemplateSpec` for ``app_type``.

    ``flask`` is an alias for ``api`` and shares the same scaffold; both
    resolve to the same registry entry. Other CLI-level types have already
    been narrowed by Click's ``Choice``, so this lookup is defensive only
    (e.g. direct API callers passing an unknown type).

    :param str app_type: CLI ``<type>`` value.
    """
    resolved_type = "api" if app_type == "flask" else app_type
    if resolved_type not in _REGISTRY:
        raise RSConnectException(
            f"Unknown project type {app_type!r}. Supported types: " + ", ".join(SUPPORTED_APP_TYPES)
        )
    return _REGISTRY[resolved_type]


# ---------------------------------------------------------------------------
# Filesystem generation
# ---------------------------------------------------------------------------


def _scaffold(target: pathlib.Path, *, name: str, spec: TemplateSpec) -> None:
    """Write every file the scaffolded project should contain.

    Filesystem-generation phase: the three always-present files
    (``pyproject.toml``, ``.gitignore``, ``README.md``) and the per-mode
    source files materialized from ``spec.source_files``. The caller owns
    ``target``'s creation and rollback, so this helper writes into an
    existing directory.
    """
    (target / "pyproject.toml").write_text(_render_pyproject(name=name, spec=spec), encoding="utf-8")
    (target / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
    (target / "README.md").write_text(_render_readme(name=name, spec=spec), encoding="utf-8")
    for file_spec in spec.source_files:
        body = _load_template(file_spec.template)
        # ``$name`` substitution in ``file_spec.name`` plus mkdir lets the
        # registry describe nested package layouts (fastapi/api) without
        # special-casing them here.
        dest = target / string.Template(file_spec.name).substitute(name=name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(string.Template(body).substitute(name=name), encoding="utf-8")


def _load_template(path: str) -> str:
    """Read a template file from the ``rsconnect.quickstart.templates`` package.

    ``pkgutil.get_data`` is stdlib since Python 3.0 and works under wheel
    install, unlike ``importlib.resources.files`` which is 3.9+.
    """
    data = pkgutil.get_data("rsconnect.quickstart.templates", path)
    if data is None:
        raise RSConnectException(f"Template not found: {path}")
    return data.decode("utf-8")


# ``requires-python`` is the single source of truth for the scaffold's Python
# requirement: ``rsconnect deploy pyproject`` reads ``pyproject.toml``, so
# emitting a separate ``.python-version`` pin would only duplicate this value.
# The floor tracks the interpreter that ran ``rsconnect quickstart`` so the
# scaffold matches the developer's working environment without committing the
# project to any version older than what its author has actually used.
_REQUIRES_PYTHON = ">={}.{}".format(*sys.version_info[:2])

_GITIGNORE_BODY = """\
__pycache__/
*.pyc
.venv/
*.egg-info/
rsconnect-python/
.env
"""


def _render_pyproject(*, name: str, spec: TemplateSpec) -> str:
    # The per-mode template owns the literal TOML, including ``app_mode``,
    # ``entrypoint`` and the dependency list. Only ``$name`` (project name)
    # and ``$requires_python`` (computed from the running interpreter) vary
    # at scaffold time.
    return string.Template(_load_template(spec.pyproject_template)).substitute(
        name=name, requires_python=_REQUIRES_PYTHON
    )


def _render_readme(*, name: str, spec: TemplateSpec) -> str:
    # The per-mode template owns every literal line of the README, including
    # the mode's local-run command, the deploy command, and any notes. Only
    # ``$name`` varies at scaffold time.
    return string.Template(_load_template(spec.readme_template)).substitute(name=name)


def _format_local_run(spec: TemplateSpec, *, name: str) -> str:
    # The registry stores the local-run argv with ``"$name"`` as a literal
    # placeholder for module-style modes (fastapi/api). Substitute once
    # here so the post-scaffold stdout line renders cleanly.
    return " ".join(string.Template(token).substitute(name=name) for token in spec.local_run_command)


# ---------------------------------------------------------------------------
# Venv population
# ---------------------------------------------------------------------------


def _install_venv(target: pathlib.Path) -> None:
    """Populate ``.venv/`` via ``uv venv`` + ``uv sync``.

    stdout/stderr are inherited from the parent process so users see uv's
    own progress output in real time ("Creating environment...", "Resolving
    dependencies..."). A non-zero exit raises ``RSConnectException``, which
    the caller translates into the rollback of the partially-created project.
    """
    # ``VIRTUAL_ENV`` is removed because uv otherwise warns that the
    # developer's currently-activated venv does not match the scaffolded
    # project's ``.venv/``. The user expects uv to operate on the new
    # project, not the shell's active environment.
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    # ``uv venv`` first so ``uv sync`` reads the freshly-created ``.venv``;
    # if the first step fails there is no point continuing.
    for command in (("uv", "venv"), ("uv", "sync")):
        result = subprocess.run(list(command), cwd=target, env=env)
        if result.returncode != 0:
            joined = " ".join(command)
            raise RSConnectException(
                f"`{joined}` failed in {target} (exit code {result.returncode}). "
                "Inspect the output above and try again."
            )


# ---------------------------------------------------------------------------
# Post-scaffold output
# ---------------------------------------------------------------------------


def _emit_summary(target: pathlib.Path, *, name: str, spec: TemplateSpec) -> None:
    """Print the confirmation, local-run, deploy, and notes lines.

    Uses :func:`click.echo` for consistency with the rest of the CLI; the
    same commands are written into the project's ``README.md`` by
    :func:`_render_readme` so stdout and on-disk docs agree.
    """
    click.echo(f"Project {target.name}/ created.")
    click.echo(f"To run locally:  {_format_local_run(spec, name=name)}")
    click.echo(f"To deploy:       rsconnect deploy pyproject {name}")
    for note in spec.notes:
        click.echo(f"Note: {note}")
