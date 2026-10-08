"""Keep new agent commands POSIX-only without restricting existing commands."""

import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from rsconnect import device_login, main, oauth, preflight, preflight_node, validation
from rsconnect.exception import RSConnectException
from rsconnect.metadata import ServerStore


def cli_runner():
    options = {"mix_stderr": False} if "mix_stderr" in inspect.signature(CliRunner).parameters else {}
    return CliRunner(**options)


@pytest.fixture
def unsupported_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(main, "server_store", ServerStore(base_dir=str(tmp_path)))
    for variable in ("CONNECT_SERVER", "CONNECT_IDENTITY_TOKEN", "CONNECT_IDENTITY_TOKEN_FILE"):
        monkeypatch.delenv(variable, raising=False)
    yield
    from rsconnect.actions import set_verbosity

    set_verbosity(0)


@pytest.mark.parametrize(
    "function,arguments",
    [
        (device_login.start_connect_login, ("https://example.test", "target")),
        (device_login.start_cloud_login, ("team", "target")),
        (device_login.finish_login, ("connect", "target")),
        (device_login.finish_login, ("cloud", "target")),
    ],
)
def test_resumable_api_rejects_windows_before_state_access(unsupported_platform, monkeypatch, function, arguments):
    lock = Mock()
    monkeypatch.setattr(device_login, "_state_lock", lock)
    with pytest.raises(RSConnectException, match="supported only on POSIX"):
        function(*arguments)
    lock.assert_not_called()


@pytest.mark.parametrize(
    "command",
    [
        ["login", "https://example.test", "--no-wait"],
        ["login", "--name", "target", "--finish"],
        ["add", "--connect-cloud", "--account", "team", "--name", "target", "--no-wait"],
        ["add", "--connect-cloud", "--name", "target", "--finish"],
        ["server", "add", "--connect-cloud", "--account", "team", "--name", "target", "--no-wait"],
        ["server", "add", "--connect-cloud", "--name", "target", "--finish"],
    ],
)
def test_resumable_cli_rejects_windows_on_stderr(unsupported_platform, monkeypatch, command):
    start = Mock()
    finish = Mock()
    monkeypatch.setattr(device_login, "start_connect_login", start)
    monkeypatch.setattr(device_login, "start_cloud_login", start)
    monkeypatch.setattr(device_login, "finish_login", finish)
    result = cli_runner().invoke(main.cli, command)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "supported only on POSIX" in result.stderr
    start.assert_not_called()
    finish.assert_not_called()


@pytest.mark.parametrize("runtime", ["python", "nodejs"])
def test_preflight_cli_rejects_windows_before_executor_access(unsupported_platform, monkeypatch, tmp_path, runtime):
    executor = Mock()
    monkeypatch.setattr(main, "RSConnectExecutor", executor)
    result = cli_runner().invoke(main.cli, ["preflight", str(tmp_path), "--runtime", runtime])
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    assert report["runtime"] == runtime
    assert "supported only on POSIX" in report["error"]
    assert report["changed_files"] == []
    executor.assert_not_called()


@pytest.mark.parametrize("function", [preflight.run_preflight, preflight_node.run_node_preflight])
def test_preflight_api_rejects_windows_before_project_access(unsupported_platform, function):
    with pytest.raises(RSConnectException, match="supported only on POSIX"):
        function(None, "/missing/project")


def test_existing_blocking_device_login_remains_available_on_windows(unsupported_platform, monkeypatch):
    login = Mock(return_value={"access_token": "dummy-access", "refresh_token": "dummy-refresh"})
    monkeypatch.setattr(oauth, "discover_oauth_metadata", lambda *args: {})
    monkeypatch.setattr(oauth, "login_with_device_code", login)
    monkeypatch.setattr(oauth, "keyring_store_token", lambda *args: False)

    result = cli_runner().invoke(
        main.cli, ["login", "https://example.test", "--name", "target", "--client-id", "public", "--use-device-code"]
    )

    assert result.exit_code == 0, result.output
    login.assert_called_once_with("https://example.test", "public", {}, False, None, open_browser=False)
    assert main.server_store.get_by_name("target")["oauth_access_token"] == "dummy-access"
