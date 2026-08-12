from __future__ import annotations

import os
import pathlib
import tarfile
import typing
from io import BytesIO

import pytest

from rsconnect.exception import RSConnectException
from rsconnect.publisher import config, record
from rsconnect.publisher.service import (
    CONTENT_TYPES,
    InitRequest,
    PublishRequest,
    initialize_project,
    publish_project,
)

SERVER_URL = "https://connect.example.com"


def test_content_types_map_the_source_deploy_commands():
    commands = {command: spec.type for spec in CONTENT_TYPES for command in spec.deploy_commands}
    assert commands["streamlit"] == "python-streamlit"
    assert commands["shiny"] == "python-shiny"
    assert commands["fastapi"] == "python-fastapi"
    assert commands["api"] == commands["flask"] == "python-flask"
    assert commands["notebook"] == "jupyter-notebook"
    assert commands["html"] == "html"
    assert commands["nodejs"] == "nodejs"


def test_initialize_project_writes_complete_config(tmp_path: pathlib.Path):
    result = initialize_project(
        InitRequest(
            project_dir=str(tmp_path),
            config_name="sales",
            content_type="python-fastapi",
            entrypoint="app.py:app",
            title="Sales API",
            description="Quarterly sales data",
            files=("app.py", "data/**", "!data/private/**"),
            python={
                "version": "3.12",
                "package_file": "pyproject.toml",
                "package_manager": "pip",
                "requires_python": ">=3.12",
            },
            environment={"API_URL": "https://example.com"},
            secrets=("API_KEY",),
            connect={"runtime": {"min_processes": 1, "max_processes": 3}},
        )
    )

    assert result.config_name == "sales"
    cfg = config.read_config(result.config_path)
    assert cfg.type == "python-fastapi"
    assert cfg.entrypoint == "app.py:app"
    assert cfg.description == "Quarterly sales data"
    assert cfg.files[:3] == ["app.py", "data/**", "!data/private/**"]
    assert "/pyproject.toml" in cfg.files
    assert "/.posit/publish/sales.toml" in cfg.files
    assert cfg.environment == {"API_URL": "https://example.com"}
    assert cfg.secrets == ["API_KEY"]
    assert cfg.connect == {"runtime": {"min_processes": 1, "max_processes": 3}}


def test_initialize_project_supplies_python_defaults(tmp_path: pathlib.Path):
    result = initialize_project(
        InitRequest(
            project_dir=str(tmp_path),
            config_name="app",
            content_type="python-shiny",
            entrypoint="app.py",
        )
    )
    assert result.config.python == {"package_file": "requirements.txt", "package_manager": "pip"}
    assert result.config.files == [
        "*",
        "/requirements.txt",
        "/.posit/publish/app.toml",
    ]


def test_initialize_project_requires_quarto_version(tmp_path: pathlib.Path):
    with pytest.raises(RSConnectException, match="requires a quarto mapping"):
        initialize_project(
            InitRequest(
                project_dir=str(tmp_path),
                content_type="quarto-static",
                entrypoint="report.qmd",
            )
        )


def test_initialize_project_refuses_implicit_overwrite(tmp_path: pathlib.Path):
    request = InitRequest(
        project_dir=str(tmp_path),
        config_name="app",
        content_type="python-shiny",
        entrypoint="app.py",
    )
    initialize_project(request)
    with pytest.raises(RSConnectException, match="already exists"):
        initialize_project(request)


