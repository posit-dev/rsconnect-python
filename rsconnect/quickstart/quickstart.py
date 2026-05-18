"""
rsconnect quickstart: scaffold a deployable Posit Connect project.

This module is the deep boundary for the ``rsconnect quickstart`` command.
It owns the whole scaffolding flow: pre-flight checks, template rendering,
``pyproject.toml`` generation, ``uv``-based venv population, atomic rollback
on failure, and the post-scaffold console output.

Public entrypoint: :func:`run_quickstart`. Callers (the Click command in
``rsconnect/main.py``) should not need to import anything else from this
module.

See ``SPEC_QUICKSTART.md`` at the repository root for the full product
contract.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import pkgutil
import re
import shutil
import subprocess
import typing

import click

from ..exception import RSConnectException


# Supported CLI ``<type>`` values per SPEC §4. ``flask`` is an alias for
# ``api``; both share the same scaffold and ``python-api`` app mode. The
# deferred modes from §4.1 (dash, gradio, panel, bokeh) are intentionally
# absent. Kept as a module-level constant so error messages and future
# template registration share one source of truth.
SUPPORTED_APP_TYPES: typing.Tuple[str, ...] = (
    "streamlit",
    "shiny",
    "fastapi",
    "api",
    "flask",
    "notebook",
    "voila",
    "quarto",
)


# SPEC §2.2: lowercase ASCII letter start, only lowercase letters / digits /
# underscores, no trailing underscore. Underscores (not hyphens) so the name
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
    shiny: bool = False,
    cwd: typing.Optional[pathlib.Path] = None,
) -> pathlib.Path:
    """Scaffold a new Connect project of ``app_type`` named ``name``.

    Returns the absolute path to the created project directory on success.
    Raises :class:`rsconnect.exception.RSConnectException` on any pre-flight
    or scaffold failure; rollback of the partially-created directory is the
    caller-visible invariant defined in SPEC §11.

    :param str app_type: one of the supported CLI types in SPEC §4.
    :param str name: project name; must satisfy SPEC §2.2.
    :param bool shiny: quarto-only flag; selects ``quarto-shiny``.
    :param pathlib.Path cwd: override the working directory (testing hook);
        defaults to :func:`pathlib.Path.cwd`.
    """
    cwd = (cwd or pathlib.Path.cwd()).resolve()

    # SPEC §10 pre-flight order. Each helper raises ``RSConnectException``
    # with an actionable message; nothing on disk is mutated until every
    # check has passed. Type validation now lives in Click's argument
    # parser (see ``rsconnect/main.py``), so it has already passed before
    # we get here.
    _require_uv_on_path()
    _validate_project_name(name)
    target = cwd / name
    _require_target_does_not_exist(target)
    _require_cwd_writable(cwd)

    # SPEC §4/§6: resolve the per-mode template once. Pre-flight already
    # validated ``app_type``; ``lookup_template`` is defensive against
    # impossible flag combinations only.
    spec = lookup_template(app_type, shiny=shiny)

    # SPEC §11 + I8: after ``mkdir`` succeeds, any failure in the rest of
    # the pipeline must remove ``./<name>/`` so the user sees "all or
    # nothing." ``BaseException`` catches ``KeyboardInterrupt`` too (a
    # Ctrl-C mid-``uv sync`` is the most likely real-world failure mode).
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
# Pre-flight checks (SPEC §10)
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
# Template registry (SPEC §4 / §6 / §8.2 / §12)
# ---------------------------------------------------------------------------
#
# The registry is the single source of truth that ties together what each
# supported mode produces: the canonical Connect ``app_mode`` written to
# ``[tool.rsconnect]``, the entrypoint form per §6, the local-run command
# documented in §12 and the README, the minimum dependencies for the
# hello-world, and the source files the per-mode template materializes.
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

    Resolved means the ``(app_type, shiny)`` flag pair has already been
    mapped to one entry; the dataclass itself does not know about CLI
    aliases or flags.

    :param str app_mode: canonical Connect app mode per SPEC §8.2.
    :param str entrypoint: entrypoint string written to
        ``[tool.rsconnect].entrypoint`` per SPEC §6. The literal token
        ``{name}`` (if present) is substituted with the project name at
        scaffold time so fastapi/api can name their nested package.
    :param tuple local_run_command: argv form of the documented local-run
        command per SPEC §12. The literal token ``"{name}"`` (if present) is
        substituted with the project name at scaffold time.
    :param tuple dependencies: minimum runtime dependencies for the
        hello-world, written to ``[project.dependencies]``.
    :param tuple source_files: per-mode template files to materialize.
        Each entry's body is loaded from
        ``rsconnect/quickstart/templates/`` and run through
        ``str.replace("{name}", name)`` at scaffold time.
    :param tuple notes: optional user-facing trailing lines for the
        post-scaffold output and README (e.g. "Quarto must be installed
        separately"). Empty for modes whose hello-world has no external
        tooling prerequisite.
    """

    app_mode: str
    entrypoint: str
    local_run_command: typing.Tuple[str, ...]
    dependencies: typing.Tuple[str, ...]
    source_files: typing.Tuple[FileSpec, ...]
    notes: typing.Tuple[str, ...] = ()


