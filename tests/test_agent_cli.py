"""Exercise the CLI contracts used by short-lived agent shells."""

import inspect
import json
import logging
import os
from unittest.mock import Mock, patch

import click
import pytest
from click.testing import CliRunner

from rsconnect import main
from rsconnect.main import cli
from rsconnect.api import RSConnectClient, RSConnectServer
from rsconnect.exception import RSConnectException


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Agent login and preflight require POSIX.")


def cli_runner():
    options = {"mix_stderr": False} if "mix_stderr" in inspect.signature(CliRunner).parameters else {}
    return CliRunner(**options)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for variable in (
        "CONNECT_SERVER",
        "CONNECT_API_KEY",
        "CONNECT_IDENTITY_TOKEN",
        "CONNECT_IDENTITY_TOKEN_FILE",
        "CONNECT_CLOUD_ACCOUNT",
        "CONNECT_CLOUD_CLIENT_ID",
        "CONNECT_CLOUD_CLIENT_SECRET",
        "SHINYAPPS_ACCOUNT",
    ):
        monkeypatch.delenv(variable, raising=False)
    for variable in ("HOME", "XDG_CONFIG_HOME", "APPDATA"):
        monkeypatch.setenv(variable, str(tmp_path))
    yield
    from rsconnect.actions import set_verbosity

    set_verbosity(0)


