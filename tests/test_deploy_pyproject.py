# probedev: ignore-file
# The xfail/skip reasons below cite ``TODO(EVO-###)`` markers by text. The real
# evolution markers live in ``rsconnect/``; the strings here are pointers, not
# new markers.
"""
Acceptance tests for ``rsconnect deploy pyproject`` (SPEC_QUICKSTART.md §13).

Tests exercise the CLI via ``click.testing.CliRunner`` and the pure reader
(:func:`rsconnect.pyproject.read_tool_rsconnect`) directly. They follow the
shape of ``tests/test_pyproject.py`` (fixture/parametrize-driven) and
``tests/test_main.py`` (Click invocation).

Every test is marked ``xfail`` with a pointer to the evolution that unblocks
it; the feature is not yet implemented.
"""

from __future__ import annotations

import pathlib
import textwrap
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-060): Read [tool.rsconnect] from pyproject.toml.",
)
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-060): Reader raises on missing [tool.rsconnect] section (paired with EVO-040 CLI handling).",
)
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
    assert "tool.rsconnect" in str(excinfo.value).lower() or "rsconnect" in str(excinfo.value).lower()


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
@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-060): Reader raises on missing required field (paired with EVO-040).",
)
def test_read_tool_rsconnect_missing_required_field_raises(project_dir: pathlib.Path, missing_field: str, body: str):
    from rsconnect.pyproject import read_tool_rsconnect

    _write_pyproject(project_dir, body)
    with pytest.raises(Exception) as excinfo:
        read_tool_rsconnect(project_dir / "pyproject.toml")
    assert missing_field in str(excinfo.value)


# ---------------------------------------------------------------------------
# CLI behavior on missing / invalid config (SPEC §13.3)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-040): Hard-error CLI surface when [tool.rsconnect] is missing.",
)
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-040): Hard-error CLI surface when app_mode is missing.",
)
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-040): Hard-error CLI surface when entrypoint is missing.",
)
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-040): Hard-error message mentions rsconnect quickstart (SPEC §13.3).",
)
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
    pytest.param("python-streamlit", "app.py", id="streamlit"),
    pytest.param("python-shiny", "app.py", id="shiny"),
    pytest.param("python-fastapi", "__connect__:app", id="fastapi"),
    pytest.param("python-api", "__connect__:app", id="api"),
    pytest.param("jupyter-notebook", "notebook.ipynb", id="jupyter-notebook"),
    pytest.param("jupyter-static", "notebook.ipynb", id="jupyter-static"),
    pytest.param("jupyter-voila", "notebook.ipynb", id="voila"),
    pytest.param("quarto-static", "report.qmd", id="quarto-static"),
    pytest.param("quarto-shiny", "report.qmd", id="quarto-shiny"),
]


@pytest.mark.parametrize("app_mode,entrypoint", DISPATCH_MATRIX)
@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-030): Dispatch by app_mode in deploy pyproject.",
)
def test_deploy_pyproject_dispatches_by_app_mode(
    runner: CliRunner, project_dir: pathlib.Path, app_mode: str, entrypoint: str, monkeypatch: pytest.MonkeyPatch
):
    """Each app_mode must reach the matching deploy code path.

    The implementer chooses how to prove dispatch: patching the bundle builder,
    observing the RSConnectExecutor call, or similar. This test asserts that
    the command does not short-circuit to the wrong branch by using a
    deliberately bad server URL and asserting the error surfaces from the
    deploy path rather than from config parsing (i.e. we got past the reader).
    """
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
    # Deliberately unreachable server; the failure mode we care about is
    # "tried to contact Connect" rather than "could not parse config".
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
    # Parse-time errors would mention tool.rsconnect / missing fields. Dispatch
    # success means we got past the reader into deploy territory.
    assert "[tool.rsconnect]" not in combined
    assert result.exit_code != 0  # unreachable server guarantees non-zero


# ---------------------------------------------------------------------------
# Title / entrypoint override (SPEC §13.2 steps 4-5)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-030): Dispatch by app_mode in deploy pyproject (title).",
)
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


@pytest.mark.xfail(
    strict=False,
    reason="TODO(EVO-030): Dispatch by app_mode in deploy pyproject (entrypoint override).",
)
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
