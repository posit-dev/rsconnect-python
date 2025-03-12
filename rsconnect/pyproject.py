"""
Support for detecting various information from python projects metadata.

Metadata can only be loaded from static files (e.g. pyproject.toml, setup.cfg, etc.)
but not from setup.py due to its dynamic nature.
"""

import pathlib
import typing
import configparser

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
        for filename in (".python-version", "pyproject.toml", "setup.cfg"):
            path = directory / filename
            if path.is_file():
                yield (filename, path)

    return list(_generate())


def get_python_requires_parser(
    metadata_file: pathlib.Path,
) -> typing.Optional[typing.Callable[[pathlib.Path], typing.Optional[str]]]:
    """Given the metadata file, return the appropriate parser function.

    The returned function takes a pathlib.Path and returns the parsed value.
    """
    if metadata_file.name == "pyproject.toml":
        return parse_pyproject_python_requires
    elif metadata_file.name == "setup.cfg":
        return parse_setupcfg_python_requires
    elif metadata_file.name == ".python-version":
        return parse_pyversion_python_requires
    else:
        return None


def parse_pyproject_python_requires(pyproject_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the project.requires-python field from a pyproject.toml file.

    Assumes that the pyproject.toml file exists, is accessible and well formatted.

    Returns None if the field is not found.
    """
    content = pyproject_file.read_text()
    pyproject = tomllib.loads(content)

    return pyproject.get("project", {}).get("requires-python", None)


def parse_setupcfg_python_requires(setupcfg_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the python_requires field from a setup.cfg file.

    Assumes that the setup.cfg file exists, is accessible and well formatted.

    Returns None if the field is not found.
    """
    config = configparser.ConfigParser()
    config.read(setupcfg_file)

    return config.get("options", "python_requires", fallback=None)


def parse_pyversion_python_requires(pyversion_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the python version from a .python-version file.

    Assumes that the .python-version file exists, is accessible and well formatted.

    Returns None if the field is not found.
    """
    content = pyversion_file.read_text()
    return content.strip()
