import sys
import os
import jwt
import re
from contextlib import contextmanager
from os.path import join, dirname, exists
from packaging import version
from unittest import mock

import pytest
from rsconnect.api import RSConnectServer, RSConnectClient

# Captured while this module is imported, which is before the conftest fixture hides
# keyring from tests: failing_keyring() needs the real modules back.
try:
    import keyring as _keyring
    import keyring.backends.fail as _keyring_fail
    import keyring.errors as _keyring_errors
except ImportError:  # pragma: no cover
    _keyring = None


@contextmanager
def failing_keyring():
    """Run with keyring installed and its fail backend active.

    That is the shape of a CI runner: the package is there, no backend is usable, and
    every operation raises NoKeyringError. Credentials have to land in servers.json.
    """
    if _keyring is None:  # pragma: no cover
        pytest.skip("keyring is not installed")
    previous = _keyring.get_keyring()
    _keyring.set_keyring(_keyring_fail.Keyring())
    try:
        with mock.patch.dict(sys.modules, {"keyring": _keyring, "keyring.errors": _keyring_errors}):
            yield
    finally:
        _keyring.set_keyring(previous)


def apply_common_args(args: list, server=None, key=None, cacert=None, insecure=False):
    if server:
        args.extend(["-s", server])
    if key:
        args.extend(["-k", key])
    if cacert:
        args.extend(["--cacert", cacert])
    if insecure:
        args.extend(["--insecure"])
    return args


def optional_target(default):
    return os.environ.get("CONNECT_DEPLOY_TARGET", default)


def optional_ca_data(default=None):
    # noinspection SpellCheckingInspection
    return os.environ.get("CONNECT_CADATA_FILE", default)


def require_connect():
    connect_server = os.environ.get("CONNECT_SERVER", None)
    if connect_server is None:
        pytest.skip("Set CONNECT_SERVER to test this function.")
    return connect_server


def require_api_key():
    connect_api_key = os.environ.get("CONNECT_API_KEY", None)
    if connect_api_key is None:
        pytest.skip("Set CONNECT_API_KEY to test this function.")
    return connect_api_key


def require_connect_version(min_version: str):
    """
    Skip test if Connect server version is less than min_version.

    Args:
        min_version: Minimum required version (e.g., "2025.03.0")
    """
    connect_server = require_connect()
    api_key = require_api_key()

    server = RSConnectServer(connect_server, api_key)
    client = RSConnectClient(server)

    try:
        settings = client.server_settings()
        server_version = settings["version"]

        if version.parse(server_version) < version.parse(min_version):
            pytest.skip(f"Connect server {server_version} < {min_version}")
    except Exception as e:
        pytest.skip(f"Could not determine Connect server version: {e}")


def get_dir(name):
    py_version = "py%d" % sys.version_info[0]
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), "testdata", py_version, name)
    if not exists(path):
        raise AssertionError("%s does not exist" % path)
    return path


def get_manifest_path(name, parent="R"):
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), "testdata", parent, name, "manifest.json")
    if not exists(path):
        raise AssertionError("%s does not exist" % path)
    return path


def get_api_path(name, parent="api"):
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), "testdata", parent, name)
    if not exists(path):
        raise AssertionError("%s does not exist" % path)
    return path


def has_jwt_structure(token):
    """
    Verify that token is a well-formatted JWT string
    """

    if token is None:
        return False

    return re.search("^[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+$", token) is not None


class JWTDecoder:
    """
    Used to decode / verify JWTs in testing
    """

    def __init__(self, audience: str, secret):
        self.audience = audience
        self.secret = secret

    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["HS256"])
