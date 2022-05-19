import sys
import click
import os
from os.path import abspath, basename, dirname, exists, join, relpath
import json
import subprocess
from pprint import pformat
from .exception import RSConnectException
from .log import logger
from .bundle import is_environment_dir
from .environment import MakeEnvironment


def fake_module_file_from_directory(directory):
    """
    Takes a directory and invents a properly named file that though possibly fake,
    can be used for other name/title derivation.

    :param directory: the directory to start with.
    :return: the directory plus the (potentially) fake module file.
    """
    app_name = abspath(directory)
    app_name = dirname(app_name) if app_name.endswith(os.path.sep) else basename(app_name)
    return join(directory, app_name + ".py")


def validate_extra_files(directory, extra_files):
    """
    If the user specified a list of extra files, validate that they all exist and are
    beneath the given directory and, if so, return a list of them made relative to that
    directory.

    :param directory: the directory that the extra files must be relative to.
    :param extra_files: the list of extra files to qualify and validate.
    :return: the extra files qualified by the directory.
    """
    result = []
    if extra_files:
        for extra in extra_files:
            extra_file = relpath(extra, directory)
            # It's an error if we have to leave the given dir to get to the extra
            # file.
            if extra_file.startswith("../"):
                raise RSConnectException("%s must be under %s." % (extra_file, directory))
            if not exists(join(directory, extra_file)):
                raise RSConnectException("Could not find file %s under %s" % (extra, directory))
            result.append(extra_file)
    return result


def _warn_on_ignored_manifest(directory):
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    """
    if exists(join(directory, "manifest.json")):
        click.secho(
            "    Warning: the existing manifest.json file will not be used or considered.",
            fg="yellow",
        )


def _warn_if_no_requirements_file(directory):
    """
    Checks for the existence of a file called requirements.txt in the given directory.
    If it's not there, a warning will be printed.

    :param directory: the directory to check in.
    """
    if not exists(join(directory, "requirements.txt")):
        click.secho(
            "    Warning: Capturing the environment using 'pip freeze'.\n"
            "             Consider creating a requirements.txt file instead.",
            fg="yellow",
        )


def _warn_if_environment_directory(directory):
    """
    Issue a warning if the deployment directory is itself a virtualenv (yikes!).

    :param directory: the directory to check in.
    """
    if is_environment_dir(directory):
        click.secho(
            "    Warning: The deployment directory appears to be a python virtual environment.\n"
            "             Excluding the 'bin' and 'lib' directories.",
            fg="yellow",
        )


def _warn_on_ignored_requirements(directory, requirements_file_name):
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    :param requirements_file_name: the name of the requirements file.
    """
    if exists(join(directory, requirements_file_name)):
        click.secho(
            "    Warning: the existing %s file will not be used or considered." % requirements_file_name,
            fg="yellow",
        )


def get_python_env_info(file_name, python, conda_mode=False, force_generate=False):
    """
    Gathers the python and environment information relating to the specified file
    with an eye to deploy it.

    :param file_name: the primary file being deployed.
    :param python: the optional name of a Python executable.
    :param conda_mode: inspect the environment assuming Conda
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :return: information about the version of Python in use plus some environmental
    stuff.
    """
    python = which_python(python)
    logger.debug("Python: %s" % python)
    environment = inspect_environment(python, dirname(file_name), conda_mode=conda_mode, force_generate=force_generate)
    if environment.error:
        raise RSConnectException(environment.error)
    logger.debug("Python: %s" % python)
    logger.debug("Environment: %s" % pformat(environment._asdict()))

    return python, environment


def which_python(python, env=os.environ):
    """Determine which python binary should be used.

    In priority order:
    * --python specified on the command line
    * RETICULATE_PYTHON defined in the environment
    * the python binary running this script
    """
    if python:
        if not (exists(python) and os.access(python, os.X_OK)):
            raise RSConnectException('The file, "%s", does not exist or is not executable.' % python)
        return python

    if "RETICULATE_PYTHON" in env:
        return os.path.expanduser(env["RETICULATE_PYTHON"])

    return sys.executable


def inspect_environment(
    python,  # type: str
    directory,  # type: str
    conda_mode=False,  # type: bool
    force_generate=False,  # type: bool
    check_output=subprocess.check_output,  # type: typing.Callable
):
    # type: (...) -> Environment
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    flags = []
    if conda_mode:
        flags.append("c")
    if force_generate:
        flags.append("f")
    args = [python, "-m", "rsconnect.environment"]
    if len(flags) > 0:
        args.append("-" + "".join(flags))
    args.append(directory)
    try:
        environment_json = check_output(args, universal_newlines=True)
    except subprocess.CalledProcessError as e:
        raise RSConnectException("Error inspecting environment: %s" % e.output)
    return MakeEnvironment(**json.loads(environment_json))  # type: ignore


def are_apis_supported_on_server(connect_details):
    """
    Returns whether or not the Connect server has Python itself enabled and its license allows
    for API usage.  This controls whether APIs may be deployed..

    :param connect_details: details about a Connect server as returned by gather_server_details()
    :return: boolean True if the Connect server supports Python APIs or not or False if not.
    :error: The RStudio Connect server does not allow for Python APIs.
    """
    return connect_details["python"]["api_enabled"]


def validate_entry_point(entry_point, directory):
    """
    Validates the entry point specified by the user, expanding as necessary.  If the
    user specifies nothing, a module of "app" is assumed.  If the user specifies a
    module only, the object is assumed to be the same name as the module.

    :param entry_point: the entry point as specified by the user.
    :return: the fully expanded and validated entry point and the module file name..
    """
    if not entry_point:
        entry_point = get_default_entrypoint(directory)

    parts = entry_point.split(":")

    if len(parts) > 2:
        raise RSConnectException('Entry point is not in "module:object" format.')

    return entry_point


def get_default_entrypoint(directory):
    candidates = ["app", "application", "main", "api"]
    files = set(os.listdir(directory))

    for candidate in candidates:
        filename = candidate + ".py"
        if filename in files:
            return candidate

    # if only one python source file, use it
    python_files = list(filter(lambda s: s.endswith(".py"), files))
    if len(python_files) == 1:
        return python_files[0][:-3]

    logger.warning("Can't determine entrypoint; defaulting to 'app'")
    return "app"
