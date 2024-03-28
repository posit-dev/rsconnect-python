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
from os.path import basename, dirname, exists, isdir, join, relpath, splitext
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Sequence, TextIO, cast
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

from . import api, bundle
from .api import RSConnectExecutor, filter_out_server_info
from .bundle import (
    _warn_if_environment_directory,
    _warn_if_no_requirements_file,
    _warn_on_ignored_manifest,
    _warn_on_ignored_requirements,
    create_python_environment,
    default_title_from_manifest,
    get_python_env_info,
    make_api_bundle,
    make_html_bundle,
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_quarto_source_bundle,
    read_manifest_app_mode,
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


def validate_file_is_notebook(file_name: str) -> None:
    """
    Validate that the given file is a Jupyter Notebook. If it isn't, an exception is
    thrown.  A file must exist and have the '.ipynb' extension.

    :param file_name: the name of the file to validate.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    file_suffix = splitext(file_name)[1].lower()
    if file_suffix != ".ipynb" or not exists(file_name):
        raise RSConnectException("A Jupyter notebook (.ipynb) file is required here.")


def validate_extra_files(directory: str | Path, extra_files: Sequence[str] | None) -> list[str]:
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


def validate_manifest_file(file_or_directory: str | Path) -> str:
    """
    Validates that the name given represents either an existing manifest.json file or
    a directory that contains one.  If not, an exception is raised.

    :param file_or_directory: the name of the manifest file or directory that contains it.
    :return: the real path to the manifest file.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    if isdir(file_or_directory):
        file_or_directory = join(file_or_directory, "manifest.json")
    if basename(file_or_directory) != "manifest.json" or not exists(file_or_directory):
        raise RSConnectException("A manifest.json file or a directory containing one is required here.")
    return str(file_or_directory)


def get_default_entrypoint(directory: str | Path) -> str:
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    return bundle.get_default_entrypoint(directory)


def validate_entry_point(entry_point: str | None, directory: str | Path) -> str:
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


def deploy_html(
    connect_server: Optional[api.RSConnectServer] = None,
    path: Optional[str] = None,
    entrypoint: Optional[str] = None,
    extra_files: Optional[Sequence[str]] = None,
    excludes: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
    env_vars: Optional[dict[str, str]] = None,
    verbose: bool = False,
    new: bool = False,
    app_id: Optional[str] = None,
    name: Optional[str] = None,
    server: Optional[str] = None,
    api_key: Optional[str] = None,
    insecure: bool = False,
    cacert: Optional[TextIO | BinaryIO] = None,
) -> None:
    kwargs = locals()
    ce = None
    if connect_server:
        kwargs = filter_out_server_info(**kwargs)
        ce = RSConnectExecutor.fromConnectServer(connect_server, **kwargs)
    else:
        ce = RSConnectExecutor(**kwargs)

    (
        ce.validate_server()
        .validate_app_mode(app_mode=AppModes.STATIC)
        .make_bundle(
            make_html_bundle,
            path,
            entrypoint,
            extra_files,
            excludes,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )


def deploy_jupyter_notebook(
    connect_server: api.TargetableServer,
    file_name: str,
    extra_files: Sequence[str],
    new: bool,
    app_id: int,
    title: str,
    static: bool,
    python: str,
    force_generate: bool,
    log_callback: Callable[[str], None],
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> None:
    """
    A function to deploy a Jupyter notebook to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param file_name: the Jupyter notebook file to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param new: a flag indicating a new deployment, previous default = False.
    :param app_id: the ID of an existing application to deploy new files for, previous default = None.
    :param title: an optional title for the deploy.  If this is not provided, one will
    be generated. Previous default = None.
    :param static: a flag noting whether the notebook should be deployed as a static
    HTML page or as a render-able document with sources. Previous default = False.
    :param python: the optional name of a Python executable, previous default = None.
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists. Previous default = False.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple. Previous default = None.
    :param hide_all_input: if True, will hide all input cells when rendering output.  Previous default = False.
    :param hide_tagged_input: If True, will hide input code cells with the 'hide_input' tag when rendering
    output. Previous default = False.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    kwargs = locals()
    kwargs["extra_files"] = extra_files = validate_extra_files(dirname(file_name), extra_files)
    app_mode = AppModes.JUPYTER_NOTEBOOK if not static else AppModes.STATIC

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
    else:
        raise RSConnectException("Unable to infer Connect client.")

    base_dir = dirname(file_name)
    _warn_on_ignored_manifest(base_dir)
    _warn_if_no_requirements_file(base_dir)
    _warn_if_environment_directory(base_dir)
    python, environment = get_python_env_info(file_name, python, force_generate)

    if force_generate:
        _warn_on_ignored_requirements(base_dir, environment.filename)

    ce = RSConnectExecutor(**kwargs)
    ce.validate_server().validate_app_mode(app_mode=app_mode)
    if app_mode == AppModes.STATIC:
        ce.make_bundle(
            make_notebook_html_bundle,
            file_name,
            python,
            hide_all_input,
            hide_tagged_input,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
    else:
        ce.make_bundle(
            make_notebook_source_bundle,
            file_name,
            environment,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
    ce.deploy_bundle().save_deployed_info().emit_task_log()


def deploy_app(
    name: Optional[str] = None,
    server: Optional[str] = None,
    api_key: Optional[str] = None,
    insecure: Optional[bool] = None,
    cacert: Optional[TextIO | BinaryIO] = None,
    ca_data: Optional[str] = None,
    entry_point: Optional[str] = None,
    excludes: Optional[Sequence[str]] = None,
    new: bool = False,
    app_id: Optional[str] = None,
    title: Optional[str] = None,
    python: Optional[str] = None,
    force_generate: bool = False,
    verbose: Optional[bool] = None,
    directory: Optional[str] = None,
    extra_files: Optional[Sequence[str]] = None,
    env_vars: Optional[dict[str, str]] = None,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
    account: Optional[str] = None,
    token: Optional[str] = None,
    secret: Optional[str] = None,
    app_mode: typing.Optional[AppMode] = None,
    connect_server: Optional[api.TargetableServer] = None,
    **kws: object
) -> None:
    kwargs = locals()
    kwargs["entry_point"] = entry_point = validate_entry_point(entry_point, directory)
    kwargs["extra_files"] = extra_files = validate_extra_files(directory, extra_files)

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
        directory,
        force_generate,
        python,
    )

    ce = RSConnectExecutor(**kwargs)
    (
        ce.validate_server()
        .validate_app_mode(app_mode=app_mode)
        .make_bundle(
            make_api_bundle,
            directory,
            entry_point,
            app_mode,
            environment,
            extra_files,
            excludes,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )


def deploy_python_api(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    force_generate: bool,
    log_callback: Callable[[str], None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.Tuple[str, typing.Union[list, None]]:
    """
    A function to deploy a Python WSGi API module to Connect.  Depending on the files involved
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
    return deploy_app(app_mode=AppModes.PYTHON_API, **locals())


def deploy_python_fastapi(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    conda_mode: bool,
    force_generate: bool,
    log_callback: Callable[[str], None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.Tuple[str, typing.Union[list, None]]:
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


def deploy_python_shiny(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool = False,
    app_id: Optional[int] = None,
    title: Optional[str] = None,
    python: Optional[str] = None,
    force_generate: bool = False,
    log_callback: Optional[Callable[[str], None]] = None,
):
    """
    A function to deploy a Python Shiny module to Posit Connect.  Depending on the files involved
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
        :param force_generate: force generating "requirements.txt" or "environment.yml",
        even if it already exists.
        :param log_callback: the callback to use to write the log to.  If this is None
        (the default) the lines from the deployment log will be returned as a sequence.
        If a log callback is provided, then None will be returned for the log lines part
        of the return tuple.
        :return: the ultimate URL where the deployed app may be accessed and the sequence
        of log lines.  The log lines value will be None if a log callback was provided.
    """
    return deploy_app(app_mode=AppModes.PYTHON_SHINY, **locals())


def deploy_dash_app(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    force_generate: bool,
    log_callback: Callable[[str], None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.Tuple[str, typing.Union[list, None]]:
    """
    A function to deploy a Python Dash app module to Connect.  Depending on the files involved
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
    return deploy_app(app_mode=AppModes.DASH_APP, **locals())


def deploy_streamlit_app(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    force_generate: bool,
    log_callback: Callable[[str], None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.Tuple[str, typing.Union[list, None]]:
    """
    A function to deploy a Python Streamlit app module to Connect.  Depending on the files involved
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
    return deploy_app(app_mode=AppModes.STREAMLIT_APP, **locals())


def deploy_bokeh_app(
    connect_server: api.TargetableServer,
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    new: bool,
    app_id: int,
    title: str,
    python: str,
    force_generate: bool,
    log_callback: Callable[[str], None],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.Tuple[str, typing.Union[list, None]]:
    """
    A function to deploy a Python Bokeh app module to Connect.  Depending on the files involved
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

    return deploy_app(app_mode=AppModes.BOKEH_APP, **locals())


def deploy_by_manifest(
    connect_server: api.TargetableServer,
    manifest_file_name: str,
    new: bool,
    app_id: int,
    title: str,
    log_callback: Callable[[str], None],
) -> None:
    """
    A function to deploy a Jupyter notebook to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param manifest_file_name: the manifest file to deploy.
    :param new: a flag to force this as a new deploy. Previous default = False.
    :param app_id: the ID of an existing application to deploy new files for. Previous default = None.
    :param title: an optional title for the deploy.  If this is not provided, one will
    be generated. Previous default = None.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple. Previous default = None.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    kwargs = locals()
    kwargs["manifest_file_name"] = manifest_file_name = validate_manifest_file(manifest_file_name)
    app_mode = read_manifest_app_mode(manifest_file_name)
    kwargs["title"] = title or default_title_from_manifest(manifest_file_name)

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
    else:
        raise RSConnectException("Unable to infer Connect client.")

    ce = RSConnectExecutor(**kwargs)
    (
        ce.validate_server()
        .validate_app_mode(app_mode=app_mode)
        .make_bundle(
            make_manifest_bundle,
            manifest_file_name,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )


def create_notebook_deployment_bundle(
    file_name: str,
    extra_files: list[str],
    app_mode: AppMode,
    python: str,
    environment: Environment,
    extra_files_need_validating: bool,
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.IO[bytes]:
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
    sure the names are properly qualified first. Previous default = True.
    :param hide_all_input: if True, will hide all input cells when rendering output. Previous default = False.
    :param hide_tagged_input: If True, will hide input code cells with
    the 'hide_input' tag when rendering output.  Previous default = False.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.

    :return: the bundle.
    """
    validate_file_is_notebook(file_name)

    if extra_files_need_validating:
        extra_files = validate_extra_files(dirname(file_name), extra_files)

    if app_mode == AppModes.STATIC:
        try:
            return make_notebook_html_bundle(
                file_name,
                python,
                hide_all_input,
                hide_tagged_input,
                image=image,
                env_management_py=env_management_py,
                env_management_r=env_management_r,
            )
        except subprocess.CalledProcessError as exc:
            # Jupyter rendering failures are often due to
            # user code failing, vs. an internal failure of rsconnect-python.
            raise RSConnectException(str(exc))
    else:
        return make_notebook_source_bundle(
            file_name,
            environment,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )


def create_api_deployment_bundle(
    directory: str,
    extra_files: list[str],
    excludes: list[str],
    entry_point: str,
    app_mode: AppMode,
    environment: Environment,
    extra_files_need_validating: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.IO[bytes]:
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
    are properly qualified first. Previous default = True.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the bundle.
    """
    entry_point = validate_entry_point(entry_point, directory)

    if extra_files_need_validating:
        extra_files = validate_extra_files(directory, extra_files)

    if app_mode is None:
        app_mode = AppModes.PYTHON_API

    return make_api_bundle(
        directory, entry_point, app_mode, environment, extra_files, excludes, image, env_management_py, env_management_r
    )


def create_quarto_deployment_bundle(
    file_or_directory: str,
    extra_files: list[str],
    excludes: list[str],
    app_mode: AppMode,
    inspect: QuartoInspectResult,
    environment: Environment,
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
