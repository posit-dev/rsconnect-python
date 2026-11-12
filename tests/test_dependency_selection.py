import itertools
import json
import subprocess
import tarfile

import pytest
import uv
from click.testing import CliRunner

from rsconnect.bundle import file_checksum, make_manifest_bundle
from rsconnect.main import cli, resolve_requirements_file
from rsconnect.exception import RSConnectException


@pytest.mark.parametrize("requirements,project,lock", list(itertools.product([False, True], repeat=3)))
def test_source_precedence(tmp_path, requirements, project, lock):
    if requirements:
        (tmp_path / "requirements.txt").write_text("old==1\n")
    if project:
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n")
    if lock:
        (tmp_path / "uv.lock").write_text("")
    expected = "uv.lock" if lock else "pyproject.toml" if project else "requirements.txt" if requirements else None
    if expected:
        assert resolve_requirements_file(str(tmp_path), None, False) == expected
    else:
        with pytest.raises(RSConnectException, match="No Python dependency source"):
            resolve_requirements_file(str(tmp_path), None, False)


@pytest.mark.parametrize("project", ['[project]\nname = "example"\n', '[project]\ndynamic = ["dependencies"]\n'])
def test_non_static_project_is_skipped(tmp_path, project):
    (tmp_path / "pyproject.toml").write_text(project)
    (tmp_path / "requirements.txt").write_text("example\n")
    assert resolve_requirements_file(str(tmp_path), None, False) == "requirements.txt"


def test_config_and_explicit_override(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[tool.posit.connect]\nrequirements_file = "custom.txt"\n')
    (tmp_path / "uv.lock").touch()
    assert resolve_requirements_file(str(tmp_path), None, False) == "custom.txt"
    assert resolve_requirements_file(str(tmp_path), "other.txt", False) == "other.txt"
    assert resolve_requirements_file(str(tmp_path), None, True) is None
    with pytest.raises(RSConnectException, match="cannot be combined"):
        resolve_requirements_file(str(tmp_path), "other.txt", True)


@pytest.mark.parametrize("command", ["api", "pyproject"])
def test_manifest_refreshes_generated_dependencies_without_touching_source(tmp_path, command):
    (tmp_path / "app.py").write_text("app = object()\n")
    source = tmp_path / "requirements.txt"
    source.write_text("old==1\n")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\ndependencies = ["flask==1"]\n[tool.posit.connect]\n'
        'app_mode = "python-api"\nentrypoint = "app:app"\n'
    )
    runner = CliRunner()
    for version in ("1", "2"):
        project.write_text(project.read_text().replace("flask==1", f"flask=={version}"))
        result = runner.invoke(cli, ["write-manifest", command, "--overwrite", str(tmp_path)])
        assert result.exit_code == 0, result.output
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        name = manifest["python"]["package_manager"]["package_file"]
        generated = tmp_path / name
        assert source.read_text() == "old==1\n"
        assert f"flask=={version}" in generated.read_text()
        assert manifest["files"][name]["checksum"] == file_checksum(generated)
        with make_manifest_bundle(tmp_path / "manifest.json") as bundle, tarfile.open(
            fileobj=bundle, mode="r:gz"
        ) as archive:
            assert f"flask=={version}" in archive.extractfile(name).read().decode()


