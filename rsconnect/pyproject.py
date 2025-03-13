"""
Support for detecting various information from python projects metadata.

Metadata can only be loaded from static files (e.g. pyproject.toml, setup.cfg, etc.)
but not from setup.py due to its dynamic nature.
"""

import pathlib
import typing

try:
    import tomllib
except ImportError:
    # Python 3.11+ has tomllib in the standard library
    import toml as tomllib  # type: ignore[no-redef]


def lookup_metadata_file(directory: typing.Union[str, pathlib.Path]) -> typing.List[typing.Tuple[str, pathlib.Path]]:
    """Given the directory of a project return the path of a usable metadata file.

    The returned value is either a list of tuples [(filename, path)] or
    an empty list [] if no metadata file was found.
    """
    directory = pathlib.Path(directory)

    def _generate():
        for filename in ("pyproject.toml", "setup.cfg", ".python-version"):
            path = directory / filename
            if path.is_file():
                yield (filename, path)

    return list(_generate())


def parse_pyproject_python_requires(pyproject_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the project.requires-python field from a pyproject.toml file.

    Assumes that the pyproject.toml file exists, is accessible and well formatted.

    Returns None if the field is not found.
    """
    content = pyproject_file.read_text()
    pyproject = tomllib.loads(content)

    return pyproject.get("project", {}).get("requires-python", None)
