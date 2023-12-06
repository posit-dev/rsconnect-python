import functools
import json
import os
import sys
import traceback
import typing
import textwrap
import click
from os.path import abspath, dirname, exists, isdir, join
from functools import wraps
from typing import Optional

from rsconnect.certificates import read_certificate_file

from .environment import EnvironmentException
from .exception import RSConnectException
from .actions import (
    cli_feedback,
    create_quarto_deployment_bundle,
    describe_manifest,
    quarto_inspect,
    set_verbosity,
    test_api_key,
    test_server,
    validate_quarto_engines,
    which_quarto,
    test_rstudio_server,
)
from .actions_content import (
    download_bundle,
    build_add_content,
    build_remove_content,
    build_list_content,
    build_history,
    build_start,
    search_content,
    get_content,
    emit_build_log,
)

from . import api, VERSION, validation
from .api import RSConnectExecutor, RSConnectServer, RSConnectClient, filter_out_server_info
from .bundle import (
    create_python_environment,
    default_title_from_manifest,
    is_environment_dir,
    make_manifest_bundle,
    make_html_bundle,
    make_api_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_voila_bundle,
    read_manifest_app_mode,
    write_notebook_manifest_json,
    write_api_manifest_json,
    write_environment_file,
    write_quarto_manifest_json,
    write_voila_manifest_json,
    validate_entry_point,
    validate_extra_files,
    validate_file_is_notebook,
    validate_manifest_file,
    fake_module_file_from_directory,
    get_python_env_info,
)
from .log import logger, LogOutputFormat, VERBOSE
from .metadata import ServerStore, AppStore
from .models import (
    AppMode,
    AppModes,
    BuildStatus,
    ContentGuidWithBundleParamType,
    StrippedStringParamType,
    VersionSearchFilterParamType,
)
from .json_web_token import (
    read_secret_key,
    validate_hs256_secret_key,
    TokenGenerator,
    produce_bootstrap_output,
    parse_client_response,
)
from .shiny_express import escape_to_var_name, is_express_app

server_store = ServerStore()
future_enabled = False


