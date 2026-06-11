"""
Acceptance tests for ``rsconnect write-manifest pyproject``.

Tests exercise the CLI via ``click.testing.CliRunner`` and assert the real
``manifest.json`` written into the project directory, mirroring the shape of
``tests/test_deploy_pyproject.py``. Python environment inspection and the
Quarto executable are monkeypatched at the boundary so no subprocess runs,
except one end-to-end test that exercises the real environment inspector.
"""

from __future__ import annotations

import json
import pathlib
import textwrap
import typing

import pytest
from click.testing import CliRunner

from rsconnect.bundle import make_manifest_bundle
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


def _read_manifest(project: pathlib.Path) -> dict[str, typing.Any]:
    return json.loads((project / "manifest.json").read_text())


def _fake_python_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, typing.Any]:
    """Replace subprocess-based environment inspection with a canned Environment.

    Mirrors the real inspector's filename behavior: a pyproject.toml source
    yields a generated virtual ``requirements.txt``, a ``uv.lock`` source yields
    ``requirements.txt.lock``, and any other requirements file is read as-is.
    Captures the ``requirements_file`` handed to ``create_python_environment``
    so tests can assert the requirements-source precedence without running pip.
    """
    captured: dict[str, typing.Any] = {}

    from rsconnect import main as main_mod
    from rsconnect.environment import Environment

    def fake_create(cls: typing.Any, directory: str, **kwargs: typing.Any) -> Environment:
        requirements_file = kwargs.get("requirements_file")
        captured["directory"] = directory
        captured["requirements_file"] = requirements_file
        if requirements_file == "uv.lock":
            filename = "requirements.txt.lock"
            contents = "# requirements.txt.lock generated from uv.lock by rsconnect-python\nflask==2.0.0\n"
        elif requirements_file in (None, "pyproject.toml"):
            filename = "requirements.txt"
            contents = "# requirements.txt generated from pyproject.toml by rsconnect-python\nflask\n"
        else:
            filename = requirements_file
            contents = "flask\n"
        return Environment.from_dict(
            {
                "contents": contents,
                "filename": filename,
                "locale": "en_US.UTF-8",
                "package_manager": "pip",
                "pip": "23.0.1",
                "python": "3.11.0",
                "source": "file",
            }
        )

    monkeypatch.setattr(main_mod.Environment, "create_python_environment", classmethod(fake_create))
    return captured


def _fake_quarto(monkeypatch: pytest.MonkeyPatch, engines: list[str]) -> None:
    """Stub the Quarto executable lookup/inspection at the main.py boundary."""
    from rsconnect import main as main_mod

    monkeypatch.setattr(main_mod, "which_quarto", lambda quarto=None: "quarto")
    monkeypatch.setattr(
        main_mod,
        "quarto_inspect",
        lambda quarto, path: {"quarto": {"version": "1.4.0"}, "engines": engines},
    )
    monkeypatch.setattr(main_mod, "validate_quarto_engines", lambda inspect: inspect["engines"])


_NOTEBOOK_JSON = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n'


def _pyproject_body(app_mode: str, entrypoint: str) -> str:
    return f"""
    [project]
    name = "hello_app"
    version = "0.0.1"
    dependencies = ["flask"]

    [tool.rsconnect]
    app_mode = "{app_mode}"
    entrypoint = "{entrypoint}"
    title = "hello_app"
    """


# ---------------------------------------------------------------------------
# Dispatch by app_mode
# ---------------------------------------------------------------------------


DISPATCH_MATRIX: list[typing.Any] = [
    pytest.param("python-streamlit", "app.py", "app.py", id="streamlit"),
    pytest.param("python-shiny", "app.py", "app.py", id="shiny"),
    pytest.param("python-fastapi", "app:app", "app:app", id="fastapi"),
    pytest.param("python-api", "app:app", "app:app", id="api"),
    pytest.param("jupyter-static", "notebook.ipynb", "notebook.ipynb", id="jupyter-static"),
    pytest.param("jupyter-voila", "notebook.ipynb", "notebook.ipynb", id="voila"),
]


