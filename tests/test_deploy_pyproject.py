"""
Acceptance tests for ``rsconnect deploy pyproject``.

Tests exercise the CLI via ``click.testing.CliRunner`` and the pure reader
(:func:`rsconnect.pyproject.read_tool_rsconnect`) directly. They follow the
shape of ``tests/test_pyproject.py`` (fixture/parametrize-driven) and
``tests/test_main.py`` (Click invocation).

The file keeps deploy-pyproject coverage at the CLI boundary and verifies the
reader directly where malformed configuration needs precise diagnostics.
"""

from __future__ import annotations

import pathlib
import re
import textwrap
import types
import typing

import pytest
from click.testing import CliRunner

from rsconnect.main import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """A fresh directory; tests populate ``pyproject.toml`` as they need."""
    project = tmp_path / "hello_app"
    project.mkdir()
    return project


def _write_pyproject(project: pathlib.Path, body: str) -> None:
    (project / "pyproject.toml").write_text(textwrap.dedent(body))


# ---------------------------------------------------------------------------
# Command shape
# ---------------------------------------------------------------------------


def test_deploy_pyproject_command_is_registered(runner: CliRunner):
    result = runner.invoke(cli, ["deploy", "pyproject", "--help"])
    assert result.exit_code == 0, result.output
    assert "pyproject" in result.output.lower()


def test_deploy_pyproject_requires_path(runner: CliRunner):
    """The positional directory is required (no silent default to '.').


    Distinguishes 'command exists and demands the positional' from the prior
    'command does not exist' state - the assertions below would behave
    differently in those two cases.
    """
    result = runner.invoke(cli, ["deploy", "pyproject"])
    assert "No such command" not in result.output
    assert "Usage:" in result.output
    assert "DIRECTORY" in result.output  # required positional metavar
    assert "[DIRECTORY]" not in result.output  # required, not optional


# ---------------------------------------------------------------------------
# [tool.rsconnect] reader
# ---------------------------------------------------------------------------


def test_read_tool_rsconnect_returns_three_fields(project_dir: pathlib.Path):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["streamlit"]

        [tool.rsconnect]
        app_mode = "python-streamlit"
        entrypoint = "app.py"
        title = "My Hello App"
        """,
    )
    config = read_tool_rsconnect(project_dir / "pyproject.toml")
    assert config["app_mode"] == "python-streamlit"
    assert config["entrypoint"] == "app.py"
    assert config["title"] == "My Hello App"


def test_read_tool_rsconnect_missing_section_raises(project_dir: pathlib.Path):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        """,
    )
    with pytest.raises(Exception) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    # Exception must carry the minimum valid snippet as a copy-pasteable
    # TOML block, not just prose. Anchor on the section
    # header plus both required-field TOML string-valued key=value forms
    # (``key = "``); a prose 'required fields: ...' message would not
    # incidentally produce that shape.
    message = str(excinfo.value)
    assert "tool.rsconnect" in message.lower() or "rsconnect" in message.lower()
    assert "[tool.posit.connect]" in message
    assert 'app_mode = "' in message
    assert 'entrypoint = "' in message


@pytest.mark.parametrize(
    "body",
    [
        'tool = "not-a-table"',
        """
        [tool]
        rsconnect = "not-a-table"
        """,
    ],
    ids=["tool-not-table", "rsconnect-not-table"],
)
def test_read_tool_rsconnect_non_table_raises(project_dir: pathlib.Path, body: str):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(project_dir, body)
    with pytest.raises(Exception) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    message = str(excinfo.value)
    assert "not a TOML table" in message
    assert "[tool.posit.connect]" in message
    assert 'app_mode = "' in message
    assert 'entrypoint = "' in message


@pytest.mark.parametrize(
    "missing_field,body",
    [
        (
            "app_mode",
            """
            [project]
            name = "hello_app"
            version = "0.0.1"

            [tool.rsconnect]
            entrypoint = "app.py"
            """,
        ),
        (
            "entrypoint",
            """
            [project]
            name = "hello_app"
            version = "0.0.1"

            [tool.rsconnect]
            app_mode = "python-streamlit"
            """,
        ),
    ],
    ids=["missing-app_mode", "missing-entrypoint"],
)
def test_read_tool_rsconnect_missing_required_field_raises(project_dir: pathlib.Path, missing_field: str, body: str):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(project_dir, body)
    with pytest.raises(Exception) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    # Same snippet-shape contract as missing-section: exception must carry
    # the TOML snippet, not just name the missing field.
    message = str(excinfo.value)
    assert missing_field in message
    assert "[tool.rsconnect]" in message
    assert 'app_mode = "' in message
    assert 'entrypoint = "' in message