def cli_exception_handler(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        def failed(err):
            click.secho(str(err), fg="bright_red", err=False)
            sys.exit(1)

        try:
            result = func(*args, **kwargs)
        except RSConnectException as exc:
            failed("Error: " + exc.message)
        except EnvironmentException as exc:
            failed("Error: " + str(exc))
        except Exception as exc:
            if click.get_current_context("verbose"):
                traceback.print_exc()
            failed("Internal error: " + str(exc))
        finally:
            logger.set_in_feedback(False)
        return result

    return wrapper


def output_params(
    ctx: click.Context,
    vars,
):
    if click.__version__ >= "8.0.0" and sys.version_info >= (3, 7):
        logger.log(VERBOSE, "Detected the following inputs:")
        for k, v in vars:
            if k in {"ctx", "verbose", "kwargs"}:
                continue
            if v is not None:
                val = v
                if k in {"api_key", "api-key"}:
                    val = "**********"
                sourceName = validation.get_parameter_source_name_from_ctx(k, ctx)
                logger.log(VERBOSE, "    %-18s%s (from %s)", (k + ":"), val, sourceName)


def server_args(func):
    @click.option("--name", "-n", help="The nickname of the Posit Connect server to deploy to.")
    @click.option(
        "--server",
        "-s",
        envvar="CONNECT_SERVER",
        help="The URL for the Posit Connect server to deploy to. \
(Also settable via CONNECT_SERVER environment variable.)",
    )
    @click.option(
        "--api-key",
        "-k",
        envvar="CONNECT_API_KEY",
        help="The API key to use to authenticate with Posit Connect. \
(Also settable via CONNECT_API_KEY environment variable.)",
    )
    @click.option(
        "--insecure",
        "-i",
        envvar="CONNECT_INSECURE",
        is_flag=True,
        help="Disable TLS certification/host validation. (Also settable via CONNECT_INSECURE environment variable.)",
    )
    @click.option(
        "--cacert",
        "-c",
        envvar="CONNECT_CA_CERTIFICATE",
        type=click.Path(exists=True, file_okay=True, dir_okay=False),
        help="The path to trusted TLS CA certificates. (Also settable via \
CONNECT_CA_CERTIFICATE environment variable.)",
    )
    @click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def cloud_shinyapps_args(func):
    @click.option(
        "--account",
        "-A",
        envvar=["SHINYAPPS_ACCOUNT"],
        help="The shinyapps.io/Posit Cloud account name. (Also settable via \
SHINYAPPS_ACCOUNT environment variable.)",
    )
    @click.option(
        "--token",
        "-T",
        envvar=["SHINYAPPS_TOKEN", "RSCLOUD_TOKEN"],
        help="The shinyapps.io/Posit Cloud token. (Also settable via \
SHINYAPPS_TOKEN or RSCLOUD_TOKEN environment variables.)",
    )
    @click.option(
        "--secret",
        "-S",
        envvar=["SHINYAPPS_SECRET", "RSCLOUD_SECRET"],
        help="The shinyapps.io/Posit Cloud token secret. \
(Also settable via SHINYAPPS_SECRET or RSCLOUD_SECRET environment variables.)",
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def shinyapps_deploy_args(func):
    @click.option(
        "--visibility",
        "-V",
        type=click.Choice(["public", "private"]),
        help="The visibility of the resource being deployed. (shinyapps.io only; must be public (default) or private)",
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def _passthrough(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def validate_env_vars(ctx, param, all_values):
    vars = {}

    for s in all_values:
        if not isinstance(s, str):
            raise click.BadParameter("environment variable must be a string: '{}'".format(s))

        if "=" in s:
            name, value = s.split("=", 1)
            vars[name] = value
        else:
            # inherited value from the environment
            value = os.environ.get(s)
            if value is None:
                raise click.BadParameter("'{}' not found in the environment".format(s))
            vars[s] = value

    return vars


def content_args(func):
    @click.option(
        "--new",
        "-N",
        is_flag=True,
        help=(
            "Force a new deployment, even if there is saved metadata from a "
            "previous deployment. Cannot be used with --app-id."
        ),
    )
    @click.option(
        "--app-id",
        "-a",
        help="Existing app ID or GUID to replace. Cannot be used with --new.",
    )
    @click.option("--title", "-t", help="Title of the content (default is the same as the filename).")
    @click.option(
        "--environment",
        "-E",
        "env_vars",
        multiple=True,
        callback=validate_env_vars,
        help="Set an environment variable. Specify a value with NAME=VALUE, "
        "or just NAME to use the value from the local environment. "
        "May be specified multiple times. [v1.8.6+]",
    )
    @click.option(
        "--no-verify",
        is_flag=True,
        help="Don't access the deployed content to verify that it started correctly.",
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


# This callback handles the "shorthand" --disable-env-management option.
# If the shorthand flag is provided, then it takes precendence over the R and Python flags.
# This callback also inverts the --disable-env-management-r and
# --disable-env-management-py boolean flags if they are provided,
# otherwise returns None. This is so that we can pass the
# non-negative (env_management_r, env_management_py) args to our API functions,
# which is more consistent when writing these values to the manifest.
def env_management_callback(ctx, param, value) -> typing.Optional[bool]:
    # eval the shorthand flag if it was provided
    disable_env_management = ctx.params.get("disable_env_management")
    if disable_env_management is not None:
        value = disable_env_management

    # invert value if it is defined.
    if value is not None:
        return not value
    return value


def runtime_environment_args(func):
    @click.option(
        "--image",
        "-I",
        help="Target image to be used during content build and execution. "
        "This option is only applicable if the Connect server is configured to use off-host execution.",
    )
    @click.option(
        "--disable-env-management",
        is_flag=True,
        is_eager=True,
        default=None,
        help="Shorthand to disable environment management for both Python and R.",
    )
    @click.option(
        "--disable-env-management-py",
        "env_management_py",
        is_flag=True,
        default=None,
        help="Disable Python environment management for this bundle. "
        "Connect will not create an environment or install packages. An administrator must install the "
        "required packages in the correct Python environment on the Connect server.",
        callback=env_management_callback,
    )
    @click.option(
        "--disable-env-management-r",
        "env_management_r",
        is_flag=True,
        default=None,
        help="Disable R environment management for this bundle. "
        "Connect will not create an environment or install packages. An administrator must install the "
        "required packages in the correct R environment on the Connect server.",
        callback=env_management_callback,
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


@click.group(no_args_is_help=True)
@click.option("--future", "-u", is_flag=True, hidden=True, help="Enables future functionality.")
def cli(future):
    """
    This command line tool may be used to deploy various types of content to Posit
    Connect, Posit Cloud, and shinyapps.io.

    The tool supports the notion of a simple nickname that represents the
    information needed to interact with a deployment target.  Use the add, list and
    remove commands to manage these nicknames.

    The information about an instance of Posit Connect includes its URL, the
    API key needed to authenticate against that instance, a flag that notes whether
    TLS certificate/host verification should be disabled and a path to a trusted CA
    certificate file to use for TLS.  The last two items are only relevant if the
    URL specifies the "https" protocol.

    For Posit Cloud, the information needed to connect includes the auth token, auth
    secret, and server ('posit.cloud'). For shinyapps.io, the auth token, auth secret,
    server ('shinyapps.io'), and account are needed.
    """
    global future_enabled
    future_enabled = future


@cli.command(help="Show the version of the rsconnect-python package.")
def version():
    click.echo(VERSION)


def _test_server_and_api(server, api_key, insecure, ca_cert):
    """
    Test the specified server information to make sure it works.  If so, a
    ConnectServer object is returned with the potentially expanded URL.

    :param server: the server URL, which is allowed to be missing its scheme.
    :param api_key: an optional API key to validate.
    :param insecure: a flag noting whether TLS host/validation should be skipped.
    :param ca_cert: the name of a CA certs file containing certificates to use.
    :return: a tuple containing an appropriate ConnectServer object and the username
    of the user the API key represents (or None, if no key was provided).
    """
    ca_data = None
    if ca_cert:
        ca_data = read_certificate_file(ca_cert)
    me = None

    with cli_feedback("Checking %s" % server):
        real_server, _ = test_server(api.RSConnectServer(server, api_key, insecure, ca_data))

    real_server.api_key = api_key

    if api_key:
        with cli_feedback("Checking API key"):
            me = test_api_key(real_server)

    return real_server, me


def _test_rstudio_creds(server: api.PositServer):
    with cli_feedback("Checking {} credential".format(server.remote_name)):
        test_rstudio_server(server)


@cli.command(
    short_help="Create an initial admin user to bootstrap a Connect instance.",
    help="Creates an initial admin user to bootstrap a Connect instance. Returns the provisionend API key.",
    no_args_is_help=True,
)
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    required=True,
    help="The URL for the RStudio Connect server. (Also settable via CONNECT_SERVER environment variable.)",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation. (Also settable via CONNECT_INSECURE environment variable.)",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="The path to trusted TLS CA certificates. (Also settable via CONNECT_CA_CERTIFICATE environment variable.)",
)
@click.option(
    "--jwt-keypath",
    "-j",
    help="The path to the file containing the private key used to sign the JWT.",
)
@click.option("--raw", "-r", is_flag=True, help="Return the API key as raw output rather than a JSON object")
@click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
@cli_exception_handler
def bootstrap(
    server,
    insecure,
    cacert,
    jwt_keypath,
    raw,
    verbose,
):
    set_verbosity(verbose)
    if not server.startswith("http"):
        raise RSConnectException("Server URL expected to begin with transfer protocol (ex. http/https).")

    secret_key = read_secret_key(jwt_keypath)
    validate_hs256_secret_key(secret_key)

    token_generator = TokenGenerator(secret_key)

    bootstrap_token = token_generator.bootstrap()
    logger.debug("Generated JWT:\n" + bootstrap_token)

    logger.debug("Insecure: " + str(insecure))

    ca_data = None
    if cacert:
        ca_data = read_certificate_file(cacert)

    with cli_feedback("", stderr=True):
        connect_server = RSConnectServer(
            server, None, insecure=insecure, ca_data=ca_data, bootstrap_jwt=bootstrap_token
        )
        connect_client = RSConnectClient(connect_server)

        response = connect_client.bootstrap()

        # post-processing on response data
        status, json_data = parse_client_response(response)
        output = produce_bootstrap_output(status, json_data)
        if raw:
            click.echo(output["api_key"])
        else:
            json.dump(output, sys.stdout, indent=2)
            sys.stdout.write("\n")


# noinspection SpellCheckingInspection
@cli.command(
    short_help="Define a nickname for a Posit Connect, Posit Cloud, or shinyapps.io server and credential.",
    help=(
        "Associate a simple nickname with the information needed to interact with a deployment target. "
        "Specifying an existing nickname will cause its stored information to be replaced by what is given "
        "on the command line."
    ),
    no_args_is_help=True,
)
@click.option("--name", "-n", required=True, help="The nickname of the Posit Connect server to deploy to.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the Posit Connect server to deploy to, OR \
rstudio.cloud OR shinyapps.io. (Also settable via CONNECT_SERVER \
environment variable.)",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with Posit Connect. \
(Also settable via CONNECT_API_KEY environment variable.)",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation. (Also settable via CONNECT_INSECURE environment variable.)",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="The path to trusted TLS CA certificates. (Also settable via CONNECT_CA_CERTIFICATE environment variable.)",
)
@click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
@cloud_shinyapps_args
@click.pass_context
def add(ctx, name, server, api_key, insecure, cacert, account, token, secret, verbose):
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    validation.validate_connection_options(
        ctx=ctx,
        url=server,
        api_key=api_key,
        insecure=insecure,
        cacert=cacert,
        account_name=account,
        token=token,
        secret=secret,
    )

    old_server = server_store.get_by_name(name)

    if token:
        if server and ("rstudio.cloud" in server or "posit.cloud" in server):
            real_server = api.CloudServer(server, account, token, secret)
        else:
            real_server = api.ShinyappsServer(server, account, token, secret)

        _test_rstudio_creds(real_server)

        server_store.set(
            name,
            real_server.url,
            account_name=real_server.account_name,
            token=real_server.token,
            secret=real_server.secret,
        )
        if old_server:
            click.echo('Updated {} credential "{}".'.format(real_server.remote_name, name))
        else:
            click.echo('Added {} credential "{}".'.format(real_server.remote_name, name))
    else:
        # Server must be pingable and the API key must work to be added.
        real_server, _ = _test_server_and_api(server, api_key, insecure, cacert)

        server_store.set(
            name,
            real_server.url,
            real_server.api_key,
            real_server.insecure,
            real_server.ca_data,
        )

        if old_server:
            click.echo('Updated Connect server "%s" with URL %s' % (name, real_server.url))
        else:
            click.echo('Added Connect server "%s" with URL %s' % (name, real_server.url))


@cli.command(
    "list",
    short_help="List the known Posit Connect servers.",
    help="Show the stored information about each known server nickname.",
)
@click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
def list_servers(verbose):
    set_verbosity(verbose)
    with cli_feedback(""):
        servers = server_store.get_all_servers()

        click.echo("Server information from %s" % server_store.get_path())

        if not servers:
            click.echo("No servers are saved. To add a server, see `rsconnect add --help`.")
        else:
            click.echo()
            for server in servers:
                click.echo('Nickname: "%s"' % server["name"])
                click.echo("    URL: %s" % server["url"])
                if server.get("api_key"):
                    click.echo("    API key is saved")
                if server.get("insecure"):
                    click.echo("    Insecure mode (TLS host/certificate validation disabled)")
                if server.get("ca_cert"):
                    click.echo("    Client TLS certificate data provided")
                click.echo()


# noinspection SpellCheckingInspection
@cli.command(
    short_help="Show details about a Posit Connect server.",
    help=(
        "Show details about a Posit Connect server and installed Python information. "
        "Use this command to verify that a URL refers to a Posit Connect server, optionally, that an "
        "API key is valid for authentication for that server.  It may also be used to verify that the "
        "information stored as a nickname is still valid."
    ),
    no_args_is_help=True,
)
@server_args
@cli_exception_handler
@click.pass_context
def details(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    verbose: int,
):
    set_verbosity(verbose)

    ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert).validate_server()

    click.echo("    Posit Connect URL: %s" % ce.remote_server.url)

    if not ce.remote_server.api_key:
        return

    with cli_feedback("Gathering details"):
        server_details = ce.server_details

    connect_version = server_details["connect"]
    apis_allowed = server_details["python"]["api_enabled"]
    python_versions = server_details["python"]["versions"]

    click.echo("    Posit Connect version: %s" % ("<redacted>" if len(connect_version) == 0 else connect_version))

    if len(python_versions) == 0:
        click.echo("    No versions of Python are installed.")
    else:
        click.echo("    Installed versions of Python:")
        for python_version in python_versions:
            click.echo("        %s" % python_version)

    click.echo("    APIs: %sallowed" % ("" if apis_allowed else "not "))


@cli.command(
    short_help="Remove the information about a Posit Connect server.",
    help=(
        "Remove the information about a Posit Connect server by nickname or URL. "
        "One of --name or --server is required."
    ),
    no_args_is_help=True,
)
@click.option("--name", "-n", help="The nickname of the Posit Connect server to remove.")
@click.option("--server", "-s", help="The URL of the Posit Connect server to remove.")
@click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
@click.pass_context
def remove(ctx, name, server, verbose):
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    message = None

    with cli_feedback("Checking arguments"):
        if name and server:
            raise RSConnectException("You must specify only one of -n/--name or -s/--server.")

        if not (name or server):
            raise RSConnectException("You must specify one of -n/--name or -s/--server.")

        if name:
            if server_store.remove_by_name(name):
                message = 'Removed nickname "%s".' % name
            else:
                raise RSConnectException('Nickname "%s" was not found.' % name)
        else:  # the user specified -s/--server
            if server_store.remove_by_url(server):
                message = 'Removed URL "%s".' % server
            else:
                raise RSConnectException('URL "%s" was not found.' % server)

    if message:
        click.echo(message)


def _get_names_to_check(file_or_directory):
    """
    A function to determine a set files to look for in getting information about a
    deployment.

    :param file_or_directory: the file or directory to start with.
    :return: a sequence of file names to try.
    """
    result = [file_or_directory]

    if isdir(file_or_directory):
        result.append(fake_module_file_from_directory(file_or_directory))
        result.append(join(file_or_directory, "manifest.json"))

    return result


@cli.command(
    short_help="Show saved information about the specified deployment.",
    help=(
        "Display information about a deployment. For any given file, "
        "information about it"
        "s deployments are saved on a per-server basis."
    ),
    no_args_is_help=True,
)
@click.argument("file", type=click.Path(exists=True, dir_okay=True, file_okay=True))
def info(file):
    with cli_feedback(""):
        for file_name in _get_names_to_check(file):
            app_store = AppStore(file_name)
            deployments = app_store.get_all()

            if len(deployments) > 0:
                break

        if len(deployments) > 0:
            click.echo("Loaded deployment information from %s" % abspath(app_store.get_path()))

            for deployment in deployments:
                # If this deployment was via a manifest, this will get us extra stuff about that.
                file_name = deployment.get("filename")
                entry_point, primary_document = describe_manifest(file_name)
                label = "Directory:" if isdir(file_name) else "Filename: "
                click.echo()
                click.echo("Server URL: %s" % click.style(deployment.get("server_url")))
                click.echo("    App URL:     %s" % deployment.get("app_url"))
                click.echo("    App ID:      %s" % deployment.get("app_id"))
                click.echo("    App GUID:    %s" % deployment.get("app_guid"))
                click.echo('    Title:       "%s"' % deployment.get("title"))
                click.echo("    %s   %s" % (label, file_name))
                if entry_point:
                    click.echo("    Entry point: %s" % entry_point)
                if primary_document:
                    click.echo("    Primary doc: %s" % primary_document)
                click.echo("    Type:        %s" % AppModes.get_by_name(deployment.get("app_mode"), True).desc())
        else:
            click.echo("No saved deployment information was found for %s." % file)


@cli.group(no_args_is_help=True, help="Deploy content to Posit Connect, Posit Cloud, or shinyapps.io.")
def deploy():
    pass


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
            "    Warning: Capturing the environment using 'pip freeze --disable-pip-version-check'.\n"
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
            "             Python libraries and binaries will be excluded from the deployment.",
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


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="notebook",
    short_help="Deploy Jupyter notebook to Posit Connect [v1.7.0+].",
    help=(
        "Deploy a Jupyter notebook to Posit Connect. This may be done by source or as a static HTML "
        "page. If the notebook is deployed as a static HTML page (--static), it cannot be scheduled or "
        "rerun on the Connect server."
    ),
    no_args_is_help=True,
)
@server_args
@content_args
@runtime_environment_args
@click.option(
    "--static",
    "-S",
    is_flag=True,
    help=(
        "Render the notebook locally and deploy the result as a static "
        "document. Will not include the notebook source. Static notebooks "
        "cannot be re-run on the server."
    ),
)
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help=(
        "Path to Python interpreter whose environment should be used. "
        "The Python environment must have the rsconnect package installed."
    ),
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.option("--hide-all-input", is_flag=True, default=False, help="Hide all input cells when rendering output")
@click.option(
    "--hide-tagged-input", is_flag=True, default=False, help="Hide input code cells with the 'hide_input' tag"
)
@click.argument("file", type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
@click.pass_context
def deploy_notebook(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    static: bool,
    new: bool,
    app_id: str,
    title: str,
    python,
    force_generate,
    verbose: int,
    file: str,
    extra_files,
    hide_all_input: bool,
    hide_tagged_input: bool,
    env_vars: typing.Dict[str, str],
    image: str,
    disable_env_management: bool,
    env_management_py: bool,
    env_management_r: bool,
    no_verify: bool = False,
):
    kwargs = locals()
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    kwargs["extra_files"] = extra_files = validate_extra_files(dirname(file), extra_files)
    app_mode = AppModes.JUPYTER_NOTEBOOK if not static else AppModes.STATIC

    base_dir = dirname(file)
    _warn_on_ignored_manifest(base_dir)
    _warn_if_no_requirements_file(base_dir)
    _warn_if_environment_directory(base_dir)
    python, environment = get_python_env_info(file, python, force_generate)

    if force_generate:
        _warn_on_ignored_requirements(base_dir, environment.filename)

    ce = RSConnectExecutor(**kwargs)
    ce.validate_server().validate_app_mode(app_mode=app_mode)
    if app_mode == AppModes.STATIC:
        ce.make_bundle(
            make_notebook_html_bundle,
            file,
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
            file,
            environment,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
    ce.deploy_bundle().save_deployed_info().emit_task_log()
    if not no_verify:
        ce.verify_deployment()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="voila",
    short_help="Deploy Jupyter notebook in Voila mode to Posit Connect [v2023.03.0+].",
    help=("Deploy a Jupyter notebook in Voila mode to Posit Connect."),
    no_args_is_help=True,
)
@server_args
@content_args
@runtime_environment_args
@click.option(
    "--entrypoint",
    "-e",
    help=("The module and executable object which serves as the entry point."),
)
@click.option(
    "--multi-notebook",
    "-m",
    is_flag=True,
    help=("Deploy in multi-notebook mode."),
)
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
        "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
        "This option may be repeated."
    ),
)
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help=(
        "Path to Python interpreter whose environment should be used. "
        "The Python environment must have the rsconnect package installed."
    ),
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.argument("path", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
@click.pass_context
def deploy_voila(
    ctx: click.Context,
    path: str = None,
    entrypoint: str = None,
    python=None,
    force_generate=False,
    extra_files=None,
    exclude=None,
    image: str = "",
    disable_env_management: bool = None,
    env_management_py: bool = None,
    env_management_r: bool = None,
    title: str = None,
    env_vars: typing.Dict[str, str] = None,
    verbose: int = 0,
    new: bool = False,
    app_id: str = None,
    name: str = None,
    server: str = None,
    api_key: str = None,
    insecure: bool = False,
    cacert: str = None,
    connect_server: api.RSConnectServer = None,
    multi_notebook: bool = False,
    no_verify: bool = False,
):
    kwargs = locals()
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    app_mode = AppModes.JUPYTER_VOILA
    environment = create_python_environment(
        path if isdir(path) else dirname(path),
        force_generate,
        python,
    )
    ce = RSConnectExecutor(**kwargs).validate_server().validate_app_mode(app_mode=app_mode)
    ce.make_bundle(
        make_voila_bundle,
        path,
        entrypoint,
        extra_files,
        exclude,
        force_generate,
        environment,
        image=image,
        env_management_py=env_management_py,
        env_management_r=env_management_r,
        multi_notebook=multi_notebook,
    ).deploy_bundle().save_deployed_info().emit_task_log()
    if not no_verify:
        ce.verify_deployment()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="manifest",
    short_help="Deploy content to Posit Connect, Posit Cloud, or shinyapps.io by manifest.",
    help=(
        "Deploy content to Posit Connect, Posit Cloud, or shinyapps.io using an existing manifest.json "
        'file.  The specified file must either be named "manifest.json" or '
        'refer to a directory that contains a file named "manifest.json".'
    ),
    no_args_is_help=True,
)
@server_args
@content_args
@cloud_shinyapps_args
@click.argument("file", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@shinyapps_deploy_args
@cli_exception_handler
@click.pass_context
def deploy_manifest(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    account: str,
    token: str,
    secret: str,
    new: bool,
    app_id: str,
    title: str,
    verbose: int,
    file: str,
    env_vars: typing.Dict[str, str],
    visibility: typing.Optional[str],
    no_verify: bool = False,
):
    kwargs = locals()
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    file_name = kwargs["file"] = validate_manifest_file(file)
    app_mode = read_manifest_app_mode(file_name)
    kwargs["title"] = title or default_title_from_manifest(file)

    ce = RSConnectExecutor(**kwargs)
    (
        ce.validate_server()
        .validate_app_mode(app_mode=app_mode)
        .make_bundle(
            make_manifest_bundle,
            file_name,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )
    if not no_verify:
        ce.verify_deployment()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="quarto",
    short_help="Deploy Quarto content to Posit Connect [v2021.08.0+] or Posit Cloud.",
    help=(
        "Deploy a Quarto document or project to Posit Connect or Posit Cloud. Should the content use the Quarto "
        'Jupyter engine, an environment file ("requirements.txt") is created and included in the deployment if one '
        "does not already exist. Requires Posit Connect 2021.08.0 or later."
        "\n\n"
        "FILE_OR_DIRECTORY is the path to a single-file Quarto document or the directory containing a Quarto project."
    ),
    no_args_is_help=True,
)
@server_args
@content_args
@runtime_environment_args
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
        "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
        "This option may be repeated."
    ),
)
@click.option(
    "--quarto",
    "-q",
    type=click.Path(exists=True),
    help="Path to Quarto installation.",
)
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help=(
        "Path to Python interpreter whose environment should be used. "
        "The Python environment must have the rsconnect package installed."
    ),
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.argument("file_or_directory", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
@click.pass_context
def deploy_quarto(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    new: bool,
    app_id: str,
    title: str,
    exclude,
    quarto,
    python,
    force_generate: bool,
    verbose: int,
    file_or_directory,
    extra_files,
    env_vars: typing.Dict[str, str],
    image: str,
    disable_env_management: bool,
    env_management_py: bool,
    env_management_r: bool,
    no_verify: bool = False,
):
    kwargs = locals()
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = dirname(file_or_directory)
    module_file = fake_module_file_from_directory(file_or_directory)
    extra_files = validate_extra_files(base_dir, extra_files)

    _warn_on_ignored_manifest(base_dir)

    with cli_feedback("Inspecting Quarto project"):
        quarto = which_quarto(quarto)
        logger.debug("Quarto: %s" % quarto)
        inspect = quarto_inspect(quarto, file_or_directory)
        engines = validate_quarto_engines(inspect)

    python = None
    environment = None
    if "jupyter" in engines:
        _warn_if_no_requirements_file(base_dir)
        _warn_if_environment_directory(base_dir)

        with cli_feedback("Inspecting Python environment"):
            python, environment = get_python_env_info(module_file, python, force_generate)

            if force_generate:
                _warn_on_ignored_requirements(base_dir, environment.filename)

    ce = RSConnectExecutor(**kwargs)
    (
        ce.validate_server()
        .validate_app_mode(app_mode=AppModes.STATIC_QUARTO)
        .make_bundle(
            create_quarto_deployment_bundle,
            file_or_directory,
            extra_files,
            exclude,
            AppModes.STATIC_QUARTO,
            inspect,
            environment,
            image=image,
            env_management_py=env_management_py,
            env_management_r=env_management_r,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )
    if not no_verify:
        ce.verify_deployment()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="html",
    short_help="Deploy html content to Posit Connect or Posit Cloud.",
    help=("Deploy an html file, or directory of html files with entrypoint, to Posit Connect or Posit Cloud."),
    no_args_is_help=True,
)
@server_args
@content_args
@cloud_shinyapps_args
@click.option(
    "--entrypoint",
    "-e",
    help=("The name of the html file that is the landing page."),
)
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
        "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
        "This option may be repeated."
    ),
)
@click.argument("path", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
@click.pass_context
def deploy_html(
    ctx: click.Context,
    connect_server: api.RSConnectServer = None,
    path: str = None,
    entrypoint: str = None,
    extra_files=None,
    exclude=None,
    title: str = None,
    env_vars: typing.Dict[str, str] = None,
    verbose: int = 0,
    new: bool = False,
    app_id: str = None,
    name: str = None,
    server: str = None,
    api_key: str = None,
    insecure: bool = False,
    cacert: str = None,
    account: str = None,
    token: str = None,
    secret: str = None,
    no_verify: bool = False,
):
    kwargs = locals()
    set_verbosity(verbose)
    output_params(ctx, locals().items())

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
            exclude,
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )
    if not no_verify:
        ce.verify_deployment()