def test_connect_start_json_and_default_policy():
    expected = {"status": "pending", "verification_uri": "https://example.com/verify", "user_code": "ABCD"}
    with patch("rsconnect.device_login.start_connect_login", return_value=expected) as start:
        result = cli_runner().invoke(
            cli,
            ["login", "https://example.com", "--no-wait", "--no-set-default", "--client-id", "public-client"],
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected
    start.assert_called_once_with(
        "https://example.com",
        "example.com",
        insecure=False,
        ca_data=None,
        set_default=False,
        client_id="public-client",
    )


def test_login_callback_keeps_legacy_signature_and_saves_credentials(tmp_path, monkeypatch):
    store = main.ServerStore(str(tmp_path))
    monkeypatch.setattr(main, "server_store", store)
    metadata = {"authorization_endpoint": "https://example.test/authorize"}
    tokens = {"access_token": "access", "refresh_token": "refresh"}

    with patch("rsconnect.oauth.discover_oauth_metadata", return_value=metadata) as discover:
        with patch("rsconnect.oauth.register_client", return_value="client") as register:
            with patch("rsconnect.oauth.login_with_browser", return_value=tokens) as login:
                with patch("rsconnect.oauth.keyring_store_token", return_value=False) as save_token:
                    with click.Context(main.login, info_name="login"):
                        main.login.callback(
                            None, "https://example.test", "legacy", False, None, None, None, False, None, False, 0
                        )

    discover.assert_called_once_with("https://example.test", False, None)
    register.assert_called_once_with(metadata, "https://example.test", False, None)
    login.assert_called_once_with("https://example.test", "client", metadata, False, None)
    save_token.assert_called_once_with("https://example.test", "access", "refresh")
    assert store.get_by_name("legacy")["oauth_client_id"] == "client"
    assert json.loads((tmp_path / "servers.json").read_text())["legacy"]["oauth_access_token"] == "access"


def test_add_callback_keeps_legacy_signature_and_saves_credentials(tmp_path, monkeypatch):
    store = main.ServerStore(str(tmp_path))
    monkeypatch.setattr(main, "server_store", store)
    server = RSConnectServer("https://connect.example.test", "api-key")

    with patch("rsconnect.main._test_server_and_api", return_value=(server, None)) as check:
        with click.Context(main.add, info_name="add"):
            main.add.callback(
                "legacy",
                "https://connect.example.test",
                "api-key",
                None,
                False,
                None,
                None,
                None,
                None,
                None,
                None,
                False,
                True,
                0,
            )

    check.assert_called_once_with("https://connect.example.test", "api-key", False, None)
    assert store.get_by_name("legacy")["api_key"] == "api-key"
    saved = json.loads((tmp_path / "servers.json").read_text())["legacy"]
    assert saved["url"] == "https://connect.example.test"
    assert saved["default"] is True


@pytest.mark.parametrize(
    "command,kind",
    [
        (["login"], "connect"),
        (["add", "--connect-cloud"], "cloud"),
        (["server", "add", "--connect-cloud"], "cloud"),
    ],
)
def test_finish_selected_login_and_pending_json(command, kind):
    expected = {"status": "pending", "name": "target"}
    with patch("rsconnect.device_login.finish_login", return_value=expected) as finish:
        result = cli_runner().invoke(cli, command + ["--name", "target", "--finish", "--timeout", "7"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected
    finish.assert_called_once_with(kind, "target", 7)


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["login", "--finish"], "--finish requires --name"),
        (["login", "--finish", "--no-wait"], "only one"),
        (["login", "https://one.example", "-s", "https://two.example", "--no-wait"], "only one"),
        (["login", "--no-wait"], "specify the server"),
        (["login", "https://example.com", "--identity-token", "synthetic", "--no-wait"], "identity token"),
        (["login", "https://example.com", "--timeout", "7"], "--timeout requires --finish"),
        (["login", "https://example.com", "--timeout", "120"], "--timeout requires --finish"),
        (["login", "https://example.com", "--no-wait", "--timeout", "7"], "--timeout requires --finish"),
        (["login", "https://example.com", "-n", "target", "--finish"], "saved login options"),
        (["login", "-n", "target", "--finish", "--timeout", "0"], "Invalid value"),
        (["login", "-n", "target", "--finish", "--timeout", "-1"], "Invalid value"),
        (["add", "-n", "target", "--no-wait"], "require --connect-cloud"),
        (["add", "--connect-cloud", "--no-wait"], "requires --account"),
        (["add", "--connect-cloud", "-A", "team", "--client-id", "id", "--no-wait"], "service account"),
        (["add", "--connect-cloud", "-A", "team", "-s", "https://other.example", "--no-wait"], "cannot be combined"),
        (["add", "--connect-cloud", "-A", "team", "--insecure", "--no-wait"], "Posit Connect options"),
        (["add", "--connect-cloud", "-A", "team", "--api-key", "synthetic", "--no-wait"], "Posit Connect options"),
        (["add", "--connect-cloud", "-A", "team", "--token", "synthetic", "--no-wait"], "shinyapps.io options"),
        (["add", "--connect-cloud", "-n", "cloud", "--finish", "--account", "team"], "saved login options"),
        (["add", "--connect-cloud", "-n", "cloud", "--finish", "--api-key", "synthetic"], "saved login options"),
    ],
)
def test_device_login_option_errors(arguments, message):
    result = cli_runner().invoke(cli, arguments)
    assert result.exit_code == (2 if "Invalid value" in message else 1)
    assert result.stdout == ""
    assert message in result.stderr