# Registry key: ``(resolved_type, shiny)``. The ``flask`` alias resolves to
# ``api`` before lookup (see :func:`lookup_template`); the v1 deferred modes
# from SPEC §4.1 (dash, gradio, panel, bokeh) are intentionally absent.
_QUARTO_INSTALL_NOTE = "Quarto must be installed separately: https://quarto.org"

_REGISTRY: typing.Mapping[typing.Tuple[str, bool], TemplateSpec] = {
    ("streamlit", False): TemplateSpec(
        app_mode="python-streamlit",
        entrypoint="app.py",
        local_run_command=("uv", "run", "streamlit", "run", "app.py"),
        dependencies=("streamlit",),
        source_files=(FileSpec(name="app.py", template="streamlit/app.py.tmpl"),),
    ),
    ("shiny", False): TemplateSpec(
        app_mode="python-shiny",
        entrypoint="app.py",
        local_run_command=("uv", "run", "shiny", "run", "app.py"),
        dependencies=("shiny",),
        source_files=(FileSpec(name="app.py", template="shiny/app.py.tmpl"),),
    ),
    # fastapi/api produce a nested ``<name>/<name>/`` package so the
    # documented ``python -m <name>`` local-run command resolves cleanly
    # and ``from .app import create_app`` relative imports work.
    ("fastapi", False): TemplateSpec(
        app_mode="python-fastapi",
        entrypoint="{name}.__connect__:app",
        local_run_command=("uv", "run", "python", "-m", "{name}"),
        dependencies=("fastapi", "uvicorn"),
        source_files=(
            FileSpec(name="{name}/__init__.py", template="fastapi/__init__.py.tmpl"),
            FileSpec(name="{name}/__main__.py", template="fastapi/__main__.py.tmpl"),
            FileSpec(name="{name}/__connect__.py", template="fastapi/__connect__.py.tmpl"),
            FileSpec(name="{name}/app.py", template="fastapi/app.py.tmpl"),
        ),
    ),
    ("api", False): TemplateSpec(
        app_mode="python-api",
        entrypoint="{name}.__connect__:app",
        local_run_command=("uv", "run", "python", "-m", "{name}"),
        dependencies=("flask",),
        source_files=(
            FileSpec(name="{name}/__init__.py", template="api/__init__.py.tmpl"),
            FileSpec(name="{name}/__main__.py", template="api/__main__.py.tmpl"),
            FileSpec(name="{name}/__connect__.py", template="api/__connect__.py.tmpl"),
            FileSpec(name="{name}/app.py", template="api/app.py.tmpl"),
        ),
    ),
    # notebook and voila share the same template body; they differ only in
    # ``app_mode`` and the documented local-run command.
    ("notebook", False): TemplateSpec(
        app_mode="jupyter-static",
        entrypoint="notebook.ipynb",
        local_run_command=("uv", "run", "jupyter", "lab", "notebook.ipynb"),
        dependencies=("jupyter",),
        source_files=(FileSpec(name="notebook.ipynb", template="notebook/notebook.ipynb.tmpl"),),
    ),
    ("voila", False): TemplateSpec(
        app_mode="jupyter-voila",
        entrypoint="notebook.ipynb",
        local_run_command=("uv", "run", "voila", "notebook.ipynb"),
        dependencies=("voila", "jupyter"),
        source_files=(FileSpec(name="notebook.ipynb", template="notebook/notebook.ipynb.tmpl"),),
    ),
    ("quarto", False): TemplateSpec(
        app_mode="quarto-static",
        entrypoint="report.qmd",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        dependencies=(),
        source_files=(FileSpec(name="report.qmd", template="quarto/report.qmd.tmpl"),),
        notes=(_QUARTO_INSTALL_NOTE,),
    ),
    ("quarto", True): TemplateSpec(
        app_mode="quarto-shiny",
        entrypoint="report.qmd",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        dependencies=("shiny",),
        source_files=(FileSpec(name="report.qmd", template="quarto/report_shiny.qmd.tmpl"),),
        notes=(_QUARTO_INSTALL_NOTE,),
    ),
}


