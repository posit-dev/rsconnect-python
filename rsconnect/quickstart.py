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

    # TODO(EVO-080): Implement the scaffold + venv + post-output phases.
    #                Scope: quickstart
    #                Why: Pre-flight passes (SPEC §10) are landed. The
    #                     remaining flow (template rendering, pyproject.toml
    #                     writing, ``uv venv`` + ``uv sync``, post-scaffold
    #                     stdout per §12, and rollback per §11) still needs
    #                     to live behind this public entrypoint so the
    #                     capability stays understandable through one
    #                     module boundary.
    #                Done: Calling ``run_quickstart`` with valid inputs
    #                      creates the directory tree per SPEC §5/§6, writes
    #                      a pyproject.toml per §3/§8.2, runs ``uv venv`` +
    #                      ``uv sync``, prints the §12 lines, and returns
    #                      the project path. The ATDD tests in
    #                      ``tests/test_quickstart.py`` named
    #                      ``test_quickstart_creates_*`` and
    #                      ``test_quickstart_*_post_scaffold_output`` pass.
    #                Non-Goals: Do not implement framework-specific templates
    #                           here (that is separate per-mode evolutions);
    #                           do not implement the ``deploy pyproject``
    #                           command; do not add interactive prompts or a
    #                           ``--deploy`` flag.
    raise NotImplementedError(
        "rsconnect quickstart scaffolding is not yet implemented; "
        "see SPEC_QUICKSTART.md and the TODO markers in rsconnect/quickstart.py"
    )


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
# Scaffolding phases (SPEC §5 / §6 / §9)
# ---------------------------------------------------------------------------
#
# After pre-flight succeeds, the scaffold phase creates the directory,
# materializes the template for the chosen mode, writes pyproject.toml with a
# valid [tool.rsconnect] section, seeds .python-version / .gitignore /
# README.md, then runs uv to populate .venv/. Each of these is a separate
# evolution so the devteam can land them in order and the ATDD suite has
# meaningful per-evolution acceptance signals.


# TODO(EVO-140): Create the project directory and always-present files.
#                Scope: quickstart
#                Why: SPEC §5.1 fixes a uniform "always present" set -
#                     pyproject.toml, .python-version, .gitignore, README.md -
#                     across every mode. Landing the mode-agnostic skeleton
#                     first makes later per-mode evolutions a pure "add source
#                     files" change.
#                Done: Tests
#                      ``test_quickstart_generates_always_present_files`` and
#                      ``test_quickstart_gitignore_covers_rsconnect_dirs`` in
#                      ``tests/test_quickstart.py`` pass: the four files exist
#                      with the expected baseline content (including the
#                      rsconnect-specific ``.gitignore`` entries from §5.1).
#                Non-Goals: Do not write mode-specific source files here; do
#                           not run ``uv`` yet; do not generate a
#                           ``manifest.json`` (I6).


# TODO(EVO-150): Write the [tool.rsconnect] table to pyproject.toml.
#                Scope: quickstart
#                Why: SPEC §3 makes ``[tool.rsconnect]`` the sole configuration
#                     surface for ``deploy pyproject``. Writing ``app_mode``,
#                     ``entrypoint``, and ``title`` with the canonical values
#                     from §8.2 is the invariant that links quickstart output
#                     to the companion deploy command.
#                Done: Tests ``test_quickstart_pyproject_has_tool_rsconnect``,
#                      ``test_quickstart_app_mode_for_<mode>``, and
#                      ``test_quickstart_does_not_duplicate_deps_in_tool_rsconnect``
#                      pass. The generated table contains exactly the three
#                      required fields (no ``dependencies``, no
#                      ``requires-python`` duplication).
#                Non-Goals: Do not add ``[tool.rsconnect.files]`` entries;
#                           §3.2 reserves the name for later. Do not encode
#                           server credentials.


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


# TODO(EVO-230): Define the template registry layout and extension contract.
#                Scope: quickstart
#                Why: SPEC §4.1 requires adding the four deferred modes (dash,
#                     gradio, panel, bokeh) to reduce to "drop a template
#                     directory plus one registration line." The registry is
#                     the shared shape - how a template declares its files,
#                     its app_mode, its entrypoint form, and its local-run
#                     command - so per-mode evolutions above can all plug in.
#                Done: The per-mode evolutions above each consume the
#                      registry; adding a hypothetical ninth mode in
#                      ``tests/test_quickstart.py::test_quickstart_registry_accepts_new_mode``
#                      (an in-test registry insertion) works without touching
#                      non-registry code.
#                Non-Goals: Do not ship the four deferred modes in v1; the
#                           registry exists so *future* work is small, not so
#                           this PR is big.


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
