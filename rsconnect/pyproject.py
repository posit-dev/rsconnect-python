"""
Support for detecting various information from python projects metadata.

Metadata can only be loaded from static files (e.g. pyproject.toml, setup.cfg, etc.)
but not from setup.py due to its dynamic nature.
"""

import configparser
import dataclasses
import pathlib
import re
import typing
from collections.abc import Mapping

from .log import logger
from .models import AppMode, AppModes

TOMLDecodeError: typing.Type[Exception]
try:
    import tomllib

    TOMLDecodeError = tomllib.TOMLDecodeError
except ImportError:
    # Python 3.11+ has tomllib in the standard library
    import toml as tomllib  # type: ignore[no-redef]

    TOMLDecodeError = tomllib.TomlDecodeError


PEP440_OPERATORS_REGEX = r"(===|==|!=|<=|>=|<|>|~=)"
VALID_VERSION_REQ_REGEX = rf"^({PEP440_OPERATORS_REGEX}?\d+(\.[\d\*]+)*)+$"


def detect_python_version_requirement(directory: typing.Union[str, pathlib.Path]) -> typing.Optional[str]:
    """Detect the python version requirement for a project.

    The directory should contain a metadata file such as pyproject.toml,
    setup.cfg, or .python-version.

    Returns the python version requirement as a string or None if not found.
    """
    for _, metadata_file in lookup_metadata_file(directory):
        parser = get_python_version_requirement_parser(metadata_file)
        try:
            version_constraint = parser(metadata_file)
        except InvalidVersionConstraintError as err:
            logger.error(f"Invalid python version constraint in {metadata_file}, ignoring it: {err}")
            continue

        if version_constraint:
            return version_constraint

    return None


def lookup_metadata_file(directory: typing.Union[str, pathlib.Path]) -> typing.List[typing.Tuple[str, pathlib.Path]]:
    """Given the directory of a project return the path of a usable metadata file.

    The returned value is either a list of tuples [(filename, path)] or
    an empty list [] if no metadata file was found.

    The metadata files are returned in the priority they should be processed
    to determine the python version requirements.
    """
    directory = pathlib.Path(directory)

    def _generate():
        for filename in (".python-version", "pyproject.toml", "setup.cfg"):
            path = directory / filename
            if path.is_file():
                yield (filename, path)

    return list(_generate())


def get_python_version_requirement_parser(
    metadata_file: pathlib.Path,
) -> typing.Callable[[pathlib.Path], typing.Optional[str]]:
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
        raise NotImplementedError(f"Unknown metadata file type: {metadata_file.name}")