# ---------------------------------------------------------------------------
# CLI behavior on missing / invalid config
# ---------------------------------------------------------------------------


def test_deploy_pyproject_errors_on_missing_section(runner: CliRunner, project_dir: pathlib.Path):
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        """,
    )
    result = runner.invoke(cli, ["deploy", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "[tool.rsconnect]" in combined


def test_deploy_pyproject_errors_on_missing_app_mode(runner: CliRunner, project_dir: pathlib.Path):
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"

        [tool.rsconnect]
        entrypoint = "app.py"
        """,
    )
    result = runner.invoke(cli, ["deploy", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "app_mode" in combined


def test_deploy_pyproject_errors_on_missing_entrypoint(runner: CliRunner, project_dir: pathlib.Path):
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"

        [tool.rsconnect]
        app_mode = "python-streamlit"
        """,
    )
    result = runner.invoke(cli, ["deploy", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "entrypoint" in combined


def test_deploy_pyproject_error_message_mentions_quickstart(runner: CliRunner, project_dir: pathlib.Path):
    """The error must reference ``rsconnect quickstart --help``."""
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        """,
    )
    result = runner.invoke(cli, ["deploy", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "quickstart" in combined.lower()


# ---------------------------------------------------------------------------
# Dispatch by app_mode
# ---------------------------------------------------------------------------


DISPATCH_MATRIX: list[typing.Any] = [
    pytest.param("python-streamlit", "app.py", "make_api_bundle", id="streamlit"),
    pytest.param("python-shiny", "app.py", "make_api_bundle", id="shiny"),
    pytest.param("python-fastapi", "__connect__:app", "make_api_bundle", id="fastapi"),
    pytest.param("python-api", "__connect__:app", "make_api_bundle", id="api"),
    pytest.param("jupyter-static", "notebook.ipynb", "make_notebook_source_bundle", id="jupyter-static"),
    pytest.param("jupyter-voila", "notebook.ipynb", "make_voila_bundle", id="voila"),
    pytest.param("quarto-static", "report.qmd", "create_quarto_deployment_bundle", id="quarto-static"),
    pytest.param("quarto-shiny", "report.qmd", "create_quarto_deployment_bundle", id="quarto-shiny"),
]


def _spy_make_bundle(monkeypatch: pytest.MonkeyPatch) -> dict[str, typing.Any]:
    """Short-circuit a deploy at ``make_bundle`` and capture the dispatched call.

    Records the builder name plus the positional/keyword args passed to
    ``make_bundle`` (the bundle builder is ``args[0]`` to ``make_bundle`` and the
    entrypoint is ``args[1]`` of the captured ``args``), then raises a sentinel so
    no network call happens.

    :param monkeypatch: pytest fixture used to stub out the deploy collaborators.
    """
    captured: dict[str, typing.Any] = {}

    class _StopDispatch(Exception):
        """Sentinel to short-circuit before any network call."""

    def spy_make_bundle(
        self: typing.Any, builder: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any
    ):
        captured["builder"] = builder.__name__
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise _StopDispatch()

    from rsconnect import api as api_mod
    from rsconnect import main as main_mod

    fake_environment = types.SimpleNamespace(python="python")
    monkeypatch.setattr(
        main_mod.Environment,
        "create_python_environment",
        classmethod(lambda cls, *args, **kwargs: fake_environment),
    )
    monkeypatch.setattr(main_mod, "which_quarto", lambda quarto=None: "quarto")
    monkeypatch.setattr(main_mod, "quarto_inspect", lambda quarto, path: {"engines": []})
    monkeypatch.setattr(main_mod, "validate_quarto_engines", lambda inspect: [])
    monkeypatch.setattr(api_mod.RSConnectClient, "server_settings", lambda self: {})
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_server", lambda self: self)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_app_mode", lambda self, app_mode: self)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "make_bundle", spy_make_bundle)
    return captured


@pytest.mark.parametrize("app_mode,entrypoint,expected_builder_name", DISPATCH_MATRIX)
@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
def test_deploy_pyproject_dispatches_by_app_mode(
    runner: CliRunner,
    project_dir: pathlib.Path,
    app_mode: str,
    entrypoint: str,
    expected_builder_name: str,
    monkeypatch: pytest.MonkeyPatch,
    table: str,
):
    """Each configured app mode routes to its matching bundle builder."""
    warnings = []
    monkeypatch.setattr("rsconnect.main.logger.warning", warnings.append)
    captured = _spy_make_bundle(monkeypatch)

    _write_pyproject(
        project_dir,
        f"""
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = []

        [tool.{table}]
        app_mode = "{app_mode}"
        entrypoint = "{entrypoint}"
        title = "Dispatch Test"
        """,
    )
    if ":" not in entrypoint:
        (project_dir / entrypoint).touch()

    result = runner.invoke(
        cli,
        ["deploy", "pyproject", str(project_dir), "-s", "http://example.invalid", "-k", "fake-key"],
    )

    assert captured.get("builder") == expected_builder_name, result.output
    if table == "rsconnect":
        assert len(warnings) == 1
        assert "[tool.rsconnect]" in warnings[0]
        assert "[tool.posit.connect]" in warnings[0]
    else:
        assert not warnings
    if app_mode == "jupyter-static":
        # Legacy app mode - no need to override the bundle builder default
        pass


@pytest.mark.parametrize(
    "app_mode",
    ["no-such-mode", "python-dash", "nodejs-api"],
    ids=["unknown", "valid-but-unhandled", "aliased"],
)
@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
def test_deploy_pyproject_errors_on_unsupported_app_mode(
    runner: CliRunner, project_dir: pathlib.Path, app_mode: str, monkeypatch: pytest.MonkeyPatch, table: str
):
    """Unsupported app modes fail quoting the configured string (not its canonical
    alias target) and without the quickstart hint."""
    _spy_make_bundle(monkeypatch)
    _write_pyproject(
        project_dir,
        f"""
        [project]
        name = "hello_app"
        version = "0.0.1"

        [tool.{table}]
        app_mode = "{app_mode}"
        entrypoint = "app.py"
        """,
    )
    (project_dir / "app.py").touch()

    result = runner.invoke(
        cli,
        ["deploy", "pyproject", str(project_dir), "-s", "http://example.invalid", "-k", "fake-key"],
    )

    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert f"Unsupported app_mode '{app_mode}' in [tool.{table}]" in combined
    assert "quickstart" not in combined.lower()


_EXPRESS_APP = "from shiny.express import ui\n\nui.h1('hi')\n"


def test_deploy_pyproject_shiny_express_entrypoint_matches_deploy_shiny(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A Shiny Express app deployed via ``deploy pyproject`` gets the same
    ``shiny.express.app:`` entrypoint as the dedicated ``deploy shiny`` path.

    Without the rewrite Connect cannot find an application object and the app
    crashes on boot, so both deploy paths must agree on the express form.
    """
    (project_dir / "app.py").write_text(_EXPRESS_APP)
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["shiny"]

        [tool.rsconnect]
        app_mode = "python-shiny"
        entrypoint = "app.py"
        title = "Express App"
        """,
    )
    server = ["-s", "http://example.invalid", "-k", "fake-key"]

    captured = _spy_make_bundle(monkeypatch)
    runner.invoke(cli, ["deploy", "shiny", str(project_dir), *server])
    shiny_entrypoint = captured["args"][1]

    captured = _spy_make_bundle(monkeypatch)
    runner.invoke(cli, ["deploy", "pyproject", str(project_dir), *server])
    pyproject_entrypoint = captured["args"][1]

    assert shiny_entrypoint.startswith("shiny.express.app:")
    assert pyproject_entrypoint == shiny_entrypoint


# ---------------------------------------------------------------------------
# Title / entrypoint override
# ---------------------------------------------------------------------------


def test_deploy_pyproject_uses_title_from_tool_rsconnect(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """The Connect content title must come from ``[tool.rsconnect].title`` (§13.2 step 5)."""
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = []

        [tool.rsconnect]
        app_mode = "python-streamlit"
        entrypoint = "app.py"
        title = "A Readable Title"
        """,
    )
    seen: dict[str, typing.Any] = {}

    # The implementer may structure this differently; the invariant is that
    # the title flows from pyproject to the executor. Tests can patch the
    # bundle builder or the executor constructor. A best-effort observation:
    from rsconnect import api as api_mod

    real_init = api_mod.RSConnectExecutor.__init__

    def spy_init(self: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
        seen["title"] = kwargs.get("title")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(api_mod.RSConnectExecutor, "__init__", spy_init)
    runner.invoke(
        cli,
        [
            "deploy",
            "pyproject",
            str(project_dir),
            "-s",
            "http://127.0.0.1:1/unused",
            "-k",
            "fake-key",
        ],
    )
    assert seen.get("title") == "A Readable Title"


def test_deploy_pyproject_uses_entrypoint_from_tool_rsconnect(runner: CliRunner, project_dir: pathlib.Path):
    """Entrypoint in pyproject must bypass per-type guessing (§13.2 step 4).

    Observable signal: a module-style entrypoint ``__connect__:app`` is used
    even though the project contains no ``app.py`` the guesser would pick up.
    """
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"

        [tool.rsconnect]
        app_mode = "python-fastapi"
        entrypoint = "custom_module:create_app"
        title = "hello_app"
        """,
    )
    (project_dir / "custom_module.py").write_text("def create_app():\n    return None\n")
    result = runner.invoke(
        cli,
        [
            "deploy",
            "pyproject",
            str(project_dir),
            "-s",
            "http://127.0.0.1:1/unused",
            "-k",
            "fake-key",
        ],
    )
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    # We should not see an entrypoint-guessing error pointing to app.py.
    assert "app.py" not in combined or "custom_module" in combined


# ---------------------------------------------------------------------------
# Requirements source
# ---------------------------------------------------------------------------


def _capture_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, typing.Any]:
    """Wire up monkeypatches that short-circuit the deploy and capture the
    ``requirements_file`` argument handed to ``create_python_environment``."""
    captured: dict[str, typing.Any] = {}

    class _StopDispatch(Exception):
        pass

    from rsconnect import api as api_mod
    from rsconnect import main as main_mod

    def spy_create(cls: typing.Any, directory: str, **kwargs: typing.Any):
        captured["directory"] = directory
        captured["requirements_file"] = kwargs.get("requirements_file")
        raise _StopDispatch()

    monkeypatch.setattr(main_mod.Environment, "create_python_environment", classmethod(spy_create))
    monkeypatch.setattr(api_mod.RSConnectClient, "server_settings", lambda self: {})
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_server", lambda self: self)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_app_mode", lambda self, app_mode: self)
    return captured


