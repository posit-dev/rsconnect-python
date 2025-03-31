import json
from subprocess import CalledProcessError, run
from typing import Any, Dict, Optional, cast

from .exception import RSConnectException
from .log import logger


def snow(*args: str):
    ensure_snow_installed()
    return run(["snow"] + list(args), capture_output=True, text=True, check=True)


def ensure_snow_installed() -> None:
    try:
        import snowflake.cli

        logger.debug("snowflake-cli is installed.")

    except ImportError:
        logger.warning("snowflake-cli is not installed.")
        try:
            run(["snow", "--version"], capture_output=True, check=True)
        except CalledProcessError:
            raise RSConnectException("snow is installed but could not be run.")
        except FileNotFoundError:
            raise RSConnectException("snow cannot be found.")


def list_connections():

    try:
        res = snow("connection", "list", "--format", "json")
        connection_list = json.loads(res.stdout)
        return connection_list
    except:
        raise RSConnectException("Could not list snowflake connections.")


def get_connection_parameters(name: Optional[str] = None):

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


def generate_jwt(name: Optional[str] = None):

    _ = get_connection_parameters(name)
    connection_name = "" if name is None else name

    try:
        res = snow("connection", "generate-jwt", "--connection", connection_name, "--format", "json")
        try:
            output = json.loads(res.stdout)
        except json.JSONDecodeError as e:
            raise RSConnectException(f"Failed to parse JSON from snow-cli: {res.stdout}")
        jwt = output.get("message")
        if jwt is None:
            raise RSConnectException(f"Failed to generate JWT: Missing 'message' field in response: {output}")
        return jwt
    except CalledProcessError as e:
        raise RSConnectException(f"Failed to generate JWT for connection '{name}': {e.stderr}")
