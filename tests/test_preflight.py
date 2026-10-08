from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from rsconnect.api import ConnectCloudServer, RSConnectClient, RSConnectExecutor, RSConnectServer, SPCSConnectServer
from rsconnect.exception import RSConnectException
from rsconnect.environment import fake_module_file_from_directory
from rsconnect.metadata import AppStore, sha1
from rsconnect.preflight import run_preflight

SERVER_URL = "https://connect.example.test"
DEFAULT_SETTINGS = {
    "installations": [
        {"version": "3.12.8", "publishable": True},
        {"version": "3.11.9", "publishable": True},
    ]
}


class Client(RSConnectClient):
    def __init__(self, settings: Any, content: dict[str, dict[str, Any]] | None = None):
        self.settings = settings
        self.content = content or {}
        self.content_requests: list[str] = []

    def python_settings(self) -> Any:
        return self.settings

    def get_content_by_id(self, id: str) -> Any:
        self.content_requests.append(id)
        return self.content.get(id, {})


class Store:
    def __init__(self, record: dict[str, Any] | None = None):
        self.record = record
        self.requests: list[str] = []

    def get(self, server_url: str):
        self.requests.append(server_url)
        return self.record


def make_executor(
    project: Path,
    *,
    settings: Any = None,
    content: dict[str, dict[str, Any]] | None = None,
    record: dict[str, Any] | None = None,
    app_id: str | None = None,
    new: bool = False,
    store: Any = None,
    server: Any = None,
) -> tuple[RSConnectExecutor, Client, Any]:
    client = Client(DEFAULT_SETTINGS if settings is None else settings, content)
    app_store = Store(record) if store is None else store
    executor = cast(Any, RSConnectExecutor.__new__(RSConnectExecutor))
    executor.remote_server = server or RSConnectServer(SERVER_URL, "api-key")
    executor.client = client
    executor.app_store = app_store
    executor.app_id = app_id
    executor.new = new
    return cast(RSConnectExecutor, executor), client, app_store


def save_deployment_record(app_file: Path, app_id: str) -> None:
    AppStore(str(app_file)).set(
        SERVER_URL,
        str(app_file),
        "https://connect.example.test/content",
        app_id,
        app_id,
        "test",
        "python-shiny",
    )


@pytest.fixture(autouse=True)
def preflight_environment(monkeypatch):
    monkeypatch.setattr("rsconnect.preflight.platform.python_version", lambda: "3.12.2")
    monkeypatch.setattr("rsconnect.preflight.shutil.which", lambda _: "/usr/bin/quarto")


def test_metadata_precedence_and_explicit_constraint_are_preserved(tmp_path):
    (tmp_path / ".python-version").write_text("3.10\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.12"\n')
    (tmp_path / "setup.cfg").write_text("[options]\npython_requires = >=3.13\n")
    executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={"installations": [{"version": "3.10.8", "publishable": True}]},
    )

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["python_requires"] == "~=3.10.0"
    assert result["status"] == "ok"
    assert result["changed_files"] == []
    assert (tmp_path / ".python-version").read_text() == "3.10\n"


def test_new_constraint_uses_exact_patch_versions(tmp_path):
    (tmp_path / ".python-version").write_text("==3.11.8\n")
    executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={"installations": [{"version": "3.11.9", "publishable": True}]},
    )

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "incompatible"
    assert result["publishable_python_versions"] == ["3.11.9"]


