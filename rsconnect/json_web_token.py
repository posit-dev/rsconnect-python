"""
Json Web Token (JWT) utilities
"""

import base64
from datetime import datetime, timedelta, timezone
import os
import sys

import binascii
import jwt

from rsconnect.http_support import HTTPResponse

from .exception import RSConnectException

DEFAULT_ISSUER = "rsconnect-python"
DEFAULT_AUDIENCE = "rsconnect"

BOOTSTRAP_SCOPE = "bootstrap"
BOOTSTRAP_EXP = timedelta(minutes=15)

SECRET_KEY_ENV = "CONNECT_BOOTSTRAP_SECRETKEY"


def read_secret_key(keypath) -> bytes:
    """
    Reads a secret key as bytes given a path to a file containing a base64-encoded key.

    The secret key can optionally be set with an environment variable.
    """

    env_raw_data = os.getenv(SECRET_KEY_ENV)

    if keypath is not None and env_raw_data is not None:
        raise RSConnectException("Cannot specify secret key using both a keyfile and environment variable.")

    if keypath is None and env_raw_data is None:
        raise RSConnectException("Must specify secret key using either a keyfile or environment variable.")

    # check if secret key was specified using an env variable first
    if env_raw_data is not None:
        try:
            return base64.b64decode(env_raw_data.encode("utf-8"))
        except binascii.Error:
            raise RSConnectException("Unable to decode base64 data from environment variable: " + SECRET_KEY_ENV)

    if not os.path.exists(keypath):
        raise RSConnectException("Keypath does not exist.")

    with open(keypath, "r") as f:
        raw_data = f.read()
        if raw_data is None:
            raise RSConnectException("Secret key cannot be 'None'")
        try:
            return base64.b64decode(raw_data)
        except binascii.Error:
            raise RSConnectException("Unable to decode base64 data from keyfile: " + keypath)


# https://www.ibm.com/docs/vi/sva/9.0.6?topic=jwt-support
def validate_hs256_secret_key(key: bytes):
    if len(key) < 32:
        raise RSConnectException("Secret key expected to be at least 32 bytes in length")


def is_jwt_compatible_python_version() -> bool:
    """
    JWT library is incompatible with Python 3.5
    """

    return not sys.version_info < (3, 6)


def parse_client_response(response):
    """
    Helper to handle the response type from RSConnectClient, because
    it can have different types depending on the response
    """

    if isinstance(response, dict):
        return 200, response
    elif isinstance(response, HTTPResponse):
        # fail fast if a non-http exception occurred
        if hasattr(response, "exception") and response.exception is not None:
            raise RSConnectException(str(response.exception))

        status = 500
        if hasattr(response, "status"):
            status = response.status

        json_data = {}
        if hasattr(response, "json_data"):
            json_data = response.json_data

        return status, json_data

    raise RSConnectException("Unrecognized response type: " + str(type(response)))


def produce_bootstrap_output(status: int, json_data) -> dict:
    """
    Produces the expected programmatic output format from a request to the initial_admin endpoint
    """

    # Parse the returned API key if one is provided
    api_key = ""
    if json_data is not None and "api_key" in json_data:
        api_key = json_data["api_key"]

    # Catch unexpected response states and error early
    if status == 200 and api_key == "":
        raise RSConnectException("Connect returned a successful HTTP response but no API key.")

    if status != 200 and api_key != "":
        raise RSConnectException("Connect returned a non-successful HTTP response and an API key. ")

    output = {"status": status, "api_key": api_key}

    # Create a helpful error message
    message = "Unexpected response status."
    if status == 200:
        message = "Success."
    elif status == 401:
        message = "JWT authorization failed."
    elif status == 403:
        message = "Unable to provision initial admin. Please check status of Connect database."
    elif status == 404:
        message = (
            "Unable to find provisioning endpoint. Please check your 'rsconnect bootstrap --server' "
            "parameter and your Connect configuration."
        )

    output["message"] = message

    return output


class JWTEncoder:
    def __init__(self, issuer: str, audience: str, secret):
        self.issuer = issuer
        self.audience = audience
        self.secret = secret

    def generate_standard_claims(self, current_datetime: datetime, exp: timedelta):

        if exp < timedelta(0):
            raise RSConnectException("Unable to generate a token with a negative exp claim.")

        return {
            "exp": int((current_datetime + exp).timestamp()),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(current_datetime.timestamp()),
        }

    def new_token(self, custom_claims: dict, exp: timedelta):

        standard_claims = self.generate_standard_claims(datetime.now(tz=timezone.utc), exp)

        claims = {}
        for c in [standard_claims, custom_claims]:
            claims.update(c)

        return jwt.encode(claims, self.secret, algorithm="HS256")


# Uses a generic encoder to create JWTs with specific custom scopes / expiration times
class TokenGenerator:
    """
    Generates 'typed' JWTs with specific custom scopes / expiration times to serve a specific purpose.
    """

    def __init__(self, secret):
        self.encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, secret)

    def bootstrap(self):
        custom_claims = {"scope": BOOTSTRAP_SCOPE}
        return self.encoder.new_token(custom_claims, BOOTSTRAP_EXP)