def _fake_deployment(monkeypatch: pytest.MonkeyPatch, captured: dict[str, typing.Any]) -> None:
    from rsconnect import api as api_mod
    from rsconnect import deploy as deploy_mod
    from rsconnect.environment import Environment

    environment = Environment.from_dict(
        {
            "python": "3.11.0",
            "pip": "24.0",
            "locale": "en_US.UTF-8",
            "package_manager": "pip",
            "source": "requirements.txt",
            "filename": "requirements.txt",
            "contents": "shiny\n",
            "error": None,
        }
    )
    monkeypatch.setattr(
        deploy_mod.Environment,
        "create_python_environment",
        classmethod(lambda cls, *args, **kwargs: environment),
    )
    monkeypatch.setattr(api_mod.AppStore, "set", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(api_mod.RSConnectClient, "server_settings", lambda self: {})
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_server", lambda self: self)

    def validate_app_mode(self: typing.Any, app_mode: typing.Any):
        self.app_mode = app_mode
        return self

    def deploy_bundle(self: typing.Any, *_args: typing.Any, **_kwargs: typing.Any):
        self.bundle.seek(0)
        with tarfile.open(fileobj=self.bundle, mode="r:gz") as archive:
            captured["files"] = sorted(member.name for member in archive.getmembers() if member.isfile())
        self.bundle.seek(0)
        captured["app_id"] = self.app_id
        captured["server_url"] = self.remote_server.url
        captured["context"] = self.publisher_context
        self.deployed_info = {
            "task_id": "task-1",
            "app_url": SERVER_URL + "/content/guid/",
            "app_id": "7",
            "app_guid": self.app_id or "GUID-NEW",
            "title": self.title,
            "dashboard_url": SERVER_URL + "/connect/#/apps/guid",
            "draft_url": None,
            "bundle_id": "99",
        }
        return self

    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_app_mode", validate_app_mode)
    monkeypatch.setattr(
        api_mod.RSConnectExecutor,
        "make_deployment_name",
        lambda self, title, force_unique_name=False: title,
    )
    monkeypatch.setattr(api_mod.RSConnectExecutor, "deploy_bundle", deploy_bundle)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "should_deploy_as_draft", lambda self, *args: False)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "supports_verify_before_activate", False)
    for method in ("emit_task_log", "verify_deployment", "emit_content_url"):
        monkeypatch.setattr(api_mod.RSConnectExecutor, method, lambda self, *args, **kwargs: self)


def _init_shiny(tmp_path: pathlib.Path, files: typing.Tuple[str, ...] = tuple()) -> None:
    (tmp_path / "app.py").write_text("from shiny import App\n")
    (tmp_path / "requirements.txt").write_text("shiny\n")
    initialize_project(
        InitRequest(
            project_dir=str(tmp_path),
            config_name="app",
            content_type="python-shiny",
            entrypoint="app.py",
            files=files,
        )
    )


def test_first_publish_uses_config_and_creates_record(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, typing.Any] = {}
    _fake_deployment(monkeypatch, captured)
    _init_shiny(tmp_path, files=("/app.py", "/requirements.txt"))

    result = publish_project(
        PublishRequest(
            project_dir=str(tmp_path),
            server=SERVER_URL,
            api_key="fake",
            verify=False,
        )
    )

    assert result.config_name == "app"
    assert result.content_guid == "GUID-NEW"
    assert captured["files"] == [
        ".posit/publish/app.toml",
        "app.py",
        "manifest.json",
        "requirements.txt",
    ]
    records = record.discover_records(str(tmp_path))
    assert len(records) == 1
    assert os.path.basename(records[0]) == result.deployment_name + ".toml"
    assert record.read_record(records[0]).configuration_name == "app"
    assert config.read_config(str(tmp_path / ".posit" / "publish" / "app.toml")).entrypoint == "app.py"


