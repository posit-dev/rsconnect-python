"""Detects the configuration of a Python environment.

Given a directory and a Python executable, this module inspects the environment
and returns information about the Python version and the environment itself.

To inspect the environment it relies on a subprocess that runs the `rsconnect.subprocesses.inspect_environment`
module. This module is responsible for gathering the environment information and returning it in a JSON format.
"""

import typing
import sys
import dataclasses
import pprint
import subprocess
import json
import pathlib
import os.path

from . import pyproject
from .log import logger
from .exception import RSConnectException
from .subprocesses.inspect_environment import EnvironmentData, MakeEnvironmentData as _MakeEnvironmentData

import click


class Environment:
    """A Python project environment,

    The data is loaded from a rsconnect.utils.environment json response,
    the environment contains all the information provided by :class:`EnvironmentData` plus
    the environment python interpreter and the python interpreter version requirement.

    The goal is to capture all the information needed to replicate such environment.
    """

    DATA_FIELDS = {f.name for f in dataclasses.fields(EnvironmentData)}

    def __init__(
        self,
        data: EnvironmentData,
        python_interpreter: typing.Optional[str] = None,
        python_version_requirement: typing.Optional[str] = None,
    ):
        self._data = data

        # Fields that are not loaded from the environment subprocess
        self.python_version_requirement = python_version_requirement
        self.python_interpreter = python_interpreter

    def __getattr__(self, name: str) -> typing.Any:
        # We directly proxy the attributes of the EnvironmentData object
        # so that schema changes can be handled in EnvironmentData exclusively.
        return getattr(self._data, name)

    def __setattr__(self, name: str, value: typing.Any) -> None:
        if name in self.DATA_FIELDS:
            # proxy the attribute to the underlying EnvironmentData object
            self._data._replace(**{name: value})
        else:
            super().__setattr__(name, value)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Environment):
            return False

        return (
            self._data == other._data
            and self.python_interpreter == other.python_interpreter
            and self.python_version_requirement == other.python_version_requirement
        )

    def __repr__(self) -> str:
        data = self._data._asdict()
        data.pop("contents", None)  # Remove contents as it's too long to display
        return (
            f"Environment({data}, "
            f"python_interpreter={self.python_interpreter}, "
            f"python_version_requirement={self.python_version_requirement})"
        )

    @classmethod
    def from_dict(
        cls,
        data: typing.Dict[str, typing.Any],
        python_interpreter: typing.Optional[str] = None,
        python_version_requirement: typing.Optional[str] = None,
    ) -> "Environment":
        """Create an Environment instance from the dictionary representation of EnvironmentData."""
        return cls(
            _MakeEnvironmentData(**data),
            python_interpreter=python_interpreter,
            python_version_requirement=python_version_requirement,
        )

    @classmethod
    def create_python_environment(
        cls,
        directory: str,
        force_generate: bool = False,
        python: typing.Optional[str] = None,
        override_python_version: typing.Optional[str] = None,
        app_file: typing.Optional[str] = None,
    ) -> "Environment":
        """Given a project directory and a Python executable, return Environment information.

        If no Python executable is provided, the current system Python executable is used.

        :param directory: the project directory to inspect.
        :param force_generate: force generating "requirements.txt" to snapshot the environment
                               packages even if it already exists.
        :param python: the Python executable of the environment to use for inspection.
        :param override_python_version: the Python version required by  the project.
        :param app_file: the main application file to use for inspection.

        :return: a tuple containing the Python executable of the environment and the Environment object.
        """
        if app_file is None:
            module_file = fake_module_file_from_directory(directory)
        else:
            module_file = app_file

        # click.secho('    Deploying %s to server "%s"' % (directory, connect_server.url))
        _warn_on_ignored_manifest(directory)
        _warn_if_no_requirements_file(directory)
        _warn_if_environment_directory(directory)

        python_version_requirement = pyproject.detect_python_version_requirement(directory)
        _warn_on_missing_python_version(python_version_requirement)

        if python is not None:
            # TODO: Remove the option in a future release
            logger.warning(
                "On modern Posit Connect versions, the --python option won't influence "
                "the Python version used to deploy the application anymore. "
                "Please use a .python-version file to force a specific interpreter version."
            )

        if override_python_version:
            # TODO: Remove the option in a future release
            logger.warning(
                "The --override-python-version option is deprecated, "
                "please use a .python-version file to force a specific interpreter version."
            )
            python_version_requirement = f"=={override_python_version}"

        # with cli_feedback("Inspecting Python environment"):
        environment = cls._get_python_env_info(module_file, python, force_generate)
        environment.python_version_requirement = python_version_requirement

        if override_python_version:
            # Retaing backward compatibility with old Connect versions
            # that didn't support environment.python.requires
            environment.python = override_python_version

        if force_generate:
            _warn_on_ignored_requirements(directory, environment.filename)

        return environment

    @classmethod
    def _get_python_env_info(
        cls, file_name: str, python: typing.Optional[str], force_generate: bool = False
    ) -> "Environment":
        """
        Gathers the python and environment information relating to the specified file
        with an eye to deploy it.

        :param file_name: the primary file being deployed.
        :param python: the optional name of a Python executable.
        :param force_generate: force generating "requirements.txt" or "environment.yml",
        even if it already exists.
        :return: information about the version of Python in use plus some environmental
        stuff.
        """
        python = which_python(python)
        logger.debug("Python: %s" % python)
        environment = cls._inspect_environment(python, os.path.dirname(file_name), force_generate=force_generate)
        if environment.error:
            raise RSConnectException(environment.error)
        logger.debug("Python: %s" % python)
        logger.debug("Environment: %s" % pprint.pformat(environment._asdict()))
        return environment

    @classmethod
    def _inspect_environment(
        cls,
        python: str,
        directory: str,
        force_generate: bool = False,
        check_output: typing.Callable[..., bytes] = subprocess.check_output,
    ) -> "Environment":
        """Run the environment inspector using the specified python binary.

        Returns a dictionary of information about the environment,
        or containing an "error" field if an error occurred.
        """
        flags: typing.List[str] = []
        if force_generate:
            flags.append("f")

        args = [python, "-m", "rsconnect.subprocesses.inspect_environment"]
        if flags:
            args.append("-" + "".join(flags))
        args.append(directory)

        try:
            environment_json = check_output(args, text=True)
        except Exception as e:
            raise RSConnectException("Error inspecting environment (subprocess failed)") from e

        try:
            environment_data = json.loads(environment_json)
        except json.JSONDecodeError as e:
            raise RSConnectException("Error parsing environment JSON") from e

        if "error" in environment_data:
            system_error_message = environment_data.get("error")
            if system_error_message:
                raise RSConnectException(f"Error creating environment: {system_error_message}")

        try:
            return cls.from_dict(environment_data, python_interpreter=python)
        except TypeError as e:
            raise RSConnectException("Error constructing environment object") from e