def generate_deploy_python(app_mode: AppMode, alias: str, min_version: str, desc: Optional[str] = None):
    if desc is None:
        desc = app_mode.desc()

    # noinspection SpellCheckingInspection
    @deploy.command(
        name=alias,
        short_help="Deploy a {desc} to Posit Connect [v{version}+], Posit Cloud, or shinyapps.io.".format(
            desc=desc,
            version=min_version,
        ),
        help=(
            "Deploy a {desc} module to Posit Connect, Posit Cloud, or shinyapps.io (if supported by the platform). "
            'The "directory" argument must refer to an existing directory that contains the application code.'
        ).format(desc=desc),
        no_args_is_help=True,
    )
    @server_args
    @content_args
    @cloud_shinyapps_args
    @runtime_environment_args
    @click.option(
        "--entrypoint",
        "-e",
        help=(
            "The module and executable object which serves as the entry point for the {desc} (defaults to app)"
        ).format(desc=desc),
    )
    @click.option(
        "--exclude",
        "-x",
        multiple=True,
        help=(
            "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
            "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
            "This option may be repeated."
        ),
    )
    @click.option(
        "--python",
        "-p",
        type=click.Path(exists=True),
        help=(
            "Path to Python interpreter whose environment should be used. "
            "The Python environment must have the rsconnect package installed."
        ),
    )
    @click.option(
        "--force-generate",
        "-g",
        is_flag=True,
        help='Force generating "requirements.txt", even if it already exists.',
    )
    @click.argument("directory", type=click.Path(exists=True, dir_okay=True, file_okay=False))
    @click.argument(
        "extra_files",
        nargs=-1,
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
    )
    @shinyapps_deploy_args
    @cli_exception_handler
    @click.pass_context
    def deploy_app(
        ctx: click.Context,
        name: str,
        server: str,
        api_key: str,
        insecure: bool,
        cacert: str,
        entrypoint,
        exclude,
        new: bool,
        app_id: str,
        title: str,
        python,
        force_generate: bool,
        verbose: int,
        directory,
        extra_files,
        visibility: typing.Optional[str],
        env_vars: typing.Dict[str, str],
        image: str,
        disable_env_management: bool,
        env_management_py: bool,
        env_management_r: bool,
        account: str = None,
        token: str = None,
        secret: str = None,
        no_verify: bool = False,
    ):
        set_verbosity(verbose)
        entrypoint = validate_entry_point(entrypoint, directory)
        extra_files = validate_extra_files(directory, extra_files)
        environment = create_python_environment(
            directory,
            force_generate,
            python,
        )

        if is_express_app(entrypoint + ".py", directory):
            entrypoint = "shiny.express.app:" + escape_to_var_name(entrypoint + ".py")

        extra_args = dict(
            directory=directory,
            server=server,
            exclude=exclude,
            new=new,
            app_id=app_id,
            title=title,
            visibility=visibility,
            disable_env_management=disable_env_management,
            env_vars=env_vars,
        )

        ce = RSConnectExecutor(
            ctx=ctx,
            name=name,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
            account=account,
            token=token,
            secret=secret,
            **extra_args,
        )

        (
            ce.validate_server()
            .validate_app_mode(app_mode=app_mode)
            .make_bundle(
                make_api_bundle,
                directory,
                entrypoint,
                app_mode,
                environment,
                extra_files,
                exclude,
                image=image,
                env_management_py=env_management_py,
                env_management_r=env_management_r,
            )
            .deploy_bundle()
            .save_deployed_info()
            .emit_task_log()
        )
        if not no_verify:
            ce.verify_deployment()

    return deploy_app