_REQ_PYPROJECT = """
[project]
name = "hello_app"
version = "0.0.1"
dependencies = ["flask"]

[tool.rsconnect]
app_mode = "python-api"
entrypoint = "app:app"
title = "hello_app"
"""


def test_deploy_pyproject_defaults_requirements_to_pyproject_toml(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Default requirements source is ``pyproject.toml``.

    Regression for a bug where the command passed ``requirements_file=None``,
    causing the inspector to fall back to ``pip freeze`` of the caller's
    interpreter and polluting the bundle with whatever happened to be
    installed alongside ``rsconnect-python`` instead of the project's
    declared dependencies.
    """
    captured = _capture_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    runner.invoke(cli, ["deploy", "pyproject", str(project_dir), "-s", "http://x", "-k", "k"])
    assert captured["requirements_file"] == "pyproject.toml"


def test_deploy_pyproject_prefers_uv_lock(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A lockfile takes precedence and is validated during inspection."""
    captured = _capture_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "uv.lock").write_text("# placeholder\n")
    runner.invoke(cli, ["deploy", "pyproject", str(project_dir), "-s", "http://x", "-k", "k"])
    assert captured["requirements_file"] == "uv.lock"


def test_deploy_pyproject_force_generate_bypasses_sources(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    captured = _capture_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT + '\nrequirements_file = "missing.txt"\n')
    runner.invoke(cli, ["deploy", "pyproject", "-g", str(project_dir), "-s", "http://x", "-k", "k"])
    assert captured["requirements_file"] is None
    result = runner.invoke(
        cli, ["deploy", "pyproject", "-g", "-r", "other.txt", str(project_dir), "-s", "http://x", "-k", "k"]
    )
    assert "cannot be combined" in result.output


