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

SECRET_ENV_VAR = "CONNECT_JWT_SECRET"

# https://auth0.com/blog/brute-forcing-hs256-is-possible-the-importance-of-using-strong-keys-to-sign-jwts/
# 256-bit key = 32 bytes of entropy
MIN_SECRET_LEN = 32


def is_valid_secret_key(secret_key):

    if secret_key is None:
        return False

    if not isinstance(secret_key, str):
        return False

    if len(secret_key) < MIN_SECRET_LEN:
        return False

    return True

    return secret_key is not None and isinstance(secret_key, str) and secret_key != ""


def is_jwt_compatible_python_version():
    """
    JWT library is incompatible with Python 3.5
    """

    return sys.version_info > (3, 5)


def safe_instantiate_token_generator(jwt_secret):
    """
    Encapsulates checks to make verify environment / secret state before
    instantiating and returning a token generator
    """

    if not is_jwt_compatible_python_version():
        raise RSConnectException(
            "Python version > 3.5 required for JWT generation. Please upgrade your Python installation."
        )

    secret_key = load_secret(jwt_secret)
    if not is_valid_secret_key(secret_key):
        raise RSConnectException("Unable to load secret for JWT signing.")

    token_generator = TokenGenerator(secret_key)

    return token_generator


# Load the secret to be used for signing JWTs
def load_secret(secret_path=None):

    # Prioritize environment variable (if it exists)
    env_secret = os.getenv(SECRET_ENV_VAR)
    if env_secret is not None:
        return env_secret

    # Default read from filepath

    # Can't read a file if we didn't provide one
    if secret_path is None:
        raise RSConnectException("Secret filepath not specified and CONNECT_JWT_SECRET env variable not set.")

    # If file does not exist, we have no secret!
    if not os.path.exists(secret_path):
        raise RSConnectException("Secret file does not exist and CONNECT_JWT_SECRET env variable not set.")

    with open(secret_path, "r") as f:
        return f.read()


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

        return jwt.encode(claims, self.secret, algorithm="HS256")


# Used in unit tests
class JWTDecoder:
    def __init__(self, audience: str, secret: str):
        self.audience = audience
        self.secret = secret

    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["HS256"])


# Uses a generic encoder to create JWTs with specific custom scopes / expiration times
class TokenGenerator:
    def __init__(self, secret: str):
        self.encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, secret)

    def initial_admin(self):
        custom_claims = {"endpoint": "/__api__/v1/experimental/installation/initial-admin", "method": "GET"}  # todo

        exp = timedelta(minutes=15)

        return self.encoder.new_token(custom_claims, exp)