@pytest.mark.parametrize("selection", ["automatic", "cli", "configured"])
def test_fresh_and_stale_lock_offline(tmp_path, selection):
    project = tmp_path / "pyproject.toml"
    config = '\n[tool.posit.connect]\nrequirements_file = "uv.lock"\n' if selection == "configured" else ""
    project.write_text('[project]\nname = "example"\nversion = "1.0"\ndependencies = []\n' + config)
    subprocess.run([uv.find_uv_bin(), "lock", "--offline"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("app = object()\n")
    runner = CliRunner()
    args = ["write-manifest", "api", "--overwrite"]
    if selection == "cli":
        args += ["-r", "uv.lock"]
    result = runner.invoke(cli, [*args, str(tmp_path)])
    assert result.exit_code == 0, result.output
    lock = (tmp_path / "uv.lock").read_bytes()
    project.write_text(project.read_text().replace('version = "1.0"', 'version = "2.0"'))
    result = runner.invoke(cli, [*args, str(tmp_path)])
    assert result.exit_code != 0
    assert "stale" in result.output.lower()
    assert "uv lock" in result.output
    assert (tmp_path / "uv.lock").read_bytes() == lock


@pytest.mark.parametrize("command", ["api", "pyproject"])
def test_snapshot_conflicts_and_preserves_user_files(tmp_path, command):
    (tmp_path / "app.py").write_text("app = object()\n")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        "[project]\ndependencies = []\n[tool.posit.connect]\n"
        'app_mode = "python-api"\nentrypoint = "app:app"\nrequirements_file = "missing.txt"\n'
    )
    (tmp_path / "requirements.txt").write_text("owned==1\n")
    generated = tmp_path / "requirements-rsconnect.txt"
    generated.write_text("user-owned\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["write-manifest", command, "-g", "-r", "other.txt", str(tmp_path)])
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    result = runner.invoke(cli, ["write-manifest", command, "-g", "--overwrite", str(tmp_path)])
    assert result.exit_code != 0
    assert "not an rsconnect-generated" in result.output
    assert generated.read_text() == "user-owned\n"
    assert (tmp_path / "requirements.txt").read_text() == "owned==1\n"


def test_missing_lock_companion_is_an_error(tmp_path):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "requirements.txt").write_text("flask\n")
    result = CliRunner().invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert result.exit_code != 0
    assert "companion pyproject.toml is missing" in result.output


def test_broken_selected_lock_does_not_fall_back(tmp_path):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "requirements.txt").write_text("fallback==1\n")
    try:
        (tmp_path / "uv.lock").symlink_to("missing.lock")
    except OSError:
        pytest.skip("symlinks are unavailable")
    result = CliRunner().invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert result.exit_code != 0
    assert "does not exist" in result.output
    assert not (tmp_path / "manifest.json").exists()


def test_unsupported_lockfile_does_not_fall_back(tmp_path):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "requirements.txt").write_text("fallback==1\n")
    (tmp_path / "poetry.lock").write_text("[metadata]\n")
    result = CliRunner().invoke(cli, ["write-manifest", "api", "-r", "poetry.lock", str(tmp_path)])
    assert result.exit_code != 0
    assert "Unsupported dependency source" in result.output
    assert not (tmp_path / "manifest.json").exists()


def test_malformed_requirements_does_not_fall_back(tmp_path):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "requirements.txt").write_text("invalid requirement = =\n")
    result = CliRunner().invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert result.exit_code != 0
    assert "Invalid requirement in requirements.txt" in result.output
    assert not (tmp_path / "manifest.json").exists()


def test_lock_validation_reports_missing_offline_metadata(tmp_path, monkeypatch):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "example"\nversion = "1.0"\ndependencies = []\n')
    subprocess.run([uv.find_uv_bin(), "lock", "--offline"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "app.py").write_text("app = object()\n")
    project.write_text(
        project.read_text().replace("dependencies = []", 'dependencies = ["no-such-package-rsconnect-xyz==1"]')
    )
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "empty-cache"))
    result = CliRunner().invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert result.exit_code != 0
    assert "validate or export uv.lock offline" in result.output
    assert "uv cache" in result.output
    assert "uv.lock is stale" not in result.output


@pytest.mark.parametrize("command", ["api", "pyproject"])
def test_configured_source_and_cli_override(tmp_path, command):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "requirements.txt").write_text("automatic==1\n")
    (tmp_path / "configured.txt").write_text("configured==2\n")
    (tmp_path / "explicit.txt").write_text("explicit==3\n")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["project==4"]\n[tool.posit.connect]\n'
        'app_mode = "python-api"\nentrypoint = "app:app"\nrequirements_file = "configured.txt"\n'
    )
    runner = CliRunner()
    for option, name in [([], "configured.txt"), (["-r", "explicit.txt"], "explicit.txt")]:
        result = runner.invoke(cli, ["write-manifest", command, "--overwrite", *option, str(tmp_path)])
        assert result.exit_code == 0, result.output
        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert manifest["python"]["package_manager"]["package_file"] == name


