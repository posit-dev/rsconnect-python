import json
import pathlib
import typing
from unittest import mock

import pytest
from click.testing import CliRunner

from rsconnect.environment import Environment
from rsconnect.main import cli

from .utils import apply_common_args


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


def test_deploy_quarto_passes_package_installer(tmp_path: pathlib.Path):
    (tmp_path / "doc.qmd").write_text("---\ntitle: t\n---\n")
    (tmp_path / "requirements.txt").write_text("jupyter\n")
    real_create = Environment.create_python_environment
    environments: typing.List[Environment] = []

    def recording_create(*args: typing.Any, **kwargs: typing.Any) -> Environment:
        environment = real_create(*args, **kwargs)
        environments.append(environment)
        return environment

    with mock.patch.object(Environment, "_get_python_env_info", return_value=_fake_env_info()), mock.patch.object(
        Environment, "create_python_environment", side_effect=recording_create
    ), mock.patch("rsconnect.main.which_quarto", return_value="quarto"), mock.patch(
        "rsconnect.main.quarto_inspect", return_value={"quarto": {"version": "1.4.0"}, "engines": ["jupyter"]}
    ), mock.patch("rsconnect.main.RSConnectExecutor"):
        args = apply_common_args(
            ["deploy", "quarto", str(tmp_path / "doc.qmd"), "--package-installer", "uv", "--no-verify"],
            server="http://fake_server",
            key="FAKE_API_KEY",
        )
        result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert len(environments) == 1
    assert environments[0].package_manager == "uv"
    assert environments[0].package_manager_allow_uv is True