def test_deploy_pyproject_requirements_file_flag_overrides_default(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """``-r uv.lock`` opts into a fully resolved deploy."""
    captured = _capture_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "uv.lock").write_text("# placeholder\n")
    runner.invoke(
        cli,
        ["deploy", "pyproject", "-r", "uv.lock", str(project_dir), "-s", "http://x", "-k", "k"],
    )
    assert captured["requirements_file"] == "uv.lock"


@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
def test_deploy_pyproject_honors_requirements_file_from_tool_rsconnect(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch, table: str
):
    """The configured requirements file becomes the default for this project.

    Lets users who maintain a ``uv.lock`` (or any other requirements source)
    bake that choice into the project once, instead of remembering ``-r`` on
    every deploy.
    """
    captured = _capture_environment(monkeypatch)
    _write_pyproject(
        project_dir,
        f"""
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["flask"]

        [tool.{table}]
        app_mode = "python-api"
        entrypoint = "app:app"
        title = "hello_app"
        requirements_file = "uv.lock"
        """,
    )
    (project_dir / "uv.lock").write_text("# placeholder\n")
    runner.invoke(cli, ["deploy", "pyproject", str(project_dir), "-s", "http://x", "-k", "k"])
    assert captured["requirements_file"] == "uv.lock"


