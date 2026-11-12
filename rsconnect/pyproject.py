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

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion

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


def local_python_mismatch(constraint: typing.Optional[str], version: str) -> typing.Optional[str]:
    if constraint is None:
        return None
    try:
        if SpecifierSet(constraint).contains(version):
            return None
    except (InvalidSpecifier, InvalidVersion, TypeError):
        return None
    return (
        f"Local Python {version} does not satisfy the project requirement {constraint}; "
        "dependency compatibility has not been tested."
    )


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
    content = pyproject_file.read_text(encoding="utf-8-sig")
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
    """Raised when the deployment table is missing or incomplete."""


class UnsupportedAppModeError(ValueError):
    """Raised when the configured app mode is unknown.

    Kept distinct from :class:`InvalidPyprojectConfigError` because the CLI does
    not append the quickstart hint for this failure.
    """


_MINIMUM_VALID_TOOL_SNIPPET = """[tool.posit.connect]
# e.g. python-streamlit, python-shiny, python-fastapi, jupyter-static, quarto-shiny
app_mode = "<app_mode>"
entrypoint = "<entrypoint>"  # e.g. app.py"""

_PYPROJECT_APP_MODES = (
    AppModes.STREAMLIT_APP,
    AppModes.PYTHON_SHINY,
    AppModes.PYTHON_FASTAPI,
    AppModes.PYTHON_API,
    AppModes.JUPYTER_NOTEBOOK,
    AppModes.JUPYTER_VOILA,
    AppModes.STATIC_QUARTO,
    AppModes.SHINY_QUARTO,
)


def read_tool_rsconnect(pyproject_file: pathlib.Path) -> typing.Mapping[str, typing.Any]:
    """Read the deployment config from the supported pyproject.toml tables."""
    return _read_deployment_config(pyproject_file)[1]


def _read_deployment_config(
    pyproject_file: pathlib.Path, required: bool = True
) -> typing.Tuple[str, typing.Mapping[str, typing.Any]]:
    content = pyproject_file.read_text(encoding="utf-8-sig")
    pyproject = tomllib.loads(content)
    tool = pyproject.get("tool")
    if tool is not None and not isinstance(tool, Mapping):
        raise InvalidPyprojectConfigError(f"[tool] is not a TOML table. Add at least:\n\n{_MINIMUM_VALID_TOOL_SNIPPET}")
    tool = typing.cast(typing.Mapping[str, typing.Any], tool or {})
    posit = tool.get("posit", {})
    if not isinstance(posit, Mapping):
        raise InvalidPyprojectConfigError(
            f"[tool.posit] is not a TOML table. Add at least:\n\n{_MINIMUM_VALID_TOOL_SNIPPET}"
        )
    posit = typing.cast(typing.Mapping[str, typing.Any], posit)
    if "connect" in posit and "rsconnect" in tool:
        raise InvalidPyprojectConfigError(
            "Both [tool.posit.connect] and [tool.rsconnect] are present. Keep only one table."
        )
    if "connect" in posit:
        table = "[tool.posit.connect]"
        config = posit["connect"]
    elif "rsconnect" in tool:
        table = "[tool.rsconnect]"
        config = tool["rsconnect"]
    else:
        if not required:
            return "", {}
        raise InvalidPyprojectConfigError(
            f"The [tool.posit.connect] section is missing; [tool.rsconnect] is also accepted. "
            f"Add at least:\n\n{_MINIMUM_VALID_TOOL_SNIPPET}"
        )

    if not isinstance(config, Mapping):
        raise InvalidPyprojectConfigError(
            f"{table} is not a TOML table. Add at least:\n\n{_MINIMUM_VALID_TOOL_SNIPPET}"
        )
    config = typing.cast(typing.Mapping[str, typing.Any], config)
    if required:
        for field in ("app_mode", "entrypoint"):
            value = config.get(field)
            if not isinstance(value, str) or not value:
                raise InvalidPyprojectConfigError(
                    f"The {table} field {field} must be a non-empty string. "
                    f"Add at least:\n\n{_MINIMUM_VALID_TOOL_SNIPPET}"
                )
    return table, config


def optional_deployment_config(
    pyproject_file: pathlib.Path, warn_legacy: bool = True
) -> typing.Mapping[str, typing.Any]:
    table, config = _read_deployment_config(pyproject_file, required=False)
    if warn_legacy and table == "[tool.rsconnect]":
        logger.warning("[tool.rsconnect] is deprecated. Rename it to [tool.posit.connect].")
    return config


@dataclasses.dataclass(frozen=True)
class PyprojectDeployTarget:
    """Deployment configuration resolved from pyproject.toml."""

    table: str
    app_mode: AppMode
    # The app_mode string as written in pyproject.toml; may be an alias of
    # app_mode.name() and is what error messages should quote back to the user.
    configured_app_mode: str
    entrypoint: str
    title: typing.Optional[str]


def resolve_pyproject_deploy_target(
    pyproject_file: pathlib.Path,
    title_override: typing.Optional[str] = None,
) -> PyprojectDeployTarget:
    """Resolve the deployment target described in pyproject.toml.

    Raises ``InvalidPyprojectConfigError`` when the config is missing or
    incomplete, and ``UnsupportedAppModeError`` when ``app_mode`` does not name
    a known app mode.

    :param pathlib.Path pyproject_file: path to the project's pyproject.toml.
    :param typing.Optional[str] title_override: fallback title used when the
        config declares none.
    """
    table, config = _read_deployment_config(pyproject_file)

    configured_app_mode = typing.cast(str, config["app_mode"])
    app_mode = AppModes.get_by_name(configured_app_mode, return_unknown=True)
    if app_mode not in _PYPROJECT_APP_MODES:
        raise UnsupportedAppModeError(f"Unsupported app_mode '{configured_app_mode}' in {table}")

    if table == "[tool.rsconnect]":
        logger.warning("[tool.rsconnect] is deprecated. Rename it to [tool.posit.connect].")

    return PyprojectDeployTarget(
        table=table,
        app_mode=app_mode,
        configured_app_mode=configured_app_mode,
        entrypoint=typing.cast(str, config["entrypoint"]),
        title=typing.cast(typing.Optional[str], config.get("title")) or title_override,
    )
