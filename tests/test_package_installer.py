import json
import pathlib
from unittest import mock

import pytest
from click.testing import CliRunner

from rsconnect.environment import Environment
from rsconnect.main import cli


def _fake_env_info() -> Environment:
    return Environment.from_dict(
        {
            "contents": "flask\n",
            "filename": "requirements.txt",
            "locale": "en_US.UTF-8",
            "package_manager": "pip",
            "pip": "23.0.1",
            "python": "3.11.0",
            "source": "file",
        }
    )


@pytest.mark.parametrize("installer", ["uv", "pip"])
@pytest.mark.parametrize("framework", ["shiny", "streamlit", "fastapi"])
def test_write_manifest_framework_passes_package_installer(tmp_path: pathlib.Path, framework: str, installer: str):
    (tmp_path / "app.py").write_text("")
    (tmp_path / "requirements.txt").write_text("flask\n")

    with mock.patch.object(Environment, "_get_python_env_info", return_value=_fake_env_info()):
        result = CliRunner().invoke(
            cli,
            ["write-manifest", framework, "--overwrite", "--package-installer", installer, str(tmp_path)],
        )

    assert result.exit_code == 0, result.output
    package_manager = json.loads((tmp_path / "manifest.json").read_text())["python"]["package_manager"]
    assert package_manager["name"] == installer
    assert package_manager["allow_uv"] is (installer == "uv")
