import os
import pathlib

from rsconnect.pyproject import (
    lookup_metadata_file,
    parse_pyproject_python_requires,
    parse_setupcfg_python_requires,
    parse_pyversion_python_requires,
    get_python_requires_parser,
)

import pytest

HERE = os.path.dirname(__file__)
PROJECTS_DIRECTORY = os.path.abspath(os.path.join(HERE, "testdata", "python-project"))

# Most of this tests, verify against three fixture projects that are located in PROJECTS_DIRECTORY
# - using_pyproject: contains a pyproject.toml file with a project.requires-python field
# - using_setupcfg: contains a setup.cfg file with a options.python_requires field
# - using_pyversion: contains a .python-version file and a pyproject.toml file without any version constraint.
# - allofthem: contains all metadata files all with different version constraints.


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_pyproject"), ("pyproject.toml",)),
        (os.path.join(PROJECTS_DIRECTORY, "using_setupcfg"), ("setup.cfg",)),
        (
            os.path.join(PROJECTS_DIRECTORY, "using_pyversion"),
            (
                ".python-version",
                "pyproject.toml",
                "setup.cfg",
            ),
        ),
        (os.path.join(PROJECTS_DIRECTORY, "allofthem"), (".python-version", "pyproject.toml", "setup.cfg")),
    ],
    ids=["pyproject.toml", "setup.cfg", ".python-version", "allofthem"],
)
def test_python_project_metadata_detect(project_dir, expected):
    """Test that the metadata files are detected when they exist."""
    expectation = [(f, pathlib.Path(project_dir) / f) for f in expected]
    assert lookup_metadata_file(project_dir) == expectation


@pytest.mark.parametrize(
    "filename, expected_parser",
    [
        ("pyproject.toml", parse_pyproject_python_requires),
        ("setup.cfg", parse_setupcfg_python_requires),
        (".python-version", parse_pyversion_python_requires),
        ("invalid.txt", None),
    ],
    ids=["pyproject.toml", "setup.cfg", ".python-version", "invalid"],
)
def test_get_python_requires_parser(filename, expected_parser):
    metadata_file = pathlib.Path(PROJECTS_DIRECTORY) / filename
    parser = get_python_requires_parser(metadata_file)
    assert parser == expected_parser


@pytest.mark.parametrize(
    "project_dir",
    [
        os.path.join(PROJECTS_DIRECTORY, "empty"),
        os.path.join(PROJECTS_DIRECTORY, "missing"),
    ],
    ids=["empty", "missing"],
)
def test_python_project_metadata_missing(project_dir):
    """Test that lookup_metadata_file is able to deal with missing or empty directories."""
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
    """Test that the python_requires field is correctly parsed from pyproject.toml.

    Both when the option exists or when it missing in the pyproject.toml file.
    """
    pyproject_file = pathlib.Path(project_dir) / "pyproject.toml"
    assert parse_pyproject_python_requires(pyproject_file) == expected


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_setupcfg"), ">=3.8"),
        (os.path.join(PROJECTS_DIRECTORY, "using_pyversion"), None),
    ],
    ids=["option-exists", "option-missing"],
)
def test_setupcfg_python_requires(tmp_path, project_dir, expected):
    setupcfg_file = pathlib.Path(project_dir) / "setup.cfg"
    assert parse_setupcfg_python_requires(setupcfg_file) == expected


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_pyversion"), ">=3.8, <3.12"),
        # There is no case (option-missing) where the .python-version file is empty,
        # so we don't test that.
    ],
    ids=["option-exists"],
)
def test_pyversion_python_requires(tmp_path, project_dir, expected):
    versionfile = pathlib.Path(project_dir) / ".python-version"
    assert parse_pyversion_python_requires(versionfile) == expected