generate_deploy_python(app_mode=AppModes.PYTHON_API, alias="api", min_version="1.8.2")
generate_deploy_python(app_mode=AppModes.PYTHON_API, alias="flask", min_version="1.8.2", desc="Flask API")
generate_deploy_python(app_mode=AppModes.PYTHON_FASTAPI, alias="fastapi", min_version="2021.08.0")
generate_deploy_python(app_mode=AppModes.DASH_APP, alias="dash", min_version="1.8.2")
generate_deploy_python(app_mode=AppModes.STREAMLIT_APP, alias="streamlit", min_version="1.8.4")
generate_deploy_python(app_mode=AppModes.BOKEH_APP, alias="bokeh", min_version="1.8.4")
generate_deploy_python(app_mode=AppModes.PYTHON_SHINY, alias="shiny", min_version="2022.07.0")


@deploy.command(
    name="other-content",
    short_help="Describe deploying other content to Posit Connect.",
    help="Show help on how to deploy other content to Posit Connect.",
    no_args_is_help=True,
)
def deploy_help():
    text = (
        "To deploy a Shiny application or R Markdown document, use the rsconnect "
        "R package in the RStudio IDE.  Or, use rsconnect::writeManifest "
        "(again in the IDE) to create a manifest.json file and deploy that using "
        "this tool with the command, "
    )
    click.echo("\n".join(textwrap.wrap(text, 79)))
    click.echo()
    click.echo("    rsconnect deploy manifest [-n <name>|-s <url> -k <key>] <manifest-file>")
    click.echo()


