import json
import pathlib
import typing
from unittest import mock

import pytest
from click.testing import CliRunner

from rsconnect.environment import Environment
from rsconnect.main import cli

from .utils import apply_common_args


def _fake_create(captured: dict[str, typing.Any]):
    def fake_create(cls: typing.Any, directory: str, **kwargs: typing.Any) -> Environment:
        captured.update(kwargs)
        package_manager = kwargs.get("package_manager")
        return Environment.from_dict(
            {
                "contents": "flask\n",
                "filename": "requirements.txt",
                "locale": "en_US.UTF-8",
                "package_manager": package_manager.value if package_manager else "pip",
                "pip": "23.0.1",
                "python": "3.11.0",
                "source": "file",
            }
        )

    return classmethod(fake_create)


@pytest.mark.parametrize("installer", ["uv", "pip"])
@pytest.mark.parametrize("framework", ["shiny", "streamlit", "fastapi"])
def test_write_manifest_framework_passes_package_installer(tmp_path: pathlib.Path, framework: str, installer: str):
    (tmp_path / "app.py").write_text("")
    (tmp_path / "requirements.txt").write_text("flask\n")
    captured: dict[str, typing.Any] = {}

    with mock.patch("rsconnect.main.Environment.create_python_environment", new=_fake_create(captured)):
        result = CliRunner().invoke(
            cli,
            ["write-manifest", framework, "--overwrite", "--package-installer", installer, str(tmp_path)],
        )

    assert result.exit_code == 0, result.output
    assert captured["package_manager"].value == installer
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["python"]["package_manager"]["name"] == installer


def test_deploy_quarto_passes_package_installer(tmp_path: pathlib.Path):
    (tmp_path / "doc.qmd").write_text("---\ntitle: t\n---\n")
    (tmp_path / "requirements.txt").write_text("jupyter\n")
    captured: dict[str, typing.Any] = {}

    with mock.patch("rsconnect.main.Environment.create_python_environment", new=_fake_create(captured)), mock.patch(
        "rsconnect.main.which_quarto", return_value="quarto"
    ), mock.patch(
        "rsconnect.main.quarto_inspect", return_value={"quarto": {"version": "1.4.0"}, "engines": ["jupyter"]}
    ), mock.patch("rsconnect.main.RSConnectExecutor"):
        args = apply_common_args(
            ["deploy", "quarto", str(tmp_path / "doc.qmd"), "--package-installer", "uv", "--no-verify"],
            server="http://fake_server",
            key="FAKE_API_KEY",
        )
        result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert captured["package_manager"].value == "uv"