def parse_pyproject_python_requires(pyproject_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the project.requires-python field from a pyproject.toml file.

    Assumes that the pyproject.toml file exists, is accessible and well formatted.

    Returns None if the field is not found.
    """
    content = pyproject_file.read_text()
    pyproject = tomllib.loads(content)

    return pyproject.get("project", {}).get("requires-python", None)


def parse_setupcfg_python_requires(setupcfg_file: pathlib.Path) -> typing.Optional[str]:
    """Parse the options.python_requires field from a setup.cfg file.

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
    return adapt_python_requires(pyversion_file.read_text().strip())


def adapt_python_requires(
    python_requires: str,
) -> str:
    """Convert a literal python version to a PEP440 constraint.

    Connect expects a PEP440 format, but the .python-version file can contain
    plain version numbers and other formats.

    We should convert them to the constraints that connect expects.
    """
    current_contraints = python_requires.split(",")

    def _adapt_contraint(constraints: typing.List[str]) -> typing.Generator[str, None, None]:
        for constraint in constraints:
            constraint = constraint.strip()
            if "@" in constraint or "-" in constraint or "/" in constraint:
                raise InvalidVersionConstraintError(f"python specific implementations are not supported: {constraint}")

            if "b" in constraint or "rc" in constraint or "a" in constraint:
                raise InvalidVersionConstraintError(f"pre-release versions are not supported: {constraint}")

            if re.match(VALID_VERSION_REQ_REGEX, constraint) is None:
                raise InvalidVersionConstraintError(f"Invalid python version: {constraint}")

            if re.search(PEP440_OPERATORS_REGEX, constraint):
                yield constraint
            else:
                # Convert to PEP440 format
                if "*" in constraint:
                    yield f"=={constraint}"
                else:
                    # only major specified “3” → ~=3.0 → >=3.0,<4.0
                    # major and minor specified “3.8” or “3.8.11” → ~=3.8.0 → >=3.8.0,<3.9.0
                    constraint = ".".join(constraint.split(".")[:2] + ["0"])
                    yield f"~={constraint}"

    return ",".join(_adapt_contraint(current_contraints))


class InvalidVersionConstraintError(ValueError):
    pass


class InvalidPyprojectConfigError(ValueError):
    """Raised when ``[tool.rsconnect]`` is missing or incomplete."""


class UnsupportedAppModeError(ValueError):
    """Raised when ``[tool.rsconnect].app_mode`` names an app mode rsconnect does not know.

    Kept distinct from :class:`InvalidPyprojectConfigError` because the CLI does
    not append the quickstart hint for this failure.
    """


_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET = """[tool.rsconnect]
# e.g. python-streamlit, python-shiny, python-fastapi, jupyter-static, quarto-shiny
app_mode = "<app_mode>"
entrypoint = "<entrypoint>"  # e.g. app.py"""


def read_tool_rsconnect(pyproject_file: pathlib.Path) -> typing.Mapping[str, typing.Any]:
    """Read the ``[tool.rsconnect]`` deployment config from pyproject.toml.

    Returns the section mapping unchanged so forward-compatible fields pass
    through. Raises ``InvalidPyprojectConfigError`` when the section is
    missing or when required ``app_mode`` / ``entrypoint`` fields are absent or
    not non-empty strings.
    """
    content = pyproject_file.read_text()
    pyproject = tomllib.loads(content)

    tool = pyproject.get("tool")
    if tool is None:
        raise InvalidPyprojectConfigError(
            f"The [tool.rsconnect] section is missing. Add at least:\n\n{_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET}"
        )
    if not isinstance(tool, Mapping):
        raise InvalidPyprojectConfigError(
            f"[tool.rsconnect] is not a TOML table. Add at least:\n\n{_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET}"
        )
    tool = typing.cast(typing.Mapping[str, typing.Any], tool)

    tool_rsconnect = tool.get("rsconnect")
    if tool_rsconnect is None:
        raise InvalidPyprojectConfigError(
            f"The [tool.rsconnect] section is missing. Add at least:\n\n{_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET}"
        )
    if not isinstance(tool_rsconnect, Mapping):
        raise InvalidPyprojectConfigError(
            f"[tool.rsconnect] is not a TOML table. Add at least:\n\n{_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET}"
        )
    tool_rsconnect = typing.cast(typing.Mapping[str, typing.Any], tool_rsconnect)

    for field in ("app_mode", "entrypoint"):
        value = tool_rsconnect.get(field)
        if not isinstance(value, str) or not value:
            raise InvalidPyprojectConfigError(
                f"The [tool.rsconnect] field {field} must be a non-empty string. Add at least:\n\n"
                f"{_MINIMUM_VALID_TOOL_RSCONNECT_SNIPPET}"
            )

    return tool_rsconnect


@dataclasses.dataclass(frozen=True)
class PyprojectDeployTarget:
    """Deployment configuration resolved from ``[tool.rsconnect]`` in pyproject.toml."""

    app_mode: AppMode
    # The app_mode string as written in pyproject.toml; may be an alias of
    # app_mode.name() and is what error messages should quote back to the user.
    configured_app_mode: str
    entrypoint: str
    requirements_file: str
    title: typing.Optional[str]


def resolve_pyproject_deploy_target(
    pyproject_file: pathlib.Path,
    requirements_file: typing.Optional[str] = None,
    title_override: typing.Optional[str] = None,
) -> PyprojectDeployTarget:
    """Resolve the deployment target described by ``[tool.rsconnect]`` in pyproject.toml.

    Raises ``InvalidPyprojectConfigError`` when the config is missing or
    incomplete, and ``UnsupportedAppModeError`` when ``app_mode`` does not name
    a known app mode.

    :param pathlib.Path pyproject_file: path to the project's pyproject.toml.
    :param typing.Optional[str] requirements_file: caller override for the
        requirements source; wins over ``[tool.rsconnect].requirements_file``.
    :param typing.Optional[str] title_override: fallback title used when the
        config declares none.
    """
    config = read_tool_rsconnect(pyproject_file)

    configured_app_mode = typing.cast(str, config["app_mode"])
    app_mode = AppModes.get_by_name(configured_app_mode, return_unknown=True)
    if app_mode == AppModes.UNKNOWN:
        raise UnsupportedAppModeError(f"Unsupported app_mode '{configured_app_mode}' in [tool.rsconnect]")

    # Requirements source precedence: caller override (the ``-r`` flag) >
    # ``[tool.rsconnect].requirements_file`` > built-in default ``pyproject.toml``
    # (top-level deps; Connect resolves transitive). An explicit default keeps the
    # inspector from falling back to a ``pip freeze`` of the caller's interpreter.
    # Malformed TOML values (wrong type, missing file) are surfaced by the
    # inspector / file existence check.
    return PyprojectDeployTarget(
        app_mode=app_mode,
        configured_app_mode=configured_app_mode,
        entrypoint=typing.cast(str, config["entrypoint"]),
        requirements_file=typing.cast(str, requirements_file or config.get("requirements_file") or "pyproject.toml"),
        title=typing.cast(typing.Optional[str], config.get("title")) or title_override,
    )