def lookup_template(app_type: str, *, shiny: bool = False) -> TemplateSpec:
    """Resolve the :class:`TemplateSpec` for ``(app_type, shiny)``.

    ``flask`` is an alias for ``api`` and shares the same scaffold; both
    resolve to the same key. Other CLI-level flag combinations have already
    been narrowed by pre-flight, so this lookup is defensive only.

    :param str app_type: CLI ``<type>`` value per SPEC §4.
    :param bool shiny: quarto-only flag.
    """
    resolved_type = "api" if app_type == "flask" else app_type
    key = (resolved_type, shiny)
    if key not in _REGISTRY:
        raise RSConnectException(
            f"No scaffold template is registered for type {app_type!r} "
            f"with --shiny={shiny}. Re-run without the unsupported flag."
        )
    return _REGISTRY[key]


# ---------------------------------------------------------------------------
# Filesystem generation (SPEC §5.1 / §6 / §3)
# ---------------------------------------------------------------------------


def _scaffold(target: pathlib.Path, *, name: str, spec: TemplateSpec) -> None:
    """Write every file the scaffolded project should contain.

    This is the SPEC §5.1 + §6 filesystem-generation phase: the four
    always-present files (``pyproject.toml``, ``.python-version``,
    ``.gitignore``, ``README.md``) and the per-mode source files
    materialized from ``spec.source_files``. The caller owns ``target``'s
    creation and rollback, so this helper writes into an existing directory.
    """
    (target / "pyproject.toml").write_text(_render_pyproject(name=name, spec=spec), encoding="utf-8")
    (target / ".python-version").write_text(f"{_PYTHON_VERSION}\n", encoding="utf-8")
    (target / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
    (target / "README.md").write_text(_render_readme(name=name, spec=spec), encoding="utf-8")
    for file_spec in spec.source_files:
        # ``pkgutil.get_data`` is stdlib since Python 3.0 and works under
        # wheel install, unlike ``importlib.resources.files`` which is 3.9+.
        data = pkgutil.get_data("rsconnect.quickstart.templates", file_spec.template)
        if data is None:
            raise RSConnectException(f"Template not found: {file_spec.template}")
        body = data.decode("utf-8").replace("{name}", name)
        # ``{name}`` substitution in ``file_spec.name`` plus mkdir lets the
        # registry describe nested package layouts (fastapi/api) without
        # special-casing them here.
        dest = target / file_spec.name.replace("{name}", name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")


# SPEC-pinned literals: kept as separate constants because they encode two
# distinct concerns (the .python-version pin vs. the requires-python floor)
# that happen to share a Python-version shape but evolve independently.
_PYTHON_VERSION = "3.11"  # value written to .python-version
_REQUIRES_PYTHON = ">=3.9"  # value written to [project].requires-python
_GITIGNORE_BODY = "__pycache__/\n*.pyc\n.venv/\n*.egg-info/\nrsconnect-python/\n.env\n"


def _render_pyproject(*, name: str, spec: TemplateSpec) -> str:
    # Build the TOML by direct string concatenation rather than pulling in a
    # writer dependency. SPEC §3.2 forbids duplicating ``dependencies`` or
    # ``requires-python`` in ``[tool.rsconnect]``; the table holds exactly
    # ``app_mode``, ``entrypoint``, and ``title``.
    if spec.dependencies:
        deps_block = "[\n" + "".join(f'    "{dep}",\n' for dep in spec.dependencies) + "]"
    else:
        deps_block = "[]"
    # Entrypoints for fastapi/api carry a literal ``{name}`` so the
    # documented value matches the nested package layout this scaffold
    # produces.
    entrypoint = spec.entrypoint.replace("{name}", name)
    return (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.0.1"\n'
        f'requires-python = "{_REQUIRES_PYTHON}"\n'
        f"dependencies = {deps_block}\n"
        "\n"
        "[tool.rsconnect]\n"
        f'app_mode = "{spec.app_mode}"\n'
        f'entrypoint = "{entrypoint}"\n'
        f'title = "{name}"\n'
    )


def _render_readme(*, name: str, spec: TemplateSpec) -> str:
    local_run = _format_local_run(spec, name=name)
    deploy_cmd = f"rsconnect deploy pyproject {name}"
    body = (
        f"# {name}\n"
        "\n"
        "A Posit Connect project scaffolded by `rsconnect quickstart`.\n"
        "\n"
        "## Run locally\n"
        "\n"
        f"```\n{local_run}\n```\n"
        "\n"
        "## Deploy to Posit Connect\n"
        "\n"
        f"```\n{deploy_cmd}\n```\n"
    )
    if spec.notes:
        notes_block = "\n## Notes\n\n" + "".join(f"- {note}\n" for note in spec.notes)
        body += notes_block
    return body


def _format_local_run(spec: TemplateSpec, *, name: str) -> str:
    # The registry stores the local-run argv with ``"{name}"`` as a literal
    # placeholder for module-style modes. Substitute once at scaffold time so
    # README and post-scaffold stdout share one rendering path.
    return " ".join(token.replace("{name}", name) for token in spec.local_run_command)


# ---------------------------------------------------------------------------
# Venv population (SPEC §5.1 / §7 / I5)
# ---------------------------------------------------------------------------


def _install_venv(target: pathlib.Path) -> None:
    """Populate ``.venv/`` via ``uv venv`` + ``uv sync`` per SPEC §5.1 + §7.

    stdout/stderr are inherited from the parent process so users see uv's
    own progress output in real time ("Creating environment...", "Resolving
    dependencies..."). A non-zero exit raises ``RSConnectException``, which
    the caller translates into the SPEC §11 rollback.
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
# Post-scaffold output (SPEC §12 / I7)
# ---------------------------------------------------------------------------


def _emit_summary(target: pathlib.Path, *, name: str, spec: TemplateSpec) -> None:
    """Print the SPEC §12 confirmation, local-run, deploy, and notes lines.

    Uses :func:`click.echo` for consistency with the rest of the CLI; the
    same commands are written into the project's ``README.md`` by
    :func:`_render_readme` so stdout and on-disk docs agree.
    """
    click.echo(f"Project {target.name}/ created.")
    click.echo(f"To run locally:  {_format_local_run(spec, name=name)}")
    click.echo(f"To deploy:       rsconnect deploy pyproject {name}")
    for note in spec.notes:
        click.echo(f"Note: {note}")