def which_python(python: typing.Optional[str] = None) -> str:
    """Determines which Python executable to use.

    If the :param python: is provided, then validation is performed to check if the path is an executable file. If
    None, the invoking system Python executable location is returned.

    :param python: (Optional) path to a python executable.
    :return: :param python: or `sys.executable`.
    """
    if python is None:
        return sys.executable
    if not os.path.exists(python):
        raise RSConnectException(f"The path '{python}' does not exist. Expected a Python executable.")
    if os.path.isdir(python):
        raise RSConnectException(f"The path '{python}' is a directory. Expected a Python executable.")
    if not os.access(python, os.X_OK):
        raise RSConnectException(f"The path '{python}' is not executable. Expected a Python executable")
    return python


def fake_module_file_from_directory(directory: str) -> str:
    """
    Takes a directory and invents a properly named file that though possibly fake,
    can be used for other name/title derivation.

    :param directory: the directory to start with.
    :return: the directory plus the (potentially) fake module file.
    """
    app_name = os.path.abspath(directory)
    app_name = os.path.dirname(app_name) if app_name.endswith(os.path.sep) else os.path.basename(app_name)
    return os.path.join(directory, app_name + ".py")


def is_environment_dir(directory: typing.Union[str, pathlib.Path]) -> bool:
    """Detect whether `directory` is a virtualenv"""

    # A virtualenv will have Python at ./bin/python
    python_path = os.path.join(directory, "bin", "python")
    # But on Windows, it's at Scripts\Python.exe
    win_path = os.path.join(directory, "Scripts", "Python.exe")
    return os.path.exists(python_path) or os.path.exists(win_path)


def list_environment_dirs(directory: typing.Union[str, pathlib.Path]) -> typing.List[str]:
    """Returns a list of subdirectories in `directory` that appear to contain virtual environments."""
    envs: typing.List[str] = []

    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if is_environment_dir(path):
            envs.append(name)
    return envs


def _warn_on_ignored_manifest(directory: str) -> None:
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    """
    if os.path.exists(os.path.join(directory, "manifest.json")):
        click.secho(
            "    Warning: the existing manifest.json file will not be used or considered.",
            fg="yellow",
        )


def _warn_if_no_requirements_file(directory: str) -> None:
    """
    Checks for the existence of a file called requirements.txt in the given directory.
    If it's not there, a warning will be printed.

    :param directory: the directory to check in.
    """
    if not os.path.exists(os.path.join(directory, "requirements.txt")):
        click.secho(
            "    Warning: Capturing the environment using 'pip freeze'.\n"
            "             Consider creating a requirements.txt file instead.",
            fg="yellow",
        )


def _warn_if_environment_directory(directory: typing.Union[str, pathlib.Path]) -> None:
    """
    Issue a warning if the deployment directory is itself a virtualenv (yikes!).

    :param directory: the directory to check in.
    """
    if is_environment_dir(directory):
        click.secho(
            "    Warning: The deployment directory appears to be a python virtual environment.\n"
            "             Python libraries and binaries will be excluded from the deployment.",
            fg="yellow",
        )


def _warn_on_ignored_requirements(directory: str, requirements_file_name: str) -> None:
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    :param requirements_file_name: the name of the requirements file.
    """
    if os.path.exists(os.path.join(directory, requirements_file_name)):
        click.secho(
            "    Warning: the existing %s file will not be used or considered." % requirements_file_name,
            fg="yellow",
        )


def _warn_on_missing_python_version(version_constraint: typing.Optional[str]) -> None:
    """
    Check that the project has a Python version constraint requested.
    If it doesn't warn the user that it should be specified.

    :param version_constraint: the version constraint in the project.
    """
    if version_constraint is None:
        click.secho(
            "    Warning: Python version constraint missing from pyproject.toml, setup.cfg or .python-version\n"
            "             Connect will guess the version to use based on local environment.\n"
            "             Consider specifying a Python version constraint.",
            fg="yellow",
        )