def test_existing_content_checks_all_installed_versions_for_redeploy(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = "==3.11.9"\n')
    executor, client, store = make_executor(
        tmp_path,
        settings={
            "installations": [
                {"version": "3.10.14", "publishable": True},
                {"version": "3.11.9", "publishable": False},
            ]
        },
        content={"saved-guid": {"py_version": "3.10.14"}},
        record={"app_id": "saved-id", "app_guid": "saved-guid"},
    )

    result = run_preflight(executor, str(tmp_path))

    assert store.requests == [SERVER_URL]
    assert client.content_requests == ["saved-guid"]
    assert result["status"] == "ok"
    assert result["publishable_python_versions"] == ["3.10.14"]
    assert result["existing_content"] == {
        "exists": True,
        "app_id": "saved-guid",
        "installed_python_version": "3.10.14",
        "server_python_versions": ["3.10.14", "3.11.9"],
        "python_compatibility": "compatible",
    }

    new_executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={
            "installations": [
                {"version": "3.10.14", "publishable": True},
                {"version": "3.11.9", "publishable": False},
            ]
        },
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = "==3.11.9"\n')

    new_result = run_preflight(new_executor, str(tmp_path))

    assert new_result["status"] == "incompatible"


def test_explicit_app_id_overrides_local_record(tmp_path):
    executor, client, store = make_executor(
        tmp_path,
        app_id="explicit-guid",
        record={"app_id": "record-id"},
        content={"explicit-guid": {"py_version": "3.12.1"}},
    )

    result = run_preflight(executor, str(tmp_path))

    assert store.requests == []
    assert client.content_requests == ["explicit-guid"]
    assert result["existing_content"]["app_id"] == "explicit-guid"


def test_incomplete_deployment_record_is_unknown_and_does_not_fix(tmp_path):
    executor, _, _ = make_executor(tmp_path, record={"title": "unfinished deployment"})

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert any("no content ID" in warning for warning in result["warnings"])
    assert any("--app-id" in action and "--new" in action for action in result["actions"])
    assert not (tmp_path / ".python-version").exists()

    executor.new = True
    result = run_preflight(executor, str(tmp_path))
    assert result["existing_content"]["exists"] is False

    executor.new = False
    executor.app_id = "explicit-guid"
    result = run_preflight(executor, str(tmp_path))
    assert result["existing_content"]["app_id"] == "explicit-guid"


@pytest.mark.parametrize("candidate", ["directory", "module", "manifest"])
def test_directory_resolves_each_info_lookup_candidate(tmp_path, candidate):
    project = tmp_path / "project"
    project.mkdir()
    module = Path(fake_module_file_from_directory(str(project)))
    manifest = project / "manifest.json"
    target = {
        "directory": project,
        "module": module,
        "manifest": manifest,
    }[candidate]
    save_deployment_record(target, "saved-guid")
    executor, client, _ = make_executor(project, store=AppStore(str(module)))

    result = run_preflight(executor, str(project), fix=True)

    assert result["status"] == "ok"
    assert result["existing_content"]["app_id"] == "saved-guid"
    assert client.content_requests == ["saved-guid"]
    assert result["changed_files"] == []
    assert not (project / ".python-version").exists()


def test_ambiguous_directory_records_are_unknown_and_do_not_fix(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    module = Path(fake_module_file_from_directory(str(project)))
    save_deployment_record(project, "directory-guid")
    save_deployment_record(project / "manifest.json", "manifest-guid")
    executor, client, _ = make_executor(project, store=AppStore(str(module)))

    result = run_preflight(executor, str(project), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] is None
    assert client.content_requests == []
    assert result["changed_files"] == []
    assert any("Multiple local deployment records" in warning for warning in result["warnings"])
    assert not (project / ".python-version").exists()


@pytest.mark.parametrize("store_kind", ["file", "executor"])
@pytest.mark.parametrize("source_name", ["report.ipynb", "report.qmd"])
def test_directory_with_single_file_deployment_is_unknown_and_does_not_fix(
    tmp_path, monkeypatch, store_kind, source_name
):
    project = tmp_path / "project"
    project.mkdir()
    report = project / source_name
    report.write_text("{}", encoding="utf-8")
    store = None
    if store_kind == "file":
        save_deployment_record(report, "saved-guid")
    else:
        config_dir = tmp_path / "user-config"
        monkeypatch.setattr("rsconnect.metadata.config_dirname", lambda: str(config_dir))
        file_store = AppStore(fake_module_file_from_directory(str(report)))
        file_store.set(
            SERVER_URL,
            str(report),
            "https://connect.example.test/content",
            "saved-guid",
            "saved-guid",
            "test",
            "python-shiny",
        )
        store = AppStore(fake_module_file_from_directory(str(project)))
    executor, client, _ = make_executor(project, store=store)

    result = run_preflight(executor, str(project), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] is None
    assert client.content_requests == []
    assert result["changed_files"] == []
    assert any("exact file path" in action.lower() for action in result["actions"])
    assert not (project / ".python-version").exists()


def test_unreadable_appstore_is_unknown_and_does_not_fix(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store_path = tmp_path / "rsconnect-python" / "project.json"
    store_path.parent.mkdir()
    store_path.write_text("{invalid", encoding="utf-8")
    executor, _, _ = make_executor(project)

    result = run_preflight(executor, str(project), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["changed_files"] == []
    assert result["actions"]
    assert not (project / ".python-version").exists()


def test_malformed_record_id_is_unknown_and_does_not_fix(tmp_path):
    executor, client, _ = make_executor(tmp_path, record={"app_id": ["not-a-content-id"]})

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] is None
    assert client.content_requests == []
    assert result["changed_files"] == []
    assert not (tmp_path / ".python-version").exists()


@pytest.mark.parametrize("store_kind", ["file", "executor"])
def test_exact_file_target_uses_its_deployment_record_and_parent_metadata(tmp_path, store_kind):
    project = tmp_path / "project"
    project.mkdir()
    content_file = project / "report.ipynb"
    content_file.write_text("{}", encoding="utf-8")
    (project / ".python-version").write_text("3.11\n", encoding="utf-8")
    if store_kind == "file":
        save_deployment_record(content_file, "saved-guid")
        store = None
    else:
        store = Store({"app_id": "saved-guid", "app_guid": "saved-guid"})

    executor, client, _ = make_executor(
        project,
        content={"saved-guid": {"py_version": "3.11.8"}},
        store=store,
    )

    result = run_preflight(executor, str(content_file), fix=True)

    assert result["status"] == "ok"
    assert result["runtime"] == "python"
    assert result["python_requires"] == "~=3.11.0"
    assert result["existing_content"]["app_id"] == "saved-guid"
    assert client.content_requests == ["saved-guid"]
    assert result["changed_files"] == []
    assert (project / ".python-version").read_text(encoding="utf-8") == "3.11\n"


def test_appstore_config_fallback_record_is_used(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    module = Path(fake_module_file_from_directory(str(project)))
    config_dir = tmp_path / "user-config"
    monkeypatch.setattr("rsconnect.metadata.config_dirname", lambda: str(config_dir))
    fallback = config_dir / "applications" / f"{sha1(os.path.abspath(module))}.json"
    fallback.parent.mkdir(parents=True)
    fallback.write_text(json.dumps({SERVER_URL: {"app_id": "saved-id", "app_guid": "saved-guid"}}))
    store = AppStore(str(module))
    executor, client, _ = make_executor(
        project,
        store=store,
        content={"saved-guid": {"py_version": "3.12.1"}},
    )

    result = run_preflight(executor, str(project))

    assert client.content_requests == ["saved-guid"]
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] == "saved-guid"


def test_new_overrides_local_deployment_record(tmp_path):
    executor, client, store = make_executor(
        tmp_path,
        new=True,
        record={"app_id": "saved-id"},
    )

    result = run_preflight(executor, str(tmp_path))

    assert store.requests == []
    assert client.content_requests == []
    assert result["existing_content"]["exists"] is False


def test_empty_server_availability_is_unknown_without_mutation(tmp_path):
    executor, _, _ = make_executor(tmp_path, new=True, settings={"installations": []})

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["publishable_python_versions"] == []
    assert result["changed_files"] == []
    assert not (tmp_path / ".python-version").exists()


def test_python_settings_failure_is_unknown_and_actionable(tmp_path, monkeypatch):
    executor, client, _ = make_executor(tmp_path, new=True)

    def fail_settings():
        raise RSConnectException("settings unavailable", status=503)

    monkeypatch.setattr(client, "python_settings", fail_settings)
    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["changed_files"] == []
    assert any("Could not read server Python settings" in warning for warning in result["warnings"])
    assert any("Check the server's Python installations" in action for action in result["actions"])
    assert not (tmp_path / ".python-version").exists()


@pytest.mark.parametrize(
    ("status_code", "action_text"),
    [
        (404, "--new"),
        (403, "access"),
        (None, "Connect access"),
    ],
)
def test_unreadable_redeploy_content_is_unknown_with_recovery_action(tmp_path, monkeypatch, status_code, action_text):
    executor, client, _ = make_executor(
        tmp_path,
        record={"app_id": "saved-guid"},
        settings=DEFAULT_SETTINGS,
    )

    def fail_read(_app_id: str):
        raise RSConnectException("content lookup failed", status=status_code)

    monkeypatch.setattr(client, "get_content_by_id", fail_read)
    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] == "saved-guid"
    assert any(action_text in action for action in result["actions"])
    if status_code == 404:
        assert any("--new" in action for action in result["actions"])


def test_invalid_content_response_is_unknown(tmp_path):
    executor, _, _ = make_executor(
        tmp_path,
        record={"app_id": "saved-guid"},
        content={"saved-guid": None},  # type: ignore[dict-item]
    )

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "unknown"
    assert any("invalid response" in warning for warning in result["warnings"])
    assert result["actions"]


def test_missing_publishable_flags_are_unknown_legacy_permissibility(tmp_path):
    executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={"installations": [{"version": "3.12.8"}]},
    )

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["local_python_publishable"] is None
    assert result["publishable_python_versions"] == []
    assert result["changed_files"] == []
    assert any("legacy permissibility is unknown" in warning for warning in result["warnings"])


def test_invalid_python_version_is_preserved_and_content_result_is_assigned(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("")
    executor, _, _ = make_executor(tmp_path, new=True)

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is False
    assert result["changed_files"] == []
    assert pin.read_text() == ""
    assert any("unusable Python requirement" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "metadata_bytes",
    [
        b"[project\nrequires-python = '>=3.12'\n",
        b"\xff",
    ],
)
def test_unreadable_python_metadata_is_unknown_and_actionable(tmp_path, metadata_bytes):
    (tmp_path / "pyproject.toml").write_bytes(metadata_bytes)
    executor, _, _ = make_executor(tmp_path, new=True)

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["changed_files"] == []
    assert result["actions"]
    assert not (tmp_path / ".python-version").exists()


def test_metadata_permission_error_is_unknown(tmp_path, monkeypatch):
    def deny_read(_project: str):
        raise PermissionError("permission denied")

    monkeypatch.setattr("rsconnect.preflight.detect_python_version_requirement", deny_read)
    executor, _, _ = make_executor(tmp_path, new=True)

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert any("permission denied" in warning for warning in result["warnings"])
    assert result["actions"]
    assert not (tmp_path / ".python-version").exists()


def test_metadata_programming_error_is_not_hidden_as_unknown(tmp_path, monkeypatch):
    def bug(_project: str):
        raise RuntimeError("unexpected implementation failure")

    monkeypatch.setattr("rsconnect.preflight.detect_python_version_requirement", bug)
    executor, _, _ = make_executor(tmp_path, new=True)

    with pytest.raises(RuntimeError, match="unexpected implementation failure"):
        run_preflight(executor, str(tmp_path), fix=True)


@pytest.mark.parametrize(
    ("filename", "contents", "expected_constraint"),
    [
        ("pyproject.toml", '[project]\nrequires-python = ""\n', None),
        ("pyproject.toml", '[project]\nrequires-python = "not-a-specifier"\n', "not-a-specifier"),
        ("setup.cfg", "[options]\npython_requires =\n", None),
        ("setup.cfg", "[options]\npython_requires = not-a-specifier\n", "not-a-specifier"),
    ],
)
def test_invalid_declared_requirement_is_not_masked_by_fix(tmp_path, filename, contents, expected_constraint):
    metadata = tmp_path / filename
    metadata.write_text(contents)
    executor, _, _ = make_executor(tmp_path, new=True)

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["python_requires"] == expected_constraint
    assert result["changed_files"] == []
    assert not (tmp_path / ".python-version").exists()
    assert any(filename in warning and "unusable Python requirement" in warning for warning in result["warnings"])
    assert any(filename in action and "Repair or remove" in action for action in result["actions"])


def test_fix_exclusively_creates_pin_and_rechecks_constraint(tmp_path):
    executor, _, store = make_executor(
        tmp_path,
        new=True,
        record={"app_id": "must-not-be-read"},
        settings={"installations": [{"version": "3.13.4", "publishable": True}]},
    )

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert store.requests == []
    assert result["changed_files"] == [".python-version"]
    assert (tmp_path / ".python-version").read_text() == "3.13\n"
    assert result["python_requires"] == "~=3.13.0"
    assert result["status"] == "ok"


def test_unpinned_local_version_mismatch_is_unknown_until_pin_applied(tmp_path, monkeypatch):
    monkeypatch.setattr("rsconnect.preflight.platform.python_version", lambda: "3.13.2")
    executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={"installations": [{"version": "3.12.8", "publishable": True}]},
    )

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "unknown"
    assert result["recommended_python"] == "3.12"
    assert result["changed_files"] == []
    assert any("dependency compatibility has not been tested" in warning for warning in result["warnings"])


def test_existing_python_version_pin_warns_when_local_python_does_not_match(tmp_path):
    (tmp_path / ".python-version").write_text("3.11\n", encoding="utf-8")
    executor, _, _ = make_executor(
        tmp_path,
        record={"app_id": "saved-guid"},
        content={"saved-guid": {"py_version": "3.11.8"}},
    )

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "ok"
    assert any(
        "Local Python 3.12.2 does not satisfy the project requirement ~=3.11.0" in warning
        for warning in result["warnings"]
    )


def test_existing_python_version_pin_that_matches_local_has_no_mismatch_warning(tmp_path):
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    executor, _, _ = make_executor(tmp_path, new=True)

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "ok"
    assert not any("does not satisfy the project requirement" in warning for warning in result["warnings"])


def test_unknown_redeploy_has_an_action_even_without_python_constraint(tmp_path):
    executor, _, _ = make_executor(
        tmp_path,
        settings={"installations": []},
        record={"app_id": "saved-guid"},
    )

    result = run_preflight(executor, str(tmp_path))

    assert result["status"] == "unknown"
    assert result["actions"]
    assert any("existing content ID" in action for action in result["actions"])


@pytest.mark.parametrize(
    "local, versions, expected",
    [
        ("3.12.2", ["3.11.8", "3.12.9", "3.13.1"], "3.12"),
        ("3.12.2", ["3.10.8", "3.14.1"], "3.14"),
        ("3.14.2", ["3.10.8", "3.13.1"], "3.13"),
    ],
)
def test_fix_uses_helper_pin_selection(tmp_path, monkeypatch, local, versions, expected):
    monkeypatch.setattr("rsconnect.preflight.platform.python_version", lambda: local)
    executor, _, _ = make_executor(
        tmp_path,
        new=True,
        settings={"installations": [{"version": version, "publishable": True} for version in versions]},
    )

    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["recommended_python"] == expected
    assert (tmp_path / ".python-version").read_text() == expected + "\n"
    assert result["status"] == "ok"


def test_connect_cloud_is_rejected(tmp_path):
    cloud = ConnectCloudServer("account", url="https://api.connect.posit.cloud/v1")
    executor, _, _ = make_executor(tmp_path, server=cloud)

    with pytest.raises(RSConnectException, match="not Connect Cloud"):
        run_preflight(executor, str(tmp_path))


def test_spcs_executor_is_supported(tmp_path):
    server = SPCSConnectServer(SERVER_URL, "api-key", "snowflake-connection")
    executor, _, _ = make_executor(tmp_path, server=server)

    result = run_preflight(executor, str(tmp_path))

    assert result["server"] == SERVER_URL
    assert result["status"] == "ok"


def test_metadata_symlink_is_reported_without_reading_or_fixing(tmp_path, monkeypatch):
    target = tmp_path / "real-python-version"
    target.write_text("3.12\n")
    pin = tmp_path / ".python-version"
    try:
        pin.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    executor, _, _ = make_executor(tmp_path, new=True)

    def unexpected_read(_project: str):
        pytest.fail("symlinked Python metadata must not be read")

    monkeypatch.setattr("rsconnect.preflight.detect_python_version_requirement", unexpected_read)
    result = run_preflight(executor, str(tmp_path), fix=True)

    assert result["status"] == "unknown"
    assert result["changed_files"] == []
    assert result["actions"]
    assert any("is a symlink; refusing to read it" in warning for warning in result["warnings"])
    assert pin.is_symlink()