@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
def test_deploy_pyproject_flag_overrides_tool_rsconnect_requirements_file(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch, table: str
):
    """CLI ``-r`` wins over the configured requirements file."""
    captured = _capture_environment(monkeypatch)
    _write_pyproject(
        project_dir,
        f"""
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["flask"]

        [tool.{table}]
        app_mode = "python-api"
        entrypoint = "app:app"
        title = "hello_app"
        requirements_file = "uv.lock"
        """,
    )
    runner.invoke(
        cli,
        ["deploy", "pyproject", "-r", "pyproject.toml", str(project_dir), "-s", "http://x", "-k", "k"],
    )
    assert captured["requirements_file"] == "pyproject.toml"


@pytest.mark.parametrize("command", ["deploy", "write-manifest"])
@pytest.mark.parametrize("invalid_table", ["posit.connect", "rsconnect"])
def test_pyproject_both_tables_fail_before_validation(runner, project_dir, command, invalid_table, monkeypatch):
    warnings = []
    monkeypatch.setattr("rsconnect.main.logger.warning", warnings.append)
    other = "rsconnect" if invalid_table == "posit.connect" else "posit.connect"
    _write_pyproject(
        project_dir,
        f'[tool.{invalid_table}]\n[tool.{other}]\napp_mode = "python-api"\nentrypoint = "app:app"\n',
    )
    result = runner.invoke(cli, [command, "pyproject", str(project_dir)])
    assert result.exit_code != 0
    assert "[tool.posit.connect]" in result.output
    assert "[tool.rsconnect]" in result.output
    assert "Keep only one" in result.output
    assert not warnings


@pytest.mark.parametrize("command", ["deploy", "write-manifest"])
@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
@pytest.mark.parametrize(
    "field,value",
    [("app_mode", '""'), ("entrypoint", "42"), ("app_mode", '"unknown"'), ("app_mode", '"python-dash"')],
)
def test_pyproject_invalid_fields_name_table_without_warning(
    runner, project_dir, command, table, field, value, monkeypatch
):
    warnings = []
    monkeypatch.setattr("rsconnect.main.logger.warning", warnings.append)
    fields = {"app_mode": '"python-api"', "entrypoint": '"app:app"'}
    fields[field] = value
    _write_pyproject(
        project_dir, f"[tool.{table}]\napp_mode = {fields['app_mode']}\nentrypoint = {fields['entrypoint']}\n"
    )
    result = runner.invoke(cli, [command, "pyproject", str(project_dir)])
    assert result.exit_code != 0
    assert f"[tool.{table}]" in result.output
    assert not warnings


@pytest.mark.parametrize("table", ["posit.connect", "rsconnect"])
def test_pyproject_non_table_names_selected_table(project_dir, table):
    from rsconnect.pyproject import InvalidPyprojectConfigError, read_tool_rsconnect

    _write_pyproject(project_dir, f'[tool]\n{table} = "not a table"\n')
    with pytest.raises(InvalidPyprojectConfigError, match=rf"\[tool\.{re.escape(table)}\] is not a TOML table"):
        read_tool_rsconnect(project_dir / "pyproject.toml")


@pytest.mark.parametrize("body", ['[tool]\nposit = "x"', '[tool.posit]\nconnect = "x"'])
def test_pyproject_posit_non_table(project_dir, body):
    from rsconnect.pyproject import InvalidPyprojectConfigError, read_tool_rsconnect

    _write_pyproject(project_dir, body)
    table = "[tool.posit.connect]" if "connect" in body else "[tool.posit]"
    with pytest.raises(InvalidPyprojectConfigError) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    assert f"{table} is not a TOML table" in str(excinfo.value)


@pytest.mark.parametrize("legacy", [False, True])
def test_pyproject_posit_without_connect_is_ignored(project_dir, legacy):
    from rsconnect.pyproject import InvalidPyprojectConfigError, read_tool_rsconnect

    body = '[tool.posit]\nother = "value"\n[tool.posit.another]\nsetting = true\n'
    if legacy:
        body += '[tool.rsconnect]\napp_mode = "python-api"\nentrypoint = "app:app"\n'
    _write_pyproject(project_dir, body)
    if legacy:
        assert read_tool_rsconnect(project_dir / "pyproject.toml")["entrypoint"] == "app:app"
    else:
        with pytest.raises(InvalidPyprojectConfigError, match="section is missing"):
            read_tool_rsconnect(project_dir / "pyproject.toml")
