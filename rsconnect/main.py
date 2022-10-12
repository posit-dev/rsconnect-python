import functools
import json
import os
import sys
import traceback
import typing
import textwrap
import click
from six import text_type
from os.path import abspath, dirname, exists, isdir, join
from functools import wraps
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
from .api import RSConnectExecutor, filter_out_server_info
from .bundle import (
    are_apis_supported_on_server,
    create_python_environment,
    default_title_from_manifest,
    is_environment_dir,
    make_manifest_bundle,
    make_html_bundle,
    make_api_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    read_manifest_app_mode,
    write_notebook_manifest_json,
    write_api_manifest_json,
    write_environment_file,
    write_quarto_manifest_json,
    validate_entry_point,
    validate_extra_files,
    validate_file_is_notebook,
    validate_manifest_file,
    fake_module_file_from_directory,
    get_python_env_info,
)
from .log import logger, LogOutputFormat
from .metadata import ServerStore, AppStore
from .models import (
    AppModes,
    BuildStatus,
    ContentGuidWithBundleParamType,
    StrippedStringParamType,
    VersionSearchFilterParamType,
)

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


def server_args(func):
    @click.option("--name", "-n", help="The nickname of the RStudio Connect server to deploy to.")
    @click.option(
        "--server",
        "-s",
        envvar="CONNECT_SERVER",
        help="The URL for the RStudio Connect server to deploy to.",
    )
    @click.option(
        "--api-key",
        "-k",
        envvar="CONNECT_API_KEY",
        help="The API key to use to authenticate with RStudio Connect.",
    )
    @click.option(
        "--insecure",
        "-i",
        envvar="CONNECT_INSECURE",
        is_flag=True,
        help="Disable TLS certification/host validation.",
    )
    @click.option(
        "--cacert",
        "-c",
        envvar="CONNECT_CA_CERTIFICATE",
        type=click.File(),
        help="The path to trusted TLS CA certificates.",
    )
    @click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def rstudio_args(func):
    @click.option(
        "--account",
        "-A",
        envvar=["SHINYAPPS_ACCOUNT", "RSCLOUD_ACCOUNT"],
        help="The shinyapps.io/RStudio Cloud account name.",
    )
    @click.option(
        "--token",
        "-T",
        envvar=["SHINYAPPS_TOKEN", "RSCLOUD_TOKEN"],
        help="The shinyapps.io/RStudio Cloud token.",
    )
    @click.option(
        "--secret",
        "-S",
        envvar=["SHINYAPPS_SECRET", "RSCLOUD_SECRET"],
        help="The shinyapps.io/RStudio Cloud token secret.",
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
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


@click.group(no_args_is_help=True)
@click.option("--future", "-u", is_flag=True, hidden=True, help="Enables future functionality.")
def cli(future):
    """
    This command line tool may be used to deploy various types of content to RStudio
    Connect, RStudio Cloud, and shinyapps.io.

    The tool supports the notion of a simple nickname that represents the
    information needed to interact with a deployment target.  Usethe add, list and
    remove commands to manage these nicknames.

    The information about an instance of RStudio Connect includes its URL, the
    API key needed to authenticate against that instance, a flag that notes whether
    TLS certificate/host verification should be disabled and a path to a trusted CA
    certificate file to use for TLS.  The last two items are only relevant if the
    URL specifies the "https" protocol.

    For RStudio Cloud and shinyapps.io, the information needed to connect includes
    the account, auth token, auth secret, and server ('rstudio.cloud' or 'shinyapps.io').
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
    ca_data = ca_cert and text_type(ca_cert.read())
    me = None

    with cli_feedback("Checking %s" % server):
        real_server, _ = test_server(api.RSConnectServer(server, None, insecure, ca_data))

    real_server.api_key = api_key

    if api_key:
        with cli_feedback("Checking API key"):
            me = test_api_key(real_server)

    return real_server, me


def _test_rstudio_creds(server: api.RStudioServer):
    with cli_feedback("Checking {} credential".format(server.remote_name)):
        test_rstudio_server(server)


# noinspection SpellCheckingInspection
@cli.command(
    short_help="Define a nickname for an RStudio Connect, RStudio Cloud, or shinyapps.io server and credential.",
    help=(
        "Associate a simple nickname with the information needed to interact with a deployment target. "
        "Specifying an existing nickname will cause its stored information to be replaced by what is given "
        "on the command line."
    ),
)
@click.option("--name", "-n", required=True, help="The nickname of the RStudio Connect server to deploy to.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server to deploy to, OR rstudio.cloud OR shinyapps.io.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
@rstudio_args
@click.pass_context
def add(ctx, name, server, api_key, insecure, cacert, account, token, secret, verbose):

    set_verbosity(verbose)
    if sys.version_info >= (3, 8):
        click.echo("Detected the following inputs:")
        for k, v in locals().items():
            if k in {"ctx", "verbose"}:
                continue
            if v is not None:
                click.echo("    {}: {}".format(k, ctx.get_parameter_source(k).name))

    validation.validate_connection_options(
        url=server,
        api_key=api_key,
        insecure=insecure,
        cacert=cacert,
        account_name=account,
        token=token,
        secret=secret,
    )

    old_server = server_store.get_by_name(name)

    if account:
        if server and "rstudio.cloud" in server:
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
    short_help="List the known RStudio Connect servers.",
    help="Show the stored information about each known server nickname.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
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
    short_help="Show details about an RStudio Connect server.",
    help=(
        "Show details about an RStudio Connect server and installed Python information. "
        "Use this command to verify that a URL refers to an RStudio Connect server, optionally, that an "
        "API key is valid for authentication for that server.  It may also be used to verify that the "
        "information stored as a nickname is still valid."
    ),
)
@server_args
@cli_exception_handler
def details(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    ce = RSConnectExecutor(name, server, api_key, insecure, cacert).validate_server()

    click.echo("    RStudio Connect URL: %s" % ce.remote_server.url)

    if not ce.remote_server.api_key:
        return

    with cli_feedback("Gathering details"):
        server_details = ce.server_details

    connect_version = server_details["connect"]
    apis_allowed = server_details["python"]["api_enabled"]
    python_versions = server_details["python"]["versions"]
    conda_details = server_details["conda"]

    click.echo("    RStudio Connect version: %s" % ("<redacted>" if len(connect_version) == 0 else connect_version))

    if len(python_versions) == 0:
        click.echo("    No versions of Python are installed.")
    else:
        click.echo("    Installed versions of Python:")
        for python_version in python_versions:
            click.echo("        %s" % python_version)

    click.echo("    APIs: %sallowed" % ("" if apis_allowed else "not "))

    if future_enabled:
        click.echo("    Conda: %ssupported" % ("" if conda_details["supported"] else "not "))


@cli.command(
    short_help="Remove the information about an RStudio Connect server.",
    help=(
        "Remove the information about an RStudio Connect server by nickname or URL. "
        "One of --name or --server is required."
    ),
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server to remove.")
@click.option("--server", "-s", help="The URL of the RStudio Connect server to remove.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def remove(name, server, verbose):
    set_verbosity(verbose)

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
        "Display information about the deployment of a Jupyter notebook or manifest. For any given file, "
        "information about it"
        "s deployments are saved on a per-server basis."
    ),
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


@cli.group(no_args_is_help=True, help="Deploy content to RStudio Connect, RStudio Cloud, or shinyapps.io.")
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


def _warn_on_ignored_conda_env(environment):
    """
    Checks for a discovered Conda environment and produces a warning that it will be ignored when
    Conda was not requested.  The warning is only shown if we're in "future" mode since we don't
    yet want to advertise Conda support.

    :param environment: The Python environment that was discovered.
    """
    if future_enabled and environment.package_manager != "conda" and environment.conda is not None:
        click.echo(
            "    Using %s for package management; the current Conda environment will be ignored."
            % environment.package_manager
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
    short_help="Deploy Jupyter notebook to RStudio Connect [v1.7.0+].",
    help=(
        "Deploy a Jupyter notebook to RStudio Connect. This may be done by source or as a static HTML "
        "page. If the notebook is deployed as a static HTML page (--static), it cannot be scheduled or "
        "rerun on the Connect server."
    ),
)
@server_args
@content_args
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
    "--conda",
    "-C",
    is_flag=True,
    hidden=True,
    help="Use Conda to deploy (requires RStudio Connect version 1.8.2 or later)",
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
@click.option(
    "--image",
    "-I",
    help="Target image to be used during content execution (only applicable if the RStudio Connect "
    "server is configured to use off-host execution)",
)
@click.argument("file", type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
def deploy_notebook(
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: typing.IO,
    static: bool,
    new: bool,
    app_id: str,
    title: str,
    python,
    conda,
    force_generate,
    verbose: bool,
    file: str,
    extra_files,
    hide_all_input: bool,
    hide_tagged_input: bool,
    env_vars: typing.Dict[str, str],
    image: str,
):
    kwargs = locals()
    set_verbosity(verbose)

    kwargs["extra_files"] = extra_files = validate_extra_files(dirname(file), extra_files)
    app_mode = AppModes.JUPYTER_NOTEBOOK if not static else AppModes.STATIC

    base_dir = dirname(file)
    _warn_on_ignored_manifest(base_dir)
    _warn_if_no_requirements_file(base_dir)
    _warn_if_environment_directory(base_dir)
    python, environment = get_python_env_info(file, python, conda, force_generate)

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
        )
    ce.deploy_bundle().save_deployed_info().emit_task_log()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="manifest",
    short_help="Deploy content to RStudio Connect, RStudio Cloud, or shinyapps.io by manifest.",
    help=(
        "Deploy content to RStudio Connect using an existing manifest.json "
        'file.  The specified file must either be named "manifest.json" or '
        'refer to a directory that contains a file named "manifest.json".'
    ),
)
@server_args
@content_args
@rstudio_args
@click.argument("file", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@cli_exception_handler
def deploy_manifest(
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: typing.IO,
    account: str,
    token: str,
    secret: str,
    new: bool,
    app_id: str,
    title: str,
    verbose: bool,
    file: str,
    env_vars: typing.Dict[str, str],
):
    kwargs = locals()
    set_verbosity(verbose)

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


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="quarto",
    short_help="Deploy Quarto content to RStudio Connect [v2021.08.0+].",
    help=(
        "Deploy a Quarto document or project to RStudio Connect. Should the content use the Quarto Jupyter engine, "
        'an environment file ("requirements.txt") is created and included in the deployment if one does '
        "not already exist. Requires RStudio Connect 2021.08.0 or later."
        "\n\n"
        "FILE_OR_DIRECTORY is the path to a single-file Quarto document or the directory containing a Quarto project."
    ),
)
@server_args
@content_args
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
@click.option(
    "--image",
    "-I",
    help="Target image to be used during content execution (only applicable if the RStudio Connect "
    "server is configured to use off-host execution)",
)
@click.argument("file_or_directory", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
@cli_exception_handler
def deploy_quarto(
    name: str,
    server: str,
    api_key: str,
    insecure: bool,
    cacert: typing.IO,
    new: bool,
    app_id: str,
    title: str,
    exclude,
    quarto,
    python,
    force_generate: bool,
    verbose: bool,
    file_or_directory,
    extra_files,
    env_vars: typing.Dict[str, str],
    image: str,
):
    kwargs = locals()
    set_verbosity(verbose)

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
            python, environment = get_python_env_info(module_file, python, False, force_generate)

            _warn_on_ignored_conda_env(environment)

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
        )
        .deploy_bundle()
        .save_deployed_info()
        .emit_task_log()
    )


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="html",
    short_help="Deploy html content to RStudio Connect.",
    help=("Deploy an html file, or directory of html files with entrypoint, to RStudio Connect."),
)
@server_args
@content_args
@click.option(
    "--entrypoint",
    "-e",
    help=("The name of the html file that is the landing page."),
)
@click.option(
    "--excludes",
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
def deploy_html(
    connect_server: api.RSConnectServer = None,
    path: str = None,
    entrypoint: str = None,
    extra_files=None,
    excludes=None,
    title: str = None,
    env_vars: typing.Dict[str, str] = None,
    verbose: bool = False,
    new: bool = False,
    app_id: str = None,
    name: str = None,
    server: str = None,
    api_key: str = None,
    insecure: bool = False,
    cacert: typing.IO = None,
):
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


def generate_deploy_python(app_mode, alias, min_version):
    # noinspection SpellCheckingInspection
    @deploy.command(
        name=alias,
        short_help="Deploy a {desc} to RStudio Connect [v{version}+], RStudio Cloud, or shinyapps.io.".format(
            desc=app_mode.desc(), version=min_version
        ),
        help=(
            "Deploy a {desc} module to RStudio Connect, RStudio Cloud, or shinyapps.io (if supported by the platform). "
            'The "directory" argument must refer to an existing directory that contains the application code.'
        ).format(desc=app_mode.desc()),
    )
    @server_args
    @content_args
    @rstudio_args
    @click.option(
        "--entrypoint",
        "-e",
        help=(
            "The module and executable object which serves as the entry point for the {desc} (defaults to app)"
        ).format(desc=app_mode.desc()),
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
        "--conda",
        "-C",
        is_flag=True,
        hidden=True,
        help="Use Conda to deploy (requires Connect version 1.8.2 or later)",
    )
    @click.option(
        "--force-generate",
        "-g",
        is_flag=True,
        help='Force generating "requirements.txt", even if it already exists.',
    )
    @click.option(
        "--image",
        "-I",
        help="Target image to be used during content execution (only applicable if the RStudio Connect "
        "server is configured to use off-host execution)",
    )
    @click.argument("directory", type=click.Path(exists=True, dir_okay=True, file_okay=False))
    @click.argument(
        "extra_files",
        nargs=-1,
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
    )
    @cli_exception_handler
    def deploy_app(
        name: str,
        server: str,
        api_key: str,
        insecure: bool,
        cacert: typing.IO,
        entrypoint,
        exclude,
        new: bool,
        app_id: str,
        title: str,
        python,
        conda,
        force_generate: bool,
        verbose: bool,
        directory,
        extra_files,
        env_vars: typing.Dict[str, str],
        image: str,
        account: str = None,
        token: str = None,
        secret: str = None,
    ):
        kwargs = locals()
        kwargs["entrypoint"] = entrypoint = validate_entry_point(entrypoint, directory)
        kwargs["extra_files"] = extra_files = validate_extra_files(directory, extra_files)
        environment = create_python_environment(
            directory,
            force_generate,
            python,
            conda,
        )

        ce = RSConnectExecutor(**kwargs)
        (
            ce.validate_server()
            .validate_app_mode(app_mode=app_mode)
            .check_server_capabilities([are_apis_supported_on_server])
            .make_bundle(
                make_api_bundle,
                directory,
                entrypoint,
                app_mode,
                environment,
                extra_files,
                exclude,
                image=image,
            )
            .deploy_bundle()
            .save_deployed_info()
            .emit_task_log()
        )

    return deploy_app


deploy_api = generate_deploy_python(app_mode=AppModes.PYTHON_API, alias="api", min_version="1.8.2")
# TODO: set fastapi min_version correctly
# deploy_fastapi = generate_deploy_python(app_mode=AppModes.PYTHON_FASTAPI, alias="fastapi", min_version="2021.08.0")
deploy_fastapi = generate_deploy_python(app_mode=AppModes.PYTHON_FASTAPI, alias="fastapi", min_version="2021.08.0")
deploy_dash_app = generate_deploy_python(app_mode=AppModes.DASH_APP, alias="dash", min_version="1.8.2")
deploy_streamlit_app = generate_deploy_python(app_mode=AppModes.STREAMLIT_APP, alias="streamlit", min_version="1.8.4")
deploy_bokeh_app = generate_deploy_python(app_mode=AppModes.BOKEH_APP, alias="bokeh", min_version="1.8.4")
deploy_shiny = generate_deploy_python(app_mode=AppModes.PYTHON_SHINY, alias="shiny", min_version="2022.07.0")


@deploy.command(
    name="other-content",
    short_help="Describe deploying other content to RStudio Connect.",
    help="Show help on how to deploy other content to RStudio Connect.",
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
        "with the git support provided by RStudio Connect or by using the "
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
    "--conda",
    "-C",
    is_flag=True,
    hidden=True,
    help="Use Conda to deploy (requires RStudio Connect version 1.8.2 or later)",
)
@click.option(
    "--force-generate",
    "-g",
    is_flag=True,
    help='Force generating "requirements.txt", even if it already exists.',
)
@click.option("--hide-all-input", help="Hide all input cells when rendering output")
@click.option("--hide-tagged-input", is_flag=True, default=None, help="Hide input code cells with the 'hide_input' tag")
@click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
@click.option(
    "--image",
    "-I",
    help="Target image to be used during content execution (only applicable if the RStudio Connect "
    "server is configured to use off-host execution)",
)
@click.argument("file", type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
def write_manifest_notebook(
    overwrite,
    python,
    conda,
    force_generate,
    verbose,
    file,
    extra_files,
    image,
    hide_all_input=None,
    hide_tagged_input=None,
):
    set_verbosity(verbose)
    with cli_feedback("Checking arguments"):
        validate_file_is_notebook(file)

        base_dir = dirname(file)
        extra_files = validate_extra_files(base_dir, extra_files)
        manifest_path = join(base_dir, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        python, environment = get_python_env_info(file, python, conda, force_generate)

    _warn_on_ignored_conda_env(environment)

    with cli_feedback("Creating manifest.json"):
        environment_file_exists = write_notebook_manifest_json(
            file,
            environment,
            AppModes.JUPYTER_NOTEBOOK,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image,
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
    name="quarto",
    short_help="Create a manifest.json file for Quarto content.",
    help=(
        "Create a manifest.json file for a Quarto document or project for later "
        "deployment. Should the content use the Quarto Jupyter engine, "
        'an environment file ("requirements.txt") is created if one does '
        "not already exist. All files are created in the same directory "
        "as the project. Requires RStudio Connect 2021.08.0 or later."
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
@click.option(
    "--image",
    "-I",
    help="Target image to be used during content execution (only applicable if the RStudio Connect "
    "server is configured to use off-host execution)",
)
@click.argument("file_or_directory", type=click.Path(exists=True, dir_okay=True, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
def write_manifest_quarto(
    overwrite,
    exclude,
    quarto,
    python,
    force_generate,
    verbose,
    file_or_directory,
    extra_files,
    image,
):
    set_verbosity(verbose)

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = dirname(file_or_directory)

    with cli_feedback("Checking arguments"):
        extra_files = validate_extra_files(base_dir, extra_files)
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
            python, environment = get_python_env_info(base_dir, python, False, force_generate)

        _warn_on_ignored_conda_env(environment)
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
        )


def generate_write_manifest_python(app_mode, alias):
    # noinspection SpellCheckingInspection
    @write_manifest.command(
        name=alias,
        short_help="Create a manifest.json file for a {desc}.".format(desc=app_mode.desc()),
        help=(
            "Create a manifest.json file for a {desc} for later deployment. This will create an "
            'environment file ("requirements.txt") if one does not exist. All files '
            "are created in the same directory as the API code."
        ).format(desc=app_mode.desc()),
    )
    @click.option("--overwrite", "-o", is_flag=True, help="Overwrite manifest.json, if it exists.")
    @click.option(
        "--entrypoint",
        "-e",
        help=(
            "The module and executable object which serves as the entry point for the {desc} (defaults to app)"
        ).format(desc=app_mode.desc()),
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
        "--conda",
        "-C",
        is_flag=True,
        hidden=True,
        help="Use Conda to deploy (requires Connect version 1.8.2 or later)",
    )
    @click.option(
        "--force-generate",
        "-g",
        is_flag=True,
        help='Force generating "requirements.txt", even if it already exists.',
    )
    @click.option("--verbose", "-v", "verbose", is_flag=True, help="Print detailed messages")
    @click.option(
        "--image",
        "-I",
        help="Target image to be used during content execution (only applicable if the RStudio Connect "
        "server is configured to use off-host execution)",
    )
    @click.argument("directory", type=click.Path(exists=True, dir_okay=True, file_okay=False))
    @click.argument(
        "extra_files",
        nargs=-1,
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
    )
    def manifest_writer(
        overwrite,
        entrypoint,
        exclude,
        python,
        conda,
        force_generate,
        verbose,
        directory,
        extra_files,
        image,
    ):
        _write_framework_manifest(
            overwrite,
            entrypoint,
            exclude,
            python,
            conda,
            force_generate,
            verbose,
            directory,
            extra_files,
            app_mode,
            image,
        )

    return manifest_writer


write_manifest_api = generate_write_manifest_python(AppModes.PYTHON_API, alias="api")
write_manifest_fastapi = generate_write_manifest_python(AppModes.PYTHON_FASTAPI, alias="fastapi")
write_manifest_dash = generate_write_manifest_python(AppModes.DASH_APP, alias="dash")
write_manifest_streamlit = generate_write_manifest_python(AppModes.STREAMLIT_APP, alias="streamlit")
write_manifest_bokeh = generate_write_manifest_python(AppModes.BOKEH_APP, alias="bokeh")
write_manifest_shiny = generate_write_manifest_python(AppModes.PYTHON_SHINY, alias="shiny")


# noinspection SpellCheckingInspection
def _write_framework_manifest(
    overwrite,
    entrypoint,
    exclude,
    python,
    conda,
    force_generate,
    verbose,
    directory,
    extra_files,
    app_mode,
    image,
):
    """
    A common function for writing manifests for APIs as well as Dash, Streamlit, and Bokeh apps.

    :param overwrite: overwrite the manifest.json, if it exists.
    :param entrypoint: the entry point for the thing being deployed.
    :param exclude: a sequence of exclude glob patterns to exclude files from
                    the deploy.
    :param python: a path to the Python executable to use.
    :param conda: a flag to note whether Conda should be used/assumed..
    :param force_generate: a flag to force the generation of manifest and
                           requirements file.
    :param verbose: a flag to produce more (debugging) output.
    :param directory: the directory of the thing to deploy.
    :param extra_files: any extra files that should be included.
    :param app_mode: the app mode to use.
    :param image: an optional docker image for off-host execution.
    """
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        entrypoint = validate_entry_point(entrypoint, directory)
        extra_files = validate_extra_files(directory, extra_files)
        manifest_path = join(directory, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        _, environment = get_python_env_info(directory, python, conda, force_generate)

    _warn_on_ignored_conda_env(environment)

    with cli_feedback("Creating manifest.json"):
        environment_file_exists = write_api_manifest_json(
            directory,
            entrypoint,
            environment,
            app_mode,
            extra_files,
            exclude,
            image,
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


@cli.group(no_args_is_help=True, help="Interact with RStudio Connect's content API.")
def content():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="search",
    short_help="Search for content on RStudio Connect.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
@cli_exception_handler
def content_search(
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
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = search_content(
            ce.remote_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by
        )
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="describe",
    short_help="Describe a content item on RStudio Connect.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    multiple=True,
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The GUID of a content item to describe. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def content_describe(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = get_content(ce.remote_server, guid)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@content.command(
    name="download-bundle",
    short_help="Download a content item's source bundle.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def content_bundle_download(name, server, api_key, insecure, cacert, guid, output, overwrite, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        if exists(output) and not overwrite:
            raise RSConnectException("The output file already exists: %s" % output)

        result = download_bundle(ce.remote_server, guid)
        with open(output, "wb") as f:
            f.write(result.response_body)


@content.group(no_args_is_help=True, help="Build content on RStudio Connect. Requires Connect >= 2021.11.1")
def build():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="add", short_help="Mark a content item for build. Use `build run` to invoke the build on the Connect server."
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    type=ContentGuidWithBundleParamType(),
    multiple=True,
    metavar="GUID[,BUNDLE_ID]",
    help="Add a content item by its guid. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def add_content_build(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
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
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def remove_content_build(name, server, api_key, insecure, cacert, guid, all, purge, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
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
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option("--status", type=click.Choice(BuildStatus._all), help="Filter results by status of the build operation.")
@click.option(
    "--guid",
    "-g",
    multiple=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="Check the local build state of a specific content item. This flag can be passed multiple times.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def list_content_build(name, server, api_key, insecure, cacert, status, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        result = build_list_content(ce.remote_server, guid, status)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(name="history", short_help="Get the build history for a content item.")
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--guid",
    "-g",
    required=True,
    type=StrippedStringParamType(),
    metavar="TEXT",
    help="The guid of the content item.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def get_build_history(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert)
        ce.validate_server()
        result = build_history(ce.remote_server, guid)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="logs",
    short_help="Print the logs for a content build.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def get_build_logs(name, server, api_key, insecure, cacert, guid, task_id, format, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        for line in emit_build_log(ce.remote_server, guid, format, task_id):
            sys.stdout.write(line)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="run",
    short_help="Start building content on a given Connect server.",
)
@click.option("--name", "-n", help="The nickname of the RStudio Connect server.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server.",
)
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option(
    "--insecure",
    "-i",
    envvar="CONNECT_INSECURE",
    is_flag=True,
    help="Disable TLS certification/host validation.",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.File(),
    help="The path to trusted TLS CA certificates.",
)
@click.option(
    "--parallelism",
    type=click.IntRange(min=1, clamp=True),
    default=1,
    help="Defines the number of builds that can run concurrently. Defaults to 1.",
)
@click.option("--aborted", is_flag=True, help="Build content that is in the ABORTED state.")
@click.option("--error", is_flag=True, help="Build content that is in the ERROR state.")
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
@click.option("--debug", is_flag=True, help="Log stacktraces from exceptions during background operations.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def start_content_build(
    name, server, api_key, insecure, cacert, parallelism, aborted, error, all, poll_wait, format, debug, verbose
):
    set_verbosity(verbose)
    logger.set_log_output_format(format)
    with cli_feedback("", stderr=True):
        ce = RSConnectExecutor(name, server, api_key, insecure, cacert, logger=None).validate_server()
        build_start(ce.remote_server, parallelism, aborted, error, all, poll_wait, debug)


if __name__ == "__main__":
    cli()
    click.echo()
