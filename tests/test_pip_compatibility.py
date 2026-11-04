"""Opt-in integration checks against an isolated Python with pip installed."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from packaging.version import Version


@pytest.mark.skipif(not os.environ.get("RSCONNECT_COMPAT_PYTHON"), reason="No compatibility interpreter selected")
def test_dependency_inspection_with_selected_pip(tmp_path: Path):
    python = os.path.abspath(os.environ["RSCONNECT_COMPAT_PYTHON"])
    repo = Path(__file__).resolve().parents[1]
    site = tmp_path / "site"
    site.mkdir()
    for name in ("rsconnect", "rsconnect-python", "rsconnect-utils", "demo-url"):
        dist = site / f"{name.replace('-', '_')}-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
        if name == "demo-url":
            (dist / "direct_url.json").write_text(
                json.dumps({"url": "https://example.com/rsconnect/demo.whl", "archive_info": {}})
            )

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(repo), str(site)))
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    def inspect(requirements_file):
        result = subprocess.run(
            [python, "-m", "rsconnect.subprocesses.inspect_environment", "-r", requirements_file, str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
            cwd=tmp_path,
            env=env,
        )
        return json.loads(result.stdout)

    version = subprocess.check_output([python, "-m", "pip", "--version"], text=True).split()[1]
    generated = inspect("none")
    if Version(version) < Version("20.3"):
        assert f"requires pip 20.3 or later (found {version})" in generated["error"]
        assert "install --upgrade pip" in generated["error"]
    else:
        lines = generated["contents"].splitlines()
        assert "rsconnect-utils==1.0" in lines
        assert "demo-url @ https://example.com/rsconnect/demo.whl" in lines
        assert "rsconnect==1.0" not in lines
        assert "rsconnect-python==1.0" not in lines

        local = tmp_path / "rsconnect-local"
        metadata = local / "demo_local.egg-info"
        metadata.mkdir(parents=True)
        (metadata / "PKG-INFO").write_text("Metadata-Version: 2.1\nName: demo-local\nVersion: 1.0\n")
        (site / "demo-local.egg-link").write_text(f"{local}\n.\n")
        env["PYTHONPATH"] += os.pathsep + str(local)
        rejected = inspect("none")
        assert "Editable dependencies outside the deployment directory" in rejected["error"]
        assert str(local.resolve()) in rejected["error"]

    (tmp_path / "requirements.txt").write_text(
        "rsconnect==1.0\nrsconnect-python==1.0\nrsconnect-utils==1.0\n"
        "demo-url @ https://example.com/rsconnect/demo.whl\n-e ./rsconnect-local\n"
    )
    requirements = inspect("requirements.txt")
    assert requirements["contents"] == (
        "rsconnect-utils==1.0\ndemo-url @ https://example.com/rsconnect/demo.whl\n-e ./rsconnect-local\n"
    )
