import json
import logging
import subprocess
import sys

import pytest
from pytest import LogCaptureFixture, MonkeyPatch

from rsconnect.exception import RSConnectException
from rsconnect.snowflake import (
    ensure_snow_installed,
    generate_jwt,
    get_connection_parameters,
    list_connections,
)

SAMPLE_CONNECTIONS = [
    {
        "connection_name": "dev",
        "parameters": {
            "account": "example-dev-acct",
            "user": "alice@example.com",
            "database": "EXAMPLE_DB",
            "warehouse": "DEV_WH",
            "role": "ACCOUNTADMIN",
            "authenticator": "SNOWFLAKE_JWT",
        },
        "is_default": False,
    },
    {
        "connection_name": "prod",
        "parameters": {
            "account": "example-prod-acct",
            "user": "alice@example.com",
            "database": "EXAMPLE_DB_PROD",
            "schema": "DATA",
            "warehouse": "DEFAULT_WH",
            "role": "DEVELOPER",
            "authenticator": "SNOWFLAKE_JWT",
            "private_key_file": "/home/alice/snowflake/rsa_key.p8",
        },
        "is_default": True,
    },
]


@pytest.fixture(autouse=True)
def setup_caplog(caplog: LogCaptureFixture):
    # Set the log level to debug to capture all logs
    caplog.set_level(logging.DEBUG)


def test_ensure_snow_installed_success(caplog: LogCaptureFixture):
    # snowflake-cli is installed as dev-dependency and should succeed

    ensure_snow_installed()

    # Verify the debug log message
    assert "snowflake-cli is installed" in caplog.text


class MockRunResult:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def test_ensure_snow_installed_binary(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture):
    # Test when import fails but snow binary is available

    # Remove snowflake modules if they exist
    monkeypatch.delitem(sys.modules, "snowflake.cli", raising=False)
    monkeypatch.delitem(sys.modules, "snowflake", raising=False)

    monkeypatch.setattr("builtins.__import__", mocked_import)

    # Mock subprocess.run to return success
    def mock_run(cmd: list[str], **kwargs: list[str]):
        assert cmd == ["snow", "--version"]
        return MockRunResult(returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Should not raise exception
    ensure_snow_installed()

    # Verify log message
    assert "snowflake-cli is not installed" in caplog.text


def test_ensure_snow_installed_nobinary(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture):
    # Test when import fails and snow binary is not found

    # Remove snowflake modules if they exist
    monkeypatch.delitem(sys.modules, "snowflake.cli", raising=False)
    monkeypatch.delitem(sys.modules, "snowflake", raising=False)

    monkeypatch.setattr("builtins.__import__", mocked_import)

    # Mock subprocess.run to raise FileNotFoundError
    def mock_run(cmd: list[str], **kwargs):
        raise FileNotFoundError("No such file or directory: 'snow'")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RSConnectException) as excinfo:
        ensure_snow_installed()

    assert "snow cannot be found" in str(excinfo.value)

    # Verify log message
    assert "snowflake-cli is not installed" in caplog.text


def test_ensure_snow_installed_failing_binary(monkeypatch: MonkeyPatch, caplog: LogCaptureFixture):
    # Test when import fails and snow binary exits with error

    # Remove snowflake modules if they exist
    monkeypatch.delitem(sys.modules, "snowflake.cli", raising=False)
    monkeypatch.delitem(sys.modules, "snowflake", raising=False)

    monkeypatch.setattr("builtins.__import__", mocked_import)

    # Mock subprocess.run to return failure
    def mock_run(cmd: list[str], **kwargs):
        assert cmd == ["snow", "--version"]
        return MockRunResult(returncode=1)

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RSConnectException) as excinfo:
        ensure_snow_installed()

    assert "snow is installed but could not be run" in str(excinfo.value)

    # Verify log message
    assert "snowflake-cli is not installed" in caplog.text


# Patch the import to raise ImportError
original_import = __import__


def mocked_import(name: str, *args, **kwargs):
    if name == "snowflake.cli":
        raise ImportError("No module named 'snowflake.cli'")
    return original_import(name, *args, **kwargs)


def test_list_connections(monkeypatch: MonkeyPatch):

    class MockCompletedProcess:
        returncode = 0
        stdout = json.dumps(SAMPLE_CONNECTIONS)

    def mock_run(cmd: list[str], **kwargs):
        assert cmd == ["snow", "connection", "list", "--format", "json"]
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)

    connections = list_connections()

    assert len(connections) == 2
    assert connections[1]["is_default"] is True


def test_get_connection_noname_default(monkeypatch: MonkeyPatch):
    # Test that get_connection_parameters() returns parameters from
    # the default connection when no name is provided

    monkeypatch.setattr("rsconnect.snowflake.list_connections", lambda: SAMPLE_CONNECTIONS)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)

    connection = get_connection_parameters()

    assert connection["account"] == "example-prod-acct"
    assert connection["role"] == "DEVELOPER"