def test_cloud_start_does_not_take_an_ambient_connect_server(monkeypatch):
    monkeypatch.setenv("CONNECT_SERVER", "https://unrelated.example.com")
    expected = {"status": "pending", "account": "team"}
    with patch("rsconnect.device_login.start_cloud_login", return_value=expected) as start:
        result = cli_runner().invoke(cli, ["add", "--connect-cloud", "-A", "team", "-n", "cloud", "--no-wait"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected
    assert start.call_args.args == ("team", "cloud")
    assert start.call_args.kwargs["set_default"] is False
    assert "unrelated" not in start.call_args.kwargs["url"]


def test_cloud_start_does_not_take_an_ambient_shinyapps_account(monkeypatch):
    monkeypatch.setenv("SHINYAPPS_ACCOUNT", "another-team")
    result = cli_runner().invoke(cli, ["add", "--connect-cloud", "--no-wait"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "requires --account" in result.stderr


@pytest.mark.parametrize("status,exit_code", [("ok", 0), ("incompatible", 3), ("unknown", 0)])
def test_preflight_json_and_exit_status(tmp_path, status, exit_code):
    expected = {"status": status, "changed_files": []}
    executor = Mock()
    executor.validate_server.return_value = executor
    with patch("rsconnect.main.RSConnectExecutor", return_value=executor) as create:
        with patch("rsconnect.preflight.run_preflight", return_value=expected) as check:
            result = cli_runner().invoke(cli, ["preflight", "-n", "target", str(tmp_path), "--fix", "--new"])
    assert result.exit_code == exit_code, result.output
    assert json.loads(result.stdout) == expected
    check.assert_called_once_with(executor, str(tmp_path), True)
    assert create.call_args.kwargs["path"] == str(tmp_path)
    assert create.call_args.kwargs["new"] is True


def test_preflight_new_and_explicit_content_are_exclusive():
    result = cli_runner().invoke(cli, ["preflight", "--new", "--app-id", "synthetic"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "only one" in result.stderr


def test_node_preflight_dispatch_and_incompatible_exit(tmp_path):
    expected = {"status": "incompatible", "runtime": "nodejs", "changed_files": []}
    executor = Mock()
    executor.validate_server.return_value = executor
    executable = tmp_path / "node"
    executable.write_text("")
    with patch("rsconnect.main.RSConnectExecutor", return_value=executor):
        with patch("rsconnect.preflight_node.run_node_preflight", return_value=expected) as check:
            result = cli_runner().invoke(
                cli, ["preflight", "-n", "target", str(tmp_path), "--runtime", "nodejs", "--node", str(executable)]
            )
    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout) == expected
    check.assert_called_once_with(executor, str(tmp_path), str(executable))


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--runtime", "nodejs", "--fix"], "--fix applies only to Python"),
        (["--runtime", "unsupported"], "Invalid value"),
    ],
)
def test_node_preflight_invalid_options(arguments, message):
    result = cli_runner().invoke(cli, ["preflight"] + arguments)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert message in result.stderr


def test_node_executable_requires_node_runtime(tmp_path):
    executable = tmp_path / "node"
    executable.write_text("")
    result = cli_runner().invoke(cli, ["preflight", "--node", str(executable)])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--node requires --runtime nodejs" in result.stderr


@pytest.mark.parametrize(
    "command,options",
    [
        (["login"], ["https://connect.example.test"]),
        (["login"], ["--server", "https://connect.example.test"]),
        (["login"], ["--identity-token", "synthetic"]),
        (["login"], ["--identity-token-file", "{file}"]),
        (["login"], ["--client-id", "synthetic"]),
        (["login"], ["--insecure"]),
        (["login"], ["--cacert", "{file}"]),
        (["login"], ["--no-set-default"]),
        (["login"], ["--use-device-code"]),
        (["add", "--connect-cloud"], ["--account", "team"]),
        (["add", "--connect-cloud"], ["--client-id", "synthetic"]),
        (["add", "--connect-cloud"], ["--client-secret", "synthetic"]),
        (["add", "--connect-cloud"], ["--set-default"]),
        (["add", "--connect-cloud"], ["--api-key", "synthetic"]),
        (["add", "--connect-cloud"], ["--snowflake-connection-name", "synthetic"]),
        (["add", "--connect-cloud"], ["--token", "synthetic"]),
        (["add", "--connect-cloud"], ["--secret", "synthetic"]),
    ],
)
def test_finish_rejects_each_explicit_start_option(tmp_path, command, options):
    credential_file = tmp_path / "credential"
    credential_file.write_text("synthetic")
    options = [str(credential_file) if option == "{file}" else option for option in options]
    with patch("rsconnect.device_login.finish_login") as finish:
        result = cli_runner().invoke(cli, command + ["--name", "target", "--finish"] + options)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "saved login options" in result.stderr
    finish.assert_not_called()


@pytest.mark.parametrize("command", [["login"], ["add", "--connect-cloud"], ["server", "add", "--connect-cloud"]])
def test_finish_ignores_ambient_start_options(monkeypatch, command):
    monkeypatch.setenv("CONNECT_SERVER", "https://unrelated.example.test")
    monkeypatch.setenv("CONNECT_INSECURE", "true")
    expected = {"status": "pending", "name": "target"}
    with patch("rsconnect.device_login.finish_login", return_value=expected) as finish:
        result = cli_runner().invoke(cli, command + ["--name", "target", "--finish"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected
    finish.assert_called_once()


def test_preflight_operational_failure_has_json_and_distinct_exit(tmp_path):
    with patch("rsconnect.main.RSConnectExecutor", side_effect=RSConnectException("Authentication failed.")):
        result = cli_runner().invoke(cli, ["preflight", "-n", "target", str(tmp_path)])
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["status"] == "error"
    assert report["runtime"] == "python"
    assert report["error"] == "Authentication failed."
    assert report["actions"]
    assert report["changed_files"] == []
    assert result.stderr == ""


@pytest.mark.parametrize(
    "arguments",
    [["--new", "--app-id", "synthetic"], ["--runtime", "nodejs", "--fix"], ["--node", "{file}"]],
)
def test_preflight_option_conflicts_are_usage_errors(tmp_path, arguments):
    node = tmp_path / "node"
    node.write_text("")
    arguments = [str(node) if argument == "{file}" else argument for argument in arguments]
    result = cli_runner().invoke(cli, ["preflight", str(tmp_path)] + arguments)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Error:" in result.stderr


def test_node_preflight_accepts_file_deployment_target(tmp_path):
    target = tmp_path / "manifest.json"
    target.write_text("{}")
    expected = {"status": "unknown", "runtime": "nodejs", "actions": ["Verify local prerequisites."]}
    executor = Mock()
    executor.validate_server.return_value = executor
    with patch("rsconnect.main.RSConnectExecutor", return_value=executor):
        with patch("rsconnect.preflight_node.run_node_preflight", return_value=expected) as check:
            result = cli_runner().invoke(cli, ["preflight", str(target), "--runtime", "nodejs"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == expected
    check.assert_called_once_with(executor, str(target), None)


@pytest.mark.parametrize("verbose", ["-v", "-vv"])
def test_device_json_commands_honor_verbosity(caplog, verbose):
    expected = {"status": "pending", "name": "target"}
    with caplog.at_level(logging.DEBUG, logger="rsconnect"):
        with patch("rsconnect.device_login.finish_login", return_value=expected):
            result = cli_runner().invoke(cli, ["login", "-n", "target", "--finish", verbose])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == expected
    assert "Finishing device authentication." in caplog.text


@pytest.mark.parametrize("metadata,status,exit_code", [("3.12\n", "ok", 0), ("3.9\n", "incompatible", 3)])
def test_python_preflight_real_report_through_cli(tmp_path, monkeypatch, metadata, status, exit_code):
    from rsconnect.metadata import AppStore

    (tmp_path / ".python-version").write_text(metadata)
    monkeypatch.setattr("rsconnect.preflight.platform.python_version", lambda: "3.12.2")
    client = RSConnectClient(RSConnectServer("https://connect.example.test", "synthetic"))
    monkeypatch.setattr(
        client, "python_settings", lambda: {"installations": [{"version": "3.12.8", "publishable": True}]}
    )
    executor = Mock()
    executor.remote_server = client._server
    executor.client = client
    executor.app_store = AppStore(str(tmp_path / "app.py"))
    executor.path = str(tmp_path)
    executor.app_id = None
    executor.new = True
    executor.validate_server.return_value = executor
    with patch("rsconnect.main.RSConnectExecutor", return_value=executor):
        result = cli_runner().invoke(cli, ["preflight", str(tmp_path), "--new"])
    assert result.exit_code == exit_code, result.output
    report = json.loads(result.stdout)
    assert report["status"] == status
    assert report["runtime"] == "python"
    assert report["python_requires"] == ("~=3.12.0" if status == "ok" else "~=3.9.0")
    assert report["publishable_python_versions"] == ["3.12.8"]
    assert report["local_python"] == "3.12.2"
    assert report["existing_content"]["exists"] is False
    assert report["changed_files"] == []
    assert (tmp_path / ".python-version").read_text() == metadata
