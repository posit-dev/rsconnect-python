# pyright: reportMissingTypeStubs=false, reportUnusedImport=false
from __future__ import annotations

import json
from subprocess import CalledProcessError, CompletedProcess, run
from typing import Any, Dict, List, Optional

from .exception import RSConnectException
from .log import logger


def snow(*args: str) -> CompletedProcess[str]:
    ensure_snow_installed()
    return run(["snow"] + list(args), capture_output=True, text=True, check=True)


def ensure_snow_installed() -> None:
    try:
        import snowflake.cli  # noqa: F401

        logger.debug("snowflake-cli is installed.")

    except ImportError:
        logger.warning("snowflake-cli is not installed.")
        try:
            run(["snow", "--version"], capture_output=True, check=True)
        except CalledProcessError:
            raise RSConnectException("snow is installed but could not be run.")
        except FileNotFoundError:
            raise RSConnectException("snow cannot be found.")


def list_connections() -> List[Dict[str, Any]]:

    try:
        res = snow("connection", "list", "--format", "json")
        connection_list = json.loads(res.stdout)
        return connection_list
    except CalledProcessError:
        raise RSConnectException("Could not list snowflake connections.")


def get_parameters(name: Optional[str] = None) -> Dict[str, Any]:
    """Get Snowflake connection parameters.
    Args:
        name: The name of the connection to retrieve. If None, returns the default connection.

    Returns:
        A dictionary of connection parameters.
    """
    try:
        from snowflake.connector.config_manager import CONFIG_MANAGER
    except ImportError:
        raise RSConnectException("snowflake-cli is not installed.")
    try:
        connections = CONFIG_MANAGER["connections"]
        if not isinstance(connections, dict):
            raise TypeError("connections is not a dictionary")

        if name is None:
            def_connection_name = CONFIG_MANAGER["default_connection_name"]
            if not isinstance(def_connection_name, str):
                raise TypeError("default_connection_name is not a string")
            params = connections[def_connection_name]
        else:
            params = connections[name]

        if not isinstance(params, dict):
            raise TypeError("connection parameters is not a dictionary")

        return {str(k): v for k, v in params.items()}

    except (KeyError, AttributeError) as e:
        raise RSConnectException(f"Could not get Snowflake connection: {e}")


def generate_jwt(name: Optional[str] = None) -> str:

    _ = get_parameters(name)
    connection_name = "" if name is None else name

    try:
        res = snow("connection", "generate-jwt", "--connection", connection_name, "--format", "json")
        try:
            output = json.loads(res.stdout)
        except json.JSONDecodeError:
            raise RSConnectException(f"Failed to parse JSON from snow-cli: {res.stdout}")
        jwt = output.get("message")
        if jwt is None:
            raise RSConnectException(f"Failed to generate JWT: Missing 'message' field in response: {output}")
        return jwt
    except CalledProcessError as e:
        raise RSConnectException(f"Failed to generate JWT for connection '{name}': {e.stderr}")
