"""
Json Web Token (JWT) utilities
"""

import os
import sys
import getpass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import jwt
import typing
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import serialization

from .exception import RSConnectException
from .log import logger

DEFAULT_ISSUER = "rsconnect-python"
DEFAULT_AUDIENCE = "rsconnect"

OPENSSH_HEADER = b"-----BEGIN OPENSSH PRIVATE KEY-----\n"
OPENSSH_FOOTER = b"-----END OPENSSH PRIVATE KEY-----\n"

INITIAL_ADMIN_ENDPOINT = "/__api__/v1/experimental/installation/initial_admin"
INITIAL_ADMIN_METHOD = "GET"
INITIAL_ADMIN_EXP = timedelta(minutes=15)

ENV_VAR_PRIVATE_KEY_PASSWORD = "CONNECT_PRIVATE_KEY_PASSWORD"


def _load_private_key_password_env() -> typing.Union[str, None]:
    """
    Reads the private key password from the ENV_VAR_PRIVATE_KEY_PASSWORD environment variable
    and returns it (if it exists)
    """
    return os.getenv(ENV_VAR_PRIVATE_KEY_PASSWORD)


def _load_private_key_password_interactive() -> str:
    """
    Produces the password from interactive input on the command line
    """
    return getpass.getpass(prompt="Private Key Password: ")


def load_private_key_password(interactive_password_flag) -> typing.Union[bytes, None]:

    password = _load_private_key_password_env()
    if password is not None:
        logger.debug("Loaded private key password from env var " + ENV_VAR_PRIVATE_KEY_PASSWORD)
    else:
        logger.debug("Private key password not set in env var " + ENV_VAR_PRIVATE_KEY_PASSWORD)

    if interactive_password_flag:
        if password is None:
            password = _load_private_key_password_interactive()
        else:
            logger.debug("Skipping -p flag")

    if password is not None:
        password = password.encode()
    else:
        logger.debug("Private key password not provided.")

    return password


def load_ed25519_private_key(keypath, password) -> Ed25519PrivateKey:

    if keypath is None:
        raise RSConnectException("Keypath must be provided to load private key")

    bytes = read_ed25519_private_key(keypath)
    return load_ed25519_private_key_from_bytes(bytes, password)


def load_ed25519_private_key_from_bytes(key_bytes: bytes, password) -> Ed25519PrivateKey:
    """
    Deserialize private key from byte representation
    """

    if key_bytes is None:
        raise RSConnectException("Ed25519 key cannot be 'None'")

    if not key_bytes.startswith(OPENSSH_HEADER) or not key_bytes.endswith(OPENSSH_FOOTER):
        raise RSConnectException("Keyfile does not follow OpenSSH format (required for Ed25519)")

    if password is not None:
        logger.debug("Loading private key using provided password")
    else:
        logger.debug("Loading private key without using password")

    key = serialization.load_ssh_private_key(key_bytes, password)

    if not isinstance(key, Ed25519PrivateKey):
        raise RSConnectException("Private key is not expected type: Ed25519PrivateKey")

    return key


def read_ed25519_private_key(keypath: str) -> bytes:
    """
    Reads an Ed25519PrivateKey as bytes given a keypath.
    """

    if not os.path.exists(keypath):
        raise RSConnectException("Keypath does not exist.")

    with open(keypath, "rb") as f:
        key_bytes = f.read()

        if key_bytes is None:
            raise RSConnectException("Ed25519 key cannot be 'None'")

        if not key_bytes.startswith(OPENSSH_HEADER) or not key_bytes.endswith(OPENSSH_FOOTER):
            raise RSConnectException("Keyfile does not follow OpenSSH format (required for Ed25519)")

        return key_bytes


def is_jwt_compatible_python_version() -> bool:
    """
    JWT library is incompatible with Python 3.5
    """

    return not sys.version_info < (3, 6)


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

        return jwt.encode(claims, self.secret, algorithm="EdDSA")


# Uses a generic encoder to create JWTs with specific custom scopes / expiration times
class TokenGenerator:
    """
    Generates 'typed' JWTs with specific custom scopes / expiration times to serve a specific purpose.
    """

    def __init__(self, secret):
        self.encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, secret)

    def initial_admin(self):
        custom_claims = {"endpoint": INITIAL_ADMIN_ENDPOINT, "method": INITIAL_ADMIN_METHOD}
        return self.encoder.new_token(custom_claims, INITIAL_ADMIN_EXP)
