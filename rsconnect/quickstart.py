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
import re
import shutil
import typing

from .exception import RSConnectException


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
# hyphens, no trailing hyphen. The optional middle-and-end group keeps the
# rule satisfiable by single-letter names such as ``"a"``.
_project_name_pattern = re.compile(r"^[a-z]([a-z0-9-]*[a-z0-9])?$")
_PROJECT_NAME_RULE = (
    "Project name must start with a lowercase ASCII letter, contain only "
    "lowercase letters, digits, and hyphens, and not end with a hyphen."
)


def run_quickstart(
    app_type: str,
    name: str,
    *,
    static: bool = False,
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
    :param bool static: jupyter-only flag; selects ``jupyter-static``.
    :param bool shiny: quarto-only flag; selects ``quarto-shiny``.
    :param pathlib.Path cwd: override the working directory (testing hook);
        defaults to :func:`pathlib.Path.cwd`.
    """
    cwd = (cwd or pathlib.Path.cwd()).resolve()

    # SPEC §10 pre-flight order. Each helper raises ``RSConnectException``
    # with an actionable message; nothing on disk is mutated until every
    # check has passed.
    _require_uv_on_path()
    _validate_app_type(app_type)
    _validate_project_name(name)
    target = cwd / name
    _require_target_does_not_exist(target)
    _require_cwd_writable(cwd)

    # SPEC §4/§6: resolve the per-mode template once. Pre-flight already
    # validated ``app_type``; ``lookup_template`` is defensive against
    # impossible flag combinations only.
    spec = lookup_template(app_type, static=static, shiny=shiny)

    # SPEC §5.1: create the project directory and the always-present files.
    # Mode-specific source files, venv population, post-scaffold output, and
    # rollback land in subsequent evolutions (see TODO(EVO-080) below).
    target.mkdir()
    _write_always_present_files(target, name=name, spec=spec)

    # TODO(EVO-080): Finish the scaffold + venv + post-output phases.
    #                Scope: quickstart
    #                Why: Pre-flight (SPEC §10), directory creation, and the
    #                     always-present files (SPEC §5.1) are landed. The
    #                     remaining flow (mode-specific source files,
    #                     ``uv venv`` + ``uv sync``, post-scaffold stdout per
    #                     §12, and rollback per §11) still needs to live
    #                     behind this public entrypoint so the capability
    #                     stays understandable through one module boundary.
    #                Done: Calling ``run_quickstart`` with valid inputs
    #                      writes the per-mode source files (§6), runs
    #                      ``uv venv`` + ``uv sync``, prints the §12 lines,
    #                      and rolls back ``./<name>/`` on any failure. The
    #                      ATDD tests still marked ``xfail`` in
    #                      ``tests/test_quickstart.py`` (per-mode file sets,
    #                      ``creates_populated_venv``,
    #                      ``post_scaffold_output``,
    #                      ``rolls_back_directory_on_uv_failure``,
    #                      ``invariant_I9_I10_failure_exit_and_message``)
    #                      pass without ``xfail``.
    #                Non-Goals: Do not implement the ``deploy pyproject``
    #                           command; do not add interactive prompts or a
    #                           ``--deploy`` flag.

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


def _validate_app_type(app_type: str) -> None:
    if app_type not in SUPPORTED_APP_TYPES:
        supported = ", ".join(SUPPORTED_APP_TYPES)
        raise RSConnectException(f"Unsupported project type {app_type!r}. Supported types: {supported}.")


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
# directory under ``rsconnect/quickstart_templates/<mode>/``; no pre-flight,
# pyproject-writer, or post-output code needs to change.


@dataclasses.dataclass(frozen=True)
class FileSpec:
    """One per-mode template file to materialize in the scaffolded project.

    :param str name: filename relative to the project root.
    :param str template: path to the template body under
        ``rsconnect/quickstart_templates/``, discovered via
        :mod:`importlib.resources`.
    """

    name: str
    template: str


@dataclasses.dataclass(frozen=True)
class TemplateSpec:
    """Per-resolved-mode scaffold contract.

    Resolved means the ``(app_type, static, shiny)`` flag triple has already
    been mapped to one entry; the dataclass itself does not know about CLI
    aliases or flags.

    :param str app_mode: canonical Connect app mode per SPEC §8.2.
    :param str entrypoint: entrypoint string written to
        ``[tool.rsconnect].entrypoint`` per SPEC §6.
    :param tuple local_run_command: argv form of the documented local-run
        command per SPEC §12. The literal token ``"{name}"`` (if present) is
        substituted with the project name at scaffold time.
    :param tuple dependencies: minimum runtime dependencies for the
        hello-world, written to ``[project.dependencies]``.
    :param tuple source_files: per-mode template files to materialize.
        Empty for modes whose templates have not landed yet; populated by
        the per-mode evolutions below.
    """

    app_mode: str
    entrypoint: str
    local_run_command: typing.Tuple[str, ...]
    dependencies: typing.Tuple[str, ...]
    source_files: typing.Tuple[FileSpec, ...]


# Registry key: ``(resolved_type, static, shiny)``. The ``flask`` alias
# resolves to ``api`` before lookup (see :func:`lookup_template`); the v1
# deferred modes from SPEC §4.1 (dash, gradio, panel, bokeh) are intentionally
# absent.
_REGISTRY: typing.Mapping[typing.Tuple[str, bool, bool], TemplateSpec] = {
    ("streamlit", False, False): TemplateSpec(
        app_mode="python-streamlit",
        entrypoint="app.py",
        local_run_command=("uv", "run", "streamlit", "run", "app.py"),
        dependencies=("streamlit",),
        source_files=(),
    ),
    ("shiny", False, False): TemplateSpec(
        app_mode="python-shiny",
        entrypoint="app.py",
        local_run_command=("uv", "run", "shiny", "run", "app.py"),
        dependencies=("shiny",),
        source_files=(),
    ),
    ("fastapi", False, False): TemplateSpec(
        app_mode="python-fastapi",
        entrypoint="__connect__:app",
        local_run_command=("uv", "run", "python", "-m", "{name}"),
        dependencies=("fastapi", "uvicorn"),
        source_files=(),
    ),
    ("api", False, False): TemplateSpec(
        app_mode="python-api",
        entrypoint="__connect__:app",
        local_run_command=("uv", "run", "python", "-m", "{name}"),
        dependencies=("flask",),
        source_files=(),
    ),
    ("notebook", False, False): TemplateSpec(
        app_mode="jupyter-static",
        entrypoint="notebook.ipynb",
        local_run_command=("uv", "run", "jupyter", "lab", "notebook.ipynb"),
        dependencies=("jupyter",),
        source_files=(),
    ),
    ("notebook", True, False): TemplateSpec(
        app_mode="jupyter-static",
        entrypoint="notebook.ipynb",
        local_run_command=("uv", "run", "jupyter", "lab", "notebook.ipynb"),
        dependencies=("jupyter",),
        source_files=(),
    ),
    ("voila", False, False): TemplateSpec(
        app_mode="jupyter-voila",
        entrypoint="notebook.ipynb",
        local_run_command=("uv", "run", "voila", "notebook.ipynb"),
        dependencies=("voila", "jupyter"),
        source_files=(),
    ),
    ("quarto", False, False): TemplateSpec(
        app_mode="quarto-static",
        entrypoint="report.qmd",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        dependencies=(),
        source_files=(),
    ),
    ("quarto", False, True): TemplateSpec(
        app_mode="quarto-shiny",
        entrypoint="report.qmd",
        local_run_command=("uv", "run", "quarto", "preview", "report.qmd"),
        dependencies=("shiny",),
        source_files=(),
    ),
}


def lookup_template(app_type: str, *, static: bool = False, shiny: bool = False) -> TemplateSpec:
    """Resolve the :class:`TemplateSpec` for ``(app_type, static, shiny)``.

    ``flask`` is an alias for ``api`` and shares the same scaffold; both
    resolve to the same key. Other CLI-level flag combinations have already
    been narrowed by pre-flight, so this lookup is defensive only.

    :param str app_type: CLI ``<type>`` value per SPEC §4.
    :param bool static: jupyter-only flag.
    :param bool shiny: quarto-only flag.
    """
    resolved_type = "api" if app_type == "flask" else app_type
    key = (resolved_type, static, shiny)
    if key not in _REGISTRY:
        raise RSConnectException(
            f"No scaffold template is registered for type {app_type!r} "
            f"with --static={static}, --shiny={shiny}. Re-run without the "
            f"unsupported flag combination."
        )
    return _REGISTRY[key]


# ---------------------------------------------------------------------------
# Always-present files (SPEC §5.1 / §3)
# ---------------------------------------------------------------------------


def _write_always_present_files(target: pathlib.Path, *, name: str, spec: TemplateSpec) -> None:
    """Materialize the four files SPEC §5.1 requires in every scaffold.

    The pyproject.toml carries both ``[project]`` (name, version,
    requires-python, dependencies) and the SPEC §3 ``[tool.rsconnect]``
    table with exactly three keys. The README and post-scaffold output
    share the same two commands derived from ``spec`` so the two stay in
    sync without a separate source of truth.
    """
    (target / "pyproject.toml").write_text(_render_pyproject(name=name, spec=spec), encoding="utf-8")
    (target / ".python-version").write_text(f"{_PYTHON_VERSION}\n", encoding="utf-8")
    (target / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
    (target / "README.md").write_text(_render_readme(name=name, spec=spec), encoding="utf-8")


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
    return (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.0.1"\n'
        f'requires-python = "{_REQUIRES_PYTHON}"\n'
        f"dependencies = {deps_block}\n"
        "\n"
        "[tool.rsconnect]\n"
        f'app_mode = "{spec.app_mode}"\n'
        f'entrypoint = "{spec.entrypoint}"\n'
        f'title = "{name}"\n'
    )


def _render_readme(*, name: str, spec: TemplateSpec) -> str:
    local_run = _format_local_run(spec, name=name)
    deploy_cmd = f"rsconnect deploy pyproject {name}"
    return (
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


def _format_local_run(spec: TemplateSpec, *, name: str) -> str:
    # The registry stores the local-run argv with ``"{name}"`` as a literal
    # placeholder for module-style modes. Substitute once at scaffold time so
    # README and post-scaffold stdout share one rendering path.
    return " ".join(token.replace("{name}", name) for token in spec.local_run_command)


# ---------------------------------------------------------------------------
# Per-mode template registrations (SPEC §6 / §9)
# ---------------------------------------------------------------------------
#
# Each evolution below fills the ``source_files`` tuple for one registry
# entry above and adds the corresponding template files under
# ``rsconnect/quickstart_templates/``. The pyproject / .python-version /
# .gitignore / README writer above is mode-agnostic and does not change as
# modes are added.


# TODO(EVO-160): Register the streamlit template (script-style).
#                Scope: quickstart
#                Why: SPEC §4 / §6.2 / §12 define the streamlit template:
#                     one ``app.py`` with ``st.write("Hello world")``, no
#                     ``__connect__.py``, no ``__main__.py``; entrypoint
#                     ``"app.py"``; local-run ``uv run streamlit run app.py``.
#                     Land one script-style mode first so the scaffolding
#                     framework is proven end to end.
#                Done: Test ``test_quickstart_streamlit_file_set`` passes
#                      (only the expected files exist) and
#                      ``test_quickstart_streamlit_post_scaffold_output``
#                      asserts the post-scaffold stdout quotes the documented
#                      local-run and deploy commands verbatim.
#                Non-Goals: Do not delegate to ``streamlit create`` - templates
#                           are owned per §9.1.


# TODO(EVO-170): Register the shiny template (script-style).
#                Scope: quickstart
#                Why: SPEC §4 / §6.2 define the Python Shiny template: a
#                     single ``app.py`` with a Shiny Express or Core
#                     hello-world; entrypoint ``"app.py"``; local-run
#                     ``uv run shiny run app.py``; app_mode ``python-shiny``.
#                Done: Test ``test_quickstart_shiny_file_set`` and
#                      ``test_quickstart_shiny_post_scaffold_output`` pass.
#                Non-Goals: Do not pick between Shiny Express and Core via a
#                           flag - pick one idiomatic hello-world per §9.2
#                           and document it.


# TODO(EVO-180): Register the fastapi template (module-style).
#                Scope: quickstart
#                Why: SPEC §6.1 defines the module-style shape: ``app.py``
#                     with a ``create_app()`` factory, ``__connect__.py``
#                     exposing ``app = create_app()``, ``__main__.py`` that
#                     runs uvicorn locally. Entrypoint is ``__connect__:app``;
#                     local-run is ``uv run python -m <name>``. Landing one
#                     module-style mode proves the shim pattern.
#                Done: Tests ``test_quickstart_fastapi_file_set``,
#                      ``test_quickstart_fastapi_entrypoint_is_connect_app``,
#                      and ``test_quickstart_fastapi_main_runs_uvicorn`` pass.
#                Non-Goals: Do not inline uvicorn as a runtime dependency in
#                           ``app.py``; it belongs behind ``__main__.py`` so
#                           ``app.py`` stays framework-idiomatic.


# TODO(EVO-190): Register the api / flask template (module-style, alias-aware).
#                Scope: quickstart
#                Why: SPEC §4 lists ``api`` with alias ``flask``; both produce
#                     the same scaffold and app_mode ``python-api``. Module
#                     shape mirrors fastapi: ``app.py`` factory,
#                     ``__connect__.py`` shim, ``__main__.py`` runs Flask's
#                     built-in server.
#                Done: Tests
#                      ``test_quickstart_flask_alias_maps_to_api_mode``,
#                      ``test_quickstart_api_file_set``, and
#                      ``test_quickstart_api_main_runs_flask_dev_server`` pass.
#                Non-Goals: Do not use a production WSGI server in
#                           ``__main__.py`` - it is explicitly the dev server.


# TODO(EVO-200): Register the notebook template (jupyter, --static flag aware).
#                Scope: quickstart
#                Why: SPEC §2.1 + §4 + §6.3: ``jupyter`` accepts ``--static``
#                     which flips app_mode between ``jupyter-static``
#                     (default) and ``jupyter-static``. The template generates
#                     ``notebook.ipynb`` with a couple of cells; entrypoint is
#                     ``notebook.ipynb``. This uses the existing
#                     ``jupyter-static`` mode in ``rsconnect/models.py::AppModes``.
#                Done: Tests ``test_quickstart_notebook_default_app_mode``,
#                      ``test_quickstart_notebook_static_flag_sets_mode``, and
#                      ``test_quickstart_notebook_file_set`` pass.
#                Non-Goals: Do not render the notebook at scaffold time; the
#                           local-run command handles rendering.


# TODO(EVO-210): Register the voila template (jupyter-voila).
#                Scope: quickstart
#                Why: SPEC §4 + §6.3 + §12: voila reuses ``notebook.ipynb`` as
#                     the entrypoint but with app_mode ``jupyter-voila`` and
#                     local-run ``uv run voila notebook.ipynb``.
#                Done: Tests ``test_quickstart_voila_file_set`` and
#                      ``test_quickstart_voila_app_mode`` pass.
#                Non-Goals: Do not duplicate the notebook template file - share
#                           it via the template-registry layout.


# TODO(EVO-220): Register the quarto template (--shiny flag aware).
#                Scope: quickstart
#                Why: SPEC §2.1 + §4 + §6.3: ``quarto`` defaults to static
#                     (app_mode ``quarto-static``); ``--shiny`` flips to
#                     ``quarto-shiny``. Both variants generate ``report.qmd``
#                     with a minimal Quarto document. Local-run is
#                     ``uv run quarto preview report.qmd`` either way.
#                Done: Tests ``test_quickstart_quarto_default_static``,
#                      ``test_quickstart_quarto_shiny_flag_sets_mode``, and
#                      ``test_quickstart_quarto_file_set`` pass.
#                Non-Goals: Do not shell out to ``quarto create-project``
#                           (§9.1 - templates are owned).


# TODO(EVO-240): Run ``uv venv`` + ``uv sync`` inside the scaffolded directory.
#                Scope: quickstart
#                Why: SPEC §5.1 / §7 / I5 require a populated ``.venv/`` so the
#                     documented local-run command works immediately without
#                     any extra setup step. This is what makes the project
#                     actually "ready-to-deploy."
#                Done: Test ``test_quickstart_creates_populated_venv`` in
#                      ``tests/test_quickstart.py`` passes: ``.venv/`` exists
#                      and the declared dependencies are importable from it.
#                      Failure from ``uv`` triggers the rollback evolution.
#                Non-Goals: Do not reimplement venv creation; shell out to
#                           ``uv``. Do not gate on Python-version availability -
#                           §10 delegates that to uv's own output.


# TODO(EVO-250): Implement atomic rollback of ./<name>/ on any failure.
#                Scope: quickstart
#                Why: SPEC §11 + I8 require that any failure after directory
#                     creation leaves no partial project behind. Keeping this
#                     in one place (the public entrypoint's try/finally frame)
#                     preserves the "one deep module" shape - callers do not
#                     have to know about rollback.
#                Done: Test
#                      ``test_quickstart_rolls_back_directory_on_uv_failure``
#                      in ``tests/test_quickstart.py`` passes (a forced uv
#                      failure leaves no ``./<name>/``). Ancestor directories
#                      and uv cache state are untouched per §11.
#                Non-Goals: Do not roll back uv cache writes or ancestor
#                           directories; do not catch and swallow the error
#                           (I9 requires non-zero exit).


# TODO(EVO-260): Emit the post-scaffold confirmation and command lines.
#                Scope: quickstart
#                Why: SPEC §12 + I7 require three stdout lines: confirmation,
#                     local-run command, deploy command - verbatim per the §12
#                     table. The generated README.md must carry the same two
#                     commands.
#                Done: Tests ``test_quickstart_<mode>_post_scaffold_output``
#                      (one per mode) and
#                      ``test_quickstart_readme_matches_post_scaffold_output``
#                      pass. The exit code is zero only when these lines have
#                      been printed.
#                Non-Goals: Do not colorize aggressively; do not add a
#                           "next steps" multi-paragraph block - §12 caps the
#                           output at three lines.
