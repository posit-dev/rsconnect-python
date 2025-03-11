import os
import pathlib

from rsconnect.pyproject import lookup_metadata_file, parse_pyproject_python_requires

import pytest

HERE = os.path.dirname(__file__)
PROJECTS_DIRECTORY = os.path.abspath(os.path.join(HERE, "testdata", "python-project"))


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_pyproject"), ("pyproject.toml",)),
        (os.path.join(PROJECTS_DIRECTORY, "using_setupcfg"), ("setup.cfg",)),
        (
            os.path.join(PROJECTS_DIRECTORY, "using_pyversion"),
            (
                "pyproject.toml",
                ".python-version",
            ),
        ),
        (os.path.join(PROJECTS_DIRECTORY, "allofthem"), ("pyproject.toml", "setup.cfg", ".python-version")),
    ],
    ids=["pyproject.toml", "setup.cfg", ".python-version", "allofthem"],
)
def test_python_project_metadata_detect(project_dir, expected):
    expectation = [(f, pathlib.Path(project_dir) / f) for f in expected]
    assert lookup_metadata_file(project_dir) == expectation


@pytest.mark.parametrize(
    "project_dir",
    [
        os.path.join(PROJECTS_DIRECTORY, "empty"),
        os.path.join(PROJECTS_DIRECTORY, "missing"),
    ],
    ids=["empty", "missing"],
)
def test_python_project_metadata_missing(project_dir):
    assert lookup_metadata_file(project_dir) == []


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_pyproject"), ">=3.8"),
        (os.path.join(PROJECTS_DIRECTORY, "using_pyversion"), None),
    ],
    ids=["option-exists", "option-missing"],
)
def test_pyprojecttoml_python_requires(project_dir, expected):
    pyproject_file = pathlib.Path(project_dir) / "pyproject.toml"
    assert parse_pyproject_python_requires(pyproject_file) == expected
