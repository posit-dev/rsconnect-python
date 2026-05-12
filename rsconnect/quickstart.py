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

import pathlib
import typing

# TODO(EVO-070): Define the public QuickstartRequest type or simple call contract.
#                Scope: quickstart
#                Why: Establish a single validated value that downstream phases
#                     (pre-flight, scaffold, post-scaffold output) consume so the
#                     capability is understandable through one public entrypoint
#                     downward. Carrying <type>, <name>, and the type-specific
#                     flag state (jupyter --static, quarto --shiny) as one value
#                     keeps the CLI layer thin and the deep module self-contained.
#                Done: A value (or plain kwargs on ``run_quickstart``) captures
#                      the validated CLI inputs; the tests in
#                      ``tests/test_quickstart.py`` that exercise name/type
#                      validation via CliRunner pass for the error branches
#                      without needing any scaffolding work.
#                Non-Goals: Do not introduce a public ``QuickstartOptions`` /
#                           ``QuickstartContext`` passive data bag; do not add
#                           dependency injection; keep this tight to the real
#                           product concept.


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

    This is currently a probe stub: it raises NotImplementedError so that the
    CLI command registers and help text renders, while the ATDD test suite in
    ``tests/test_quickstart.py`` fails in the expected way until each
    evolution below is applied.
    """
    # TODO(EVO-080): Implement the quickstart pipeline.
    #                Scope: quickstart
    #                Why: This is the public entrypoint the Click command
    #                     delegates to. Keeping the full flow visible here
    #                     (pre-flight -> scaffold -> venv -> post-output ->
    #                     rollback-on-failure) is the "contract before detail"
    #                     shape the reviewer should see from this module alone.
    #                Done: Calling ``run_quickstart`` with valid inputs creates
    #                      the directory tree per SPEC §5/§6, writes a
    #                      pyproject.toml per §3/§8.2, runs ``uv venv`` + ``uv
    #                      sync``, and returns the project path. The ATDD tests
    #                      in ``tests/test_quickstart.py`` named
    #                      ``test_quickstart_creates_*`` pass.
    #                Non-Goals: Do not implement framework-specific templates
    #                           here (that is separate per-mode evolutions);
    #                           do not implement the ``deploy pyproject``
    #                           command (it has its own evolutions); do not add
    #                           interactive prompts or a ``--deploy`` flag.
    raise NotImplementedError(
        "rsconnect quickstart is not yet implemented; see SPEC_QUICKSTART.md and "
        "TODO(EVO-...) markers in rsconnect/quickstart.py"
    )


# ---------------------------------------------------------------------------
# Pre-flight checks (SPEC §10)
# ---------------------------------------------------------------------------
#
# Below are the five ordered pre-flight checks the spec requires. They live
# together because they are phases of one capability ("can we scaffold?") and
# should run in the documented order before any filesystem mutation. Each
# check has its own evolution so the implementer can land them one at a time
# and the ATDD tests for each failure branch can graduate independently.


# TODO(EVO-090): Pre-flight check 1 - require uv on PATH.
#                Scope: quickstart
#                Why: SPEC §7 and §10 make ``uv`` the sole dependency-manager
#                     path. Detecting its absence up front gives an actionable
#                     message before any work starts and keeps the rest of the
#                     flow from having to re-check. The install hint is part
#                     of the user-visible contract.
#                Done: Tests ``test_quickstart_requires_uv_on_path`` and
#                      ``test_quickstart_uv_missing_message_names_install`` in
#                      ``tests/test_quickstart.py`` pass. Exit code is
#                      non-zero; stderr names ``uv`` and the install command.
#                Non-Goals: Do not add a fallback to ``python -m venv`` + pip.
#                           Do not probe ``uv --version`` compatibility; mere
#                           presence on PATH is sufficient for v1.


# TODO(EVO-100): Pre-flight check 2 - validate <type> against supported list.
#                Scope: quickstart
#                Why: SPEC §2.3 + §4 enumerate the eight v1 CLI type values
#                     (streamlit, shiny, fastapi, api, flask, notebook, voila,
#                     quarto). Unknown types must exit with a message listing
#                     the supported ones so the user can self-correct without
#                     reading docs.
#                Done: Test ``test_quickstart_unknown_type_lists_supported``
#                      in ``tests/test_quickstart.py`` passes: the error lists
#                      every supported CLI type, and ``flask`` is accepted as
#                      an alias for ``api``.
#                Non-Goals: Do not advertise the four deferred modes (dash,
#                           gradio, panel, bokeh) - they are intentionally not
#                           in v1 per §4.1.


# TODO(EVO-110): Pre-flight check 3 - validate <name> against PEP 508 subset.
#                Scope: quickstart
#                Why: SPEC §2.2 restricts names to
#                     ``^[a-z][a-z0-9-]*[a-z0-9]$`` (lowercase start, lowercase
#                     alphanumerics and hyphens, no trailing hyphen). Enforcing
#                     this before scaffolding prevents generating a project
#                     whose pyproject.toml would be invalid.
#                Done: Tests ``test_quickstart_rejects_invalid_name_*`` in
#                      ``tests/test_quickstart.py`` pass for uppercase,
#                      leading-digit, underscore, trailing-hyphen, and empty
#                      name inputs. Error message states the rule verbatim.
#                Non-Goals: Do not allow underscores (they are valid in PEP 508
#                           but the spec narrows to hyphens for distribution
#                           friendliness); do not normalize (no auto-lowercase).


# TODO(EVO-120): Pre-flight check 4 - target directory must not exist.
#                Scope: quickstart
#                Why: SPEC §2 forbids in-place scaffolding and §10 lists this
#                     as a fatal pre-flight check. Catching it before any
#                     template work preserves the atomicity invariant (§11/I8)
#                     trivially: there is nothing to roll back.
#                Done: Test ``test_quickstart_fails_when_directory_exists`` in
#                      ``tests/test_quickstart.py`` passes; the directory the
#                      user already had is untouched; the error suggests a
#                      different name or removing the existing directory.
#                Non-Goals: Do not add a ``--force`` flag; the spec explicitly
#                           rejects overwriting.


# TODO(EVO-130): Pre-flight check 5 - current working directory is writable.
#                Scope: quickstart
#                Why: SPEC §10 step 5 requires a fail-fast permission check so
#                     readonly-cwd users see a clear error rather than a
#                     partial ``mkdir`` failure midway through scaffolding.
#                Done: Test ``test_quickstart_requires_writable_cwd`` in
#                      ``tests/test_quickstart.py`` passes by asserting a
#                      non-zero exit and an actionable stderr when the current
#                      directory is read-only (the test creates a readonly
#                      temp dir and invokes the CLI from it).
#                Non-Goals: Do not attempt fancy capability probing; a write
#                           attempt (or ``os.access(os.W_OK)``) is sufficient.


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
