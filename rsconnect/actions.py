"""
Public API for managing settings and deploying content.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import shutil
import subprocess
import sys
import traceback
import typing
from os.path import basename, exists, join, relpath
from typing import Optional, Sequence, cast
from warnings import warn

# Even though TypedDict is available in Python 3.8, because it's used with NotRequired,
# they should both come from the same typing module.
# https://peps.python.org/pep-0655/#usage-in-python-3-11
if sys.version_info >= (3, 11):
    from typing import NotRequired, TypedDict
else:
    from typing_extensions import NotRequired, TypedDict

from urllib.parse import urlparse

import click

from . import api
from .bundle import (
    create_python_environment,
    get_default_entrypoint,
    make_api_bundle,
    make_quarto_source_bundle,
    read_manifest_file,
)
from .environment import Environment, EnvironmentException
from .exception import RSConnectException
from .log import VERBOSE, logger
from .models import AppMode, AppModes

line_width = 45
_module_pattern = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$")
_name_sub_pattern = re.compile(r"[^A-Za-z0-9_ -]+")
_repeating_sub_pattern = re.compile(r"_+")


@contextlib.contextmanager
def cli_feedback(label: str, stderr: bool = False):
    """Context manager for OK/ERROR feedback from the CLI.

    If the enclosed block succeeds, OK will be emitted.
    If it fails, ERROR will be emitted.
    Errors will also be classified as operational errors (prefixed with 'Error')
    vs. internal errors (prefixed with 'Internal Error'). In verbose mode,
    tracebacks will be emitted for internal errors.
    """
    if label:
        pad = line_width - len(label)
        click.secho(label + "... " + " " * pad, nl=False, err=stderr)
        logger.set_in_feedback(True)

    def passed():
        if label:
            click.secho("[OK]", fg="green", err=stderr)

    def failed(err: str):
        if label:
            click.secho("[ERROR]", fg="red", err=stderr)
        click.secho(str(err), fg="bright_red", err=stderr)
        sys.exit(1)

    try:
        yield
        passed()
    except RSConnectException as exc:
        failed("Error: " + exc.message)
    except EnvironmentException as exc:
        failed("Error: " + str(exc))
    except Exception as exc:
        traceback.print_exc()
        failed("Internal error: " + str(exc))
    finally:
        logger.set_in_feedback(False)


def set_verbosity(verbose: int):
    """Set the verbosity level based on a passed flag

    :param verbose: boolean specifying verbose or not
    """
    if verbose == 0:
        logger.setLevel(logging.INFO)
    elif verbose == 1:
        logger.setLevel(VERBOSE)
    else:
        logger.setLevel(logging.DEBUG)


def _verify_server(connect_server: api.RSConnectServer):
    """
    Test whether the server identified by the given full URL can be reached and is
    running Connect.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    uri = urlparse(connect_server.url)
    if not uri.netloc:
        raise RSConnectException('Invalid server URL: "%s"' % connect_server.url)
    return api.verify_server(connect_server)


def _to_server_check_list(url: str) -> list[str]:
    """
    Build a list of servers to check from the given one.  If the specified server
    appears not to have a scheme, then we'll provide https and http variants to test.

    :param url: the server URL text to start with.
    :return: a list of server strings to test.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    # urlparse will end up with an empty netloc in this case.
    if "//" not in url:
        items = ["https://%s", "http://%s"]
    # urlparse would parse this correctly and end up with an empty scheme.
    elif url.startswith("//"):
        items = ["https:%s", "http:%s"]
    else:
        items = ["%s"]

    return [item % url for item in items]


def test_server(connect_server: api.RSConnectServer) -> tuple[api.RSConnectServer, object]:
    """
    Test whether the given server can be reached and is running Connect.  The server
    may be provided with or without a scheme.  If a scheme is omitted, the server will
    be tested with both `https` and `http` until one of them works.

    :param connect_server: the Connect server information.
    :return: a second server object with any scheme expansions applied and the server
    settings from the server.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    url = connect_server.url
    key = connect_server.api_key
    insecure = connect_server.insecure
    ca_data = connect_server.ca_data
    failures: list[str] = []
    for test in _to_server_check_list(url):
        try:
            connect_server = api.RSConnectServer(test, key, insecure, ca_data)
            result = _verify_server(connect_server)
            return connect_server, result
        except RSConnectException as exc:
            failures.append("    %s - failed to verify as Posit Connect (%s)." % (test, str(exc)))

    # In case the user may need https instead of http...
    if len(failures) == 1 and url.startswith("http://"):
        failures.append('    Do you need to use "https://%s"?' % url[7:])

    # If we're here, nothing worked.
    raise RSConnectException("\n".join(failures))


def test_rstudio_server(server: api.PositServer):
    with api.PositClient(server) as client:
        try:
            client.get_current_user()
        except RSConnectException as exc:
            raise RSConnectException("Failed to verify with {} ({}).".format(server.remote_name, exc))


