"""
Json Web Token (JWT) utilities
"""

import os
import sys

import jwt
from datetime import datetime, timedelta, timezone

from .exception import RSConnectException

DEFAULT_ISSUER = "rsconnect-python"
DEFAULT_AUDIENCE = "rsconnect"


PRIVATE_KEY_PREFIX = "-----BEGIN PRIVATE KEY-----\n"
PRIVATE_KEY_SUFFIX = "-----END PRIVATE KEY-----\n"


def validate_secret_key(secret_key):
    """
    Verify that the key is structured as expected
    """

    if secret_key is None:
        raise RSConnectException("Secret key parameter cannot be 'None'")

    if not isinstance(secret_key, str):
        raise RSConnectException("Secret key parameter expected to be a string")

    if not secret_key.startswith(PRIVATE_KEY_PREFIX) or not secret_key.endswith(PRIVATE_KEY_SUFFIX):
        raise RSConnectException("Secret key parameter expected to be in PEM / PKCS8 format")


def safe_load_secret(secret_path):
    """
    Loads the secret used to sign the JWT from a file, throwing an
    exception if there's a problem loading the key or with the key itself
    """

    if not os.path.exists(secret_path):
        raise RSConnectException("Secret file does not exist.")

    with open(secret_path, "rt") as f:
        secret_key = f.read()

        # Raise an exception with a useful error message
        validate_secret_key(secret_key)
        return secret_key


def is_jwt_compatible_python_version():
    """
    JWT library is incompatible with Python 3.5
    """

    return not sys.version_info < (3, 6)


def safe_instantiate_token_generator(secret_path):
    """
    Encapsulates checks to make verify environment / secret state before
    instantiating and returning a token generator
    """

    if not is_jwt_compatible_python_version():
        raise RSConnectException(
            "Python version > 3.5 required for JWT generation. Please upgrade your Python installation."
        )

    if secret_path is None:
        raise RSConnectException("Must specify a secret key path.")

    secret_key = safe_load_secret(secret_path)
    return TokenGenerator(secret_key)


class JWTEncoder:
    def __init__(self, issuer: str, audience: str, secret: str):
        self.issuer = issuer
        self.audience = audience
        self.secret = secret

    def generate_standard_claims(self, current_datetime: datetime, exp: timedelta):

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

        return jwt.encode(claims, self.secret, algorithm="EdDSA")


# Used in unit tests
class JWTDecoder:
    def __init__(self, audience: str, secret: str):
        self.audience = audience
        self.secret = secret

    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["EdDSA"])


# Uses a generic encoder to create JWTs with specific custom scopes / expiration times
class TokenGenerator:
    def __init__(self, secret: str):
        self.encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, secret)

    def initial_admin(self):
        custom_claims = {"endpoint": "/__api__/v1/experimental/installation/initial-admin", "method": "GET"}  # todo

        exp = timedelta(minutes=15)

        return self.encoder.new_token(custom_claims, exp)
