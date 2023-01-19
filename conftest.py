import sys
import pytest

from os.path import abspath, dirname


HERE = dirname(abspath(__file__))
sys.path.insert(0, HERE)


def pytest_addoption(parser):
    parser.addoption(
        "--vetiver", action="store_true", default=False, help="run vetiver tests"
    )

def pytest_configure(config):
    config.addinivalue_line("markers", "vetiver: test for vetiver interaction")

def pytest_collection_modifyitems(config, items):
    if config.getoption("--vetiver"):
        return
    skip_vetiver = pytest.mark.skip(reason="need --vetiver option to run")
