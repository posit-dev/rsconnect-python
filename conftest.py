import os
import sys
import pytest

from os.path import abspath, dirname


HERE = dirname(abspath(__file__))
sys.path.insert(0, HERE)

# tests/test_main_content.py expects the content build store to live in
# "rsconnect-build-test". rsconnect.metadata binds CONNECT_CONTENT_BUILD_DIR as a
# default argument value at import time, so this must be set before any test
# module imports rsconnect. (Previously injected by the Makefile's TEST_ENV.)
os.environ.setdefault("CONNECT_CONTENT_BUILD_DIR", "rsconnect-build-test")


def pytest_addoption(parser):
    parser.addoption("--vetiver", action="store_true", default=False, help="run vetiver tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "vetiver: test for vetiver interaction")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--vetiver"):
        return
    skip_vetiver = pytest.mark.skip(reason="need --vetiver option to run")
    for item in items:
        if "vetiver" in item.keywords:
            item.add_marker(skip_vetiver)