@cli.group(
    name="write-manifest",
    no_args_is_help=True,
    short_help="Create a manifest.json file for later deployment.",
    help=(
        "Create a manifest.json file for later deployment. This may be used "
        "with the git support provided by Posit Connect or by using the "
        '"deploy manifest" command in this tool.'
    ),
)
def write_manifest():
    pass


@write_manifest.command(
    name="notebook",
    short_help="Create a manifest.json file for a Jupyter notebook.",
    help=(
        "Create a manifest.json file for a Jupyter notebook for later deployment. "
        'This will create an environment file ("requirements.txt") if one does '
        "not exist. All files are created in the same directory as the notebook file."
    ),
)
@click.option("--overwrite", "-o", is_flag=True, help="Overwrite manifest.json, if it exists.")
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help="Path to Python interpreter whose environment should be used. "
    + "The Python environment must have the rsconnect package installed.",
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.option("--hide-all-input", is_flag=True, default=None, help="Hide all input cells when rendering output")
@click.option("--hide-tagged-input", is_flag=True, default=None, help="Hide input code cells with the 'hide_input' tag")
@click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@runtime_environment_args
@click.pass_context
def write_manifest_notebook(
    ctx,
    overwrite,
    python,
    force_generate,
    verbose,
    file,
    extra_files,
    image,
    disable_env_management,
    env_management_py,
    env_management_r,
    hide_all_input=None,
    hide_tagged_input=None,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("Checking arguments"):
        validate_file_is_notebook(file)

        base_dir = dirname(file)
        manifest_path = join(base_dir, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        python, environment = get_python_env_info(file, python, force_generate)

    with cli_feedback("Creating manifest.json"):
        environment_file_exists = write_notebook_manifest_json(
            file,
            environment,
            AppModes.JUPYTER_NOTEBOOK,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image,
            env_management_py,
            env_management_r,
        )

    if environment_file_exists and not force_generate:
        click.secho(
            "    Warning: %s already exists and will not be overwritten." % environment.filename,
            fg="yellow",
        )
    else:
        with cli_feedback("Creating %s" % environment.filename):
            write_environment_file(environment, base_dir)


@write_manifest.command(
    name="voila",
    short_help="Create a manifest.json file for a Voila notebook.",
    help=(
        "Create a manifest.json file for a Voila notebook for later deployment. "
        'This will create an environment file ("requirements.txt") if one does '
        "not exist. All files are created in the same directory as the notebook file."
    ),
)
@click.option("--overwrite", "-o", is_flag=True, help="Overwrite manifest.json, if it exists.")
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help="Path to Python interpreter whose environment should be used. "
    + "The Python environment must have the rsconnect package installed.",
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
@click.argument("path", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@click.option("--entrypoint", "-e", help=("The module and executable object which serves as the entry point."))
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
        "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
        "This option may be repeated."
    ),
)
@click.option(
    "--multi-notebook",
    "-m",
    is_flag=True,
    help=("Set the manifest for multi-notebook mode."),
)
@runtime_environment_args
@click.pass_context
def write_manifest_voila(
    ctx: click.Context,
    path: str,
    entrypoint: str,
    overwrite,
    python,
    force_generate,
    verbose,
    extra_files,
    exclude,
    image,
    disable_env_management,
    env_management_py,
    env_management_r,
    multi_notebook,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("Checking arguments"):
        base_dir = dirname(path)
        manifest_path = join(base_dir, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        python, environment = get_python_env_info(path, python, force_generate)

    environment_file_exists = exists(join(base_dir, environment.filename))

    if environment_file_exists and not force_generate:
        click.secho(
            "    Warning: %s already exists and will not be overwritten." % environment.filename,
            fg="yellow",
        )
    else:
        with cli_feedback("Creating %s" % environment.filename):
            write_environment_file(environment, base_dir)

    with cli_feedback("Creating manifest.json"):
        write_voila_manifest_json(
            path,
            entrypoint,
            environment,
            AppModes.JUPYTER_VOILA,
            extra_files,
            exclude,
            force_generate,
            image,
            env_management_py,
            env_management_r,
            multi_notebook,
        )


@write_manifest.command(
    name="quarto",
    short_help="Create a manifest.json file for Quarto content.",
    help=(
        "Create a manifest.json file for a Quarto document or project for later "
        "deployment. Should the content use the Quarto Jupyter engine, "
        'an environment file ("requirements.txt") is created if one does '
        "not already exist. All files are created in the same directory "
        "as the project. Requires Posit Connect 2021.08.0 or later."
        "\n\n"
        "FILE_OR_DIRECTORY is the path to a single-file Quarto document or the directory containing a Quarto project."
    ),
)
@click.option("--overwrite", "-o", is_flag=True, help="Overwrite manifest.json, if it exists.")
@click.option(
    "--exclude",
    "-x",
    multiple=True,
    help=(
        "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
        "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
        "This option may be repeated."
    ),
)
@click.option(
    "--quarto",
    "-q",
    type=click.Path(exists=True),
    help="Path to Quarto installation.",
)
@click.option(
    "--python",
    "-p",
    type=click.Path(exists=True),
    help="Path to Python interpreter whose environment should be used. "
    + "The Python environment must have the rsconnect package installed.",
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
@click.argument("file_or_directory", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@runtime_environment_args
@click.pass_context
def write_manifest_quarto(
    ctx,
    overwrite,
    exclude,
    quarto,
    python,
    force_generate,
    verbose,
    file_or_directory,
    extra_files,
    image,
    disable_env_management,
    env_management_py,
    env_management_r,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = dirname(file_or_directory)

    with cli_feedback("Checking arguments"):
        manifest_path = join(base_dir, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Quarto project"):
        quarto = which_quarto(quarto)
        logger.debug("Quarto: %s" % quarto)
        inspect = quarto_inspect(quarto, file_or_directory)
        engines = validate_quarto_engines(inspect)

    environment = None
    if "jupyter" in engines:
        with cli_feedback("Inspecting Python environment"):
            python, environment = get_python_env_info(base_dir, python, force_generate)

        environment_file_exists = exists(join(base_dir, environment.filename))
        if environment_file_exists and not force_generate:
            click.secho(
                "    Warning: %s already exists and will not be overwritten." % environment.filename,
                fg="yellow",
            )
        else:
            with cli_feedback("Creating %s" % environment.filename):
                write_environment_file(environment, base_dir)

    with cli_feedback("Creating manifest.json"):
        write_quarto_manifest_json(
            file_or_directory,
            inspect,
            AppModes.STATIC_QUARTO,
            environment,
            extra_files,
            exclude,
            image,
            env_management_py,
            env_management_r,
        )


def generate_write_manifest_python(app_mode, alias, desc: Optional[str] = None):
    if desc is None:
        desc = app_mode.desc()

    # noinspection SpellCheckingInspection
    @write_manifest.command(
        name=alias,
        short_help="Create a manifest.json file for a {desc}.".format(desc=desc),
        help=(
            "Create a manifest.json file for a {desc} for later deployment. This will create an "
            'environment file ("requirements.txt") if one does not exist. All files '
            "are created in the same directory as the API code."
        ).format(desc=desc),
    )
    @click.option("--overwrite", "-o", is_flag=True, help="Overwrite manifest.json, if it exists.")
    @click.option(
        "--entrypoint",
        "-e",
        help=(
            "The module and executable object which serves as the entry point for the {desc} (defaults to app)"
        ).format(desc=desc),
    )
    @click.option(
        "--exclude",
        "-x",
        multiple=True,
        help=(
            "Specify a glob pattern for ignoring files when building the bundle. Note that your shell may try "
            "to expand this which will not do what you expect. Generally, it's safest to quote the pattern. "
            "This option may be repeated."
        ),
    )
    @click.option(
        "--python",
        "-p",
        type=click.Path(exists=True),
        help="Path to Python interpreter whose environment should be used. "
        + "The Python environment must have the rsconnect-python package installed.",
    )
    @click.option(
        "--force-generate",
        "-g",
        is_flag=True,
        help='Force generating "requirements.txt", even if it already exists.',
    )
    @click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
    @click.argument("directory", type=click.Path(exists=True, dir_okay=True, file_okay=False))
    @click.argument(
        "extra_files",
        nargs=-1,
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
    )
    @runtime_environment_args
    @click.pass_context
    def manifest_writer(
        ctx,
        overwrite,
        entrypoint,
        exclude,
        python,
        force_generate,
        verbose,
        directory,
        extra_files,
        image,
        disable_env_management,
        env_management_py,
        env_management_r,
    ):
        _write_framework_manifest(
            ctx,
            overwrite,
            entrypoint,
            exclude,
            python,
            force_generate,
            verbose,
            directory,
            extra_files,
            app_mode,
            image,
            env_management_py,
            env_management_r,
        )

    return manifest_writer


generate_write_manifest_python(AppModes.BOKEH_APP, alias="bokeh")
generate_write_manifest_python(AppModes.DASH_APP, alias="dash")
generate_write_manifest_python(AppModes.PYTHON_API, alias="api")
generate_write_manifest_python(AppModes.PYTHON_API, alias="flask", desc="Flask API")
generate_write_manifest_python(AppModes.PYTHON_FASTAPI, alias="fastapi")
generate_write_manifest_python(AppModes.PYTHON_SHINY, alias="shiny")
generate_write_manifest_python(AppModes.STREAMLIT_APP, alias="streamlit")


# noinspection SpellCheckingInspection
def _write_framework_manifest(
    ctx,
    overwrite,
    entrypoint,
    exclude,
    python,
    force_generate,
    verbose,
    directory,
    extra_files,
    app_mode,
    image,
    env_management_py,
    env_management_r,
):
    """
    A common function for writing manifests for APIs as well as Dash, Streamlit, and Bokeh apps.

    :param overwrite: overwrite the manifest.json, if it exists.
    :param entrypoint: the entry point for the thing being deployed.
    :param exclude: a sequence of exclude glob patterns to exclude files from
                    the deploy.
    :param python: a path to the Python executable to use.
    :param force_generate: a flag to force the generation of manifest and
                           requirements file.
    :param verbose: a flag to produce more (debugging) output.
    :param directory: the directory of the thing to deploy.
    :param extra_files: any extra files that should be included.
    :param app_mode: the app mode to use.
    :param image: an optional docker image for off-host execution.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    """
    set_verbosity(verbose)
    output_params(ctx, locals().items())

    with cli_feedback("Checking arguments"):
        entrypoint = validate_entry_point(entrypoint, directory)
        manifest_path = join(directory, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        _, environment = get_python_env_info(directory, python, force_generate)

    with cli_feedback("Creating manifest.json"):
        environment_file_exists = write_api_manifest_json(
            directory,
            entrypoint,
            environment,
            app_mode,
            extra_files,
            exclude,
            image,
            env_management_py,
            env_management_r,
        )

    if environment_file_exists and not force_generate:
        click.secho(
            "    Warning: %s already exists and will not be overwritten." % environment.filename,
            fg="yellow",
        )
    else:
        with cli_feedback("Creating %s" % environment.filename):
            write_environment_file(environment, directory)


def _validate_build_rm_args(guid, all, purge):
    if guid and all:
        raise RSConnectException("You must specify only one of -g/--guid or --all, not both.")
    if not guid and not all:
        raise RSConnectException("You must specify one of -g/--guid or --all.")


@cli.group(no_args_is_help=True, help="Interact with Posit Connect's content API.")
def content():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="search",
    short_help="Search for content on Posit Connect.",
)
@server_args
@click.option(
    "--published",
    is_flag=True,
    help="Search only published content.",
)
@click.option(
    "--unpublished",
    is_flag=True,
    help="Search only unpublished content.",
)
@click.option(
    "--content-type",
    type=click.Choice(list(map(str, AppModes._modes))),
    multiple=True,
    help="Filter content results by content type.",
)
@click.option(
    "--r-version",
    type=VersionSearchFilterParamType("r_version"),
    help="Filter content results by R version.",
)
@click.option(
    "--py-version",
    type=VersionSearchFilterParamType("py_version"),
    help="Filter content results by Python version.",
)
@click.option(
    "--title-contains",
    help="Filter content results by title.",
)
@click.option(
    "--order-by",
    type=click.Choice(["created", "last_deployed"]),
    help="Order content results.",
)
# todo: --format option (json, text)
@cli_exception_handler
@click.pass_context
def content_search(
    ctx: click.Context,
    name,
    server,
    api_key,
    insecure,
    cacert,
    published,
    unpublished,
    content_type,
    r_version,
    py_version,
    title_contains,
    order_by,
    verbose,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = search_content(
            ce.remote_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by
        )
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="describe",
    short_help="Describe a content item on Posit Connect.",
)
@server_args
@click.option(
    "--guid",
    "-g",
    multiple=True,
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The GUID of a content item to describe. This flag can be passed multiple times.",
)
# todo: --format option (json, text)
@click.pass_context
def content_describe(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = get_content(ce.remote_server, guid)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="download-bundle",
    short_help="Download a content item's source bundle.",
)
@server_args
@click.option(
    "--guid",
    "-g",
    required=True,
    type=ContentGuidWithBundleParamType(),
    metavar="GUID[,BUNDLE_ID]",
    help="The GUID of a content item to download.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    required=True,
    help="Defines the output location for the download.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Overwrite the output file if it already exists.",
)
@click.pass_context
def content_bundle_download(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    output: str,
    overwrite: bool,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        if exists(output) and not overwrite:
            raise RSConnectException("The output file already exists: %s" % output)

        result = download_bundle(ce.remote_server, guid)
        with open(output, "wb") as f:
            f.write(result.response_body)


@content.group(no_args_is_help=True, help="Build content on Posit Connect. Requires Connect >= 2021.11.1")
def build():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="add", short_help="Mark a content item for build. Use `build run` to invoke the build on the Connect server."
)
@server_args
@click.option(
    "--guid",
    "-g",
    required=True,
    type=ContentGuidWithBundleParamType(),
    multiple=True,
    metavar="GUID[,BUNDLE_ID]",
    help="Add a content item by its guid. This flag can be passed multiple times.",
)
@click.pass_context
def add_content_build(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        build_add_content(ce.remote_server, guid)
        if len(guid) == 1:
            logger.info('Added "%s".' % guid[0])
        else:
            logger.info("Bulk added %d content items." % len(guid))


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="rm",
    short_help="Remove a content item from the list of content that are tracked for build. "
    + "Use `build ls` to view the tracked content.",
)
@server_args
@click.option(
    "--guid",
    "-g",
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="Remove a content item by guid.",
)
@click.option(
    "--all",
    is_flag=True,
    # TODO: Ask for confirmation?
    help="Remove all content items from the list of content tracked for build.",
)
@click.option(
    "--purge",
    "-p",
    is_flag=True,
    help="Remove build history and log files from the local filesystem.",
)
@click.pass_context
def remove_content_build(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    all: bool,
    purge: bool,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        _validate_build_rm_args(guid, all, purge)
        guids = build_remove_content(ce.remote_server, guid, all, purge)
        if len(guids) == 1:
            logger.info('Removed "%s".' % guids[0])
        else:
            logger.info("Removed %d content items." % len(guids))


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="ls", short_help="List the content items that are being tracked for build on a given Connect server."
)
@server_args
@click.option(
    "--status",
    type=click.Choice(BuildStatus._all),
    help="Filter results by status of the build operation.",
)
@click.option(
    "--guid",
    "-g",
    multiple=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="Check the local build state of a specific content item. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", count=True, help="Enable verbose output. Use -vv for very verbose (debug) output.")
# todo: --format option (json, text)
@click.pass_context
def list_content_build(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    status: str,
    guid: str,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = build_list_content(ce.remote_server, guid, status)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(name="history", short_help="Get the build history for a content item.")
@server_args
@click.option(
    "--guid",
    "-g",
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The guid of the content item.",
)
# todo: --format option (json, text)
@click.pass_context
def get_build_history(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert)
        ce.validate_server()
        result = build_history(ce.remote_server, guid)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="logs",
    short_help="Print the logs for a content build.",
)
@server_args
@click.option(
    "--guid",
    "-g",
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The guid of the content item.",
)
@click.option(
    "--task-id",
    "-t",
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The task ID of the build.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(LogOutputFormat._all),
    default=LogOutputFormat.DEFAULT,
    help="The output format of the logs. Defaults to text.",
)
@click.pass_context
def get_build_logs(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    guid: str,
    task_id: str,
    format: str,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        for line in emit_build_log(ce.remote_server, guid, format, task_id):
            sys.stdout.write(line)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="run",
    short_help="Start building content on a given Connect server.",
)
@server_args
@click.option(
    "--parallelism",
    type=click.IntRange(min=1, clamp=True),
    default=1,
    help="Defines the number of builds that can run concurrently. Defaults to 1.",
)
@click.option("--aborted", is_flag=True, hidden=True, help="Build content that is in the ABORTED state.")
@click.option("--error", is_flag=True, hidden=True, help="Build content that is in the ERROR state.")
@click.option("--running", is_flag=True, hidden=True, help="Build content that is in the RUNNING state.")
@click.option(
    "--retry",
    is_flag=True,
    help="Build all content that is in the NEEDS_BUILD, ABORTED, ERROR, or RUNNING state.",
)
@click.option("--all", is_flag=True, help="Build all content, even if it is already marked as COMPLETE.")
@click.option(
    "--poll-wait",
    type=click.FloatRange(min=0.5, clamp=True),
    default=2,
    help="Defines the number of seconds between polls when polling for build output. Defaults to 2.",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(LogOutputFormat._all),
    default=LogOutputFormat.DEFAULT,
    help="The output format of the logs. Defaults to text.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Log stacktraces from exceptions during background operations.",
)
@click.pass_context
def start_content_build(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    parallelism: int,
    aborted: bool,
    error: bool,
    running: bool,
    retry: bool,
    all: bool,
    poll_wait: float,
    format: str,
    debug: bool,
    verbose: int,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    logger.set_log_output_format(format)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        build_start(ce.remote_server, parallelism, aborted, error, running, retry, all, poll_wait, debug)


@cli.group(no_args_is_help=True, help="Interact with Posit Connect's system API.")
def system():
    pass


@system.group(no_args_is_help=True, help="Interact with Posit Connect's system caches.")
def caches():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@caches.command(
    name="list",
    short_help="List runtime caches present on a Posit Connect server.",
)
@server_args
def system_caches_list(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(None, name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = ce.runtime_caches
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@caches.command(
    name="delete",
    short_help="Delete a runtime cache on a Posit Connect server.",
)
@server_args
@click.option(
    "--language",
    "-l",
    help="The language of the target cache.",
)
@click.option(
    "--version",
    "-V",
    help="The version of the target cache.",
)
@click.option(
    "--image-name",
    "-I",
    default="Local",
    help='The image name of the target cache\'s execution environment. Defaults to "Local".',
)
@click.option(
    "--dry-run",
    "-d",
    is_flag=True,
    help="If true, verify that deletion would occur, but do not delete.",
)
@click.pass_context
def system_caches_delete(
    ctx: click.Context,
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: str,
    verbose: int,
    language: str,
    version: str,
    image_name: str,
    dry_run: bool,
):
    set_verbosity(verbose)
    output_params(ctx, locals().items())
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(ctx, name, server, api_key, insecure, cacert, logger=None).validate_server()
        ce.delete_runtime_cache(language, version, image_name, dry_run)


if __name__ == "__main__":
    cli()
    click.echo()