@pytest.mark.parametrize("app_mode,entrypoint,expected_entrypoint", DISPATCH_MATRIX)
def test_write_manifest_pyproject_writes_manifest_per_app_mode(
    runner: CliRunner,
    project_dir: pathlib.Path,
    app_mode: str,
    entrypoint: str,
    expected_entrypoint: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Each ``[tool.rsconnect].app_mode`` produces a manifest.json with the matching appmode."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _pyproject_body(app_mode, entrypoint))
    if entrypoint.endswith(".ipynb"):
        (project_dir / entrypoint).write_text(_NOTEBOOK_JSON)
    else:
        (project_dir / "app.py").write_text("# plain app, not Shiny Express\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    manifest = _read_manifest(project_dir)
    assert manifest["metadata"]["appmode"] == app_mode
    assert manifest["metadata"]["entrypoint"] == expected_entrypoint
    # The inspector turns pyproject.toml's dependencies into a virtual
    # requirements.txt, which must also land on disk next to the manifest.
    assert manifest["python"]["package_manager"]["package_file"] == "requirements.txt"
    assert "generated from pyproject.toml" in (project_dir / "requirements.txt").read_text()
    # Closed loop: deploying from the written manifest must find every file.
    with make_manifest_bundle(str(project_dir / "manifest.json")):
        pass


@pytest.mark.parametrize("app_mode", ["quarto-static", "quarto-shiny"])
def test_write_manifest_pyproject_quarto_modes(
    runner: CliRunner, project_dir: pathlib.Path, app_mode: str, monkeypatch: pytest.MonkeyPatch
):
    """Quarto modes inspect the project and write the manifest next to pyproject.toml."""
    _fake_quarto(monkeypatch, engines=["markdown"])
    _write_pyproject(project_dir, _pyproject_body(app_mode, "report.qmd"))
    (project_dir / "report.qmd").write_text("# Report\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    manifest = _read_manifest(project_dir)
    assert manifest["metadata"]["appmode"] == app_mode
    assert manifest["quarto"]["engines"] == ["markdown"]
    assert "report.qmd" in manifest["files"]


def test_write_manifest_pyproject_quarto_jupyter_engine_inspects_python(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A Quarto project on the Jupyter engine also embeds the Python environment."""
    captured = _fake_python_environment(monkeypatch)
    _fake_quarto(monkeypatch, engines=["jupyter"])
    _write_pyproject(project_dir, _pyproject_body("quarto-static", "report.qmd"))
    (project_dir / "report.qmd").write_text("# Report\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    assert captured["requirements_file"] == "pyproject.toml"
    manifest = _read_manifest(project_dir)
    assert manifest["metadata"]["appmode"] == "quarto-static"
    assert "python" in manifest
    assert (project_dir / "requirements.txt").exists()


def test_write_manifest_pyproject_shiny_express_entrypoint_is_rewritten(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A Shiny Express app gets the same ``shiny.express.app:`` entrypoint deploy uses."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _pyproject_body("python-shiny", "app.py"))
    (project_dir / "app.py").write_text("from shiny.express import ui\n\nui.h1('hi')\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    manifest = _read_manifest(project_dir)
    assert manifest["metadata"]["entrypoint"].startswith("shiny.express.app:")


# ---------------------------------------------------------------------------
# Requirements source precedence (mirrors deploy pyproject)
# ---------------------------------------------------------------------------


_REQ_PYPROJECT = _pyproject_body("python-api", "app:app")


def test_write_manifest_pyproject_defaults_requirements_to_pyproject_toml(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    captured = _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert captured["requirements_file"] == "pyproject.toml"
    assert captured["directory"] == str(project_dir)


def test_write_manifest_pyproject_requirements_file_flag_overrides_default(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    captured = _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "uv.lock").write_text("# placeholder\n")
    result = runner.invoke(cli, ["write-manifest", "pyproject", "-r", "uv.lock", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert captured["requirements_file"] == "uv.lock"
    # uv.lock is exported to a virtual requirements.txt.lock, which must land on disk.
    assert (project_dir / "requirements.txt.lock").exists()
    with make_manifest_bundle(str(project_dir / "manifest.json")):
        pass


def test_write_manifest_pyproject_honors_requirements_file_from_tool_rsconnect(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    captured = _fake_python_environment(monkeypatch)
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["flask"]

        [tool.rsconnect]
        app_mode = "python-api"
        entrypoint = "app:app"
        title = "hello_app"
        requirements_file = "uv.lock"
        """,
    )
    (project_dir / "uv.lock").write_text("# placeholder\n")
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code == 0, result.output
    assert captured["requirements_file"] == "uv.lock"


# ---------------------------------------------------------------------------
# Environment file lands next to the manifest
# ---------------------------------------------------------------------------


def test_write_manifest_pyproject_writes_env_file_next_to_subdir_manifest(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Notebook manifests land next to the entrypoint, and the env file must too."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _pyproject_body("jupyter-static", "nb/notebook.ipynb"))
    (project_dir / "nb").mkdir()
    (project_dir / "nb" / "notebook.ipynb").write_text(_NOTEBOOK_JSON)

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    assert (project_dir / "nb" / "requirements.txt").exists()
    assert not (project_dir / "requirements.txt").exists()
    with make_manifest_bundle(str(project_dir / "nb" / "manifest.json")):
        pass


def test_write_manifest_pyproject_regenerates_stale_env_file(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A stale generated env file is rewritten so deployments ship current dependencies."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "requirements.txt").write_text("stale-dependency==0.1\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    contents = (project_dir / "requirements.txt").read_text()
    assert "stale-dependency" not in contents
    assert "flask" in contents


def test_write_manifest_pyproject_never_rewrites_explicit_requirements_source(
    runner: CliRunner, project_dir: pathlib.Path
):
    """When requirements.txt IS the configured source, it must stay untouched.

    Unmocked on purpose: the real inspector strips rsconnect lines from the
    contents it returns, so a wrongful rewrite would corrupt the user's file.
    """
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        dependencies = ["flask"]

        [tool.rsconnect]
        app_mode = "python-api"
        entrypoint = "app:app"
        requirements_file = "requirements.txt"
        """,
    )
    (project_dir / "app.py").write_text("app = None\n")
    source = "flask\nrsconnect-python==1.25.0\n"
    (project_dir / "requirements.txt").write_text(source)

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    assert (project_dir / "requirements.txt").read_text() == source
    with make_manifest_bundle(str(project_dir / "manifest.json")):
        pass


def test_write_manifest_pyproject_unmocked_end_to_end(runner: CliRunner, project_dir: pathlib.Path):
    """Real environment inspection: default config must yield a deployable manifest."""
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "app.py").write_text("app = None\n")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    manifest = _read_manifest(project_dir)
    assert manifest["python"]["package_manager"]["package_file"] == "requirements.txt"
    assert "flask" in (project_dir / "requirements.txt").read_text()
    with make_manifest_bundle(str(project_dir / "manifest.json")):
        pass


# ---------------------------------------------------------------------------
# Overwrite guard
# ---------------------------------------------------------------------------


def test_write_manifest_pyproject_refuses_to_overwrite_without_flag(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "manifest.json").write_text("{}")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code != 0
    assert "manifest.json already exists" in result.output
    assert "--overwrite" in result.output
    assert _read_manifest(project_dir) == {}  # untouched


def test_write_manifest_pyproject_overwrite_flag_replaces_manifest(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _REQ_PYPROJECT)
    (project_dir / "manifest.json").write_text("{}")

    result = runner.invoke(cli, ["write-manifest", "pyproject", "--overwrite", str(project_dir)])

    assert result.exit_code == 0, result.output
    assert _read_manifest(project_dir)["metadata"]["appmode"] == "python-api"


def test_write_manifest_pyproject_guards_manifest_next_to_subdir_entrypoint(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """Notebook manifests land next to the entrypoint, so the guard must too."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _pyproject_body("jupyter-static", "nb/notebook.ipynb"))
    (project_dir / "nb").mkdir()
    (project_dir / "nb" / "notebook.ipynb").write_text(_NOTEBOOK_JSON)
    (project_dir / "nb" / "manifest.json").write_text("{}")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code != 0
    assert "manifest.json already exists" in result.output
    assert json.loads((project_dir / "nb" / "manifest.json").read_text()) == {}  # untouched


def test_write_manifest_pyproject_stale_root_manifest_does_not_block_subdir_entrypoint(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """A manifest.json at the project root is not the writer's destination and must not block."""
    _fake_python_environment(monkeypatch)
    _write_pyproject(project_dir, _pyproject_body("jupyter-static", "nb/notebook.ipynb"))
    (project_dir / "nb").mkdir()
    (project_dir / "nb" / "notebook.ipynb").write_text(_NOTEBOOK_JSON)
    (project_dir / "manifest.json").write_text("{}")

    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])

    assert result.exit_code == 0, result.output
    manifest = json.loads((project_dir / "nb" / "manifest.json").read_text())
    assert manifest["metadata"]["appmode"] == "jupyter-static"
    assert _read_manifest(project_dir) == {}  # stale root manifest untouched


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------


def test_write_manifest_pyproject_errors_on_missing_section(runner: CliRunner, project_dir: pathlib.Path):
    _write_pyproject(
        project_dir,
        """
        [project]
        name = "hello_app"
        version = "0.0.1"
        """,
    )
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    # The error carries the copy-pasteable TOML snippet plus the quickstart hint.
    assert "[tool.rsconnect]" in result.output
    assert 'app_mode = "' in result.output
    assert 'entrypoint = "' in result.output
    assert "quickstart" in result.output.lower()


def test_write_manifest_pyproject_errors_on_missing_pyproject(runner: CliRunner, project_dir: pathlib.Path):
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    assert "pyproject.toml not found" in result.output
    assert "quickstart" in result.output.lower()


def test_write_manifest_pyproject_errors_on_malformed_pyproject(runner: CliRunner, project_dir: pathlib.Path):
    (project_dir / "pyproject.toml").write_text("[tool.rsconnect\napp_mode =")
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    assert "could not be parsed" in result.output
    assert "quickstart" in result.output.lower()


@pytest.mark.parametrize(
    "app_mode",
    ["no-such-mode", "python-dash", "nodejs-api"],
    ids=["unknown", "valid-but-unhandled", "aliased"],
)
def test_write_manifest_pyproject_errors_on_unsupported_app_mode(
    runner: CliRunner, project_dir: pathlib.Path, app_mode: str
):
    """Unsupported app modes fail with deploy's exact message and no quickstart hint."""
    _write_pyproject(project_dir, _pyproject_body(app_mode, "app.py"))
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(project_dir)])
    assert result.exit_code != 0
    assert f"Unsupported app_mode '{app_mode}' in [tool.rsconnect]" in result.output
    assert "quickstart" not in result.output.lower()
