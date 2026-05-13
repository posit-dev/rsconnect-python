# probedev: ignore-file
# The xfail/skip reasons below cite ``TODO(EVO-###)`` markers by text. The real
# evolution markers live in ``rsconnect/`` and ``tests/smoke_boot_harness.py``;
# the strings here are pointers, not new markers. This pragma keeps
# ``probedev list`` focused on the real plan.
"""
Acceptance tests for ``rsconnect quickstart`` (SPEC_QUICKSTART.md §§ 2-12, 14-15).

Tests are written against the CLI using ``click.testing.CliRunner`` and inspect
externally observable behavior per SPEC §17.3: exit code, filesystem tree,
``pyproject.toml`` AST, stdout/stderr, and the populated ``.venv/``. They are
expected to fail today because the feature is not yet implemented; each test
cites the evolution marker that unblocks it via ``@pytest.mark.xfail``.

Test layout mirrors ``tests/test_main.py`` (CliRunner) and ``tests/test_pyproject.py``
(fixture- and parametrize-driven).
"""

from __future__ import annotations

import os
import pathlib
import re
import stat
import subprocess
import sys
import typing
from unittest import mock

import pytest

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 fallback
    import toml as tomllib  # type: ignore[no-redef]

from click.testing import CliRunner

from rsconnect.main import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_tmp_cwd(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Run the CLI with ``tmp_path`` as the current working directory.

    Quickstart writes to ``./<name>/`` in the CWD, so tests need a clean,
    isolated directory for every invocation.
    """
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _invoke_quickstart(runner: CliRunner, *args: str):
    return runner.invoke(cli, ["quickstart", *args], catch_exceptions=False)


def _read_pyproject(project_dir: pathlib.Path) -> typing.Mapping[str, typing.Any]:
    return tomllib.loads((project_dir / "pyproject.toml").read_text())


# ---------------------------------------------------------------------------
# Command shape (SPEC §2, §2.1)
# ---------------------------------------------------------------------------


def test_quickstart_command_is_registered(runner: CliRunner):
    """The ``quickstart`` subcommand exists and has help text."""
    result = runner.invoke(cli, ["quickstart", "--help"])
    assert result.exit_code == 0, result.output
    assert "quickstart" in result.output.lower()
    assert "TYPE" in result.output
    assert "NAME" in result.output


def test_quickstart_requires_type_and_name(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """Both positional args are required; invoking with none prints help."""
    result = runner.invoke(cli, ["quickstart"])
    # Click's ``no_args_is_help`` yields exit code 0 or 2 depending on version;
    # the important invariant is that it did not silently scaffold.
    assert not (in_tmp_cwd / "unnamed").exists()
    # Invoking with only the type must also fail loudly.
    result = runner.invoke(cli, ["quickstart", "streamlit"])
    assert result.exit_code != 0


def test_quickstart_help_exposes_static_and_shiny_flags(runner: CliRunner):
    result = runner.invoke(cli, ["quickstart", "--help"])
    assert result.exit_code == 0, result.output
    assert "--static" in result.output
    assert "--shiny" in result.output


@pytest.mark.parametrize(
    "args,expected",
    [
        (
            ["streamlit", "hello-app"],
            {"app_type": "streamlit", "name": "hello-app", "static": False, "shiny": False},
        ),
        (
            ["notebook", "--static", "hello-notebook"],
            {"app_type": "notebook", "name": "hello-notebook", "static": True, "shiny": False},
        ),
        (
            ["quarto", "--shiny", "hello-quarto"],
            {"app_type": "quarto", "name": "hello-quarto", "static": False, "shiny": True},
        ),
    ],
)
def test_quickstart_delegates_to_run_quickstart(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    args: typing.List[str],
    expected: typing.Mapping[str, typing.Any],
):
    run_quickstart = mock.Mock()
    monkeypatch.setattr("rsconnect.quickstart.run_quickstart", run_quickstart)

    result = runner.invoke(cli, ["quickstart", *args])

    assert result.exit_code == 0, result.output
    run_quickstart.assert_called_once_with(**expected)


# ---------------------------------------------------------------------------
# Pre-flight checks (SPEC §10)
# ---------------------------------------------------------------------------


def test_quickstart_requires_uv_on_path(runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Pre-flight check 1: absent ``uv`` must produce a clear, actionable error."""
    monkeypatch.setenv("PATH", str(in_tmp_cwd))  # empty PATH so uv cannot be found
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "uv" in combined.lower()
    assert not (in_tmp_cwd / "hello-app").exists()  # I8: no partial dir on pre-flight failure


def test_quickstart_uv_missing_message_names_install(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """The error message should include the recommended install command (SPEC §7)."""
    monkeypatch.setenv("PATH", str(in_tmp_cwd))
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    # "install" or "astral" or the canonical install URL - any of these proves
    # the message is actionable rather than a bare "not found".
    assert re.search(r"install|astral|github\.com/astral-sh/uv", combined, re.IGNORECASE)


def test_quickstart_unknown_type_lists_supported(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "nonesuch", "hello-app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    for expected in ("streamlit", "shiny", "fastapi", "api", "flask", "notebook", "voila", "quarto"):
        assert expected in combined, f"{expected!r} missing from error output: {combined!r}"
    assert not (in_tmp_cwd / "hello-app").exists()


@pytest.mark.parametrize(
    "bad_name",
    [
        "Hello",  # uppercase
        "1hello",  # leading digit
        "hello_world",  # underscore
        "hello-",  # trailing hyphen
        "-hello",  # leading hyphen
        "",  # empty
        "hello world",  # whitespace
    ],
)
def test_quickstart_rejects_invalid_name(runner: CliRunner, in_tmp_cwd: pathlib.Path, bad_name: str):
    result = _invoke_quickstart(runner, "streamlit", bad_name)
    assert result.exit_code != 0
    # Empty-name case resolves to the cwd itself, which always exists;
    # for every other invalid name, no partial directory may be left behind.
    if bad_name:
        assert not (in_tmp_cwd / bad_name).exists()


def test_quickstart_fails_when_directory_exists(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    (in_tmp_cwd / "hello-app").mkdir()
    (in_tmp_cwd / "hello-app" / "existing-file.txt").write_text("keep me")
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code != 0
    # The pre-existing file must be untouched (SPEC §11 Atomicity).
    assert (in_tmp_cwd / "hello-app" / "existing-file.txt").read_text() == "keep me"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod read-only semantics differ on Windows")
def test_quickstart_requires_writable_cwd(runner: CliRunner, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        monkeypatch.chdir(readonly)
        result = _invoke_quickstart(runner, "streamlit", "hello-app")
        assert result.exit_code != 0
        assert not (readonly / "hello-app").exists()
    finally:
        readonly.chmod(stat.S_IRWXU)


def test_quickstart_flask_alias_passes_type_validation(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """SPEC §4: 'flask' is accepted as an alias for 'api' at pre-flight."""
    result = _invoke_quickstart(runner, "flask", "hello-app")
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    # The type-validation gate does not reject 'flask'. The command still
    # fails downstream (scaffolding is not implemented yet); that failure
    # must not look like a type-rejection message.
    # `flask` should NOT appear in a "supported types" error listing.
    assert "Unsupported" not in combined and "supported types" not in combined.lower()


def test_quickstart_preflight_order_uv_before_type(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """SPEC §10: uv-presence is checked before type validation."""
    monkeypatch.setenv("PATH", str(in_tmp_cwd))  # uv unavailable
    result = _invoke_quickstart(runner, "nonesuch", "hello-app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "uv" in combined.lower()
    # If the type check had run, the message would name 'nonesuch'.
    assert "nonesuch" not in combined.lower()


# ---------------------------------------------------------------------------
# Always-present generated files (SPEC §5.1)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-140): Create the project directory and always-present files.",
)
def test_quickstart_generates_always_present_files(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello-app"
    for name in ("pyproject.toml", ".python-version", ".gitignore", "README.md"):
        assert (project / name).is_file(), f"{name} missing from {list(project.iterdir())}"


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-140): Create the project directory and always-present files (gitignore).",
)
def test_quickstart_gitignore_covers_rsconnect_dirs(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    gitignore = (in_tmp_cwd / "hello-app" / ".gitignore").read_text()
    for expected in ("__pycache__", ".venv", "rsconnect-python", ".env"):
        assert expected in gitignore, f"{expected} missing from .gitignore"


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-140): Invariant I6 - no manifest.json on scaffold.",
)
def test_quickstart_does_not_create_manifest_json(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    assert not (in_tmp_cwd / "hello-app" / "manifest.json").exists()


# ---------------------------------------------------------------------------
# pyproject.toml contents (SPEC §3 + §8.2)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-150): Write the [tool.rsconnect] table to pyproject.toml.",
)
def test_quickstart_pyproject_has_tool_rsconnect(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello-app")
    assert data["project"]["name"] == "hello-app"
    assert data["project"]["version"] == "0.0.1"
    tool_rsconnect = data["tool"]["rsconnect"]
    assert tool_rsconnect["app_mode"] == "python-streamlit"
    assert tool_rsconnect["entrypoint"] == "app.py"
    assert tool_rsconnect["title"] == "hello-app"


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-150): Write the [tool.rsconnect] table to pyproject.toml (no duplication).",
)
def test_quickstart_does_not_duplicate_deps_in_tool_rsconnect(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """SPEC §3.2: dependencies and requires-python live in [project], not in [tool.rsconnect]."""
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    tool_rsconnect = _read_pyproject(in_tmp_cwd / "hello-app")["tool"]["rsconnect"]
    assert "dependencies" not in tool_rsconnect
    assert "requires-python" not in tool_rsconnect
    assert "requires_python" not in tool_rsconnect
    assert set(tool_rsconnect.keys()) == {"app_mode", "entrypoint", "title"}


# ---------------------------------------------------------------------------
# Per-mode app_mode matrix (SPEC §4 / §8.2)
# ---------------------------------------------------------------------------


APP_MODE_MATRIX = [
    pytest.param(("streamlit",), "python-streamlit", id="streamlit"),
    pytest.param(("shiny",), "python-shiny", id="shiny"),
    pytest.param(("fastapi",), "python-fastapi", id="fastapi"),
    pytest.param(("api",), "python-api", id="api"),
    pytest.param(("flask",), "python-api", id="flask-alias"),
    pytest.param(("notebook",), "jupyter-static", id="notebook-default"),
    pytest.param(("notebook", "--static"), "jupyter-static", id="notebook-static"),
    pytest.param(("voila",), "jupyter-voila", id="voila"),
    pytest.param(("quarto",), "quarto-static", id="quarto-default"),
    pytest.param(("quarto", "--shiny"), "quarto-shiny", id="quarto-shiny"),
]


@pytest.mark.parametrize("cli_args,expected_mode", APP_MODE_MATRIX)
@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-150): Write the [tool.rsconnect] table to pyproject.toml (per-mode app_mode).",
)
def test_quickstart_app_mode_for_each_type(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    cli_args: tuple[str, ...],
    expected_mode: str,
):
    # Put flags before NAME per Click convention.
    args = [cli_args[0], *cli_args[1:], "hello-app"]
    result = _invoke_quickstart(runner, *args)
    assert result.exit_code == 0, result.output
    assert _read_pyproject(in_tmp_cwd / "hello-app")["tool"]["rsconnect"]["app_mode"] == expected_mode


# ---------------------------------------------------------------------------
# Per-category file sets (SPEC §6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_type,expected_files,forbidden_files",
    [
        ("streamlit", {"app.py"}, {"__connect__.py", "__main__.py", "notebook.ipynb", "report.qmd"}),
        ("shiny", {"app.py"}, {"__connect__.py", "__main__.py", "notebook.ipynb", "report.qmd"}),
        ("fastapi", {"app.py", "__connect__.py", "__main__.py"}, {"notebook.ipynb", "report.qmd"}),
        ("api", {"app.py", "__connect__.py", "__main__.py"}, {"notebook.ipynb", "report.qmd"}),
        ("notebook", {"notebook.ipynb"}, {"app.py", "__connect__.py", "__main__.py", "report.qmd"}),
        ("voila", {"notebook.ipynb"}, {"app.py", "__connect__.py", "__main__.py", "report.qmd"}),
        ("quarto", {"report.qmd"}, {"app.py", "__connect__.py", "__main__.py", "notebook.ipynb"}),
    ],
)
@pytest.mark.xfail(
    strict=False,
    reason=(
        "TODO(EVO-160..220): Register the per-mode templates " "(file set covered by EVO-160..220 - one per app mode)."
    ),
)
def test_quickstart_mode_file_set(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    expected_files: set[str],
    forbidden_files: set[str],
):
    result = _invoke_quickstart(runner, app_type, "hello-app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello-app"
    present = {p.name for p in project.iterdir() if p.is_file()}
    for name in expected_files:
        assert name in present, f"{name} missing; got {present}"
    for name in forbidden_files:
        assert name not in present, f"{name} unexpectedly present; SPEC §6 forbids it for {app_type}"


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-180): Register the fastapi template (module-style, entrypoint).",
)
def test_quickstart_fastapi_entrypoint_is_connect_app(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "fastapi", "hello-app")
    assert result.exit_code == 0, result.output
    tool_rsconnect = _read_pyproject(in_tmp_cwd / "hello-app")["tool"]["rsconnect"]
    assert tool_rsconnect["entrypoint"] == "__connect__:app"
    connect_py = (in_tmp_cwd / "hello-app" / "__connect__.py").read_text()
    assert "create_app" in connect_py
    assert "app = " in connect_py


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-180): Register the fastapi template (module-style, __main__).",
)
def test_quickstart_fastapi_main_runs_uvicorn(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "fastapi", "hello-app")
    assert result.exit_code == 0, result.output
    main_py = (in_tmp_cwd / "hello-app" / "__main__.py").read_text()
    assert "uvicorn" in main_py


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-190): Register the api / flask template.",
)
def test_quickstart_api_main_runs_flask_dev_server(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "api", "hello-app")
    assert result.exit_code == 0, result.output
    main_py = (in_tmp_cwd / "hello-app" / "__main__.py").read_text()
    assert "flask" in main_py.lower() or "app.run(" in main_py


