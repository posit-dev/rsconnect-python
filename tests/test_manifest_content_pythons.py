import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from rsconnect.main import cli
from scripts.content_python_versions import content_python_versions


@pytest.mark.parametrize("version", content_python_versions())
def test_manifest_uses_content_python_environment(version, tmp_path):
    found = subprocess.run(
        ["uv", "python", "find", "--no-project", "--no-python-downloads", "cpython@" + version],
        capture_output=True,
        text=True,
    )
    if found.returncode:
        if "No interpreter found" in found.stderr:
            pytest.skip("CPython %s is not installed" % version)
        found.check_returncode()

    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "--python", found.stdout.strip(), str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), "idna==3.10"], check=True)
    expected_version = subprocess.check_output(
        [str(python), "-c", "import platform; print(platform.python_version())"], text=True
    ).strip()

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("app = None\n")
    result = CliRunner().invoke(
        cli, ["write-manifest", "api", str(project), "--python", str(python), "--force-generate", "--exclude-renv"]
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((project / "manifest.json").read_text())
    assert manifest["python"]["version"] == expected_version
    assert manifest["python"]["package_manager"]["package_file"] == "requirements-connect.txt"
    assert "idna==3.10" in (project / "requirements-connect.txt").read_text().splitlines()