@pytest.mark.parametrize("dependencies", ['"wrong"', "[42]", '["not a valid requirement @"]'])
def test_invalid_selected_project_does_not_fall_back(tmp_path, dependencies):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "requirements.txt").write_text("fallback==1\n")
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = {dependencies}\n")
    result = CliRunner().invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert result.exit_code != 0
    assert "Invalid project.dependencies" in result.output
    assert not (tmp_path / "manifest.json").exists()


def test_framework_accepts_source_only_deployment_table(tmp_path):
    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "pyproject.toml").write_text('[tool.posit.connect]\nrequirements_file = "custom.txt"\n')
    (tmp_path / "custom.txt").write_text("configured==1\n")
    runner = CliRunner()
    framework = runner.invoke(cli, ["write-manifest", "api", str(tmp_path)])
    assert framework.exit_code == 0, framework.output
    project = runner.invoke(cli, ["write-manifest", "pyproject", str(tmp_path)])
    assert project.exit_code != 0
    assert "app_mode" in project.output


def test_nested_manifest_copies_selected_source_without_overwriting(tmp_path):
    notebook = tmp_path / "nested" / "notebook.ipynb"
    notebook.parent.mkdir()
    notebook.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    (tmp_path / "pyproject.toml").write_text(
        '[tool.posit.connect]\napp_mode = "jupyter-static"\n'
        'entrypoint = "nested/notebook.ipynb"\nrequirements_file = "requirements.txt"\n'
    )
    source = tmp_path / "requirements.txt"
    source.write_text("example==1\n")
    runner = CliRunner()
    result = runner.invoke(cli, ["write-manifest", "pyproject", str(tmp_path)])
    assert result.exit_code == 0, result.output
    with make_manifest_bundle(notebook.parent / "manifest.json"):
        pass
    target = notebook.parent / "requirements.txt"
    target.write_text("owned==2\n")
    previous_manifest = (notebook.parent / "manifest.json").read_bytes()
    result = runner.invoke(cli, ["write-manifest", "pyproject", "--overwrite", str(tmp_path)])
    assert result.exit_code != 0
    assert "Cannot overwrite" in result.output
    assert target.read_text() == "owned==2\n"
    assert source.read_text() == "example==1\n"
    assert (notebook.parent / "manifest.json").read_bytes() == previous_manifest


@pytest.mark.parametrize("command", ["api", "notebook", "quarto", "pyproject"])
@pytest.mark.parametrize(
    "option,expected", [([], "configured.txt"), (["-r", "explicit.txt"], "explicit.txt"), (["-g"], None)]
)
def test_deploy_commands_apply_source_selection(tmp_path, monkeypatch, command, option, expected):
    from rsconnect import main

    (tmp_path / "app.py").write_text("app = object()\n")
    (tmp_path / "notebook.ipynb").write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}')
    (tmp_path / "report.qmd").write_text("# Report\n")
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\ndependencies = []\n[tool.posit.connect]\n"
        'app_mode = "python-api"\nentrypoint = "app:app"\nrequirements_file = "configured.txt"\n'
    )
    selected = []

    def capture(cls, directory, **kwargs):
        selected.append(kwargs["requirements_file"])
        raise RSConnectException("Inspection reached")

    monkeypatch.setattr(main.Environment, "create_python_environment", classmethod(capture))
    monkeypatch.setattr(main, "which_quarto", lambda *_: "quarto")
    monkeypatch.setattr(main, "quarto_inspect", lambda *_: {"engines": ["jupyter"]})
    targets = {
        "api": tmp_path,
        "notebook": tmp_path / "notebook.ipynb",
        "quarto": tmp_path / "report.qmd",
        "pyproject": tmp_path,
    }
    result = CliRunner().invoke(cli, ["deploy", command, *option, str(targets[command]), "-s", "http://x", "-k", "k"])
    assert "Inspection reached" in result.output
    assert selected == [expected]
