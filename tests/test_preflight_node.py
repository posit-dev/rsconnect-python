from __future__ import annotations

import json
import locale
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from rsconnect.api import (
    ConnectCloudServer,
    RSConnectClient,
    RSConnectExecutor,
    RSConnectServer,
    SPCSConnectServer,
)
from rsconnect.exception import RSConnectException
from rsconnect.preflight_node import (
    _evaluate_node_range,
    _npm_cli_path,
    _parse_node_evaluation,
    run_node_preflight,
)

SERVER_URL = "https://connect.example.test"
DEFAULT_SETTINGS = {
    "enabled": True,
    "status": {"state": "ready"},
    "installations": [
        {"version": "22.4.1", "publishable": True},
        {"version": "20.18.0", "publishable": False},
    ],
}
GO_RUNTIME_SETTINGS = {
    "enabled": True,
    "status": {"enabled": True, "licensed": True, "available": True, "usable": True},
    "installations": [{"version": "22.4.1", "publishable": True}],
}


class FakeClient(RSConnectClient):
    def __init__(
        self,
        settings: Any = DEFAULT_SETTINGS,
        content: dict[str, dict[str, Any]] | None = None,
        settings_error: RSConnectException | None = None,
    ):
        self.settings = settings
        self.content = content or {}
        self.settings_error = settings_error
        self.content_requests: list[str] = []

    def nodejs_settings(self):
        if self.settings_error:
            raise self.settings_error
        return self.settings

    def get_content_by_id(self, app_id: str):
        self.content_requests.append(app_id)
        return self.content.get(app_id, {})


class FakeStore:
    def __init__(self, record: dict[str, Any] | None = None):
        self.record = record
        self.requests: list[str] = []

    def get(self, server_url: str):
        self.requests.append(server_url)
        return self.record


def make_executor(
    *,
    settings: Any = DEFAULT_SETTINGS,
    content: dict[str, dict[str, Any]] | None = None,
    record: dict[str, Any] | None = None,
    app_id: str | None = None,
    new: bool = False,
    store: FakeStore | None = None,
    server: Any = None,
    settings_error: RSConnectException | None = None,
) -> tuple[RSConnectExecutor, FakeClient, FakeStore]:
    client = FakeClient(settings, content, settings_error)
    app_store = store or FakeStore(record)
    executor = cast(Any, RSConnectExecutor.__new__(RSConnectExecutor))
    executor.remote_server = server or RSConnectServer(SERVER_URL, "api-key")
    executor.client = client
    executor.app_store = app_store
    executor.app_id = app_id
    executor.new = new
    return cast(RSConnectExecutor, executor), client, app_store