# ---------------------------------------------------------------------------
# Venv population (SPEC §5.1, §7, I5)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-240): Run uv venv + uv sync inside the scaffolded directory.",
)
def test_quickstart_creates_populated_venv(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello-app"
    assert (project / ".venv").is_dir()
    # A populated venv has a site-packages or pyvenv.cfg.
    assert (project / ".venv" / "pyvenv.cfg").is_file()


# ---------------------------------------------------------------------------
# Atomicity on failure (SPEC §11, I8)
# ---------------------------------------------------------------------------


# strict=True: today this would XPASS for the wrong reason (no rollback runs
# because the scaffold phase that would invoke the fake uv is not implemented
# yet, so nothing is ever created to roll back). Flip to xfail-non-strict and
# remove the decorator once the real rollback path lands.
@pytest.mark.xfail(
    strict=True,
    reason="TODO(EVO-250): Implement atomic rollback of ./<name>/ on any failure.",
)
def test_quickstart_rolls_back_directory_on_uv_failure(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Force ``uv`` to fail and assert the project directory is removed."""
    fake_uv_dir = in_tmp_cwd / "fake-bin"
    fake_uv_dir.mkdir()
    fake_uv = fake_uv_dir / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake_uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_uv_dir}{os.pathsep}{os.environ['PATH']}")

    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code != 0
    assert not (in_tmp_cwd / "hello-app").exists()  # I8: all or nothing


# ---------------------------------------------------------------------------
# Post-scaffold output (SPEC §12, I7)
# ---------------------------------------------------------------------------


POST_SCAFFOLD_COMMANDS = [
    pytest.param("streamlit", (), "uv run streamlit run app.py", id="streamlit"),
    pytest.param("shiny", (), "uv run shiny run app.py", id="shiny"),
    pytest.param("fastapi", (), "uv run python -m hello-app", id="fastapi"),
    pytest.param("api", (), "uv run python -m hello-app", id="api"),
    pytest.param("flask", (), "uv run python -m hello-app", id="flask-alias"),
    pytest.param("notebook", (), "uv run jupyter lab notebook.ipynb", id="notebook"),
    pytest.param("voila", (), "uv run voila notebook.ipynb", id="voila"),
    pytest.param("quarto", (), "uv run quarto preview report.qmd", id="quarto-default"),
    pytest.param("quarto", ("--shiny",), "uv run quarto preview report.qmd", id="quarto-shiny"),
]


@pytest.mark.parametrize("app_type,extra_flags,local_run", POST_SCAFFOLD_COMMANDS)
@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-260): Emit the post-scaffold confirmation and command lines.",
)
def test_quickstart_post_scaffold_output(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    extra_flags: tuple[str, ...],
    local_run: str,
):
    result = _invoke_quickstart(runner, app_type, *extra_flags, "hello-app")
    assert result.exit_code == 0, result.output
    assert "hello-app" in result.output  # confirmation line
    assert local_run in result.output
    assert "rsconnect deploy pyproject hello-app" in result.output


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-260): Emit the post-scaffold confirmation and command lines (README parity).",
)
def test_quickstart_readme_matches_post_scaffold_output(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    readme = (in_tmp_cwd / "hello-app" / "README.md").read_text()
    assert "uv run streamlit run app.py" in readme
    assert "rsconnect deploy pyproject hello-app" in readme


# ---------------------------------------------------------------------------
# Invariants (SPEC §15, I1-I10)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-080): Invariants I1-I2 - directory exists and pyproject is valid (covered by the full pipeline).",
)
def test_invariant_I1_I2_directory_and_pyproject(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello-app"
    assert project.is_dir()
    data = _read_pyproject(project)
    assert data["project"]["name"] == "hello-app"
    for required in ("app_mode", "entrypoint", "title"):
        assert required in data["tool"]["rsconnect"]


# strict=True: today this XPASSes via the directory-must-not-exist pre-flight,
# but the test is intended to prove pipeline-level failure translation, not the
# pre-flight short-circuit. Remove the decorator once the real pipeline path
# raises and the message-quality assertions exercise that translation.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "TODO(EVO-080): Invariants I9-I10 - non-zero exit and actionable "
        "stderr on failure (pipeline error translation)."
    ),
)
def test_invariant_I9_I10_failure_exit_and_message(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    (in_tmp_cwd / "hello-app").mkdir()
    result = _invoke_quickstart(runner, "streamlit", "hello-app")
    assert result.exit_code != 0  # I9
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "hello-app" in combined  # I10 - message names the failing check


# ---------------------------------------------------------------------------
# Template registry extensibility (SPEC §4.1)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-230): Define the template registry layout and extension contract.",
)
def test_quickstart_registry_accepts_new_mode(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A future template can be registered by inserting into the registry alone.

    This test is aspirational - it documents the extensibility invariant from
    SPEC §4.1. The implementer decides the exact registry shape; what matters
    is that inserting a ninth mode does not require touching pre-flight,
    pyproject writing, or post-scaffold output modules.
    """
    # Import here so the test collection does not fail before the module exists.
    import rsconnect.quickstart as quickstart_mod  # noqa: F401

    # The implementer provides a registry accessor; the test asserts extension
    # works without other code changes. Exact API is left to the evolution.
    assert hasattr(quickstart_mod, "run_quickstart")


# ---------------------------------------------------------------------------
# Per-mode boot smoke tests (SPEC §14.1)
# ---------------------------------------------------------------------------


BOOT_SMOKE_MATRIX = [
    pytest.param("streamlit", ("streamlit", "run", "app.py"), "http", id="streamlit"),
    pytest.param("shiny", ("shiny", "run", "app.py"), "http", id="shiny"),
    pytest.param("fastapi", ("python", "-m", "hello-app"), "http", id="fastapi"),
    pytest.param("api", ("python", "-m", "hello-app"), "http", id="api"),
    pytest.param("voila", ("voila", "notebook.ipynb"), "http", id="voila"),
    pytest.param("notebook", ("jupyter", "nbconvert", "--execute", "notebook.ipynb"), "artifact", id="notebook"),
    pytest.param("quarto", ("quarto", "render", "report.qmd"), "artifact", id="quarto"),
]


@pytest.mark.parametrize("app_type,local_cmd,readiness", BOOT_SMOKE_MATRIX)
@pytest.mark.skip(
    reason="TODO(EVO-280): Per-mode boot smoke test harness (SPEC §14.1).",
)
def test_quickstart_per_mode_boot_smoke(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    local_cmd: tuple[str, ...],
    readiness: str,
):
    """Boot smoke test per SPEC §14.1.

    Implementation note: the evolution that graduates this test must add a
    harness that (1) runs quickstart, (2) runs the documented local-run
    command via ``uv run ...``, (3) asserts readiness - HTTP GET for web
    modes, artifact existence for notebook/quarto - and (4) cleans up. Until
    that harness exists, the tests stay skipped.
    """
    result = _invoke_quickstart(runner, app_type, "hello-app")
    assert result.exit_code == 0
    proc = subprocess.Popen(["uv", "run", *local_cmd], cwd=in_tmp_cwd / "hello-app")
    try:
        assert proc.poll() is None
    finally:
        proc.terminate()
