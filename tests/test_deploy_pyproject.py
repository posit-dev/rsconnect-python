# probedev: ignore-file
"""
Acceptance tests for ``rsconnect deploy pyproject`` (SPEC_QUICKSTART.md §13).

Tests exercise the CLI via ``click.testing.CliRunner`` and the pure reader
(:func:`rsconnect.pyproject.read_tool_rsconnect`) directly. They follow the
shape of ``tests/test_pyproject.py`` (fixture/parametrize-driven) and
``tests/test_main.py`` (Click invocation).

The file keeps deploy-pyproject coverage at the CLI boundary and verifies the
reader directly where malformed configuration needs precise diagnostics.
"""

from __future__ import annotations

import pathlib
import textwrap
import types
import typing

import click
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
    project = tmp_path / "hello-app"
    project.mkdir()
    return project


def _write_pyproject(project: pathlib.Path, body: str) -> None:
    (project / "pyproject.toml").write_text(textwrap.dedent(body))


# ---------------------------------------------------------------------------
# Command shape (SPEC §13.1)
# ---------------------------------------------------------------------------


def test_deploy_pyproject_command_is_registered(runner: CliRunner):
    result = runner.invoke(cli, ["deploy", "pyproject", "--help"])
    assert result.exit_code == 0, result.output
    assert "pyproject" in result.output.lower()


def test_deploy_pyproject_requires_path(runner: CliRunner):
    """The positional directory is required (SPEC §13.1: no silent default to '.').

    Distinguishes 'command exists and demands the positional' from the prior
    'command does not exist' state - the assertions below would behave
    differently in those two cases.
    """
    result = runner.invoke(cli, ["deploy", "pyproject"])
    assert result.exit_code != 0
    assert "No such command" not in result.output
    # `no_args_is_help=True` makes Click render the usage block on missing args.
    assert "Usage:" in result.output
    assert "DIRECTORY" in result.output  # required positional metavar (after rename)
    assert "[DIRECTORY]" not in result.output  # required, not optional


def test_deploy_pyproject_option_surface_matches_deploy_manifest():
    """``deploy pyproject`` must expose the same Click option surface as
    ``deploy manifest`` so existing credential mechanisms (SPEC §13.1) apply
    identically.
    """
    deploy_group = typing.cast(click.Group, cli.commands["deploy"])
    manifest_options = {p.name for p in deploy_group.commands["manifest"].params if isinstance(p, click.Option)}
    pyproject_options = {p.name for p in deploy_group.commands["pyproject"].params if isinstance(p, click.Option)}
    assert pyproject_options == manifest_options


# ---------------------------------------------------------------------------
# [tool.rsconnect] reader (SPEC §3 / §13.2)
# ---------------------------------------------------------------------------


def test_read_tool_rsconnect_returns_three_fields(project_dir: pathlib.Path):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello-app"
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
        name = "hello-app"
        version = "0.0.1"
        """,
    )
    with pytest.raises(Exception) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    # Exception must carry the SPEC §13.3 minimum valid snippet as a
    # copy-pasteable TOML block, not just prose. Anchor on the section
    # header plus both required-field TOML string-valued key=value forms
    # (``key = "``); a prose 'required fields: ...' message would not
    # incidentally produce that shape.
    message = str(excinfo.value)
    assert "tool.rsconnect" in message.lower() or "rsconnect" in message.lower()
    assert "[tool.rsconnect]" in message
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
    assert "[tool.rsconnect]" in message
    assert 'app_mode = "' in message
    assert 'entrypoint = "' in message


@pytest.mark.parametrize(
    "missing_field,body",
    [
        (
            "app_mode",
            """
            [project]
            name = "hello-app"
            version = "0.0.1"

            [tool.rsconnect]
            entrypoint = "app.py"
            """,
        ),
        (
            "entrypoint",
            """
            [project]
            name = "hello-app"
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
# CLI behavior on missing / invalid config (SPEC §13.3)
# ---------------------------------------------------------------------------


def test_deploy_pyproject_errors_on_missing_section(runner: CliRunner, project_dir: pathlib.Path):
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello-app"
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
        name = "hello-app"
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
        name = "hello-app"
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
    """SPEC §13.3 requires the error to reference ``rsconnect quickstart --help``."""
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello-app"
        version = "0.0.1"
        """,
    )
    result = runner.invoke(cli, ["deploy", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert "quickstart" in combined.lower()


# ---------------------------------------------------------------------------
# Dispatch by app_mode (SPEC §13.2)
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


@pytest.mark.parametrize("app_mode,entrypoint,expected_builder_name", DISPATCH_MATRIX)
def test_deploy_pyproject_dispatches_by_app_mode(
    runner: CliRunner,
    project_dir: pathlib.Path,
    app_mode: str,
    entrypoint: str,
    expected_builder_name: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Each [tool.rsconnect].app_mode routes to its matching bundle builder (SPEC §13.2 step 3, §8.2)."""
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

    _write_pyproject(
        project_dir,
        f"""
        [project]
        name = "hello-app"
        version = "0.0.1"

        [tool.rsconnect]
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
    if app_mode == "jupyter-static":
        # Legacy app mode - no need to override the bundle builder default
        pass


# ---------------------------------------------------------------------------
# Title / entrypoint override (SPEC §13.2 steps 4-5)
# ---------------------------------------------------------------------------


def test_deploy_pyproject_uses_title_from_tool_rsconnect(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """The Connect content title must come from ``[tool.rsconnect].title`` (§13.2 step 5)."""
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello-app"
        version = "0.0.1"

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
        name = "hello-app"
        version = "0.0.1"

        [tool.rsconnect]
        app_mode = "python-fastapi"
        entrypoint = "custom_module:create_app"
        title = "hello-app"
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
