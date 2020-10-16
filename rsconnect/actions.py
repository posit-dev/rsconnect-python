"""
Public API for managing settings and deploying content.
"""

import contextlib
import json
import logging
import os
import re
import traceback
import sys
import subprocess

try:
    import typing
except ImportError:
    typing = None

from os.path import abspath, basename, dirname, exists, isdir, join, relpath, splitext
from pprint import pformat

from rsconnect import api
from .bundle import (
    make_api_bundle,
    make_api_manifest,
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_source_manifest,
    manifest_add_buffer,
    manifest_add_file,
    read_manifest_file,
)
from .environment import Environment, MakeEnvironment, EnvironmentException
from .log import logger
from .metadata import AppStore
from .models import AppModes

import click
from six.moves.urllib_parse import urlparse

line_width = 45
_module_pattern = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$")
_name_sub_pattern = re.compile(r"[^A-Za-z0-9_ -]+")
_repeating_sub_pattern = re.compile(r"_+")


@contextlib.contextmanager
def cli_feedback(label):
    """Context manager for OK/ERROR feedback from the CLI.

    If the enclosed block succeeds, OK will be emitted.
    If it fails, ERROR will be emitted.
    Errors will also be classified as operational errors (prefixed with 'Error')
    vs. internal errors (prefixed with 'Internal Error'). In verbose mode,
    tracebacks will be emitted for internal errors.
    """
    if label:
        pad = line_width - len(label)
        click.secho(label + "... " + " " * pad, nl=False, fg="bright_white")
        logger.set_in_feedback(True)

    def passed():
        if label:
            click.secho("[OK]", fg="bright_green")

    def failed(err):
        if label:
            click.secho("[ERROR]", fg="red")
        click.secho(str(err), fg="bright_red")
        sys.exit(1)

    try:
        yield
        passed()
    except api.RSConnectException as exc:
        failed("Error: " + exc.message)
    except EnvironmentException as exc:
        failed("Error: " + str(exc))
    except Exception as exc:
        if click.get_current_context("verbose"):
            traceback.print_exc()
        failed("Internal error: " + str(exc))
    finally:
        logger.set_in_feedback(False)


def set_verbosity(verbose):
    """Set the verbosity level based on a passed flag

    :param verbose: boolean specifying verbose or not
    """
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.WARN)


def which_python(python, env=os.environ):
    """Determine which python binary should be used.

    In priority order:
    * --python specified on the command line
    * RETICULATE_PYTHON defined in the environment
    * the python binary running this script
    """
    if python:
        if not (exists(python) and os.access(python, os.X_OK)):
            raise api.RSConnectException('The file, "%s", does not exist or is not executable.' % python)
        return python

    if "RETICULATE_PYTHON" in env:
        return env["RETICULATE_PYTHON"]

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
        raise api.RSConnectException("Error inspecting environment: %s" % e.output)
    return MakeEnvironment(**json.loads(environment_json))  # type: ignore