def test_api_key(connect_server: api.RSConnectServer) -> str:
    """
    Test that an API Key may be used to authenticate with the given Posit Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information.
    :return: the username of the user to whom the API key belongs.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    return api.verify_api_key(connect_server)


def which_quarto(quarto: Optional[str] = None) -> str:
    """
    Identify a valid Quarto executable. When a Quarto location is not provided
    as input, an attempt is made to discover Quarto from the PATH and other
    well-known locations.
    """
    if quarto:
        found = shutil.which(quarto)
        if not found:
            raise RSConnectException('The Quarto installation, "%s", does not exist or is not executable.' % quarto)
        return found

    # Fallback -- try to find Quarto when one was not supplied.
    locations = [
        # Discover using $PATH
        "quarto",
        # Location used by some installers, and often-added symbolic link.
        "/usr/local/bin/quarto",
        # Location used by some installers.
        "/opt/quarto/bin/quarto",
        # macOS RStudio IDE embedded installation
        "/Applications/RStudio.app/Contents/MacOS/quarto/bin/quarto",
        # macOS RStudio IDE electron embedded installation; location not final.
        # see: https://github.com/rstudio/rstudio/issues/10674
    ]

    for each in locations:
        found = shutil.which(each)
        if found:
            return found
    raise RSConnectException("Unable to locate a Quarto installation.")


class QuartoInspectResultQuarto(TypedDict):
    version: str


class QuartoInspectResultConfigProject(TypedDict):
    render: list[str]


class QuartoInspectResultConfig(TypedDict):
    project: QuartoInspectResultConfigProject


class QuartoInspectResult(TypedDict):
    quarto: QuartoInspectResultQuarto
    engines: list[str]
    config: NotRequired[QuartoInspectResultConfig]


def quarto_inspect(
    quarto: str,
    target: str,
    check_output: typing.Callable[..., bytes] = subprocess.check_output,
) -> QuartoInspectResult:
    """
    Runs 'quarto inspect' against the target and returns its output as a
    parsed JSON object.

    The JSON result has different structure depending on whether or not the
    target is a directory or a file.
    """

    args = [quarto, "inspect", target]
    try:
        inspect_json = check_output(args, universal_newlines=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        raise RSConnectException("Error inspecting target: %s" % e.output)
    return cast(QuartoInspectResult, json.loads(inspect_json))


def validate_quarto_engines(inspect: QuartoInspectResult):
    """
    The markdown and jupyter engines are supported. Not knitr.
    """
    supported = ["markdown", "jupyter"]
    engines = inspect.get("engines", [])
    unsupported = [engine for engine in engines if engine not in supported]
    if unsupported:
        raise RSConnectException("The following Quarto engine(s) are not supported: %s" % ", ".join(unsupported))
    return engines


# ===============================================================================
# START: The following deprecated functions are here only for the vetiver-python
# package.
# Some the code in this section has `pyright: ignore` comments, because this
# deprecated code which will be removed in the future.
# ===============================================================================
def validate_extra_files(directory: str, extra_files: Sequence[str]):
    """
    If the user specified a list of extra files, validate that they all exist and are
    beneath the given directory and, if so, return a list of them made relative to that
    directory.

    :param directory: the directory that the extra files must be relative to.
    :param extra_files: the list of extra files to qualify and validate.
    :return: the extra files qualified by the directory.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    result: list[str] = []
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


