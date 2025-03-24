import json
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import requests

from .exception import RSConnectException
from .http_support import HTTPServer


def is_snow_installed() -> bool:
    try:
        import snowflake.cli  # noqa

        return True
    except ImportError:
        try:
            subprocess.run(["snow", "--help"], capture_output=True)
            return True
        except OSError:
            return False


def list_connections():

    if not is_snow_installed():
        raise RSConnectException(
            "The snowflake-cli is required bit not installed."
            "Install it with 'pip install rsconnect-python[snowflake]'"
        )
    snow_cx_list = subprocess.run(
        ["snow", "connection", "list", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    connection_list = json.loads(snow_cx_list.stdout)
    return connection_list


def get_connection(name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    connection_list = list_connections()

    if not name:
        return next((x["parameters"] for x in connection_list if x.get("is_default")), None)
    else:
        return next((x["parameters"] for x in connection_list if x.get("connection_name") == name), None)


def get_jwt(snowflake_connection_name: Optional[str] = None):
    connection_name = "" if snowflake_connection_name is None else snowflake_connection_name
    snow_cx_jwt = subprocess.run(
        args=["snow", "connection", "generate-jwt", "--connection", connection_name, "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(snow_cx_jwt.stdout)
    jwt = output.get("message")
    return jwt


def get_access_token(spcs_endpoint: str, snowflake_connection_name: Optional[str] = None) -> str:

    cx = get_connection(snowflake_connection_name)
    if cx is None:
        raise RSConnectException("No Snowflake connection found")
    spcs_url = urlparse(spcs_endpoint)

    token_endpoint = f"https://{cx["account"]}.snowflakecomputing.com/oauth/token"
    scope = f"session:role:{cx["role"]} {spcs_url.netloc}"
    jwt = get_jwt(snowflake_connection_name)
    GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"

    payload = {"scope": scope, "assertion": jwt, "grant_type": GRANT_TYPE}

    r = requests.post(url=token_endpoint, data=payload)
    r.raise_for_status()

    return r.text


def get_token_endpoint(snowflake_connection_name: Optional[str] = None) -> str:
    cx = get_connection(snowflake_connection_name)
    if cx is None:
        raise RSConnectException("No Snowflake connection found")

    return f"https://{cx["account"]}.snowflakecomputing.com/"


class SnowflakeExchangeClient(HTTPServer):

    def fmt_payload(self, spcs_endpoint: str, snowflake_connection_name: Optional[str] = None):
        cx = get_connection(snowflake_connection_name)
        if cx is None:
            raise RSConnectException("No Snowflake connection found")
        spcs_url = urlparse(spcs_endpoint)

        scope = f"session:role:{cx["role"]} {spcs_url.netloc}"
        jwt = get_jwt(snowflake_connection_name)
        grant_type = "urn:ietf:params:oauth:grant-type:jwt-bearer"

        payload = {"scope": scope, "assertion": jwt, "grant_type": grant_type}
        payload = urlencode(payload)
        return payload

    def exchange_token(self, spcs_endpoint: str, snowflake_connection_name: Optional[str] = None):

        payload = self.fmt_payload(spcs_endpoint, snowflake_connection_name)

        response = self.request(
            method="POST",
            path="/oauth/token",
            body=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.response_body:
            return response.response_body

        return None