def _verify_server(connect_server):
    """
    Test whether the server identified by the given full URL can be reached and is
    running Connect.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    uri = urlparse(connect_server.url)
    if not uri.netloc:
        raise api.RSConnectException('Invalid server URL: "%s"' % connect_server.url)
    return api.verify_server(connect_server)


def _to_server_check_list(url):
    """
    Build a list of servers to check from the given one.  If the specified server
    appears not to have a scheme, then we'll provide https and http variants to test.

    :param url: the server URL text to start with.
    :return: a list of server strings to test.
    """
    # urlparse will end up with an empty netloc in this case.
    if "//" not in url:
        items = ["https://%s", "http://%s"]
    # urlparse would parse this correctly and end up with an empty scheme.
    elif url.startswith("//"):
        items = ["https:%s", "http:%s"]
    else:
        items = ["%s"]

    return [item % url for item in items]


def test_server(connect_server):
    """
    Test whether the given server can be reached and is running Connect.  The server
    may be provided with or without a scheme.  If a scheme is omitted, the server will
    be tested with both `https` and `http` until one of them works.

    :param connect_server: the Connect server information.
    :return: a second server object with any scheme expansions applied and the server
    settings from the server.
    """
    url = connect_server.url
    key = connect_server.api_key
    insecure = connect_server.insecure
    ca_data = connect_server.ca_data
    failures = []
    for test in _to_server_check_list(url):
        try:
            connect_server = api.RSConnectServer(test, key, insecure, ca_data)
            result = _verify_server(connect_server)
            return connect_server, result
        except api.RSConnectException as exc:
            failures.append("    %s - failed to verify as RStudio Connect (%s)." % (test, str(exc)))

    # In case the user may need https instead of http...
    if len(failures) == 1 and url.startswith("http://"):
        failures.append('    Do you need to use "https://%s"?' % url[7:])

    # If we're here, nothing worked.
    raise api.RSConnectException("\n".join(failures))


def test_api_key(connect_server):
    """
    Test that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information.
    :return: the username of the user to whom the API key belongs.
    """
    return api.verify_api_key(connect_server)


def gather_server_details(connect_server):
    """
    Builds a dictionary containing the version of RStudio Connect that is running
    and the versions of Python installed there.

    :param connect_server: the Connect server information.
    :return: a three-entry dictionary.  The key 'connect' will refer to the version
    of Connect that was found.  The key `python` will refer to a sequence of version
    strings for all the versions of Python that are installed.  The key `conda` will
    refer to data about whether Connect is configured to support Conda environments.
    """

    def _to_sort_key(text):
        parts = [part.zfill(5) for part in text.split(".")]
        return "".join(parts)

    server_settings = api.verify_server(connect_server)
    python_settings = api.get_python_info(connect_server)
    python_versions = sorted([item["version"] for item in python_settings["installations"]], key=_to_sort_key)
    conda_settings = {"supported": python_settings["conda_enabled"] if "conda_enabled" in python_settings else False}
    return {
        "connect": server_settings["version"],
        "python": {
            "api_enabled": python_settings["api_enabled"] if "api_enabled" in python_settings else False,
            "versions": python_versions,
        },
        "conda": conda_settings,
    }


def are_apis_supported_on_server(connect_details):
    """
    Returns whether or not the Connect server has Python itself enabled and its license allows
    for API usage.  This controls whether APIs may be deployed..

    :param connect_details: details about a Connect server as returned by gather_server_details()
    :return: boolean True if the Connect server supports Python APIs or not or False if not.
    :error: The RStudio Connect server does not allow for Python APIs.
    """
    return connect_details["python"]["api_enabled"]


def is_conda_supported_on_server(connect_details):
    """
    Returns whether or not conda is supported on a Connect server.

    :param connect_details: details about a Connect server as returned by gather_server_details()
    :return: boolean True if supported, False otherwise
    :error: Conda is not supported on the target server.  Try deploying without requesting Conda.
    """
    return connect_details.get("conda", {}).get("supported", False)


def check_server_capabilities(connect_server, capability_functions, details_source=gather_server_details):
    """
    Uses a sequence of functions that check for capabilities in a Connect server.  The
    server settings data is retrieved by the gather_server_details() function.

    Each function provided must accept one dictionary argument which will be the server
    settings data returned by the gather_server_details() function.  That function must
    return a boolean value.  It must also contain a docstring which itself must contain
    an ":error:" tag as the last thing in the docstring.  If the function returns False,
    an exception is raised with the function's ":error:" text as its message.

    :param connect_server: the information needed to interact with the Connect server.
    :param capability_functions: a sequence of functions that will be called.
    :param details_source: the source for obtaining server details, gather_server_details(),
    by default.
    """
    details = details_source(connect_server)

    for function in capability_functions:
        if not function(details):
            index = function.__doc__.find(":error:") if function.__doc__ else -1
            if index >= 0:
                message = function.__doc__[index + 7 :].strip()
            else:
                message = "The server does not satisfy the %s capability check." % function.__name__
            raise api.RSConnectException(message)


def _make_deployment_name(connect_server, title, force_unique):
    """
    Produce a name for a deployment based on its title.  It is assumed that the
    title is already defaulted and validated as appropriate (meaning the title
    isn't None or empty).

    We follow the same rules for doing this as the R rsconnect package does.  See
    the title.R code in https://github.com/rstudio/rsconnect/R with the exception
    that we collapse repeating underscores and, if the name is too short, it is
    padded to the left with underscores.

    :param connect_server: the information needed to interact with the Connect server.
    :param title: the title to start with.
    :param force_unique: a flag noting whether the generated name must be forced to be
    unique.
    :return: a name for a deployment based on its title.
    """
    # First, Generate a default name from the given title.
    name = _name_sub_pattern.sub("", title.lower()).replace(" ", "_")
    name = _repeating_sub_pattern.sub("_", name)[:64].rjust(3, "_")

    # Now, make sure it's unique, if needed.
    if force_unique:
        name = api.find_unique_name(connect_server, name)

    return name


def _validate_title(title):
    """
    If the user specified a title, validate that it meets Connect's length requirements.
    If the validation fails, an exception is raised.  Otherwise,

    :param title: the title to validate.
    """
    if title:
        if not (3 <= len(title) <= 1024):
            raise api.RSConnectException("A title must be between 3-1024 characters long.")


def _default_title(file_name):
    """
    Produce a default content title from the given file path.  The result is
    guaranteed to be between 3 and 1024 characters long, as required by RStudio
    Connect.

    :param file_name: the name from which the title will be derived.
    :return: the derived title.
    """
    # Make sure we have enough of a path to derive text from.
    file_name = abspath(file_name)
    # noinspection PyTypeChecker
    return basename(file_name).rsplit(".", 1)[0][:1024].rjust(3, "0")


def _default_title_from_manifest(the_manifest, manifest_file):
    """
    Produce a default content title from the contents of a manifest.
    """
    filename = None

    metadata = the_manifest.get("metadata")
    if metadata:
        # noinspection SpellCheckingInspection
        filename = metadata.get("entrypoint") or metadata.get("primary_rmd") or metadata.get("primary_html")
        # If the manifest is for an API, revert to using the parent directory.
        if filename and _module_pattern.match(filename):
            filename = None
    return _default_title(filename or dirname(manifest_file))


def validate_file_is_notebook(file_name):
    """
    Validate that the given file is a Jupyter Notebook. If it isn't, an exception is
    thrown.  A file must exist and have the '.ipynb' extension.

    :param file_name: the name of the file to validate.
    """
    file_suffix = splitext(file_name)[1].lower()
    if file_suffix != ".ipynb" or not exists(file_name):
        raise api.RSConnectException("A Jupyter notebook (.ipynb) file is required here.")


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
                raise api.RSConnectException("%s must be under %s." % (extra_file, directory))
            if not exists(join(directory, extra_file)):
                raise api.RSConnectException("Could not find file %s under %s" % (extra, directory))
            result.append(extra_file)
    return result


def validate_manifest_file(file_or_directory):
    """
    Validates that the name given represents either an existing manifest.json file or
    a directory that contains one.  If not, an exception is raised.

    :param file_or_directory: the name of the manifest file or directory that contains it.
    :return: the real path to the manifest file.
    """
    if isdir(file_or_directory):
        file_or_directory = join(file_or_directory, "manifest.json")
    if basename(file_or_directory) != "manifest.json" or not exists(file_or_directory):
        raise api.RSConnectException("A manifest.json file or a directory containing one is required here.")
    return file_or_directory


def validate_entry_point(entry_point):
    """
    Validates the entry point specified by the user, expanding as necessary.  If the
    user specifies nothing, a module of "app" is assumed.  If the user specifies a
    module only, the object is assumed to be the same name as the module.

    :param entry_point: the entry point as specified by the user.
    :return: the fully expanded and validated entry point and the module file name..
    """
    if not entry_point:
        entry_point = "app"

    parts = entry_point.split(":")

    if len(parts) > 2:
        raise api.RSConnectException('Entry point is not in "module:object" format.')

    return entry_point


def deploy_jupyter_notebook(
    connect_server,
    file_name,
    extra_files,
    new=False,
    app_id=None,
    title=None,
    static=False,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Jupyter notebook to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param file_name: the Jupyter notebook file to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param static: a flag noting whether the notebook should be deployed as a static
    HTML page or as a render-able document with sources.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    app_store = AppStore(file_name)
    (app_id, deployment_name, deployment_title, default_title, app_mode,) = gather_basic_deployment_info_for_notebook(
        connect_server, app_store, file_name, new, app_id, title, static
    )
    python, environment = get_python_env_info(file_name, python, conda_mode=conda_mode, force_generate=force_generate,)
    bundle = create_notebook_deployment_bundle(file_name, extra_files, app_mode, python, environment)
    return _finalize_deploy(
        connect_server,
        app_store,
        file_name,
        app_id,
        app_mode,
        deployment_name,
        deployment_title,
        default_title,
        bundle,
        log_callback,
    )


def _finalize_deploy(
    connect_server, app_store, file_name, app_id, app_mode, name, title, title_is_default, bundle, log_callback,
):
    """
    A common function to finish up the deploy process once all the data (bundle
    included) has been resolved.

    :param connect_server: the Connect server information.
    :param app_store: the store for the specified file
    :param file_name: the primary file or directory being deployed.
    :param app_id: the ID of an existing application to deploy new files for.
    :param app_mode: the app mode to use.
    :param name: the name to use for the deploy.
    :param title: the title to use for the deploy.
    :param title_is_default: a flag noting whether the title carries a defaulted value.
    :param bundle: the bundle to deploy.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    app = deploy_bundle(connect_server, app_id, name, title, title_is_default, bundle)
    app_url, log_lines = spool_deployment_log(connect_server, app, log_callback)
    app_store.set(
        connect_server.url, abspath(file_name), app_url, app["app_id"], app["app_guid"], title, app_mode,
    )
    return app_url, log_lines


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


def deploy_python_api(
    connect_server,
    directory,
    extra_files,
    excludes,
    entry_point,
    new=False,
    app_id=None,
    title=None,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Python WSGi API module to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param directory: the app directory to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return _deploy_by_python_framework(
        connect_server,
        directory,
        extra_files,
        excludes,
        entry_point,
        gather_basic_deployment_info_for_api,
        new,
        app_id,
        title,
        python,
        conda_mode,
        force_generate,
        log_callback,
    )


def deploy_dash_app(
    connect_server,
    directory,
    extra_files,
    excludes,
    entry_point,
    new=False,
    app_id=None,
    title=None,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Python Dash app module to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param directory: the app directory to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return _deploy_by_python_framework(
        connect_server,
        directory,
        extra_files,
        excludes,
        entry_point,
        gather_basic_deployment_info_for_dash,
        new,
        app_id,
        title,
        python,
        conda_mode,
        force_generate,
        log_callback,
    )


def deploy_streamlit_app(
    connect_server,
    directory,
    extra_files,
    excludes,
    entry_point,
    new=False,
    app_id=None,
    title=None,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Python Streamlit app module to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param directory: the app directory to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return _deploy_by_python_framework(
        connect_server,
        directory,
        extra_files,
        excludes,
        entry_point,
        gather_basic_deployment_info_for_streamlit,
        new,
        app_id,
        title,
        python,
        conda_mode,
        force_generate,
        log_callback,
    )


def deploy_bokeh_app(
    connect_server,
    directory,
    extra_files,
    excludes,
    entry_point,
    new=False,
    app_id=None,
    title=None,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Python Bokeh app module to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param directory: the app directory to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return _deploy_by_python_framework(
        connect_server,
        directory,
        extra_files,
        excludes,
        entry_point,
        gather_basic_deployment_info_for_bokeh,
        new,
        app_id,
        title,
        python,
        conda_mode,
        force_generate,
        log_callback,
    )


def _deploy_by_python_framework(
    connect_server,
    directory,
    extra_files,
    excludes,
    entry_point,
    gatherer,
    new=False,
    app_id=None,
    title=None,
    python=None,
    conda_mode=False,
    force_generate=False,
    log_callback=None,
):
    """
    A function to deploy a Python WSGi API module to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param directory: the app directory to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param gatherer: the function to use to gather basic information.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param python: the optional name of a Python executable.
    :param conda_mode: use conda to build an environment.yml
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    module_file = fake_module_file_from_directory(directory)
    app_store = AppStore(module_file)
    (entry_point, app_id, deployment_name, deployment_title, default_title, app_mode,) = gatherer(
        connect_server, app_store, directory, entry_point, new, app_id, title
    )
    _, environment = get_python_env_info(directory, python, conda_mode=conda_mode, force_generate=force_generate,)
    bundle = create_api_deployment_bundle(directory, extra_files, excludes, entry_point, app_mode, environment)
    return _finalize_deploy(
        connect_server,
        app_store,
        directory,
        app_id,
        app_mode,
        deployment_name,
        deployment_title,
        default_title,
        bundle,
        log_callback,
    )


def deploy_by_manifest(
    connect_server, manifest_file_name, new=False, app_id=None, title=None, log_callback=None,
):
    """
    A function to deploy a Jupyter notebook to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param manifest_file_name: the manifest file to deploy.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    app_store = AppStore(manifest_file_name)
    (
        app_id,
        deployment_name,
        deployment_title,
        default_title,
        app_mode,
        package_manager,
    ) = gather_basic_deployment_info_from_manifest(connect_server, app_store, manifest_file_name, new, app_id, title)
    bundle = make_manifest_bundle(manifest_file_name)
    return _finalize_deploy(
        connect_server,
        app_store,
        manifest_file_name,
        app_id,
        app_mode,
        deployment_name,
        deployment_title,
        default_title,
        bundle,
        log_callback,
    )


def gather_basic_deployment_info_for_notebook(connect_server, app_store, file_name, new, app_id, title, static):
    """
    Helps to gather the necessary info for performing a deployment.

    :param connect_server: the Connect server information.
    :param app_store: the store for the specified file
    :param file_name: the primary file being deployed.
    :param new: a flag noting whether we should force a new deployment.
    :param app_id: the ID of the app to redeploy.
    :param title: an optional title.  If this isn't specified, a default title will
    be generated.
    :param static: a flag to note whether a static document should be deployed.
    :return: the app ID, name, title information and mode for the deployment.
    """
    validate_file_is_notebook(file_name)
    _validate_title(title)

    if new and app_id:
        raise api.RSConnectException("Specify either a new deploy or an app ID but not both.")

    if app_id is not None:
        # Don't read app metadata if app-id is specified. Instead, we need
        # to get this from Connect.
        app = api.get_app_info(connect_server, app_id)
        app_mode = AppModes.get_by_ordinal(app.get("app_mode", 0), True)

        logger.debug("Using app mode from app %s: %s" % (app_id, app_mode))
    elif static:
        app_mode = AppModes.STATIC
    else:
        app_mode = AppModes.JUPYTER_NOTEBOOK

    if not new and app_id is None:
        # Possible redeployment - check for saved metadata.
        # Use the saved app information unless overridden by the user.
        app_id, app_mode = app_store.resolve(connect_server.url, app_id, app_mode)
        if static and app_mode != AppModes.STATIC:
            raise api.RSConnectException(
                'Cannot change app mode to "static" once deployed. Use --new to create a new deployment.'
            )

    default_title = not bool(title)
    title = title or _default_title(file_name)

    return (
        app_id,
        _make_deployment_name(connect_server, title, app_id is None),
        title,
        default_title,
        app_mode,
    )


def gather_basic_deployment_info_from_manifest(connect_server, app_store, file_name, new, app_id, title):
    """
    Helps to gather the necessary info for performing a deployment.

    :param connect_server: the Connect server information.
    :param app_store: the store for the specified file
    :param file_name: the manifest file being deployed.
    :param new: a flag noting whether we should force a new deployment.
    :param app_id: the ID of the app to redeploy.
    :param title: an optional title.  If this isn't specified, a default title will
    be generated.
    :return: the app ID, name, title information, mode, and package manager for the
    deployment.
    """
    file_name = validate_manifest_file(file_name)

    _validate_title(title)

    if new and app_id:
        raise api.RSConnectException("Specify either a new deploy or an app ID but not both.")

    source_manifest, _ = read_manifest_file(file_name)
    # noinspection SpellCheckingInspection
    app_mode = AppModes.get_by_name(source_manifest["metadata"]["appmode"])

    if not new and app_id is None:
        # Possible redeployment - check for saved metadata.
        # Use the saved app information unless overridden by the user.
        app_id, app_mode = app_store.resolve(connect_server.url, app_id, app_mode)

    package_manager = source_manifest.get("python", {}).get("package_manager", {}).get("name", None)
    default_title = not bool(title)
    title = title or _default_title_from_manifest(source_manifest, file_name)

    return (
        app_id,
        _make_deployment_name(connect_server, title, app_id is None),
        title,
        default_title,
        app_mode,
        package_manager,
    )


def _generate_gather_basic_deployment_info_for_python(app_mode):
    """
    Generates function to gather the necessary info for performing a deployment by app mode
    """

    def gatherer(connect_server, app_store, directory, entry_point, new, app_id, title):
        return _gather_basic_deployment_info_for_framework(
            connect_server, app_store, directory, entry_point, new, app_id, app_mode, title,
        )

    return gatherer


gather_basic_deployment_info_for_api = _generate_gather_basic_deployment_info_for_python(AppModes.PYTHON_API)
gather_basic_deployment_info_for_dash = _generate_gather_basic_deployment_info_for_python(AppModes.DASH_APP)
gather_basic_deployment_info_for_streamlit = _generate_gather_basic_deployment_info_for_python(AppModes.STREAMLIT_APP)
gather_basic_deployment_info_for_bokeh = _generate_gather_basic_deployment_info_for_python(AppModes.BOKEH_APP)


def _gather_basic_deployment_info_for_framework(
    connect_server, app_store, directory, entry_point, new, app_id, app_mode, title
):
    """
    Helps to gather the necessary info for performing a deployment.

    :param connect_server: the Connect server information.
    :param app_store: the store for the specified directory.
    :param directory: the primary file being deployed.
    :param entry_point: the entry point for the API in '<module>:<object> format.  if
    the object name is omitted, it defaults to the module name.  If nothing is specified,
    it defaults to 'app'.
    :param new: a flag noting whether we should force a new deployment.
    :param app_id: the ID of the app to redeploy.
    :param app_mode: the app mode to use.
    :param title: an optional title.  If this isn't specified, a default title will
    be generated.
    :return: the entry point, app ID, name, title and mode for the deployment.
    """
    entry_point = validate_entry_point(entry_point)

    _validate_title(title)

    if new and app_id:
        raise api.RSConnectException("Specify either a new deploy or an app ID but not both.")

    if app_id is not None:
        # Don't read app metadata if app-id is specified. Instead, we need
        # to get this from Connect.
        app = api.get_app_info(connect_server, app_id)
        app_mode = AppModes.get_by_ordinal(app.get("app_mode", 0), True)

        logger.debug("Using app mode from app %s: %s" % (app_id, app_mode))

    if not new and app_id is None:
        # Possible redeployment - check for saved metadata.
        # Use the saved app information unless overridden by the user.
        app_id, existing_app_mode = app_store.resolve(connect_server.url, app_id, app_mode)
        if existing_app_mode and app_mode != existing_app_mode:
            msg = (
                "Deploying with mode '%s',\n"
                + "but the existing deployment has mode '%s'.\n"
                + "Use the --new option to create a new deployment of the desired type."
            ) % (app_mode.desc(), existing_app_mode.desc())
            raise api.RSConnectException(msg)

    if directory[-1] == "/":
        directory = directory[:-1]

    default_title = not bool(title)
    title = title or _default_title(directory)

    return (
        entry_point,
        app_id,
        _make_deployment_name(connect_server, title, app_id is None),
        title,
        default_title,
        app_mode,
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
        raise api.RSConnectException(environment.error)
    logger.debug("Python: %s" % python)
    logger.debug("Environment: %s" % pformat(environment._asdict()))

    return python, environment


def create_notebook_deployment_bundle(
    file_name, extra_files, app_mode, python, environment, extra_files_need_validating=True,
):
    """
    Create an in-memory bundle, ready to deploy.

    :param file_name: the Jupyter notebook being deployed.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param app_mode: the mode of the app being deployed.
    :param python: information about the version of Python being used.
    :param environment: environmental information.
    :param extra_files_need_validating: a flag indicating whether the list of extra
    files should be validated or not.  Part of validating includes qualifying each
    with the parent directory of the notebook file.  If you provide False here, make
    sure the names are properly qualified first.
    :return: the bundle.
    """
    validate_file_is_notebook(file_name)

    if extra_files_need_validating:
        extra_files = validate_extra_files(dirname(file_name), extra_files)

    if app_mode == AppModes.STATIC:
        try:
            return make_notebook_html_bundle(file_name, python)
        except subprocess.CalledProcessError as exc:
            # Jupyter rendering failures are often due to
            # user code failing, vs. an internal failure of rsconnect-python.
            raise api.RSConnectException(str(exc))
    else:
        return make_notebook_source_bundle(file_name, environment, extra_files)


def create_api_deployment_bundle(
    directory, extra_files, excludes, entry_point, app_mode, environment, extra_files_need_validating=True,
):
    """
    Create an in-memory bundle, ready to deploy.

    :param directory: the directory that contains the code being deployed.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param app_mode: the mode of the app being deployed.
    :param environment: environmental information.
    :param extra_files_need_validating: a flag indicating whether the list of extra
    files should be validated or not.  Part of validating includes qualifying each
    with the specified directory.  If you provide False here, make sure the names
    are properly qualified first.
    :return: the bundle.
    """
    entry_point = validate_entry_point(entry_point)

    if extra_files_need_validating:
        extra_files = validate_extra_files(directory, extra_files)

    if app_mode is None:
        app_mode = AppModes.PYTHON_API

    return make_api_bundle(directory, entry_point, app_mode, environment, extra_files, excludes)


def deploy_bundle(connect_server, app_id, name, title, title_is_default, bundle):
    """
    Deploys the specified bundle.

    :param connect_server: the Connect server information.
    :param app_id: the ID of the app to deploy, if this is a redeploy.
    :param name: the name for the deploy.
    :param title: the title for the deploy.
    :param title_is_default: a flag noting whether the title carries a defaulted value.
    :param bundle: the bundle to deploy.
    :return: application information about the deploy.  This includes the ID of the
    task that may be queried for deployment progress.
    """
    return api.do_bundle_deploy(connect_server, app_id, name, title, title_is_default, bundle)


def spool_deployment_log(connect_server, app, log_callback):
    """
    Helper for spooling the deployment log for an app.

    :param connect_server: the Connect server information.
    :param app: the app that was returned by the deploy_bundle function.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return api.emit_task_log(connect_server, app["app_id"], app["task_id"], log_callback)


def create_notebook_manifest_and_environment_file(
    entry_point_file, environment, app_mode=None, extra_files=None, force=True
):
    """
    Creates and writes a manifest.json file for the given notebook entry point file.
    If the related environment file (requirements.txt, environment.yml, etc.) doesn't
    exist (or force is set to True), the environment file will also be written.

    :param entry_point_file: the entry point file (Jupyter notebook, etc.) to build
    the manifest for.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one.
    :param extra_files: any extra files that should be included in the manifest.
    :param force: if True, forces the environment file to be written. even if it
    already exists.
    :return:
    """
    if not write_notebook_manifest_json(entry_point_file, environment, app_mode, extra_files) or force:
        write_environment_file(environment, dirname(entry_point_file))


def write_notebook_manifest_json(entry_point_file, environment, app_mode=None, extra_files=None):
    """
    Creates and writes a manifest.json file for the given entry point file.  If
    the application mode is not provided, an attempt will be made to resolve one
    based on the extension portion of the entry point file.

    :param entry_point_file: the entry point file (Jupyter notebook, etc.) to build
    the manifest for.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one.
    :param extra_files: any extra files that should be included in the manifest.
    :return: whether or not the environment file (requirements.txt, environment.yml,
    etc.) that goes along with the manifest exists.
    """
    extra_files = validate_extra_files(dirname(entry_point_file), extra_files)
    directory = dirname(entry_point_file)
    file_name = basename(entry_point_file)
    manifest_path = join(directory, "manifest.json")

    if app_mode is None:
        _, extension = splitext(file_name)
        app_mode = AppModes.get_by_extension(extension, True)
        if app_mode == AppModes.UNKNOWN:
            raise api.RSConnectException('Could not determine the app mode from "%s"; please specify one.' % extension)

    manifest_data = make_source_manifest(file_name, environment, app_mode)
    manifest_add_file(manifest_data, file_name, directory)
    manifest_add_buffer(manifest_data, environment.filename, environment.contents)

    for rel_path in extra_files:
        manifest_add_file(manifest_data, rel_path, directory)

    with open(manifest_path, "w") as f:
        json.dump(manifest_data, f, indent=2)

    return exists(join(directory, environment.filename))


def create_api_manifest_and_environment_file(
    directory, entry_point, environment, app_mode=AppModes.PYTHON_API, extra_files=None, excludes=None, force=True,
):
    """
    Creates and writes a manifest.json file for the given Python API entry point.  If
    the related environment file (requirements.txt, environment.yml, etc.) doesn't
    exist (or force is set to True), the environment file will also be written.

    :param directory: the root directory of the Python API.
    :param entry_point: the module/executable object for the WSGi framework.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.
    :param extra_files: any extra files that should be included in the manifest.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param force: if True, forces the environment file to be written. even if it
    already exists.
    :return:
    """
    if not write_api_manifest_json(directory, entry_point, environment, app_mode, extra_files, excludes) or force:
        write_environment_file(environment, directory)


def write_api_manifest_json(
    directory, entry_point, environment, app_mode=AppModes.PYTHON_API, extra_files=None, excludes=None,
):
    """
    Creates and writes a manifest.json file for the given entry point file.  If
    the application mode is not provided, an attempt will be made to resolve one
    based on the extension portion of the entry point file.

    :param directory: the root directory of the Python API.
    :param entry_point: the module/executable object for the WSGi framework.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.
    :param extra_files: any extra files that should be included in the manifest.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: whether or not the environment file (requirements.txt, environment.yml,
    etc.) that goes along with the manifest exists.
    """
    extra_files = validate_extra_files(directory, extra_files)
    manifest, _ = make_api_manifest(directory, entry_point, app_mode, environment, extra_files, excludes)
    manifest_path = join(directory, "manifest.json")

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return exists(join(directory, environment.filename))


def write_environment_file(environment, directory):
    """
    Writes the environment file (requirements.txt, environment.yml, etc.) to the
    specified directory.

    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param directory: the directory where the file should be written.
    """
    environment_file_path = join(directory, environment.filename)
    with open(environment_file_path, "w") as f:
        f.write(environment.contents)


def describe_manifest(file_name):
    """
    Determine the entry point and/or primary file from the given manifest file.
    If no entry point is recorded in the manifest, then None will be returned for
    that.  The same is true for the primary document.  None will be returned for
    both if the file doesn't exist or doesn't look like a manifest file.

    :param file_name: the name of the manifest file to read.
    :return: the entry point and primary document from the manifest.
    """
    if basename(file_name) == "manifest.json" and exists(file_name):
        manifest, _ = read_manifest_file(file_name)
        metadata = manifest.get("metadata")
        if metadata:
            # noinspection SpellCheckingInspection
            return (
                metadata.get("entrypoint"),
                metadata.get("primary_rmd") or metadata.get("primary_html"),
            )
    return None, None
