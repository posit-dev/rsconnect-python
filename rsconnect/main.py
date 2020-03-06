import logging
import textwrap
import threading
from os.path import abspath, dirname, exists, join

import click
from six import text_type

from rsconnect import VERSION
from rsconnect.actions import are_apis_supported_on_server, check_server_capabilities, cli_feedback, \
    create_api_deployment_bundle, create_notebook_deployment_bundle, deploy_bundle, \
    gather_basic_deployment_info_for_api, gather_basic_deployment_info_for_notebook, \
    gather_basic_deployment_info_from_manifest, gather_server_details, get_python_env_info, \
    is_conda_supported_on_server, set_verbosity, spool_deployment_log, test_api_key, test_server, \
    validate_entry_point, validate_extra_files, validate_file_is_notebook, validate_manifest_file, \
    write_api_manifest_json, write_environment_file, write_notebook_manifest_json, fake_module_file_from_directory

from . import api
from .bundle import make_manifest_bundle
from .metadata import ServerStore, AppStore
from .models import AppModes

server_store = ServerStore()
logging.basicConfig()


@click.group(no_args_is_help=True)
def cli():
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
    threading.local().is_cli = True


@cli.command(help='Show the version of the rsconnect-python package.')
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

    with cli_feedback('Checking %s' % server):
        real_server, _ = test_server(api.RSConnectServer(server, api_key, insecure, ca_data))

    if api_key:
        with cli_feedback('Checking API key'):
            me = test_api_key(real_server)

    return real_server, me


# noinspection SpellCheckingInspection
@cli.command(short_help='Define a nickname for an RStuio Connect server.',
             help='Associate a simple nickname with the information needed to interact with an RStudio Connect server. '
                  'Specifying an existing nickname will cause its stored information to be replaced by what is given '
                  'on the command line.')
