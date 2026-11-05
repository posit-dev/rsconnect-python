import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from rsconnect.bundle import file_checksum
from rsconnect.main import cli


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "report.ipynb").write_text('{"cells":[],"metadata":{},"nbformat":4,"nbformat_minor":5}')
    (project_dir / "requirements.txt").write_text("voila\n")
    return project_dir


@pytest.mark.parametrize("path", ["proj", "proj/", "proj/report.ipynb"])
@pytest.mark.parametrize("parent_requirements", [False, True])
def test_write_manifest_voila_uses_project_requirements(project: Path, path: str, parent_requirements: bool):
    if parent_requirements:
        Path("requirements.txt").write_text("pandas\n")

    result = CliRunner().invoke(cli, ["write-manifest", "voila", path])

    assert result.exit_code == 0, result.output
    manifest = json.loads((project / "manifest.json").read_text())
    assert manifest["files"]["requirements.txt"]["checksum"] == file_checksum(project / "requirements.txt")


def test_write_manifest_voila_checks_project_manifest_for_overwrite(project: Path):
    manifest_path = project / "manifest.json"
    manifest_path.write_text("{}")

    result = CliRunner().invoke(cli, ["write-manifest", "voila", "proj"])

    assert result.exit_code != 0
    assert "manifest.json already exists" in result.output
    assert manifest_path.read_text() == "{}"

    result = CliRunner().invoke(cli, ["write-manifest", "voila", "--overwrite", "proj"])

    assert result.exit_code == 0, result.output
    assert json.loads(manifest_path.read_text())["metadata"]["appmode"] == "jupyter-voila"


def test_write_manifest_voila_ignores_parent_manifest(project: Path):
    Path("manifest.json").write_text("{}")

    result = CliRunner().invoke(cli, ["write-manifest", "voila", "proj"])

    assert result.exit_code == 0, result.output
    assert (project / "manifest.json").exists()
    assert Path("manifest.json").read_text() == "{}"
