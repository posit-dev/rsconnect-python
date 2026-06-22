"""
Acceptance tests for ``rsconnect quickstart``.

Tests are written against the CLI using ``click.testing.CliRunner`` and inspect
externally observable behavior: exit code, filesystem tree, ``pyproject.toml``
AST, stdout/stderr, and the populated ``.venv/``. Real ``uv venv`` + ``uv sync``
subprocesses run as part of the end-to-end coverage, so some tests incur a
short network round-trip.

The boot-smoke matrix (``test_quickstart_per_mode_boot_smoke``) drives the
helpers in ``tests/_local_run.py``: it scaffolds each mode, launches the
documented local-run command under ``uv run``, and asserts readiness
(HTTP probe for web modes; artifact existence for notebook/quarto).

Test layout mirrors ``tests/test_main.py`` (CliRunner) and ``tests/test_pyproject.py``
(fixture- and parametrize-driven).
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
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
from tests import _local_run


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
# Command shape
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


def test_quickstart_help_lists_quarto(runner: CliRunner):
    """``quarto`` is a supported TYPE; the broken ``quarto-shiny`` scaffold was removed."""
    result = runner.invoke(cli, ["quickstart", "--help"])
    assert result.exit_code == 0, result.output
    assert "quarto" in result.output
    assert "quarto-shiny" not in result.output
    # The legacy ``--shiny`` flag was removed in favor of the explicit type.
    assert "--shiny" not in result.output


def test_quickstart_quarto_shiny_not_supported(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """``quarto-shiny`` stays a known alias but no longer scaffolds.

    The template produced an invalid doc that Connect rejected, so the
    scaffold was removed while the alias still routes to the shared
    "does not yet support" error rather than a hard "unknown type".
    """
    result = _invoke_quickstart(runner, "quarto-shiny", "hello_app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "does not yet support" in combined
    assert "quarto-shiny" in combined
    assert not (in_tmp_cwd / "hello_app").exists()


@pytest.mark.parametrize(
    "args,expected",
    [
        (
            ["streamlit", "hello_app"],
            {"app_type": "streamlit", "name": "hello_app", "python_version": None},
        ),
        (
            ["notebook", "hello_notebook"],
            {"app_type": "notebook", "name": "hello_notebook", "python_version": None},
        ),
        (
            ["quarto-shiny", "hello_quarto"],
            {"app_type": "quarto-shiny", "name": "hello_quarto", "python_version": None},
        ),
        (
            ["streamlit", "hello_app", "--python", ">=3.11"],
            {"app_type": "streamlit", "name": "hello_app", "python_version": ">=3.11"},
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
    monkeypatch.setattr("rsconnect.quickstart.quickstart.run_quickstart", run_quickstart)

    result = runner.invoke(cli, ["quickstart", *args])

    assert result.exit_code == 0, result.output
    run_quickstart.assert_called_once_with(**expected)


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def test_quickstart_requires_uv_on_path(runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Pre-flight check 1: absent ``uv`` must produce a clear, actionable error."""
    monkeypatch.setenv("PATH", str(in_tmp_cwd))  # empty PATH so uv cannot be found
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "uv" in combined.lower()
    assert not (in_tmp_cwd / "hello_app").exists()  # no partial dir on pre-flight failure