@click.option('--name', '-n', required=True, help='The nickname to associate with the server.')
@click.option('--server', '-s', required=True, help='The URL for the RStudio Connect server.')
@click.option('--api-key', '-k', required=True, help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', is_flag=True, help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', type=click.File(), help='The path to trusted TLS CA certificates.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
def add(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    old_server = server_store.get_by_name(name)

    # Server must be pingable and the API key must work to be added.
    real_server, _ = _test_server_and_api(server, api_key, insecure, cacert)

    server_store.set(name, real_server.url, real_server.api_key, real_server.insecure, real_server.ca_data)

    if old_server:
        click.echo('Updated server "%s" with URL %s' % (name, real_server.url))
    else:
        click.echo('Added server "%s" with URL %s' % (name, real_server.url))


@cli.command('list', short_help='List the known RStudio Connect servers.',
             help='Show the stored information about each known server nickname.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
def list_servers(verbose):
    set_verbosity(verbose)
    with cli_feedback(''):
        servers = server_store.get_all_servers()

        click.echo('Server information from %s' % server_store.get_path())

        if not servers:
            click.echo('No servers are saved. To add a server, see `rsconnect add --help`.')
        else:
            click.echo()
            for server in servers:
                click.echo('Nickname: "%s"' % server['name'])
                click.echo('    URL: %s' % server['url'])
                click.echo('    API key is saved')
                if server['insecure']:
                    click.echo('    Insecure mode (TLS host/certificate validation disabled)')
                if server['ca_cert']:
                    click.echo('    Client TLS certificate data provided')
                click.echo()


# noinspection SpellCheckingInspection
@cli.command(short_help='Show details about an RStudio Connect server.',
             help='Show details about an RStudio Connect server and installed Python/Conda information. '
                  'Use this command to verify that a URL refers to an RStudio Connect server, optionally, that an '
                  'API key is valid for authentication for that server.  It may also be used to verify that the '
                  'information stored as a nickname is still valid.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to get details for.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',
              help='The URL for the RStudio Connect server to get details for.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
def details(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    with cli_feedback('Checking arguments'):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert, api_key_is_required=False)

    click.echo('    RStudio Connect URL: %s' % connect_server.url)

    if not connect_server.api_key:
        return

    with cli_feedback('Gathering details'):
        server_details = gather_server_details(connect_server)

    connect_version = server_details['connect']
    apis_allowed = server_details['python']['api_enabled']
    python_versions = server_details['python']['versions']
    conda_details = server_details['conda']
    click.echo('    RStudio Connect version: %s' % ('<redacted>' if len(connect_version) == 0 else connect_version))

    if len(python_versions) == 0:
        click.echo('    No versions of Python are installed.')
    else:
        click.echo('    Installed versions of Python:')
        for python_version in python_versions:
            click.echo('        %s' % python_version)

    click.echo('    APIs: %sallowed' % ('' if apis_allowed else 'not '))
    click.echo('    Conda: %ssupported' % ('' if conda_details['supported'] else 'not '))


@cli.command(short_help='Remove the information about an RStudio Connect server.',
             help='Remove the information about an RStudio Connect server by nickname or URL. '
                  'One of --name or --server is required.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to remove.')
@click.option('--server', '-s',  help='The URL of the RStudio Connect server to remove.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
def remove(name, server, verbose):
    set_verbosity(verbose)

    message = None

    with cli_feedback('Checking arguments'):
        if name and server:
            raise api.RSConnectException('You must specify only one of -n/--name or -s/--server.')

        if not (name or server):
            raise api.RSConnectException('You must specify one of -n/--name or -s/--server.')

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


@cli.command(short_help='Show saved information about the specified deployment.',
             help='Display information about the deployment of a Jupyter notebook or manifest. For any given file, '
                  'information about it''s deployments are saved on a per-server basis.')
@click.argument('file', type=click.Path(exists=True, dir_okay=True, file_okay=True))
def info(file):
    with cli_feedback(''):
        app_store = AppStore(file)
        deployments = app_store.get_all()

        if len(deployments) > 0:
            click.echo('Loaded deployment information from %s' % abspath(app_store.get_path()))

            for deployment in deployments:
                click.echo()
                click.echo('Server URL: %s' % deployment.get('server_url'))
                click.echo('App URL:    %s' % deployment.get('app_url'))
                click.echo('App ID:     %s' % deployment.get('app_id'))
                click.echo('App GUID:   %s' % deployment.get('app_guid'))
                click.echo('Title:      "%s"' % deployment.get('title'))
                click.echo('Filename:   %s' % deployment.get('filename'))
                click.echo('Type:       %s' % AppModes.get_by_name(deployment.get('app_mode'), True).desc())
        else:
            click.echo('No saved deployment information was found for %s.' % file)


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
        raise api.RSConnectException('You must specify only one of -n/--name or -s/--server, not both.')

    real_server, api_key, insecure, ca_data, from_store = server_store.resolve(name, url, api_key, insecure, ca_data)

    # This can happen if the user specifies neither --name or --server and there's not
    # a single default to go with.
    if not real_server:
        raise api.RSConnectException('You must specify one of -n/--name or -s/--server.')

    connect_server = api.RSConnectServer(real_server, api_key, insecure, ca_data)

    # If our info came from the command line, make sure the URL really works.
    if not from_store:
        connect_server, _ = test_server(connect_server)

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
    if exists(join(directory, 'manifest.json')):
        click.secho('    Warning: the existing manifest.json file will not be used or considered.', fg='yellow')


def _warn_on_ignored_requirements(directory, requirements_file_name):
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    :param requirements_file_name: the name of the requirements file.
    """
    if exists(join(directory, requirements_file_name)):
        click.secho('    Warning: the existing %s file will not be used or considered.' % requirements_file_name,
                    fg='yellow')


def _deploy_bundle(connect_server, app_store, primary_path, app_id, app_mode, name, title, bundle):
    """
    Does the work of uploading a prepared bundle.

    :param connect_server: the Connect server information.
    :param app_store: the store where data is saved about deployments.
    :param primary_path: the base path (file or directory) that's being deployed.
    :param app_id: the ID of the app.
    :param app_mode: the mode of the app.
    :param name: the name of the app.
    :param title: the title of the app.
    :param bundle: the bundle to deploy.
    """
    with cli_feedback('Uploading bundle'):
        app = deploy_bundle(connect_server, app_id, name, title, bundle)

    with cli_feedback('Saving deployment data'):
        app_store.set(connect_server.url, abspath(primary_path), app['app_url'], app['app_id'], app['app_guid'], title,
                      app_mode)

    with cli_feedback(''):
        click.secho('\nDeployment log:', fg='bright_white')
        app_url, _ = spool_deployment_log(connect_server, app, click.echo)
        click.secho('Deployment completed successfully.', fg='bright_white')
        click.secho('    Dashboard content URL: %s' % app_url, fg='bright_white')
        click.secho('    Direct content URL: %s' % app['app_url'], fg='bright_white')

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(connect_server.url, abspath(primary_path), app_url, app['app_id'], app['app_guid'], title,
                      app_mode)


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(name='notebook', short_help='Deploy Jupyter notebook to RStudio Connect.',
                help='Deploy a Jupyter notebook to RStudio Connect. This may be done by source or as a static HTML '
                     'page. If the notebook is deployed as a static HTML page (--static), it cannot be scheduled or '
                     'rerun on the Connect server.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to deploy to.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',  help='The URL for the RStudio Connect server to deploy to.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--static', '-S', is_flag=True,
              help='Render the notebook locally and deploy the result as a static document. '
                   'Will not include the notebook source. Static notebooks cannot be re-run on the server.')
@click.option('--new', '-N', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment. '
                   'Cannot be used with --app-id.')
@click.option('--app-id', '-a', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename).')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to Python interpreter whose environment should be used. '
                   'The Python environment must have the rsconnect package installed.')
@click.option('--conda', '-C', is_flag=True,
              help='Use conda to deploy (requires Connect version 1.8.2 or later)')
@click.option('--force-generate', '-g', is_flag=True,
              help='Force generating "requirements.txt" or "environment.yml", even if it already exists.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
@click.argument('file', type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument('extra_files', nargs=-1, type=click.Path(exists=True, dir_okay=False, file_okay=True))
def deploy_notebook(name, server, api_key, insecure, cacert, static, new, app_id, title, python, conda, force_generate,
                    verbose, file, extra_files):
    set_verbosity(verbose)

    with cli_feedback('Checking arguments'):
        app_store = AppStore(file)
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        extra_files = validate_extra_files(dirname(file), extra_files)
        app_id, deployment_name, title, app_mode = \
            gather_basic_deployment_info_for_notebook(connect_server, app_store, file, new, app_id, title, static)

    click.secho('    Deploying %s to server "%s"' % (file, connect_server.url), fg='white')

    _warn_on_ignored_manifest(dirname(file))

    if conda:
        with cli_feedback('Ensuring conda is supported'):
            check_server_capabilities(connect_server, [is_conda_supported_on_server])

    with cli_feedback('Inspecting Python environment'):
        python, environment = get_python_env_info(file, python, not conda, force_generate)

    if force_generate:
        _warn_on_ignored_requirements(dirname(file), environment['filename'])

    with cli_feedback('Creating deployment bundle'):
        bundle = create_notebook_deployment_bundle(file, extra_files, app_mode, python, environment, False)

    _deploy_bundle(connect_server, app_store, file, app_id, app_mode, deployment_name, title, bundle)


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(name='manifest', short_help='Deploy content to RStudio Connect by manifest.',
                help='Deploy content to RStudio Connect using an existing manifest.json file.  The specified file must '
                     'either be named "manifest.json" or refer to a directory that contains a file named '
                     '"manifest.json".')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to deploy to.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',  help='The URL for the RStudio Connect server to deploy to.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--new', '-N', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment.')
@click.option('--app-id', '-a', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename).')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
@click.argument('file', type=click.Path(exists=True, dir_okay=False, file_okay=True))
def deploy_manifest(name, server, api_key, insecure, cacert, new, app_id, title, verbose, file):
    set_verbosity(verbose)

    with cli_feedback('Checking arguments'):
        app_store = AppStore(file)
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        file = validate_manifest_file(file)

        app_id, deployment_name, title, app_mode, package_manager = \
            gather_basic_deployment_info_from_manifest(connect_server, app_store, file, new, app_id, title)

    click.secho('    Deploying %s to server "%s"' % (file, connect_server.url), fg='white')

    if package_manager == 'conda':
        with cli_feedback('Ensuring conda is supported'):
            check_server_capabilities(connect_server, [is_conda_supported_on_server])

    with cli_feedback('Creating deployment bundle'):
        bundle = make_manifest_bundle(file)

    _deploy_bundle(connect_server, app_store, file, app_id, app_mode, deployment_name, title, bundle)


# noinspection SpellCheckingInspection
@deploy.command(name='api', short_help='Deploy a Python API to RStudio Connect.',
                help='Deploy a WSGi-based API module to RStudio Connect. The "directory" argument must refer to an '
                     'existing directory that contains the API code.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to deploy to.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',  help='The URL for the RStudio Connect server to deploy to.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--entrypoint', '-e', help='The module and executable object which serves as the entry point for the '
                                         'WSGi framework of choice (defaults to app:app)')
@click.option('--exclude', '-x', multiple=True,
              help='Specify a glob pattern for ignoring files when building the bundle. This option may be repeated/')
@click.option('--new', '-N', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment. '
                   'Cannot be used with --app-id.')
@click.option('--app-id', '-a', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the directory).')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to Python interpreter whose environment should be used. '
                   'The Python environment must have the rsconnect package installed.')
@click.option('--conda', '-C', is_flag=True, help='Use conda to deploy.')
@click.option('--force-generate', '-g', is_flag=True,
              help='Force generating "requirements.txt" or "environment.yml", even if it already exists.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
@click.argument('directory', type=click.Path(exists=True, dir_okay=True, file_okay=False))
@click.argument('extra_files', nargs=-1, type=click.Path(exists=True, dir_okay=False, file_okay=True))
def deploy_api(name, server, api_key, insecure, cacert, entrypoint, exclude, new, app_id, title, python, conda,
               force_generate, verbose, directory, extra_files):
    set_verbosity(verbose)

    with cli_feedback('Checking arguments'):
        connect_server = _validate_deploy_to_args(name, server, api_key, insecure, cacert)
        module_file = fake_module_file_from_directory(directory)
        extra_files = validate_extra_files(directory, extra_files)
        app_store = AppStore(module_file)
        entrypoint, app_id, deployment_name, title, app_mode = \
            gather_basic_deployment_info_for_api(connect_server, app_store, directory, entrypoint, new, app_id, title)

    click.secho('    Deploying %s to server "%s"' % (directory, connect_server.url), fg='white')

    _warn_on_ignored_manifest(directory)

    with cli_feedback('Checking server capabilities'):
        checks = [are_apis_supported_on_server]
        if conda:
            checks.append(is_conda_supported_on_server)
        check_server_capabilities(connect_server, checks)

    with cli_feedback('Inspecting Python environment'):
        _, environment = get_python_env_info(module_file, python, not conda, force_generate)

    if force_generate:
        _warn_on_ignored_requirements(directory, environment['filename'])

    with cli_feedback('Creating deployment bundle'):
        bundle = create_api_deployment_bundle(directory, extra_files, exclude, entrypoint, app_mode, environment, False)

    _deploy_bundle(connect_server, app_store, directory, app_id, app_mode, deployment_name, title, bundle)


@deploy.command(name='other-content', short_help='Describe deploying other content to RStudio Connect.',
                help='Show help on how to deploy other content to RStudio Connect.')
def deploy_help():
    text = 'To deploy a Shiny application or R Markdown document, use the rsconnect R package in the RStudio IDE.  ' \
           'Or, use rsconnect::writeManifest (again in the IDE) to create a manifest.json file and deploy that using ' \
           'this tool with the command, '
    click.echo('\n'.join(textwrap.wrap(text, 79)))
    click.echo()
    click.echo('    rsconnect deploy manifest [-n <name>|-s <url> -k <key>] <manifest-file>')
    click.echo()


@cli.group(name="write-manifest", no_args_is_help=True,
           short_help='Create a manifest.json file for later deployment.',
           help='Create a manifest.json file for later deployment. This may be used with the git support provided by '
                'RStudio Connect or by using the "deploy manifest" command in this tool.')
def write_manifest():
    pass


@write_manifest.command(name="notebook", short_help='Create a manifest.json file for a Jupyter notebook.',
                        help="Create a manifest.json file for a Jupyter notebook for later deployment. This will "
                             "create an environment file (requirements.txt or environment.yml) if one does not exist. "
                             "All files are created in the same directory as the notebook file.")
@click.option('--force', '-f', is_flag=True, help='Replace manifest.json, if it exists.')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to Python interpreter whose environment should be used. ' +
                   'The Python environment must have the rsconnect package installed.')
@click.option('--conda', '-C', is_flag=True,
              help='Use conda to deploy (requires Connect version 1.8.2 or later)')
@click.option('--force-generate', '-g', is_flag=True,
              help='Force generating "requirements.txt" or "environment.yml", even if it already exists.')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True, dir_okay=False, file_okay=True))
@click.argument('extra_files', nargs=-1, type=click.Path(exists=True, dir_okay=False, file_okay=True))
def write_manifest_notebook(force, python, conda, force_generate, verbose, file, extra_files):
    set_verbosity(verbose)
    with cli_feedback('Checking arguments'):
        validate_file_is_notebook(file)

        base_dir = dirname(file)
        extra_files = validate_extra_files(base_dir, extra_files)
        manifest_path = join(base_dir, 'manifest.json')

        if exists(manifest_path) and not force:
            raise api.RSConnectException('manifest.json already exists. Use --force to overwrite.')

    with cli_feedback('Inspecting Python environment'):
        python, environment = get_python_env_info(file, python, not conda, force_generate)

    with cli_feedback('Creating manifest.json'):
        environment_file_exists = write_notebook_manifest_json(
            file, environment, AppModes.JUPYTER_NOTEBOOK, extra_files
        )

    if environment_file_exists and not force_generate:
        click.secho('    Warning: %s already exists and will not be overwritten.' % environment['filename'],
                    fg='yellow')
    else:
        with cli_feedback('Creating %s' % environment['filename']):
            write_environment_file(environment, base_dir)


# noinspection SpellCheckingInspection
@write_manifest.command(name="api", short_help='Create a manifest.json file for a Python API.',
                        help='Create a manifest.json file for a Python API for later deployment. This will create an '
                             'environment file (requirements.txt or environment.yml) if one does not exist. All files '
                             'are created in the same directory as the API code.')
@click.option('--force', '-f', is_flag=True, help='Replace manifest.json, if it exists.')
@click.option('--entrypoint', '-e', help='The module and executable object which serves as the entry point for the '
                                         'WSGi framework of choice (defaults to app:app)')
@click.option('--exclude', '-x', multiple=True,
              help='Specify a glob pattern for ignoring files when building the bundle. This option may be repeated/')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to Python interpreter whose environment should be used. ' +
                   'The Python environment must have the rsconnect-python package installed.')
@click.option('--conda', '-C', is_flag=True,
              help='Use conda to deploy (requires Connect version 1.8.2 or later)')
@click.option('--force-generate', '-g', is_flag=True,
              help='Force generating "requirements.txt" or "environment.yml", even if it already exists.')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='Print detailed messages')
@click.argument('directory', type=click.Path(exists=True, dir_okay=True, file_okay=False))
@click.argument('extra_files', nargs=-1, type=click.Path(exists=True, dir_okay=False, file_okay=True))
def write_manifest_api(force, entrypoint, exclude, python, conda, force_generate, verbose, directory, extra_files):
    set_verbosity(verbose)
    with cli_feedback('Checking arguments'):
        entrypoint = validate_entry_point(entrypoint)
        extra_files = validate_extra_files(directory, extra_files)
        manifest_path = join(directory, 'manifest.json')

        if exists(manifest_path) and not force:
            raise api.RSConnectException('manifest.json already exists. Use --force to overwrite.')

    with cli_feedback('Inspecting Python environment'):
        _, environment = get_python_env_info(directory, python, not conda, force_generate)

    with cli_feedback('Creating manifest.json'):
        environment_file_exists = write_api_manifest_json(
            directory, entrypoint, environment, AppModes.PYTHON_API, extra_files, exclude
        )

    if environment_file_exists and not force_generate:
        click.secho('    Warning: %s already exists and will not be overwritten.' % environment['filename'],
                    fg='yellow')
    else:
        with cli_feedback('Creating %s' % environment['filename']):
            write_environment_file(environment, directory)


if __name__ == '__main__':
    cli()
    click.echo()
