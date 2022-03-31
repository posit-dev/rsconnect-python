import sys
import os
from os.path import join, dirname, exists
from unittest import TestCase


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


def require_connect(tc: TestCase):
    connect_server = os.environ.get("CONNECT_SERVER", None)
    if connect_server is None:
        tc.skipTest("Set CONNECT_SERVER to test this function.")
    return connect_server


def require_api_key(tc: TestCase):
    connect_api_key = os.environ.get("CONNECT_API_KEY", None)
    if connect_api_key is None:
        tc.skipTest("Set CONNECT_API_KEY to test this function.")
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