def make_project(directory: Path, package: Any = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    contents = {"name": "demo", "engines": {"node": "^20.0.0"}} if package is None else package
    (directory / "package.json").write_text(json.dumps(contents), encoding="utf-8")
    (directory / "package-lock.json").write_text("{}", encoding="utf-8")
    return directory


def fake_preflight_tools(monkeypatch, matches: bool = True):
    calls: list[tuple[str, str | None]] = []

    def create(project: str, node_executable: str | None = None):
        calls.append((project, node_executable))
        return SimpleNamespace(node_version="22.22.1")

    def evaluate(node: str, requirement: str, versions: list[str]):
        return {
            "range_valid": True,
            "valid_versions": [True] * len(versions),
            "matches": [matches] * len(versions),
        }, None

    monkeypatch.setattr("rsconnect.preflight_node.NodeEnvironment", SimpleNamespace(create=create))
    monkeypatch.setattr("rsconnect.preflight_node._evaluate_node_range", evaluate)
    return calls


def disable_local_node_tools(monkeypatch):
    def missing_node(project, node_executable=None):
        raise RSConnectException("Could not find npm")

    monkeypatch.setattr("rsconnect.preflight_node.NodeEnvironment", SimpleNamespace(create=missing_node))
    monkeypatch.setattr("rsconnect.preflight_node._npm_cli_path", lambda: None)


def test_new_content_reports_node_runtime_fields_and_does_not_mutate_project(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    before = {path.name: path.read_bytes() for path in project.iterdir()}
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result == {
        "status": "ok",
        "runtime": "nodejs",
        "server": SERVER_URL,
        "local_node": "22.22.1",
        "node_requires": "^20.0.0",
        "server_node_versions": ["22.4.1", "20.18.0"],
        "publishable_node_versions": ["22.4.1"],
        "nodejs_enabled": True,
        "nodejs_status": {"state": "ready"},
        "existing_content": {
            "exists": False,
            "app_id": None,
            "node_version": None,
            "compatibility": "not_applicable",
        },
        "changed_files": [],
        "warnings": [],
        "actions": [],
    }
    assert {path.name: path.read_bytes() for path in project.iterdir()} == before
    assert not any("python" in key for key in result)


def test_missing_engines_node_means_any_publishable_installed_version(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app", {"name": "demo"})
    calls = fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "ok"
    assert result["node_requires"] is None
    assert result["publishable_node_versions"] == ["22.4.1"]
    assert calls == [(str(project), None)]


def test_new_content_ignores_installed_but_unpublishable_versions(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={
            "enabled": True,
            "status": {},
            "installations": [{"version": "20.18.0", "publishable": False}],
        },
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "incompatible"
    assert result["publishable_node_versions"] == []


def test_redeploy_uses_all_installed_versions_and_current_version_is_informational(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, client, store = make_executor(
        content={"saved-guid": {"node_version": "18.17.0"}},
        record={"app_id": "saved-id", "app_guid": "saved-guid"},
        settings={
            "enabled": True,
            "status": {},
            "installations": [{"version": "20.18.0", "publishable": False}],
        },
    )

    result = run_node_preflight(executor, str(project))

    assert store.requests == [SERVER_URL]
    assert client.content_requests == ["saved-guid"]
    assert result["status"] == "ok"
    assert result["existing_content"] == {
        "exists": True,
        "app_id": "saved-guid",
        "node_version": "18.17.0",
        "compatibility": "compatible",
    }


@pytest.mark.parametrize(
    ("content_status", "settings"),
    [
        pytest.param(403, DEFAULT_SETTINGS, id="forbidden"),
        pytest.param(404, DEFAULT_SETTINGS, id="not-found"),
        pytest.param(
            404,
            {"enabled": True, "status": {"state": "ready"}, "installations": []},
            id="not-found-with-server-incompatibility",
        ),
    ],
)
def test_unreadable_existing_content_is_unknown(tmp_path, monkeypatch, content_status, settings):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, client, _ = make_executor(record={"app_guid": "saved-guid"}, settings=settings)

    def inaccessible_content(app_id):
        raise RSConnectException("Content lookup failed.", status=content_status)

    monkeypatch.setattr(client, "get_content_by_id", inaccessible_content)
    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["existing_content"]["compatibility"] == "unknown"
    if content_status == 404:
        assert any("--new" in action for action in result["actions"])
    else:
        assert any("permission" in action.lower() for action in result["actions"])


def test_empty_server_installations_are_incompatible(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={"enabled": True, "status": {}, "installations": []},
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "incompatible"
    assert result["publishable_node_versions"] == []


@pytest.mark.parametrize(
    "installations",
    [
        pytest.param([], id="no-installed-versions"),
        pytest.param([{"version": "22.4.1", "publishable": False}], id="none-publishable"),
    ],
)
def test_complete_empty_publishable_set_is_incompatible_without_local_node_or_npm(tmp_path, monkeypatch, installations):
    project = make_project(tmp_path / "app")
    disable_local_node_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={"enabled": True, "status": {"state": "ready"}, "installations": installations},
    )

    result = run_node_preflight(executor, str(project))

    assert result["local_node"] is None
    assert result["status"] == "incompatible"
    assert result["publishable_node_versions"] == []


def test_incomplete_empty_publishable_set_remains_unknown_without_local_node_or_npm(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    disable_local_node_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={
            "enabled": True,
            "status": {"state": "ready"},
            "installations": [{"version": "22.4.1"}],
        },
    )

    result = run_node_preflight(executor, str(project))

    assert result["local_node"] is None
    assert result["status"] == "unknown"
    assert any("did not report whether Node.js 22.4.1 is publishable" in warning for warning in result["warnings"])


def test_unresolved_target_overrides_empty_server_candidate_set(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    disable_local_node_tools(monkeypatch)
    executor, _, _ = make_executor(
        record={},
        settings={"enabled": True, "status": {"state": "ready"}, "installations": []},
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["existing_content"]["exists"] is True
    assert result["existing_content"]["app_id"] is None
    assert any("no content ID" in warning for warning in result["warnings"])
    assert any("--app-id" in action for action in result["actions"])


def test_missing_publishable_flag_is_unknown_for_new_content(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={
            "enabled": True,
            "status": {},
            "installations": [{"version": "22.4.1"}],
        },
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert any("did not report whether Node.js 22.4.1 is publishable" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    ("field", "value", "expected_status", "expected_action"),
    [
        pytest.param("enabled", False, "incompatible", "enable", id="disabled-status-flag"),
        pytest.param("licensed", False, "incompatible", "license", id="unlicensed"),
        pytest.param("available", False, "incompatible", "available", id="unavailable"),
        pytest.param("usable", False, "incompatible", "usable", id="unusable"),
        pytest.param("configured", False, "incompatible", "configure", id="unconfigured-alias"),
        pytest.param("licensed", "false", "unknown", None, id="malformed-license-flag"),
        pytest.param("available", None, "unknown", None, id="malformed-availability-flag"),
    ],
)
def test_nodejs_status_flags_distinguish_false_from_malformed(
    tmp_path, monkeypatch, field, value, expected_status, expected_action
):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={
            **GO_RUNTIME_SETTINGS,
            "status": {**GO_RUNTIME_SETTINGS["status"], field: value},
        },
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == expected_status
    if expected_action:
        assert any(expected_action in action.lower() for action in result["actions"])
    else:
        assert any("invalid Node.js" in warning for warning in result["warnings"])


def test_go_runtime_status_shape_is_compatible_when_all_flags_are_true(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True, settings=GO_RUNTIME_SETTINGS)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "ok"
    assert result["nodejs_status"] == GO_RUNTIME_SETTINGS["status"]


@pytest.mark.parametrize(
    "settings",
    [
        {"status": {}, "installations": [{"version": "22.4.1", "publishable": True}]},
        {"enabled": True, "installations": [{"version": "22.4.1", "publishable": True}]},
    ],
)
def test_missing_server_nodejs_metadata_is_unknown(tmp_path, monkeypatch, settings):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True, settings=settings)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["nodejs_enabled"] is settings.get("enabled")
    assert result["nodejs_status"] == settings.get("status")


def test_explicitly_disabled_nodejs_is_incompatible(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={
            "enabled": False,
            "status": {"reason": "license", "licensed": False},
            "installations": [],
        },
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "incompatible"
    assert result["nodejs_enabled"] is False
    assert any("Enable Node.js" in action for action in result["actions"])
    assert any("license" in action.lower() for action in result["actions"])


def test_unsupported_settings_endpoint_is_unknown(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings_error=RSConnectException("HTTP 404"),
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["nodejs_enabled"] is None
    assert any("HTTP 404" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "package",
    [
        [],
        {"name": "demo", "engines": []},
        {"name": "demo", "engines": {"node": 22}},
    ],
)
def test_malformed_package_metadata_is_unknown_and_unchanged(tmp_path, monkeypatch, package):
    project = make_project(tmp_path / "app", package)
    before = (project / "package.json").read_bytes()
    fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["changed_files"] == []
    assert (project / "package.json").read_bytes() == before
    assert result["actions"]


def test_invalid_npm_range_is_unknown_with_repair_action(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    monkeypatch.setattr(
        "rsconnect.preflight_node._evaluate_node_range",
        lambda node, requirement, versions: (
            {"range_valid": False, "valid_versions": [True] * len(versions), "matches": []},
            None,
        ),
    )
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert any("not a valid npm semver range" in warning for warning in result["warnings"])
    assert any("Repair package.json engines.node" in action for action in result["actions"])


def test_missing_local_node_tools_are_unknown(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)

    def missing_tools(project, node_executable=None):
        raise RSConnectException("Could not find npm")

    monkeypatch.setattr("rsconnect.preflight_node.NodeEnvironment", SimpleNamespace(create=missing_tools))
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["local_node"] is None
    assert any("Could not find npm" in warning for warning in result["warnings"])


def test_missing_lockfile_does_not_hide_a_proven_server_version_mismatch(tmp_path):
    if not shutil.which("node") or not shutil.which("npm") or not _npm_cli_path():
        pytest.skip("Local Node.js/npm are required to evaluate a real npm range.")
    project = make_project(tmp_path / "app", {"name": "demo", "engines": {"node": "^99.0.0"}})
    (project / "package-lock.json").unlink()
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["local_node"] is None
    assert result["status"] == "incompatible"
    assert result["node_requires"] == "^99.0.0"
    assert any("package-lock.json" in warning for warning in result["warnings"])
    assert any("No publishable server" in warning for warning in result["warnings"])
    assert result["changed_files"] == []


def test_non_utf8_package_is_reported_without_a_traceback_or_mutation(tmp_path):
    project = make_project(tmp_path / "app")
    invalid_bytes = b"\xff"
    (project / "package.json").write_bytes(invalid_bytes)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert any("Could not read package.json" in warning for warning in result["warnings"])
    assert result["changed_files"] == []
    assert (project / "package.json").read_bytes() == invalid_bytes


def test_non_executable_node_is_reported_as_a_local_prerequisite_failure(tmp_path):
    project = make_project(tmp_path / "app")
    executable = tmp_path / "non-executable-node"
    executable.write_text("not an executable", encoding="utf-8")
    executable.chmod(0o600)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project), node=str(executable))

    assert result["status"] == "unknown"
    assert result["local_node"] is None
    assert any("Could not inspect local Node.js/npm prerequisites" in warning for warning in result["warnings"])
    assert result["changed_files"] == []


def test_missing_npm_semver_module_is_unknown(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    monkeypatch.setattr(
        "rsconnect.preflight_node._evaluate_node_range",
        lambda node, requirement, versions: (None, "Could not load npm's semver module."),
    )
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert any("semver module" in warning for warning in result["warnings"])


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_non_utf8_node_evaluator_output_is_reported_as_unknown(tmp_path, monkeypatch, stream):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to verify evaluator output decoding.")

    project = make_project(tmp_path / "app")
    monkeypatch.setattr(
        "rsconnect.preflight_node.NodeEnvironment",
        SimpleNamespace(create=lambda project, node_executable=None: SimpleNamespace(node_version="22.22.1")),
    )
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "utf-8")
    monkeypatch.setattr("rsconnect.preflight_node._npm_cli_path", lambda: "npm-cli.js")
    monkeypatch.setattr(
        "rsconnect.preflight_node._SEMVER_SCRIPT",
        f"process.{stream}.write(Buffer.from([0xff]));",
    )
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project), node=node)

    assert result["status"] == "unknown"
    assert any("Could not run npm's semver evaluator:" in warning for warning in result["warnings"])


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"range_valid": True, "valid_versions": [True], "matches": []},
            id="missing-match-result",
        ),
        pytest.param(
            {"range_valid": True, "valid_versions": [True], "matches": [True, False]},
            id="extra-match-result",
        ),
        pytest.param(
            {"range_valid": True, "valid_versions": [1], "matches": [True]},
            id="non-boolean-valid-version",
        ),
        pytest.param(
            {"range_valid": True, "valid_versions": [True], "matches": [1]},
            id="non-boolean-match",
        ),
        pytest.param(
            {"range_valid": False, "valid_versions": [True], "matches": [False]},
            id="invalid-range-with-match-results",
        ),
    ],
)
def test_node_evaluation_rejects_malformed_version_results(payload):
    evaluation, error = _parse_node_evaluation(json.dumps(payload), version_count=1)

    assert evaluation is None
    assert error == "npm's semver evaluator returned incomplete version results."


def test_node_evaluation_accepts_empty_matches_for_invalid_range():
    payload = {"range_valid": False, "valid_versions": [True, False], "matches": []}

    evaluation, error = _parse_node_evaluation(json.dumps(payload), version_count=2)

    assert error is None
    assert evaluation == payload


def test_custom_node_executable_is_used(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    calls = fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project), node="/opt/node/bin/node")

    assert result["local_node"] == "22.22.1"
    assert calls == [(str(project), "/opt/node/bin/node")]


@pytest.mark.parametrize("filename", ["app.js", "manifest.json"])
def test_preflight_accepts_a_project_file_and_checks_its_parent(tmp_path, monkeypatch, filename):
    project = make_project(tmp_path / "app")
    project_file = project / filename
    project_file.write_text("{}", encoding="utf-8")
    calls = fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project_file))

    assert result["status"] == "ok"
    assert calls == [(str(project), None)]