def validate_entry_point(entry_point: Optional[str], directory: str):
    """
    Validates the entry point specified by the user, expanding as necessary.  If the
    user specifies nothing, a module of "app" is assumed.  If the user specifies a
    module only, the object is assumed to be the same name as the module.

    :param entry_point: the entry point as specified by the user.
    :return: the fully expanded and validated entry point and the module file name..
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    if not entry_point:
        entry_point = get_default_entrypoint(directory)

    parts = entry_point.split(":")

    if len(parts) > 2:
        raise RSConnectException('Entry point is not in "module:object" format.')

    return entry_point


def deploy_app(
    name: Optional[str] = None,
    server: Optional[str] = None,
    api_key: Optional[str] = None,
    insecure: Optional[bool] = None,
    cacert: Optional[typing.IO[str]] = None,
    ca_data: Optional[str] = None,
    entry_point: Optional[str] = None,
    excludes: Optional[list[str]] = None,
    new: bool = False,
    app_id: Optional[str] = None,
    title: Optional[str] = None,
    python: Optional[str] = None,
    force_generate: bool = False,
    verbose: Optional[bool] = None,
    directory: Optional[str] = None,
    extra_files: Optional[list[str]] = None,
    env_vars: Optional[dict[str, str]] = None,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
    account: Optional[str] = None,
    token: Optional[str] = None,
    secret: Optional[str] = None,
    app_mode: Optional[AppMode] = None,
    connect_server: Optional[api.TargetableServer] = None,
    **kws: object,
):
    kwargs = locals()
    kwargs["entry_point"] = entry_point = validate_entry_point(entry_point, directory)  # pyright: ignore
    kwargs["extra_files"] = extra_files = validate_extra_files(directory, extra_files)  # pyright: ignore

    if isinstance(connect_server, api.RSConnectServer):
        kwargs.update(
            dict(
                url=connect_server.url,
                api_key=connect_server.api_key,
                insecure=connect_server.insecure,
                ca_data=connect_server.ca_data,
                cookies=connect_server.cookie_jar,
            )
        )
    elif isinstance(connect_server, api.ShinyappsServer) or isinstance(connect_server, api.CloudServer):
        kwargs.update(
            dict(
                url=connect_server.url,
                account=connect_server.account_name,
                token=connect_server.token,
                secret=connect_server.secret,
            )
        )

    environment = create_python_environment(
        directory,  # pyright: ignore
        force_generate,
        python,
    )

    # At this point, kwargs has a lot of things, but we can need to prune it down to just the things that
    # the RSConnectExecutor constructor knows about.
    executor_params = [
        "ctx",
        "name",
        "url",
        "api_key",
        "insecure",
        "cacert",
        "ca_data",
        "cookies",
        "account",
        "token",
        "secret",
        "timeout",
        "logger",
        "path",
        "server",
        "exclude",
        "new",
        "app_id",
        "title",
        "visibility",
        "disable_env_management",
        "env_vars",
    ]
    shared_keys = set(executor_params).intersection(kwargs.keys())
    kwargs = {key: kwargs[key] for key in shared_keys}

    ce = api.RSConnectExecutor(**kwargs)
    (
        ce.validate_server()
        .validate_app_mode(app_mode=app_mode)  # pyright: ignore
        .make_bundle(
            make_api_bundle,
            directory,  # pyright: ignore
            entry_point,
            app_mode,  # pyright: ignore
            environment,
            extra_files,
            excludes,  # pyright: ignore
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )


# ===============================================================================
# END deprecated functions for the vetiver-python package
# ===============================================================================


def deploy_python_fastapi(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    conda_mode: bool,
    force_generate: bool,
    log_callback: typing.Callable[..., None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
):
    """
    A function to deploy a Python ASGI API module to Posit Connect.  Depending on the files involved
        and network latency, this may take a bit of time.
        :param connect_server: the Connect server information.
        :param directory: the app directory to deploy.
        :param extra_files: any extra files that should be included in the deploy.
        :param excludes: a sequence of glob patterns that will exclude matched files.
        :param entry_point: the module/executable object for the WSGi framework.
        :param new: a flag to force this as a new deploy. Previous default = False.
        :param app_id: the ID of an existing application to deploy new files for. Previous default = None.
        :param title: an optional title for the deploy.  If this is not provided, one will
        be generated. Previous default = None.
        :param python: the optional name of a Python executable. Previous default = None.
        :param conda_mode: depricated parameter, included for compatibility. Ignored.
        :param force_generate: force generating "requirements.txt" or "environment.yml",
        even if it already exists. Previous default = False.
        :param log_callback: the callback to use to write the log to.  If this is None
        (the default) the lines from the deployment log will be returned as a sequence.
        If a log callback is provided, then None will be returned for the log lines part
        of the return tuple. Previous default = None.
        :param image: the optional docker image to be specified for off-host execution. Default = None.
        :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
        :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
        :return: the ultimate URL where the deployed app may be accessed and the sequence
        of log lines.  The log lines value will be None if a log callback was provided.
    """
    return deploy_app(app_mode=AppModes.PYTHON_FASTAPI, **locals())


def create_quarto_deployment_bundle(
    file_or_directory: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    app_mode: AppMode,
    inspect: QuartoInspectResult,
    environment: Optional[Environment],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.IO[bytes]:
    """
    Create an in-memory bundle, ready to deploy.

    :param file_or_directory: The Quarto document or the directory containing the Quarto project.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param entry_point: the module/executable object for the WSGi framework.
    :param app_mode: the mode of the app being deployed.
    :param environment: environmental information.
    :param extra_files_need_validating: a flag indicating whether the list of extra
    files should be validated or not.  Part of validating includes qualifying each
    with the specified directory.  If you provide False here, make sure the names
    are properly qualified first. Previous default = True.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the bundle.
    """
    if app_mode is None:
        app_mode = AppModes.STATIC_QUARTO

    return make_quarto_source_bundle(
        file_or_directory,
        inspect,
        app_mode,
        environment,
        extra_files,
        excludes,
        image,
        env_management_py,
        env_management_r,
    )


def describe_manifest(file_name: str) -> tuple[str | None, str | None]:
    """
    Determine the entry point and/or primary file from the given manifest file.
    If no entry point is recorded in the manifest, then None will be returned for
    that.  The same is true for the primary document.  None will be returned for
    both if the file doesn't exist or doesn't look like a manifest file.

    :param file_name: the name of the manifest file to read.
    :return: the entry point and primary document from the manifest.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
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