def test_get_connection_named(monkeypatch: MonkeyPatch):
    # Test that get_connection_parameters() returns the specified connection when a name is provided

    monkeypatch.setattr("rsconnect.snowflake.list_connections", lambda: SAMPLE_CONNECTIONS)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)

    connection = get_connection_parameters("dev")

    # Should return the connection with the specified name
    assert connection["account"] == "example-dev-acct"
    assert connection["role"] == "ACCOUNTADMIN"


def test_get_connection_errs_if_none(monkeypatch: MonkeyPatch):
    # Test that get_connection_parameters() raises an exception when no matching connection is found

    # Test with empty connections list
    monkeypatch.setattr("rsconnect.snowflake.list_connections", lambda: [])
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)

    with pytest.raises(RSConnectException) as excinfo:
        get_connection_parameters()
    assert "No Snowflake connections found" in str(excinfo.value)

    # Test with connections but non-existent name
    monkeypatch.setattr("rsconnect.snowflake.list_connections", lambda: SAMPLE_CONNECTIONS)

    with pytest.raises(RSConnectException) as excinfo:
        get_connection_parameters("nexiste")
    assert "No Snowflake connection found with name 'nexiste'" in str(excinfo.value)


def test_generate_jwt(monkeypatch: MonkeyPatch):
    """Test the JWT generation for Snowflake connections."""
    # Mock the generate_jwt subprocess call
    sample_jwt = '{"message": "header.payload.signature"}'

    class MockSnowGenerateJWT:
        returncode = 0
        stdout = sample_jwt

    def mock_run(cmd: list[str], **kwargs):
        assert cmd[0:3] == ["snow", "connection", "generate-jwt"]
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True
        assert kwargs.get("check") is True

        # Check which connection we're generating a JWT for
        if "--connection" in cmd:
            connection_idx = cmd.index("--connection") + 1
            conn_name = cmd[connection_idx]

            # Empty string means default connection
            if conn_name == "":
                return MockSnowGenerateJWT()
            elif conn_name == "dev":
                return MockSnowGenerateJWT()
            elif conn_name == "prod":
                return MockSnowGenerateJWT()
            else:
                raise subprocess.CalledProcessError(
                    returncode=1, cmd=cmd, output="", stderr=f"Error: No connection found with name '{conn_name}'"
                )
        return MockSnowGenerateJWT()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("rsconnect.snowflake.list_connections", lambda: SAMPLE_CONNECTIONS)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)

    # Case 1: Test with default connection (no name parameter)
    jwt = generate_jwt()
    assert jwt == "header.payload.signature"

    # Case 2: Test with a valid connection name
    jwt = generate_jwt("dev")
    assert jwt == "header.payload.signature"

    # Case 3: Test with an invalid connection name
    with pytest.raises(RSConnectException) as excinfo:
        generate_jwt("nexiste")
    assert "No Snowflake connection found with name 'nexiste'" in str(excinfo.value)


def test_generate_jwt_command_failure(monkeypatch: MonkeyPatch):
    """Test error handling when snow command fails."""

    def mock_run(cmd: list[str], **kwargs):
        raise RSConnectException(message="Error: Authentication failed")

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)
    monkeypatch.setattr("rsconnect.snowflake.get_connection_parameters", lambda name=None: {})

    with pytest.raises(RSConnectException) as excinfo:
        generate_jwt()
    assert "Error: Authentication failed" in str(excinfo)


def test_generate_jwt_invalid_json(monkeypatch: MonkeyPatch):
    """Test handling of invalid JSON output."""

    class MockProcessInvalidJSON:
        returncode = 0
        stdout = "Not a JSON string"

    def mock_run(cmd: list[str], **kwargs):
        return MockProcessInvalidJSON()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)
    monkeypatch.setattr("rsconnect.snowflake.get_connection_parameters", lambda name=None: {})

    with pytest.raises(RSConnectException) as excinfo:
        generate_jwt()
    assert "Failed to parse JSON" in str(excinfo)


def test_generate_jwt_missing_message(monkeypatch: MonkeyPatch):
    """Test handling of JSON without the expected message field."""

    class MockProcessNoMessage:
        returncode = 0
        stdout = '{"status": "success", "data": {}}'

    def mock_run(cmd: list[str], **kwargs):
        return MockProcessNoMessage()

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr("rsconnect.snowflake.ensure_snow_installed", lambda: None)
    monkeypatch.setattr("rsconnect.snowflake.get_connection_parameters", lambda name=None: {})

    with pytest.raises(RSConnectException) as excinfo:
        generate_jwt()
    assert "Failed to generate JWT" in str(excinfo)