def test_publish_maps_configured_bundle_options(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    from rsconnect.publisher import service as service_mod

    captured: dict[str, typing.Any] = {}
    _fake_deployment(monkeypatch, captured)
    (tmp_path / "report.ipynb").write_text("{}")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'report'\nversion = '1.0'\n")
    initialize_project(
        InitRequest(
            project_dir=str(tmp_path),
            config_name="report",
            content_type="jupyter-notebook",
            entrypoint="report.ipynb",
            python={
                "version": "3.12.2",
                "requires_python": ">=3.12",
                "package_file": "pyproject.toml",
                "package_manager": "uv",
            },
            jupyter={"hide_all_input": True, "hide_tagged_input": True},
            connect={
                "kubernetes": {
                    "default_image_name": "registry.example.com/python:3.12",
                    "default_py_environment_management": False,
                    "default_r_environment_management": True,
                }
            },
        )
    )
    original_plan = service_mod.plan_deploy_bundle

    def capture_plan(*args: typing.Any, **kwargs: typing.Any):
        captured["options"] = kwargs["options"]
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(service_mod, "plan_deploy_bundle", capture_plan)

    publish_project(
        PublishRequest(
            project_dir=str(tmp_path),
            server=SERVER_URL,
            api_key="fake",
            verify=False,
        )
    )

    options = captured["options"]
    assert options.python_version == "3.12.2"
    assert options.python_requires == ">=3.12"
    assert options.package_installer == "uv"
    assert options.hide_all_input is True
    assert options.hide_tagged_input is True
    assert options.image == "registry.example.com/python:3.12"
    assert options.env_management_py is False
    assert options.env_management_r is True


def test_subsequent_publish_reuses_record_identity(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, typing.Any] = {}
    _fake_deployment(monkeypatch, captured)
    _init_shiny(tmp_path)
    first = publish_project(PublishRequest(project_dir=str(tmp_path), server=SERVER_URL, api_key="fake", verify=False))

    captured.clear()
    second = publish_project(PublishRequest(project_dir=str(tmp_path), api_key="fake", verify=False))

    assert second.deployment_name == first.deployment_name
    assert captured["app_id"] == "GUID-NEW"
    assert len(record.discover_records(str(tmp_path))) == 1


def test_executor_without_publisher_context_does_not_write_posit_files(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    from rsconnect.api import RSConnectExecutor
    from rsconnect.models import AppModes

    executor = RSConnectExecutor(
        path=str(tmp_path),
        server=SERVER_URL,
        api_key="fake",
        app_id="GUID-1",
    )
    executor.app_mode = AppModes.PYTHON_SHINY
    executor.bundle = BytesIO(b"not inspected without a Publisher context")
    executor.deployed_info = {
        "task_id": "task-1",
        "app_url": SERVER_URL + "/content/guid/",
        "app_id": "7",
        "app_guid": "GUID-1",
        "title": "App",
        "dashboard_url": SERVER_URL + "/connect/#/apps/guid",
        "draft_url": None,
        "bundle_id": "99",
    }
    monkeypatch.setattr(executor.app_store, "set", lambda *args, **kwargs: None)

    executor.save_deployed_info()

    assert not (tmp_path / ".posit").exists()


def test_publish_requires_explicit_deployment_when_ambiguous(tmp_path: pathlib.Path):
    _init_shiny(tmp_path)
    deployments = tmp_path / ".posit" / "publish" / "deployments"
    deployments.mkdir()
    for name, guid in (("production", "GUID-1"), ("staging", "GUID-2")):
        record.write_record(
            str(tmp_path),
            name,
            record.PublisherRecord(
                server_url=SERVER_URL,
                type="python-shiny",
                configuration_name="app",
                id=guid,
            ),
        )

    with pytest.raises(RSConnectException, match="specify a deployment record"):
        publish_project(PublishRequest(project_dir=str(tmp_path), api_key="fake"))


def test_publish_selects_exact_deployment(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, typing.Any] = {}
    _fake_deployment(monkeypatch, captured)
    _init_shiny(tmp_path)
    for name, guid in (("production", "GUID-1"), ("staging", "GUID-2")):
        record.write_record(
            str(tmp_path),
            name,
            record.PublisherRecord(
                server_url=SERVER_URL,
                type="python-shiny",
                configuration_name="app",
                id=guid,
            ),
        )

    result = publish_project(
        PublishRequest(
            project_dir=str(tmp_path),
            deployment_name="staging",
            api_key="fake",
            verify=False,
        )
    )
    assert result.deployment_name == "staging"
    assert captured["app_id"] == "GUID-2"
