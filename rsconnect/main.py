import errno
import json
import sys
import textwrap
from os.path import abspath, dirname, exists, isdir, join

import click
from six import text_type

from .actions import (
    are_apis_supported_on_server,
    check_server_capabilities,
    cli_feedback,
    create_api_deployment_bundle,
    create_notebook_deployment_bundle,
    deploy_bundle,
    describe_manifest,
    gather_basic_deployment_info_for_api,
    gather_basic_deployment_info_for_fastapi,
    gather_basic_deployment_info_for_dash,
    gather_basic_deployment_info_for_streamlit,
    gather_basic_deployment_info_for_bokeh,
    gather_basic_deployment_info_for_notebook,
    gather_basic_deployment_info_from_manifest,
    gather_server_details,
    get_python_env_info,
    is_conda_supported_on_server,
    set_verbosity,
    spool_deployment_log,
    test_api_key,
    test_server,
    validate_entry_point,
    validate_extra_files,
    validate_file_is_notebook,
    validate_manifest_file,
    write_api_manifest_json,
    write_environment_file,
    write_notebook_manifest_json,
    fake_module_file_from_directory,
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

from . import api, VERSION
from .bundle import is_environment_dir, make_manifest_bundle
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

@click.group(no_args_is_help=True)
@click.option("--future", "-u", is_flag=True, hidden=True, help="Enables future functionality.")
def cli(future):
    """
    This command line tool may be used to deploy Jupyter notebooks to RStudio
    Connect.  Support for deploying other content types is also provided.

    The tool supports the notion of a simple nickname that represents the
    information needed to interact with an RStudio Connect server instance.  Use
    the add, list and remove commands to manage these nicknames.

    The information about an instance of RStudio Connect includes its URL, the
    API key needed to authenticate against that instance, a flag that notes whether
    TLS certificate/host verification should be disabled and a path to a trusted CA
    certificate file to use for TLS.  The last two items are only relevant if the
    URL specifies the "https" protocol.
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


# noinspection SpellCheckingInspection
@cli.command(
    short_help="Define a nickname for an RStudio Connect server.",
    help=(
        "Associate a simple nickname with the information needed to interact with an RStudio Connect server. "
        "Specifying an existing nickname will cause its stored information to be replaced by what is given "
        "on the command line."
    ),
)
@click.option("--name", "-n", required=True, help="The nickname to associate with the server.")
@click.option("--server", "-s", required=True, help="The URL for the RStudio Connect server.")
@click.option(
    "--api-key",
    "-k",
    required=True,
    help="The API key to use to authenticate with RStudio Connect.",
)
@click.option("--insecure", "-i", is_flag=True, help="Disable TLS certification/host validation.")
@click.option("--cacert", "-c", type=click.File(), help="The path to trusted TLS CA certificates.")
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def add(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    old_server = server_store.get_by_name(name)

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
        click.echo('Updated server "%s" with URL %s' % (name, real_server.url))
    else:
        click.echo('Added server "%s" with URL %s' % (name, real_server.url))


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
                click.echo("    API key is saved")
                if server["insecure"]:
                    click.echo("    Insecure mode (TLS host/certificate validation disabled)")
                if server["ca_cert"]:
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
@click.option(
    "--name",
    "-n",
    help="The nickname of the RStudio Connect server to get details for.",
)
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="The URL for the RStudio Connect server to get details for.",
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
def details(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert, api_key_is_required=False)

    click.echo("    RStudio Connect URL: %s" % connect_server.url)

    if not connect_server.api_key:
        return

    with cli_feedback("Gathering details"):
        server_details = gather_server_details(connect_server)

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
            raise api.RSConnectException("You must specify only one of -n/--name or -s/--server.")

        if not (name or server):
            raise api.RSConnectException("You must specify one of -n/--name or -s/--server.")

        if name:
            if server_store.remove_by_name(name):
                message = 'Removed nickname "%s".' % name
            else:
                raise api.RSConnectException('Nickname "%s" was not found.' % name)
        else:  # the user specified -s/--server
            if server_store.remove_by_url(server):
                message = 'Removed URL "%s".' % server
            else:
                raise api.RSConnectException('URL "%s" was not found.' % server)

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


@cli.group(no_args_is_help=True, help="Deploy content to RStudio Connect.")
def deploy():
    pass


def _validate_deploy_to_args(name, url, api_key, insecure, ca_cert, api_key_is_required=True):
    """
    Validate that the user gave us enough information to talk to a Connect server.

    :param name: the nickname, if any, specified by the user.
    :param url: the URL, if any, specified by the user.
    :param api_key: the API key, if any, specified by the user.
    :param insecure: a flag noting whether TLS host/validation should be skipped.
    :param ca_cert: the name of a CA certs file containing certificates to use.
    :param api_key_is_required: a flag that notes whether the API key is required or may
    be omitted.
    :return: a ConnectServer object that carries all the right info.
    """
    ca_data = ca_cert and text_type(ca_cert.read())

    if name and url:
        raise api.RSConnectException("You must specify only one of -n/--name or -s/--server, not both.")

    real_server, api_key, insecure, ca_data, from_store = server_store.resolve(name, url, api_key, insecure, ca_data)

    # This can happen if the user specifies neither --name or --server and there's not
    # a single default to go with.
    if not real_server:
        raise api.RSConnectException("You must specify one of -n/--name or -s/--server.")

    connect_server = api.RSConnectServer(real_server, None, insecure, ca_data)

    # If our info came from the command line, make sure the URL really works.
    if not from_store:
        connect_server, _ = test_server(connect_server)

    connect_server.api_key = api_key

    if not connect_server.api_key:
        if api_key_is_required:
            raise api.RSConnectException('An API key must be specified for "%s".' % connect_server.url)
        return connect_server

    # If our info came from the command line, make sure the key really works.
    if not from_store:
        _ = test_api_key(connect_server)

    return connect_server


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


def _deploy_bundle(
    connect_server,
    app_store,
    primary_path,
    app_id,
    app_mode,
    name,
    title,
    title_is_default,
    bundle,
):
    """
    Does the work of uploading a prepared bundle.

    :param connect_server: the Connect server information.
    :param app_store: the store where data is saved about deployments.
    :param primary_path: the base path (file or directory) that's being deployed.
    :param app_id: the ID of the app.
    :param app_mode: the mode of the app.
    :param name: the name of the app.
    :param title: the title of the app.
    :param title_is_default: a flag noting whether the title carries a defaulted value.
    :param bundle: the bundle to deploy.
    """
    with cli_feedback("Uploading bundle"):
        app = deploy_bundle(connect_server, app_id, name, title, title_is_default, bundle)

    with cli_feedback("Saving deployment data"):
        app_store.set(
            connect_server.url,
            abspath(primary_path),
            app["app_url"],
            app["app_id"],
            app["app_guid"],
            title,
            app_mode,
        )

    with cli_feedback(""):
        click.secho("\nDeployment log:")
        app_url, _, _ = spool_deployment_log(connect_server, app, click.echo)
        click.secho("Deployment completed successfully.")
        click.secho("    Dashboard content URL: ", nl=False)
        click.secho(app_url, fg="green")
        click.secho("    Direct content URL: ", nl=False)
        click.secho(app["app_url"], fg="green")

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(
            connect_server.url,
            abspath(primary_path),
            app_url,
            app["app_id"],
            app["app_guid"],
            app["title"],
            app_mode,
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
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
def deploy_notebook(
    name,
    server,
    api_key,
    insecure,
    cacert,
    static,
    new,
    app_id,
    title,
    python,
    conda,
    force_generate,
    verbose,
    file,
    extra_files,
    hide_all_input,
    hide_tagged_input,
):
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        app_store = AppStore(file)
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        extra_files = validate_extra_files(dirname(file), extra_files)
        (
            app_id,
            deployment_name,
            title,
            default_title,
            app_mode,
        ) = gather_basic_deployment_info_for_notebook(connect_server, app_store, file, new, app_id, title, static)

    click.secho('    Deploying %s to server "%s"' % (file, connect_server.url))

    base_dir = dirname(file)
    _warn_on_ignored_manifest(base_dir)
    _warn_if_no_requirements_file(base_dir)
    _warn_if_environment_directory(base_dir)

    with cli_feedback("Inspecting Python environment"):
        python, environment = get_python_env_info(file, python, conda, force_generate)

    if environment.package_manager == "conda":
        with cli_feedback("Ensuring Conda is supported"):
            check_server_capabilities(connect_server, [is_conda_supported_on_server])
    else:
        _warn_on_ignored_conda_env(environment)

    if force_generate:
        _warn_on_ignored_requirements(base_dir, environment.filename)

    with cli_feedback("Creating deployment bundle"):
        bundle = create_notebook_deployment_bundle(
            file, extra_files, app_mode, python, environment, False, hide_all_input, hide_tagged_input
        )
    _deploy_bundle(
        connect_server,
        app_store,
        file,
        app_id,
        app_mode,
        deployment_name,
        title,
        default_title,
        bundle,
    )


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(
    name="manifest",
    short_help="Deploy content to RStudio Connect by manifest.",
    help=(
        "Deploy content to RStudio Connect using an existing manifest.json "
        'file.  The specified file must either be named "manifest.json" or '
        'refer to a directory that contains a file named "manifest.json".'
    ),
)
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
@click.argument("file", type=click.Path(exists=True, dir_okay=True, file_okay=True))
def deploy_manifest(name, server, api_key, insecure, cacert, new, app_id, title, verbose, file):
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        file = validate_manifest_file(file)
        app_store = AppStore(file)

        (
            app_id,
            deployment_name,
            title,
            default_title,
            app_mode,
            package_manager,
        ) = gather_basic_deployment_info_from_manifest(connect_server, app_store, file, new, app_id, title)

    click.secho('    Deploying %s to server "%s"' % (file, connect_server.url))

    if package_manager == "conda":
        with cli_feedback("Ensuring Conda is supported"):
            check_server_capabilities(connect_server, [is_conda_supported_on_server])

    with cli_feedback("Creating deployment bundle"):
        try:
            bundle = make_manifest_bundle(file)
        except IOError as error:
            msg = "Unable to include the file %s in the bundle: %s" % (
                error.filename,
                error.args[1],
            )
            if error.args[0] == errno.ENOENT:
                msg = "\n".join(
                    [
                        msg,
                        "Since the file is missing but referenced in the manifest, "
                        "you will need to\nregenerate your manifest.  See the help "
                        'for the "write-manifest" command or,\nfor non-Python '
                        'content, run the "deploy other-content" command.',
                    ]
                )
            raise api.RSConnectException(msg)

    _deploy_bundle(
        connect_server,
        app_store,
        file,
        app_id,
        app_mode,
        deployment_name,
        title,
        default_title,
        bundle,
    )


def generate_deploy_python(app_mode, alias, min_version):
    # noinspection SpellCheckingInspection
    @deploy.command(
        name=alias,
        short_help="Deploy a {desc} to RStudio Connect [v{version}+].".format(
            desc=app_mode.desc(), version=min_version
        ),
        help=(
            'Deploy a {desc} module to RStudio Connect. The "directory" argument must refer to an '
            "existing directory that contains the application code."
        ).format(desc=app_mode.desc()),
    )
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
        "--new",
        "-N",
        is_flag=True,
        help=(
            "Force a new deployment, even if there is saved metadata from a previous deployment. "
            "Cannot be used with --app-id."
        ),
    )
    @click.option(
        "--app-id",
        "-a",
        help="Existing app ID or GUID to replace. Cannot be used with --new.",
    )
    @click.option(
        "--title",
        "-t",
        help="Title of the content (default is the same as the directory).",
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
    @click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
    @click.argument("directory", type=click.Path(exists=True, dir_okay=True, file_okay=False))
    @click.argument(
        "extra_files",
        nargs=-1,
        type=click.Path(exists=True, dir_okay=False, file_okay=True),
    )
    def deploy_app(
        name,
        server,
        api_key,
        insecure,
        cacert,
        entrypoint,
        exclude,
        new,
        app_id,
        title,
        python,
        conda,
        force_generate,
        verbose,
        directory,
        extra_files,
    ):
        _deploy_by_framework(
            name,
            server,
            api_key,
            insecure,
            cacert,
            entrypoint,
            exclude,
            new,
            app_id,
            title,
            python,
            conda,
            force_generate,
            verbose,
            directory,
            extra_files,
            {
                AppModes.PYTHON_API: gather_basic_deployment_info_for_api,
                AppModes.PYTHON_FASTAPI: gather_basic_deployment_info_for_fastapi,
                AppModes.DASH_APP: gather_basic_deployment_info_for_dash,
                AppModes.STREAMLIT_APP: gather_basic_deployment_info_for_streamlit,
                AppModes.BOKEH_APP: gather_basic_deployment_info_for_bokeh,
            }[app_mode],
        )

    return deploy_app


deploy_api = generate_deploy_python(app_mode=AppModes.PYTHON_API, alias="api", min_version="1.8.2")
# TODO: set fastapi min_version correctly
deploy_fastapi = generate_deploy_python(app_mode=AppModes.PYTHON_FASTAPI, alias="fastapi", min_version="2021.08.0")
deploy_dash_app = generate_deploy_python(app_mode=AppModes.DASH_APP, alias="dash", min_version="1.8.2")
deploy_streamlit_app = generate_deploy_python(app_mode=AppModes.STREAMLIT_APP, alias="streamlit", min_version="1.8.4")
deploy_bokeh_app = generate_deploy_python(app_mode=AppModes.BOKEH_APP, alias="bokeh", min_version="1.8.4")


# noinspection SpellCheckingInspection
def _deploy_by_framework(
    name,
    server,
    api_key,
    insecure,
    cacert,
    entrypoint,
    exclude,
    new,
    app_id,
    title,
    python,
    conda,
    force_generate,
    verbose,
    directory,
    extra_files,
    gatherer,
):
    """
    A common function for deploying APIs, as well as Dash, Streamlit, and Bokeh apps.

    :param name: the nickname of the Connect server to use.
    :param server: the URL of the Connect server to use.
    :param api_key: the API key to use to authenticate with Connect.
    :param insecure: a flag noting whether insecure TLS should be used.
    :param cacert: a path to a CA certificates file to use with TLS.
    :param entrypoint: the entry point for the thing being deployed.
    :param exclude: a sequence of exclude glob patterns to exclude files
                    from the deploy.
    :param new: a flag to force the deploy to be new.
    :param app_id: the ID of the app to redeploy.
    :param title: the title to use for the app.
    :param python: a path to the Python executable to use.
    :param conda: a flag to note whether Conda should be used/assumed..
    :param force_generate: a flag to force the generation of manifest and
                           requirements file.
    :param verbose: a flag to produce more (debugging) output.
    :param directory: the directory of the thing to deploy.
    :param extra_files: any extra files that should be included.
    :param gatherer: the function to use to gather basic information.
    """
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        module_file = fake_module_file_from_directory(directory)
        extra_files = validate_extra_files(directory, extra_files)
        app_store = AppStore(module_file)
        entrypoint, app_id, deployment_name, title, default_title, app_mode = gatherer(
            connect_server, app_store, directory, entrypoint, new, app_id, title
        )

    click.secho('    Deploying %s to server "%s"' % (directory, connect_server.url))

    _warn_on_ignored_manifest(directory)
    _warn_if_no_requirements_file(directory)
    _warn_if_environment_directory(directory)

    with cli_feedback("Inspecting Python environment"):
        _, environment = get_python_env_info(module_file, python, conda, force_generate)

    with cli_feedback("Checking server capabilities"):
        checks = [are_apis_supported_on_server]
        if environment.package_manager == "conda":
            checks.append(is_conda_supported_on_server)
        check_server_capabilities(connect_server, checks)

    _warn_on_ignored_conda_env(environment)

    if force_generate:
        _warn_on_ignored_requirements(directory, environment.filename)

    with cli_feedback("Creating deployment bundle"):
        bundle = create_api_deployment_bundle(directory, extra_files, exclude, entrypoint, app_mode, environment, False)

    _deploy_bundle(
        connect_server,
        app_store,
        directory,
        app_id,
        app_mode,
        deployment_name,
        title,
        default_title,
        bundle,
    )


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
@click.argument("file", type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument(
    "extra_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, file_okay=True),
)
def write_manifest_notebook(
    overwrite, python, conda, force_generate, verbose, file, extra_files, hide_all_input=None, hide_tagged_input=None
):
    set_verbosity(verbose)
    with cli_feedback("Checking arguments"):
        validate_file_is_notebook(file)

        base_dir = dirname(file)
        extra_files = validate_extra_files(base_dir, extra_files)
        manifest_path = join(base_dir, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise api.RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

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
        )

    if environment_file_exists and not force_generate:
        click.secho(
            "    Warning: %s already exists and will not be overwritten." % environment.filename,
            fg="yellow",
        )
    else:
        with cli_feedback("Creating %s" % environment.filename):
            write_environment_file(environment, base_dir)


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
        )

    return manifest_writer


write_manifest_api = generate_write_manifest_python(AppModes.PYTHON_API, alias="api")
write_manifest_fastapi = generate_write_manifest_python(AppModes.PYTHON_FASTAPI, alias="fastapi")
write_manifest_dash = generate_write_manifest_python(AppModes.DASH_APP, alias="dash")
write_manifest_streamlit = generate_write_manifest_python(AppModes.STREAMLIT_APP, alias="streamlit")
write_manifest_bokeh = generate_write_manifest_python(AppModes.BOKEH_APP, alias="bokeh")


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
    """
    set_verbosity(verbose)

    with cli_feedback("Checking arguments"):
        entrypoint = validate_entry_point(entrypoint, directory)
        extra_files = validate_extra_files(directory, extra_files)
        manifest_path = join(directory, "manifest.json")

        if exists(manifest_path) and not overwrite:
            raise api.RSConnectException("manifest.json already exists. Use --overwrite to overwrite.")

    with cli_feedback("Inspecting Python environment"):
        _, environment = get_python_env_info(directory, python, conda, force_generate)

    _warn_on_ignored_conda_env(environment)

    with cli_feedback("Creating manifest.json"):
        environment_file_exists = write_api_manifest_json(
            directory, entrypoint, environment, app_mode, extra_files, exclude
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
        raise api.RSConnectException("You must specify only one of -g/--guid or --all, not both.")
    if not guid and not all:
        raise api.RSConnectException("You must specify one of -g/--guid or --all.")


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
    help="Filter content results by content type."
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
def content_search(name, server, api_key, insecure, cacert, published, unpublished, content_type, r_version, py_version, title_contains, order_by, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = search_content(connect_server, published, unpublished, content_type, r_version, py_version, title_contains, order_by)
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = get_content(connect_server, guid)
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        if exists(output) and not overwrite:
            raise api.RSConnectException("The output file already exists: %s" % output)

        result = download_bundle(connect_server, guid)
        with open(output, 'wb') as f:
            f.write(result.response_body)


@content.group(no_args_is_help=True, help="Build content on RStudio Connect. Requires Connect >= 2021.11.1")
def build():
    pass

# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="add",
    short_help="Mark a content item for build. Use `build run` to invoke the build on the Connect server."
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        build_add_content(connect_server, guid)
        if len(guid) == 1:
            logger.info("Added \"%s\"." % guid[0])
        else:
            logger.info("Bulk added %d content items." % len(guid))


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="rm",
    short_help="Remove a content item from the list of content that are tracked for build. " +
        "Use `build ls` to view the tracked content."
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        _validate_build_rm_args(guid, all, purge)
        guids = build_remove_content(connect_server, guid, all, purge)
        if len(guids) == 1:
            logger.info("Removed \"%s\"." % guids[0])
        else:
            logger.info("Removed %d content items." % len(guids))


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="ls",
    short_help="List the content items that are being tracked for build on a given Connect server."
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
    "--status",
    type=click.Choice(BuildStatus._all),
    help="Filter results by status of the build operation."
)
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = build_list_content(connect_server, guid, status)
        json.dump(result, sys.stdout, indent=2)


# noinspection SpellCheckingInspection,DuplicatedCode
@build.command(
    name="history",
    short_help="Get the build history for a content item."
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
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
# todo: --format option (json, text)
def get_build_history(name, server, api_key, insecure, cacert, guid, verbose):
    set_verbosity(verbose)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        result = build_history(connect_server, guid)
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
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        for line in emit_build_log(connect_server, guid, format, task_id):
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
    help="Defines the number of builds that can run concurrently. Defaults to 1."
)
@click.option(
    "--aborted",
    is_flag=True,
    help="Build content that is in the ABORTED state."
)
@click.option(
    "--error",
    is_flag=True,
    help="Build content that is in the ERROR state."
)
@click.option(
    "--all",
    is_flag=True,
    help="Build all content, even if it is already marked as COMPLETE."
)
@click.option(
    "--poll-wait",
    type=click.FloatRange(min=.5, clamp=True),
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
    help="Log stacktraces from exceptions during background operations."
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed messages.")
def start_content_build(name, server, api_key, insecure, cacert, parallelism, aborted, error, all, poll_wait, format, debug, verbose):
    set_verbosity(verbose)
    logger.set_log_output_format(format)
    with cli_feedback("", stderr=True):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        build_start(connect_server, parallelism, aborted, error, all, poll_wait, debug)


if __name__ == "__main__":
    cli()
    click.echo()
