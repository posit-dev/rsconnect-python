# pyright: reportMissingTypeStubs=false, reportUnusedImport=false
from __future__ import annotations

import json
import os
import pathlib
from subprocess import CalledProcessError, CompletedProcess, run
from typing import Any, Dict, List, Optional

# Flag to track if tomlkit is available
_has_tomlkit = False
try:
    import tomlkit

    _has_tomlkit = True
except ImportError:
    pass

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


# Implement get_connection_parameters using
# the snowflake.connector package
def _resolve_config_paths():
    """Resolve Snowflake configuration file paths following snowflake-connector-python's approach.

    Returns a tuple of (config_file_path, connections_file_path)
    """
    # Check for SNOWFLAKE_HOME env var first
    snowflake_home = os.environ.get("SNOWFLAKE_HOME")
    if snowflake_home:
        base_path = pathlib.Path(snowflake_home).expanduser()
        if base_path.exists():
            return (base_path / "config.toml", base_path / "connections.toml")

    # Otherwise use platform-specific directories
    try:
        # Try to use platformdirs if available
        from platformdirs import PlatformDirs

        platform_dirs = PlatformDirs(appname="snowflake", appauthor=False)
        config_path = pathlib.Path(platform_dirs.user_config_path)
        return (config_path / "config.toml", config_path / "connections.toml")
    except ImportError:
        # If platformdirs is not available, fall back to ~/.snowflake/
        # This matches the default behavior in earlier versions of snowflake-connector-python
        base_path = pathlib.Path("~/.snowflake/").expanduser()
        return (base_path / "config.toml", base_path / "connections.toml")


def read_config_file(connection_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Read Snowflake connection configuration from config files.

    This follows the same approach as the snowflake-connector-python package:
    1. Look for config files in SNOWFLAKE_HOME or platform-specific directories
    2. Read both config.toml and connections.toml
    3. Return connection parameters for the specified connection or default

    Args:
        connection_name: The name of the connection to retrieve. If None, returns the default connection.

    Returns:
        A dictionary of connection parameters or None if not found or on error.
    """
    if not _has_tomlkit:
        logger.debug("tomlkit package is not available, unable to read config files")
        return None

    try:
        # Get config file paths
        config_path, connections_path = _resolve_config_paths()
        connections_dict: Dict[str, Any] = {}
        default_connection_name = "default"

        # Read config.toml for default connection name
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    config_content = f.read()
                    config_dict = tomlkit.parse(config_content)

                # Convert tomlkit types to Python native types to avoid type issues
                config: Dict[str, Any] = {}
                for key, value in config_dict.items():
                    if hasattr(value, "unwrap"):
                        # Use tomlkit's unwrap method if available
                        config[str(key)] = value.unwrap()
                    else:
                        # Fallback for simple types
                        config[str(key)] = value

                if "default_connection_name" in config:
                    default_connection_name = str(config["default_connection_name"])
            except Exception as e:
                logger.debug(f"Error reading config file: {e}")

        # Read connections.toml for connection parameters
        if connections_path.exists():
            try:
                with open(connections_path, "r") as f:
                    connections_content = f.read()
                    connections_toml = tomlkit.parse(connections_content)

                # Convert tomlkit types to Python native types
                connections_config: Dict[str, Any] = {}
                for key, value in connections_toml.items():
                    if hasattr(value, "unwrap"):
                        connections_config[str(key)] = value.unwrap()
                    else:
                        connections_config[str(key)] = value

                if "connections" in connections_config:
                    connections_section = connections_config["connections"]
                    if isinstance(connections_section, dict):
                        connections_dict = connections_section
            except Exception as e:
                logger.debug(f"Error reading connections file: {e}")

        # Determine which connection to use
        conn_name = connection_name if connection_name is not None else default_connection_name

        if conn_name in connections_dict:
            # Extract connection parameters
            conn_params = connections_dict[conn_name]
            if isinstance(conn_params, dict):
                # Convert to a regular dictionary with string keys
                return {str(k): v for k, v in conn_params.items()}

        logger.debug(f"No connection found with name '{conn_name}'")
        return None

    except Exception as e:
        logger.debug(f"Error retrieving Snowflake connection parameters: {e}")
        return None


def get_parameters(name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get Snowflake connection parameters.

    This function tries to get connection parameters in the following order:
    1. From the snowflake-connector-python package if installed
    2. From config files directly using our own implementation

    Args:
        name: The name of the connection to retrieve. If None, returns the default connection.

    Returns:
        A dictionary of connection parameters or None if not found or on error.
    """
    # First try to use the snowflake-connector-python package
    try:
        # Import here to avoid dependency requirement
        import snowflake.connector

        try:
            # Try to get connection parameters from the snowflake connector
            if name is None:
                # Get default connection using direct module import
                from snowflake.connector.config_manager import (
                    _get_default_connection_params,
                )

                connection_params = _get_default_connection_params()
                return {str(k): v for k, v in connection_params.items()}
            else:
                # Get named connection
                from snowflake.connector.config_manager import CONFIG_MANAGER

                connections = CONFIG_MANAGER["connections"]
                if isinstance(connections, dict) and name in connections:
                    connection_params = connections[name]
                    if hasattr(connection_params, "items"):
                        return {str(k): v for k, v in connection_params.items()}
        except (ImportError, AttributeError) as e:
            logger.debug(f"Error using snowflake-connector-python config manager: {e}")
    except ImportError:
        logger.debug("snowflake-connector-python package is not installed")
    except Exception as e:
        logger.debug(f"Error using snowflake-connector-python: {e}")

    # Fall back to our own implementation that reads the config files directly
    return read_config_file(name)


def get_connection_parameters(name: Optional[str] = None) -> Optional[Dict[str, Any]]:

    connection_list = list_connections()
    # return parameters for default connection if configured
    # otherwise return named connection

    if not connection_list:
        raise RSConnectException("No Snowflake connections found.")

    try:
        if not name:
            return next((x["parameters"] for x in connection_list if x.get("is_default")), None)
        else:
            return next((x["parameters"] for x in connection_list if x.get("connection_name") == name))
    except StopIteration:
        raise RSConnectException(f"No Snowflake connection found with name '{name}'.")


def generate_jwt(name: Optional[str] = None) -> str:

    _ = get_connection_parameters(name)
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
