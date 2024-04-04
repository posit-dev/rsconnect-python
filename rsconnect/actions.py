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
from os.path import basename, exists
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
from .bundle import make_quarto_source_bundle, read_manifest_file
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