def test_quickstart_uv_missing_message_names_install(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """The error message should include the recommended install command."""
    monkeypatch.setenv("PATH", str(in_tmp_cwd))
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    # "install" or "astral" or the canonical install URL - any of these proves
    # the message is actionable rather than a bare "not found".
    assert re.search(r"install|astral|github\.com/astral-sh/uv", combined, re.IGNORECASE)


def test_quickstart_unknown_type_lists_supported(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "nonesuch", "hello_app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    for expected in ("streamlit", "shiny", "fastapi", "api", "flask", "notebook", "voila", "quarto"):
        assert expected in combined, f"{expected!r} missing from error output: {combined!r}"
    assert not (in_tmp_cwd / "hello_app").exists()


@pytest.mark.parametrize(
    "bad_name",
    [
        "Hello",  # uppercase
        "1hello",  # leading digit
        "hello-app",  # hyphen (not a valid Python identifier)
        "hello-world",  # hyphen
        "hello_",  # trailing underscore
        "_hello",  # leading underscore
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
    (in_tmp_cwd / "hello_app").mkdir()
    (in_tmp_cwd / "hello_app" / "existing-file.txt").write_text("keep me")
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code != 0
    # The pre-existing file must be untouched (atomicity).
    assert (in_tmp_cwd / "hello_app" / "existing-file.txt").read_text() == "keep me"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod read-only semantics differ on Windows")
def test_quickstart_requires_writable_cwd(runner: CliRunner, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        monkeypatch.chdir(readonly)
        result = _invoke_quickstart(runner, "streamlit", "hello_app")
        assert result.exit_code != 0
        assert not (readonly / "hello_app").exists()
    finally:
        readonly.chmod(stat.S_IRWXU)


def test_quickstart_flask_alias_passes_type_validation(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """'flask' is accepted as an alias for 'api' at pre-flight."""
    result = _invoke_quickstart(runner, "flask", "hello_app")
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    # The type-validation gate does not reject 'flask'. The command still
    # fails downstream (scaffolding is not implemented yet); that failure
    # must not look like a type-rejection message.
    # `flask` should NOT appear in a "supported types" error listing.
    assert "Unsupported" not in combined and "supported types" not in combined.lower()


# ---------------------------------------------------------------------------
# Always-present generated files
# ---------------------------------------------------------------------------


def test_quickstart_generates_always_present_files(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello_app"
    for name in ("pyproject.toml", ".gitignore", "README.md"):
        assert (project / name).is_file(), f"{name} missing from {list(project.iterdir())}"
    # No separate ``.python-version`` is emitted: ``requires-python`` in
    # ``pyproject.toml`` is the single source of truth for the Python pin.
    assert not (project / ".python-version").exists()


def test_quickstart_gitignore_covers_rsconnect_dirs(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    gitignore = (in_tmp_cwd / "hello_app" / ".gitignore").read_text()
    for expected in ("__pycache__", ".venv", "rsconnect-python", ".env"):
        assert expected in gitignore, f"{expected} missing from .gitignore"


def test_quickstart_does_not_create_manifest_json(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    assert not (in_tmp_cwd / "hello_app" / "manifest.json").exists()


# ---------------------------------------------------------------------------
# pyproject.toml contents
# ---------------------------------------------------------------------------


def test_quickstart_pyproject_has_tool_rsconnect(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["project"]["name"] == "hello_app"
    assert data["project"]["version"] == "0.0.1"
    # ``requires-python`` tracks the interpreter that ran ``rsconnect quickstart``.
    expected_requires = ">={}.{}".format(*sys.version_info[:2])
    assert data["project"]["requires-python"] == expected_requires
    assert data["project"]["dependencies"] == ["streamlit"]
    tool_rsconnect = data["tool"]["rsconnect"]
    assert tool_rsconnect["app_mode"] == "python-streamlit"
    assert tool_rsconnect["entrypoint"] == "app.py"
    assert tool_rsconnect["title"] == "hello_app"
    # Scaffolded projects ship a uv.lock from ``uv sync``; default deploys
    # use it so ``rsconnect deploy pyproject`` is reproducible out of the box.
    assert tool_rsconnect["requirements_file"] == "uv.lock"


def test_quickstart_does_not_duplicate_deps_in_tool_rsconnect(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """``dependencies`` and ``requires-python`` live in ``[project]``, not in ``[tool.rsconnect]``."""
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    tool_rsconnect = _read_pyproject(in_tmp_cwd / "hello_app")["tool"]["rsconnect"]
    assert "dependencies" not in tool_rsconnect
    assert "requires-python" not in tool_rsconnect
    assert "requires_python" not in tool_rsconnect
    assert set(tool_rsconnect.keys()) == {"app_mode", "entrypoint", "title", "requirements_file"}


def test_quickstart_python_option_sets_requires_python(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """``--python`` overrides the detected interpreter version in ``requires-python``."""
    monkeypatch.setattr("rsconnect.quickstart.quickstart._install_venv", lambda target: None)
    result = _invoke_quickstart(runner, "streamlit", "--python", ">=3.10", "hello_app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["project"]["requires-python"] == ">=3.10"


def test_quickstart_python_option_used_verbatim(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A value starting with an operator (incl. a range) passes through unchanged."""
    monkeypatch.setattr("rsconnect.quickstart.quickstart._install_venv", lambda target: None)
    result = _invoke_quickstart(runner, "streamlit", "--python", ">=3.11,<3.14", "hello_app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["project"]["requires-python"] == ">=3.11,<3.14"


def test_quickstart_python_option_bare_version_means_any_patch(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A bare ``major.minor`` becomes ``==3.10.*`` so any 3.10.x satisfies it."""
    monkeypatch.setattr("rsconnect.quickstart.quickstart._install_venv", lambda target: None)
    result = _invoke_quickstart(runner, "streamlit", "--python", "3.10", "hello_app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["project"]["requires-python"] == "==3.10.*"


def test_quickstart_python_option_full_version_is_exact(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A full ``major.minor.patch`` becomes ``==3.11.14`` (exact, no trailing ``.*``)."""
    monkeypatch.setattr("rsconnect.quickstart.quickstart._install_venv", lambda target: None)
    result = _invoke_quickstart(runner, "streamlit", "--python", "3.11.14", "hello_app")
    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["project"]["requires-python"] == "==3.11.14"


# ---------------------------------------------------------------------------
# Per-mode app_mode matrix
# ---------------------------------------------------------------------------


APP_MODE_MATRIX = [
    pytest.param(("streamlit",), "python-streamlit", id="streamlit"),
    pytest.param(("shiny",), "python-shiny", id="shiny"),
    pytest.param(("fastapi",), "python-fastapi", id="fastapi"),
    pytest.param(("api",), "python-api", id="api"),
    pytest.param(("flask",), "python-api", id="flask-alias"),
    pytest.param(("notebook",), "jupyter-static", id="notebook-default"),
    pytest.param(("voila",), "jupyter-voila", id="voila"),
    pytest.param(("quarto",), "quarto-static", id="quarto-default"),
]


@pytest.mark.parametrize("cli_args,expected_mode", APP_MODE_MATRIX)
def test_quickstart_app_mode_for_each_type(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    cli_args: tuple[str, ...],
    expected_mode: str,
):
    # Put flags before NAME per Click convention.
    args = [cli_args[0], *cli_args[1:], "hello_app"]
    result = _invoke_quickstart(runner, *args)
    assert result.exit_code == 0, result.output
    tool_rsconnect = _read_pyproject(in_tmp_cwd / "hello_app")["tool"]["rsconnect"]
    assert tool_rsconnect["app_mode"] == expected_mode
    if expected_mode == "python-api":
        # Flask aliases to api: both module-style modes share entrypoint.
        assert tool_rsconnect["entrypoint"] == "hello_app.__connect__:app"


# ---------------------------------------------------------------------------
# Per-category file sets
# ---------------------------------------------------------------------------


# Expected per-mode source files: ``path → content_sentinel``. Empty
# sentinel means "must exist; body not asserted". The four always-present
# files are tested separately by ``_ALWAYS_PRESENT``.
EXPECTED_FILES = [
    pytest.param("streamlit", {"app.py": "streamlit"}, id="streamlit"),
    pytest.param("shiny", {"app.py": "shiny"}, id="shiny"),
    pytest.param(
        "fastapi",
        {
            "hello_app/__init__.py": "",
            "hello_app/__main__.py": "uvicorn",
            "hello_app/__connect__.py": "create_app",
            "hello_app/app.py": "FastAPI",
        },
        id="fastapi",
    ),
    pytest.param(
        "api",
        {
            "hello_app/__init__.py": "",
            "hello_app/__main__.py": "app.run(",
            "hello_app/__connect__.py": "create_app",
            "hello_app/app.py": "Flask",
        },
        id="api",
    ),
    pytest.param(
        "flask",
        {
            "hello_app/__init__.py": "",
            "hello_app/__main__.py": "app.run(",
            "hello_app/__connect__.py": "create_app",
            "hello_app/app.py": "Flask",
        },
        id="flask-alias",
    ),
    pytest.param("notebook", {"notebook.ipynb": "cells"}, id="notebook"),
    pytest.param("voila", {"notebook.ipynb": "cells"}, id="voila"),
    pytest.param("quarto", {"report.qmd": "title"}, id="quarto"),
]

_ALWAYS_PRESENT = {"pyproject.toml", ".gitignore", "README.md"}
_IGNORED_PARTS = {".venv", "__pycache__"}
_IGNORED_FILES = {"uv.lock"}


@pytest.mark.parametrize("app_type,expected_sources", EXPECTED_FILES)
def test_quickstart_mode_file_set(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    expected_sources: typing.Mapping[str, str],
):
    """Each mode writes EXACTLY the always-present files plus its expected sources."""
    result = _invoke_quickstart(runner, app_type, "hello_app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello_app"

    actual: set[str] = set()
    for p in project.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(project)
        if any(part in _IGNORED_PARTS for part in rel.parts):
            continue
        if rel.name in _IGNORED_FILES:
            continue
        # ``as_posix`` normalizes the separator so the expected set (always
        # written with ``/``) matches on Windows where ``str(rel)`` uses ``\``.
        actual.add(rel.as_posix())

    expected = _ALWAYS_PRESENT | set(expected_sources.keys())
    assert actual == expected, (
        f"file set mismatch:\n" f"  extra:   {sorted(actual - expected)}\n" f"  missing: {sorted(expected - actual)}"
    )

    for path, sentinel in expected_sources.items():
        if sentinel:
            body = (project / path).read_text()
            assert sentinel in body, f"{path}: missing sentinel {sentinel!r}\n{body}"


def test_quickstart_fastapi_entrypoint_is_connect_app(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "fastapi", "hello_app")
    assert result.exit_code == 0, result.output
    tool_rsconnect = _read_pyproject(in_tmp_cwd / "hello_app")["tool"]["rsconnect"]
    assert tool_rsconnect["entrypoint"] == "hello_app.__connect__:app"
    connect_py = (in_tmp_cwd / "hello_app" / "hello_app" / "__connect__.py").read_text()
    assert "create_app" in connect_py
    assert "app = " in connect_py


def test_quickstart_fastapi_main_runs_uvicorn(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "fastapi", "hello_app")
    assert result.exit_code == 0, result.output
    main_py = (in_tmp_cwd / "hello_app" / "hello_app" / "__main__.py").read_text()
    assert "uvicorn" in main_py


def test_quickstart_api_main_runs_flask_dev_server(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "api", "hello_app")
    assert result.exit_code == 0, result.output
    main_py = (in_tmp_cwd / "hello_app" / "hello_app" / "__main__.py").read_text()
    assert "flask" in main_py.lower() or "app.run(" in main_py


@pytest.mark.parametrize(
    "app_type,filename",
    [
        ("streamlit", "app.py"),
        ("quarto", "report.qmd"),
        ("notebook", "notebook.ipynb"),
        # ``fastapi`` and ``api`` materialize ``<name>/<name>/__init__.py``;
        # asserting the body proves substitution runs on BOTH the rendered
        # path and the file content for the nested-package layout.
        ("fastapi", "alt_project/__init__.py"),
        ("api", "alt_project/__init__.py"),
    ],
)
def test_quickstart_substitutes_name_in_template_body(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, app_type: str, filename: str
):
    """Verify ``{name}`` substitution actually runs on template content."""
    result = _invoke_quickstart(runner, app_type, "alt_project")
    assert result.exit_code == 0, result.output
    body = (in_tmp_cwd / "alt_project" / filename).read_text()
    assert "alt_project" in body, body


def test_quickstart_notebook_is_valid_json(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """The generated notebook.ipynb must parse as JSON after name substitution."""
    result = _invoke_quickstart(runner, "notebook", "hello_app")
    assert result.exit_code == 0, result.output
    body = (in_tmp_cwd / "hello_app" / "notebook.ipynb").read_text()
    data = json.loads(body)
    assert data["nbformat"] >= 4
    assert isinstance(data["cells"], list) and len(data["cells"]) >= 1


def test_quickstart_voila_and_notebook_share_template(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """voila reuses the notebook template rather than duplicating it."""
    _invoke_quickstart(runner, "notebook", "hello_app")
    notebook_body = (in_tmp_cwd / "hello_app" / "notebook.ipynb").read_text()
    shutil.rmtree(in_tmp_cwd / "hello_app")
    _invoke_quickstart(runner, "voila", "hello_app")
    voila_body = (in_tmp_cwd / "hello_app" / "notebook.ipynb").read_text()
    assert notebook_body == voila_body


# ---------------------------------------------------------------------------
# Venv population
# ---------------------------------------------------------------------------


def test_install_venv_clears_virtual_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """``uv`` must not see the developer's activated venv (avoids the venv-mismatch warning)."""
    monkeypatch.setenv("VIRTUAL_ENV", "/some/parent/.venv")
    captured_envs: typing.List[typing.Mapping[str, str]] = []

    def fake_run(cmd, cwd, env):
        captured_envs.append(env)
        return mock.Mock(returncode=0)

    monkeypatch.setattr("rsconnect.quickstart.quickstart.subprocess.run", fake_run)
    from rsconnect.quickstart.quickstart import _install_venv

    _install_venv(tmp_path)

    assert len(captured_envs) == 2  # uv venv + uv sync
    for env in captured_envs:
        assert "VIRTUAL_ENV" not in env, env


def test_quickstart_creates_populated_venv(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello_app"
    assert (project / ".venv").is_dir()
    # A populated venv has a site-packages or pyvenv.cfg.
    assert (project / ".venv" / "pyvenv.cfg").is_file()
    # uv sync writes uv.lock; ``uv venv`` alone does not. Catches a future
    # regression that creates the venv but skips dependency resolution.
    assert (project / "uv.lock").is_file()


# ---------------------------------------------------------------------------
# Atomicity on failure
# ---------------------------------------------------------------------------


def _force_uv_to_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``subprocess.run`` return ``returncode=1`` for the ``uv`` invocations
    inside the scaffold pipeline. Cross-platform: avoids the brittle
    "fake binary on PATH" trick which cannot execute extension-less shell
    scripts under ``CreateProcessW`` on Windows.
    """

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_quickstart_rolls_back_directory_on_uv_failure(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Force ``uv`` to fail and assert the project directory is removed."""
    _force_uv_to_fail(monkeypatch)

    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code != 0
    assert not (in_tmp_cwd / "hello_app").exists()  # all or nothing


def test_quickstart_rolls_back_on_keyboard_interrupt(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Ctrl-C mid-pipeline triggers the same rollback path as a uv failure.

    The production ``except BaseException`` exists precisely so a user who
    aborts ``uv sync`` does not end up with a half-built project. This test
    pins that guarantee hermetically by raising ``KeyboardInterrupt`` from
    the venv-install phase; no real ``uv`` runs.
    """
    from rsconnect.quickstart import quickstart as qs

    monkeypatch.setattr(qs, "_install_venv", mock.MagicMock(side_effect=KeyboardInterrupt))

    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code != 0
    assert not (in_tmp_cwd / "hello_app").exists()


# ---------------------------------------------------------------------------
# Post-scaffold output
# ---------------------------------------------------------------------------


POST_SCAFFOLD_COMMANDS = [
    pytest.param("streamlit", (), "uv run streamlit run app.py", (), id="streamlit"),
    pytest.param("shiny", (), "uv run shiny run app.py", (), id="shiny"),
    pytest.param("fastapi", (), "uv run python -m hello_app", (), id="fastapi"),
    pytest.param("api", (), "uv run python -m hello_app", (), id="api"),
    pytest.param("flask", (), "uv run python -m hello_app", (), id="flask-alias"),
    pytest.param("notebook", (), "uv run jupyter lab notebook.ipynb", (), id="notebook"),
    pytest.param("voila", (), "uv run voila notebook.ipynb", (), id="voila"),
    pytest.param(
        "quarto",
        (),
        "uv run quarto preview report.qmd",
        ("Note: Quarto must be installed separately: https://quarto.org",),
        id="quarto-default",
    ),
]


@pytest.mark.parametrize("app_type,extra_flags,local_run,extra_lines", POST_SCAFFOLD_COMMANDS)
def test_quickstart_post_scaffold_output(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    extra_flags: tuple[str, ...],
    local_run: str,
    extra_lines: tuple[str, ...],
):
    result = _invoke_quickstart(runner, app_type, *extra_flags, "hello_app")
    assert result.exit_code == 0, result.output
    # The wording and order of the summary lines are part of the user-visible
    # contract; a substring check would tolerate extra debug output or reordering.
    lines = [line for line in result.output.splitlines() if line.strip()]
    expected = [
        "Project hello_app/ created.",
        "To get started:  cd hello_app",
        f"To run locally:  {local_run}",
        "To deploy:       rsconnect deploy pyproject .",
        *extra_lines,
    ]
    assert lines == expected, result.output


def test_quickstart_readme_matches_post_scaffold_output(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    readme = (in_tmp_cwd / "hello_app" / "README.md").read_text()
    # The README and stdout agree on the two commands the user needs.
    assert "uv run streamlit run app.py" in readme
    assert "rsconnect deploy pyproject ." in readme


def test_quickstart_quarto_readme_includes_install_note(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    """Per-mode notes appear in both stdout and README for quarto."""
    result = _invoke_quickstart(runner, "quarto", "hello_app")
    assert result.exit_code == 0, result.output
    readme = (in_tmp_cwd / "hello_app" / "README.md").read_text()
    assert "## Notes" in readme
    assert "Quarto must be installed separately" in readme
    # Pin the install URL so stdout (asserted in test_quickstart_post_scaffold_output)
    # and the on-disk README stay in agreement on the actionable link.
    assert "https://quarto.org" in readme


# ---------------------------------------------------------------------------
# End-to-end invariants
# ---------------------------------------------------------------------------


def test_invariant_I1_I2_directory_and_pyproject(runner: CliRunner, in_tmp_cwd: pathlib.Path):
    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code == 0, result.output
    project = in_tmp_cwd / "hello_app"
    assert project.is_dir()
    data = _read_pyproject(project)
    assert data["project"]["name"] == "hello_app"
    for required in ("app_mode", "entrypoint", "title"):
        assert required in data["tool"]["rsconnect"]


def test_invariant_I9_I10_failure_exit_and_message(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Pipeline failure produces non-zero exit and actionable stderr."""
    _force_uv_to_fail(monkeypatch)

    result = _invoke_quickstart(runner, "streamlit", "hello_app")
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "uv" in combined.lower()  # message names the failing tool


# ---------------------------------------------------------------------------
# Template registry extensibility
# ---------------------------------------------------------------------------


def test_quickstart_registry_accepts_new_mode(
    runner: CliRunner, in_tmp_cwd: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Adding a mode is "register an AppMode + alias + template directory."

    The test proves the extensibility contract: registering a new
    :class:`AppMode` + CLI alias in :class:`AppModes` and adding the
    corresponding ``_REGISTRY`` entry yields a working scaffold without
    touching the pre-flight, pyproject writer, or post-scaffold output
    modules.
    """
    import pkgutil

    from rsconnect.models import AppMode, AppModes
    from rsconnect.quickstart import quickstart as qs

    # Stand in for ``rsconnect/quickstart/templates/newmode/pyproject.toml.tmpl``:
    # the contract is "drop a template file under the package", so we hook
    # ``pkgutil.get_data`` to materialize the body without touching the
    # installed package on disk.
    new_pyproject_body = (
        "[project]\n"
        'name = "$name"\n'
        'version = "0.0.1"\n'
        'requires-python = "$requires_python"\n'
        "dependencies = []\n"
        "\n"
        "[tool.rsconnect]\n"
        'app_mode = "python-newmode"\n'
        'entrypoint = "app.py"\n'
        'title = "$name"\n'
    )
    new_readme_body = "# $name\n\nNew mode scaffold.\n"
    fake_templates = {
        "newmode/pyproject.toml.tmpl": new_pyproject_body,
        "newmode/README.md.tmpl": new_readme_body,
    }
    real_get_data = pkgutil.get_data

    def fake_get_data(package: str, resource: str):
        if resource in fake_templates:
            return fake_templates[resource].encode("utf-8")
        return real_get_data(package, resource)

    monkeypatch.setattr(pkgutil, "get_data", fake_get_data)

    new_spec = qs.TemplateSpec(
        pyproject_template="newmode/pyproject.toml.tmpl",
        readme_template="newmode/README.md.tmpl",
        local_run_command=("uv", "run", "newtool", "app.py"),
        source_files=(),
    )
    # Mint a fresh AppMode singleton and register the alias on AppModes.
    # An ordinal of 999 is safely outside the declared range; the registry
    # entry only requires a hashable identity.
    new_app_mode = AppMode(999, "python-newmode", "New Mode App")
    extended_cli_aliases = dict(AppModes._cli_aliases)
    extended_cli_aliases["newmode"] = new_app_mode
    monkeypatch.setattr(AppModes, "_cli_aliases", extended_cli_aliases)
    extended_registry = dict(qs._REGISTRY)
    extended_registry[new_app_mode] = new_spec
    monkeypatch.setattr(qs, "_REGISTRY", extended_registry)
    # Click's argument type was bound at decorator time, so injecting a new
    # supported type means widening the choice list on the live command.
    quickstart_cmd = cli.commands["quickstart"]
    type_param = next(p for p in quickstart_cmd.params if p.name == "app_type")
    monkeypatch.setattr(type_param, "type", type(type_param.type)(AppModes.cli_aliases()))

    result = _invoke_quickstart(runner, "newmode", "hello_app")

    assert result.exit_code == 0, result.output
    data = _read_pyproject(in_tmp_cwd / "hello_app")
    assert data["tool"]["rsconnect"]["app_mode"] == "python-newmode"
    assert data["tool"]["rsconnect"]["entrypoint"] == "app.py"
    assert data["project"]["dependencies"] == []


# ---------------------------------------------------------------------------
# Per-mode boot smoke tests
# ---------------------------------------------------------------------------


# nbconvert pulls mistune>=3.3, which uses re.Pattern[str] and is broken on
# Python 3.8; skip the jupyter-based scaffolds there.
_PY38_NBCONVERT_SKIP = pytest.mark.skipif(
    sys.version_info < (3, 9),
    reason="nbconvert pulls mistune>=3.3 which is broken on Python 3.8",
)

BOOT_SMOKE_MATRIX = [
    pytest.param("streamlit", "http", id="streamlit"),
    pytest.param("shiny", "http", id="shiny"),
    pytest.param("fastapi", "http", id="fastapi"),
    pytest.param("api", "http", id="api"),
    pytest.param("voila", "http", id="voila", marks=_PY38_NBCONVERT_SKIP),
    pytest.param("notebook", "artifact", id="notebook", marks=_PY38_NBCONVERT_SKIP),
    pytest.param("quarto", "artifact", id="quarto"),
]


@pytest.mark.skipif(sys.platform == "win32", reason="boot smoke uses POSIX process groups")
@pytest.mark.parametrize("app_type,readiness", BOOT_SMOKE_MATRIX)
def test_quickstart_per_mode_boot_smoke(
    runner: CliRunner,
    in_tmp_cwd: pathlib.Path,
    app_type: str,
    readiness: str,
):
    """Each scaffolded project boots cleanly.

    HTTP modes bind a probe-allocated port and respond to GET ``/`` with a
    non-5xx status; artifact modes render to a non-empty output file and
    exit 0. Failures from a framework release (renamed flag, broken
    default) make this test red.
    """
    if app_type == "quarto" and shutil.which("quarto") is None:
        pytest.skip("quarto CLI not installed")

    result = _invoke_quickstart(runner, app_type, "hello_app")
    assert result.exit_code == 0, result.output
    project_dir = in_tmp_cwd / "hello_app"

    if readiness == "http":
        port = _local_run.find_free_port()
        cmd, extra_env = _local_run.http_command(app_type, port)
        with _local_run.spawn(cmd, cwd=project_dir, extra_env=extra_env) as proc:
            _local_run.wait_for_http(port, proc=proc)
    else:
        cmd = _local_run.artifact_command(app_type)
        target = _local_run.artifact_path(app_type, project_dir)
        with _local_run.spawn(cmd, cwd=project_dir) as proc:
            _local_run.wait_for_artifact(proc, target)
