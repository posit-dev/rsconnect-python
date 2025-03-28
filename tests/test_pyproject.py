import os
import pathlib

from rsconnect.pyproject import (
    lookup_metadata_file,
    parse_pyproject_python_requires,
    parse_setupcfg_python_requires,
    parse_pyversion_python_requires,
    get_python_version_requirement_parser,
    detect_python_version_requirement,
)

import pytest

HERE = os.path.dirname(__file__)
PROJECTS_DIRECTORY = os.path.abspath(os.path.join(HERE, "testdata", "python-project"))

# Most of this tests, verify against three fixture projects that are located in PROJECTS_DIRECTORY
# - using_pyproject: contains a pyproject.toml file with a project.requires-python field
# - using_setupcfg: contains a setup.cfg file with a options.python_requires field
# - using_pyversion: contains a .python-version file and pyproject.toml, setup.cfg without any version constraint.
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
        ("invalid.txt", NotImplementedError("Unknown metadata file type: invalid.txt")),
    ],
    ids=["pyproject.toml", "setup.cfg", ".python-version", "invalid"],
)
def test_get_python_version_requirement_parser(filename, expected_parser):
    """Test that given a metadata file name, the correct parser is returned."""
    metadata_file = pathlib.Path(PROJECTS_DIRECTORY) / filename
    if isinstance(expected_parser, Exception):
        with pytest.raises(expected_parser.__class__) as excinfo:
            parser = get_python_version_requirement_parser(metadata_file)
            assert str(excinfo.value) == expected_parser.args[0]
    else:
        parser = get_python_version_requirement_parser(metadata_file)
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
    """Test that the requires-python field is correctly parsed from pyproject.toml.

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
def test_setupcfg_python_requires(project_dir, expected):
    """Test that the python_requires field is correctly parsed from setup.cfg.

    Both when the option exists or when it missing in the file.
    """
    setupcfg_file = pathlib.Path(project_dir) / "setup.cfg"
    assert parse_setupcfg_python_requires(setupcfg_file) == expected


@pytest.mark.parametrize(
    "project_dir, expected",
    [
        (os.path.join(PROJECTS_DIRECTORY, "using_pyversion"), ">=3.8, <3.12"),
    ],
    ids=["option-exists"],
)
def test_pyversion_python_requires(project_dir, expected):
    """Test that the python version is correctly parsed from .python-version.

    We do not test the case where the option is missing, as an empty .python-version file
    is not a valid case for a python project.
    """
    versionfile = pathlib.Path(project_dir) / ".python-version"
    assert parse_pyversion_python_requires(versionfile) == expected


def test_detect_python_version_requirement():
    """Test that the python version requirement is correctly detected from the metadata files.

    Given that we already know from the other tests that the metadata files are correctly parsed,
    this test primarily checks that when there are multiple metadata files, the one with the most specific
    version requirement is used.
    """
    project_dir = os.path.join(PROJECTS_DIRECTORY, "allofthem")
    assert detect_python_version_requirement(project_dir) == ">=3.8, <3.12"

    assert detect_python_version_requirement(os.path.join(PROJECTS_DIRECTORY, "empty")) is None