@pytest.mark.parametrize("filename", ["package.json", "package-lock.json"])
def test_package_metadata_symlinks_are_unknown_and_never_opened(tmp_path, monkeypatch, filename):
    project = make_project(tmp_path / "app")
    target = tmp_path / "target"
    target.write_text("{}")
    path = project / filename
    path.unlink()
    try:
        path.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    calls = fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(new=True)

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "unknown"
    assert result["changed_files"] == []
    assert calls == []
    assert any(f"{filename} is a symlink" in warning for warning in result["warnings"])
    assert any(filename in action for action in result["actions"])


def test_symlinked_metadata_does_not_hide_a_disabled_server(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    package_path = project / "package.json"
    package_path.unlink()
    try:
        package_path.symlink_to(tmp_path / "target")
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")
    calls = fake_preflight_tools(monkeypatch)
    executor, _, _ = make_executor(
        new=True,
        settings={"enabled": False, "status": {}, "installations": []},
    )

    result = run_node_preflight(executor, str(project))

    assert result["status"] == "incompatible"
    assert calls == []


def test_spcs_is_supported_and_connect_cloud_is_rejected(tmp_path, monkeypatch):
    project = make_project(tmp_path / "app")
    fake_preflight_tools(monkeypatch)
    spcs = SPCSConnectServer(SERVER_URL, "api-key", "snowflake-connection")
    executor, _, _ = make_executor(new=True, server=spcs)
    result = run_node_preflight(executor, str(project))
    assert result["server"] == SERVER_URL

    cloud = ConnectCloudServer("account", url="https://api.connect.posit.cloud/v1")
    cloud_executor, _, _ = make_executor(server=cloud)
    with pytest.raises(RSConnectException, match="supports self-hosted"):
        run_node_preflight(cloud_executor, str(project))


@pytest.mark.parametrize(
    ("requirement", "version", "expected"),
    [
        ("^20.0.0", "20.8.1", True),
        ("~20.2.0", "20.2.9", True),
        (">=20.0.0 <21", "20.18.0", True),
        ("20.x || 22.x", "22.4.1", True),
        ("*", "v22.4.1", True),
        ("^22.0.0-0", "22.0.0-rc.2", True),
        ("^22.0.0", "22.0.0-rc.2", False),
    ],
)
def test_ranges_use_local_npm_semver_when_available(requirement, version, expected):
    node = shutil.which("node")
    if not node or not _npm_cli_path():
        pytest.skip("Node.js and npm's semver module are unavailable")

    result, error = _evaluate_node_range(node, requirement, [version])

    if error:
        pytest.skip(error)
    assert result is not None
    assert result["range_valid"] is True
    assert result["valid_versions"] == [True]
    assert result["matches"] == [expected]


def test_npm_shim_cannot_supply_global_semver(tmp_path, monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to verify the npm shim behavior.")

    bin_directory = tmp_path / "volta" / "bin"
    bin_directory.mkdir(parents=True)
    npm_shim = bin_directory / ("npm.cmd" if os.name == "nt" else "npm")
    npm_root = tmp_path / "volta" / "tools" / "image" / "node" / "22.22.1" / "lib" / "node_modules" / "npm"
    npm_cli = npm_root / "bin" / "npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.write_text("process.exit(0);\n", encoding="utf-8")
    (npm_root / "package.json").write_text(json.dumps({"name": "npm"}), encoding="utf-8")
    npm_semver = npm_root / "node_modules" / "semver"
    npm_semver.mkdir(parents=True)
    (npm_semver / "package.json").write_text(json.dumps({"name": "semver"}), encoding="utf-8")
    (npm_semver / "index.js").write_text(
        "module.exports = {validRange: () => '^20.0.0', valid: value => value, satisfies: () => false};",
        encoding="utf-8",
    )
    if os.name == "nt":
        npm_shim.write_text(
            f"@{subprocess.list2cmdline([node, str(npm_cli)])} %*\r\n",
            encoding="utf-8",
        )
    else:
        npm_shim.write_text(
            f'#!/bin/sh\nexec {shlex.quote(node)} {shlex.quote(str(npm_cli))} "$@"\n',
            encoding="utf-8",
        )
        npm_shim.chmod(0o755)
    global_semver = bin_directory / "node_modules" / "semver"
    global_semver.mkdir(parents=True)
    (global_semver / "package.json").write_text(json.dumps({"name": "semver"}), encoding="utf-8")
    (global_semver / "index.js").write_text(
        "module.exports = {validRange: () => '*', valid: value => value, satisfies: () => true};",
        encoding="utf-8",
    )

    legacy_evaluation = subprocess.run(
        [
            node,
            "-e",
            (
                'const {createRequire} = require("module"); '
                'const semver = createRequire(process.argv[1])("semver"); '
                'const valid = semver.valid("22.4.1") !== null; '
                'process.stdout.write(JSON.stringify({matches: [valid && semver.satisfies("22.4.1", "^20.0.0")]}));'
            ),
            str(npm_shim),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert legacy_evaluation.returncode == 0
    assert json.loads(legacy_evaluation.stdout) == {"matches": [True]}

    def which(name):
        return str(npm_shim) if name == "npm" else None

    monkeypatch.setattr("rsconnect.preflight_node.shutil.which", which)

    result, error = _evaluate_node_range(node, "^20.0.0", ["22.4.1"])

    assert result is None
    assert error == "Could not locate npm's local semver module."


@pytest.mark.parametrize(
    ("package", "expected_requirement", "expected_status"),
    [
        ({"name": "demo"}, None, "ok"),
        ({"name": "demo", "engines": {"node": "*"}}, "*", "incompatible"),
    ],
)
def test_preflight_distinguishes_absent_range_from_wildcard_for_prereleases(
    tmp_path, monkeypatch, package, expected_requirement, expected_status
):
    node = shutil.which("node")
    if not node or not _npm_cli_path():
        pytest.skip("Node.js and npm's semver module are unavailable")
    _, error = _evaluate_node_range(node, None, ["22.0.0-rc.1"])
    if error:
        pytest.skip(error)

    project = make_project(tmp_path / "app", package)
    monkeypatch.setattr(
        "rsconnect.preflight_node.NodeEnvironment",
        SimpleNamespace(create=lambda project, node_executable=None: SimpleNamespace(node_version="22.22.1")),
    )
    executor, _, _ = make_executor(
        new=True,
        settings={
            "enabled": True,
            "status": {"state": "ready"},
            "installations": [{"version": "22.0.0-rc.1", "publishable": True}],
        },
    )

    result = run_node_preflight(executor, str(project), node=node)

    assert result["status"] == expected_status
    assert result["node_requires"] == expected_requirement
    assert result["server_node_versions"] == ["22.0.0-rc.1"]
    assert result["publishable_node_versions"] == ["22.0.0-rc.1"]
