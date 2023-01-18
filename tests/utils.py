import sys
import os
import jwt
import re
from os.path import join, dirname, exists

import pytest


def apply_common_args(args: list, server=None, key=None, cacert=None, insecure=False):
    if server:
        args.extend(["-s", server])
    if key:
        args.extend(["-k", key])
    if cacert:
        args.extend(["--cacert", cacert])
    if insecure:
        args.extend(["--insecure"])


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
