import json
import logging
import os
import subprocess
import textwrap

from os.path import abspath, basename, dirname, exists, join, splitext
from pprint import pformat

import click
from six import text_type
from six.moves.urllib_parse import urlparse

from rsconnect import VERSION
from rsconnect.actions import set_verbosity, cli_feedback, which_python, inspect_environment, make_deployment_name, \
    default_title, default_title_for_manifest, test_server, test_api_key, gather_server_details
from . import api
from .bundle import (
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_source_manifest,
    manifest_add_buffer,
    manifest_add_file)
from .metadata import ServerStore, AppStore

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
    pass


@cli.command(help='Show the version of rsconnect-python.')
def version():
    click.echo(VERSION)


# noinspection SpellCheckingInspection
@cli.command(help='Verify that a URL refers to a running RStudio Connect server.  This involves making sure that the '
                  'URL is both accessible and running RStudio Connect.   If an API key is provided, it is checked to '
                  'make sure it can be used to authenticate against the RStudio Connect server.')
@click.option('--server', '-s', envvar='CONNECT_SERVER', required=True, help='The URL for the RStudio Connect server.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
def test(server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)

    real_server, me, _ = _test_server_and_api(server, api_key, insecure, cacert)

    if real_server:
        click.echo('    RStudio Connect URL: %s' % real_server)

    if me:
        click.echo('    Username: %s' % me)


def _test_server_and_api(server, api_key, insecure, ca_cert):
    ca_data = ca_cert and text_type(ca_cert.read())
    me = None

    with cli_feedback('Checking %s' % server):
        real_server, _ = test_server(server, insecure, ca_data)

    if real_server and api_key:
        with cli_feedback('Checking API key'):
            me = test_api_key(real_server, api_key, insecure, ca_data)

    return real_server, me, ca_data


# noinspection SpellCheckingInspection
@cli.command(help='Associate a simple nickname with the information needed to interact with an RStudio Connect server.')
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
    real_server, _, ca_data = _test_server_and_api(server, api_key, insecure, cacert)

    server_store.set(name, real_server, api_key, insecure, ca_data)

    if old_server:
        click.echo('Updated server "%s" with URL %s' % (name, real_server))
    else:
        click.echo('Added server "%s" with URL %s' % (name, real_server))


@cli.command('list', help='List the known RStudio Connect servers.')
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
                    click.echo('    Insecure mode (TLS certificate validation disabled)')
                if server['ca_cert']:
                    click.echo('    Client TLS certificate data provided')
                click.echo()


# noinspection SpellCheckingInspection
@cli.command(help='Show version details about an RStudio Connect server and the versions of Python installed.')
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
        server, api_key, insecure, ca_data = _validate_deploy_to_args(name, server, api_key, insecure, cacert)

    with cli_feedback('Gathering details'):
        server_details = gather_server_details(server, api_key, insecure, ca_data)

    if server_details:
        python_versions = server_details['python']
        conda_details = server_details['conda']
        click.echo('    RStudio Connect version: %s' % server_details['connect'])

        if len(python_versions) == 0:
            click.echo('    No versions of Python are installed.')
        else:
            click.echo('    Installed versions of Python:')
            for python_version in python_versions:
                click.echo('        %s' % python_version)

        click.echo('    Conda: %ssupported' % ('' if conda_details['supported'] else 'not '))


@cli.command(help='Remove the information about an RStudio Connect server by nickname or URL.  '
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


@cli.command(help='Show saved information about the specified deployment.')
@click.argument('file', type=click.Path(exists=True))
def info(file):
    with cli_feedback(''):
        app_store = AppStore(file)
        deployments = app_store.get_all()

        user_app_modes = {
            'unknown': 'unknown',
            'shiny': 'Shiny App',
            'rmd-shiny': 'Shiny App (Rmd)',
            'rmd-static': 'R Markdown',
            'static': 'Static HTML',
            'api': 'API',
            'tensorflow-saved-model': 'TensorFlow Model',
            'jupyter-static': 'Jupyter Notebook',
        }

        if deployments:
            click.echo('Loaded deployment information from %s' % abspath(app_store.get_path()))

            for deployment in deployments:
                click.echo()
                click.echo('Server URL: %s' % deployment.get('server_url'))
                click.echo('App URL:    %s' % deployment.get('app_url'))
                click.echo('App ID:     %s' % deployment.get('app_id'))
                click.echo('App GUID:   %s' % deployment.get('app_guid'))
                click.echo('Title:      "%s"' % deployment.get('title'))
                click.echo('Filename:   %s' % deployment.get('filename'))
                click.echo('Type:       %s' % user_app_modes.get(deployment.get('app_mode')))
        else:
            click.echo('No saved deployment information was found.')


@cli.group(no_args_is_help=True, help="Deploy content to RStudio Connect.")
def deploy():
    pass


def _validate_deploy_to_args(name, server, api_key, insecure, ca_cert):
    ca_data = ca_cert and text_type(ca_cert.read())

    if name and server:
        raise api.RSConnectException('You must specify only one of -n/--name or -s/--server, not both.')

    real_server, api_key, insecure, ca_data, from_store = server_store.resolve(name, server, api_key, insecure, ca_data)

    # This can happen if the user specifies neither --name or --server and there's not
    # a single default to go with.
    if not real_server:
        raise api.RSConnectException('You must specify one of -n/--name or -s/--server.')

    if not from_store:
        real_server, _ = test_server(real_server, insecure, ca_data)

    if not urlparse(real_server).netloc:
        raise api.RSConnectException('Invalid server URL: "%s".' % real_server)

    if not api_key:
        raise api.RSConnectException('An API key must be specified for "%s".' % real_server)

    # If our info came from the command line, we really should test it out first.
    if not from_store:
        _ = test_api_key(real_server, api_key, insecure, ca_data)

    return real_server, api_key, insecure, ca_data


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(name='notebook', help='Deploy content to RStudio Connect.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to deploy to.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',  help='The URL for the RStudio Connect server to deploy to.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--static', '-S', is_flag=True,
              help='Render a notebook locally and deploy the result as a static notebook. '
                   'Will not include the notebook source. Static notebooks cannot be re-run on the server.')
@click.option('--new', '-N', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment.')
@click.option('--app-id', '-a', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename).')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to python interpreter whose environment should be used. '
                   'The python environment must have the rsconnect package installed.')
@click.option('--compatibility-mode', is_flag=True, help='Force freezing the current environment using pip instead ' +
                                                         'of conda, when conda is not supported on RStudio Connect ' +
                                                         '(version<=1.8.0)')
@click.option('--force-generate', is_flag=True, help='Force generating "requirements.txt" or "environment.yml", ' +
                                                     'even if it already exists')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
@click.argument('file', type=click.Path(exists=True))
@click.argument('extra_files', nargs=-1, type=click.Path())
def deploy_notebook(name, server, api_key, static, new, app_id, title, python, compatibility_mode, force_generate, insecure, cacert, verbose, file,
                    extra_files):
    set_verbosity(verbose)
    logger = logging.getLogger('rsconnect')

    with cli_feedback('Checking arguments'):
        app_store = AppStore(file)

        server, api_key, insecure, ca_data = _validate_deploy_to_args(name, server, api_key, insecure, cacert)

        file_suffix = splitext(file)[1].lower()
        if file_suffix != '.ipynb':
            raise api.RSConnectException(
                'Only Jupyter notebook (.ipynb) files can be deployed with "deploy notebook".'
                'Run "deploy help" for more information.')

        # we check the extra files ourselves, since they are paths relative to the base file
        for extra in extra_files:
            if not exists(join(dirname(file), extra)):
                raise api.RSConnectException('Could not find file %s in %s' % (extra, os.getcwd()))

        deployment_name = make_deployment_name()
        if not title:
            title = default_title(file)

        api_client = api.RSConnect(server, api_key, insecure, ca_data)

        if app_id is not None:
            # Don't read app metadata if app-id is specified. Instead, we need
            # to get this from Connect.
            app = api_client.app_get(app_id)
            app_mode = api.app_modes.get(app.get('app_mode', 0), 'unknown')

            logger.debug('Using app mode from app %s: %s' % (app_id, app_mode))
        elif static:
            app_mode = 'static'
        else:
            app_mode = 'jupyter-static'

        if new:
            if app_id is not None:
                raise api.RSConnectException('Cannot specify both --new and --app-id.')
        elif app_id is None:
            # Possible redeployment - check for saved metadata.
            # Use the saved app information unless overridden by the user.
            app_id, title, app_mode = app_store.resolve(server, app_id, title, app_mode)
            if static and app_mode != 'static':
                raise api.RSConnectException('Cannot change app mode to "static" once deployed. '
                                             'Use --new to create a new deployment.')

    if name or server:
        click.secho('    Deploying %s to server "%s"' % (file, server), fg='white')
    else:
        click.secho('    Deploying %s' % file, fg='white')

    with cli_feedback('Inspecting python environment'):
        python = which_python(python)
        logger.debug('Python: %s' % python)
        environment = inspect_environment(python, dirname(file), compatibility_mode=compatibility_mode,
                                          force_generate=force_generate)
        logger.debug('Environment: %s' % pformat(environment))

    with cli_feedback('Creating deployment bundle'):
        if app_mode == 'static':
            try:
                bundle = make_notebook_html_bundle(file, python)
            except subprocess.CalledProcessError as exc:
                # Jupyter rendering failures are often due to
                # user code failing, vs. an internal failure of rsconnect-python.
                raise api.RSConnectException(str(exc))
        else:
            bundle = make_notebook_source_bundle(file, environment, extra_files)

    with cli_feedback('Uploading bundle'):
        app = api_client.deploy(app_id, deployment_name, title, bundle)

    with cli_feedback('Saving deployment data'):
        app_store.set(server, abspath(file), app['app_url'], app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()

    with cli_feedback(''):
        click.secho('\nDeployment log:', fg='bright_white')
        app_url = api_client.wait_for_task(app['app_id'], app['task_id'], click.echo)
        click.secho('Deployment completed successfully.\nApp URL: %s' % app_url, fg='bright_white')

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(server, abspath(file), app_url, app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(name='manifest', short_help='Deploy content to RStudio Connect using an existing manifest.json file.')
@click.option('--name', '-n', help='The nickname of the RStudio Connect server to deploy to.')
@click.option('--server', '-s', envvar='CONNECT_SERVER',  help='The URL for the RStudio Connect server to deploy to.')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY',
              help='The API key to use to authenticate with RStudio Connect.')
@click.option('--new', '-N', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment.')
@click.option('--app-id', '-a', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename).')
@click.option('--insecure', '-i', envvar='CONNECT_INSECURE', is_flag=True,
              help='Disable TLS certification/host validation.')
@click.option('--cacert', '-c', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='The path to trusted TLS CA certificates.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages.')
@click.argument('file', type=click.Path(exists=True))
def deploy_manifest(name, server, api_key, new, app_id, title, insecure, cacert, verbose, file):
    set_verbosity(verbose)

    with cli_feedback('Checking arguments'):
        app_store = AppStore(file)

        server, api_key, insecure, ca_data = _validate_deploy_to_args(name, server, api_key, insecure, cacert)

        if basename(file) != 'manifest.json':
            raise api.RSConnectException(
                'The deploy manifest command requires an existing '
                'manifest.json file to be provided on the command line.')

        with open(file, 'r') as f:
            source_manifest = json.load(f)

        deployment_name = make_deployment_name()
        if not title:
            title = default_title_for_manifest(source_manifest)

        app_mode = source_manifest['metadata']['appmode']

        if new:
            if app_id is not None:
                raise api.RSConnectException('Cannot specify both --new and --app-id.')
        elif app_id is None:
            # Possible redeployment - check for saved metadata.
            # Use the saved app information unless overridden by the user.
            app_id, title, app_mode = app_store.resolve(server, app_id, title, app_mode)

        api_client = api.RSConnect(server, api_key, insecure, ca_data)

    if name or server:
        click.secho('    Deploying %s to server "%s"' % (file, server), fg='white')
    else:
        click.secho('    Deploying %s' % file, fg='white')

    with cli_feedback('Creating deployment bundle'):
        bundle = make_manifest_bundle(file)

    with cli_feedback('Uploading bundle'):
        app = api_client.deploy(app_id, deployment_name, title, bundle)

    with cli_feedback('Saving deployment data'):
        app_store.set(server, abspath(file), app['app_url'], app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()

    with cli_feedback(''):
        click.secho('\nDeployment log:', fg='bright_white')
        app_url = api_client.wait_for_task(app['app_id'], app['task_id'], click.echo)
        click.secho('Deployment completed successfully.\nApp URL: %s' % app_url, fg='bright_white')

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(server, abspath(file), app_url, app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()


@deploy.command(name='other-content', help='Show help on how to deploy other content to RStudio Connect.')
def deploy_help():
    text = 'To deploy a Shiny application or R Markdown document, use the rsconnect R package in the RStudio IDE.  ' \
           'Or, use rsconnect::writeManifest (again in the IDE) to create a manifest.json file and deploy that using ' \
           'this tool with the command, '
    click.echo('\n'.join(textwrap.wrap(text, 79)))
    click.echo()
    click.echo('    rsconnect deploy manifest [-n <name>|-s <url> -k <key>] <manifest-file>')
    click.echo()


@cli.group(name="write-manifest", no_args_is_help=True,
           help="Create a manifest.json file for later deployment from git")
def manifest():
    pass


@manifest.command(name="notebook", help='Create a manifest.json file for a notebook, for later deployment. '
                                        'Creates an environment file (requirements.txt) if one does not exist. '
                                        'All files are created in the same directory as the notebook file.')
@click.option('--force', '-f', is_flag=True, help='Replace manifest.json, if it exists.')
@click.option('--python', '-p', type=click.Path(exists=True),
              help='Path to python interpreter whose environment should be used. ' +
                   'The python environment must have the rsconnect package installed.'
              )
@click.option('--compatibility-mode', is_flag=True, help='Force freezing the current environment using pip instead ' +
                                                         'of conda, when conda is not supported on RStudio Connect ' +
                                                         '(version<=1.8.0)')
@click.option('--force-generate', is_flag=True, help='Force generating "requirements.txt" or "environment.yml", ' +
                                                     'even if it already exists')
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True))
@click.argument('extra_files', nargs=-1, type=click.Path())
def manifest_notebook(force, python, compatibility_mode, force_generate, verbose, file, extra_files):
    set_verbosity(verbose)
    with cli_feedback('Checking arguments'):
        if not file.endswith('.ipynb'):
            raise api.RSConnectException('Can only create a manifest for a Jupyter Notebook (.ipynb file).')

        base_dir = dirname(file)

        manifest_path = join(base_dir, 'manifest.json')
        if exists(manifest_path) and not force:
            raise api.RSConnectException('manifest.json already exists. Use --force to overwrite.')

    with cli_feedback('Inspecting python environment'):
        python = which_python(python)
        environment = inspect_environment(python, dirname(file), compatibility_mode=compatibility_mode,
                                          force_generate=force_generate)
        environment_filename = environment['filename']
        if verbose:
            click.echo('Python: %s' % python)
            click.echo('Environment: %s' % pformat(environment))

    with cli_feedback('Creating manifest.json'):
        notebook_filename = basename(file)
        manifest_data = make_source_manifest(notebook_filename, environment, 'jupyter-static')
        manifest_add_file(manifest_data, notebook_filename, base_dir)
        manifest_add_buffer(manifest_data, environment_filename, environment['contents'])

        for rel_path in extra_files:
            manifest_add_file(manifest_data, rel_path, base_dir)

        with open(manifest_path, 'w') as f:
            json.dump(manifest_data, f, indent=2)

    environment_file_path = join(base_dir, environment_filename)
    if exists(environment_file_path):
        click.echo('%s already exists and will not be overwritten.' % environment_filename)
    else:
        with cli_feedback('Creating %s' % environment_filename):
            with open(environment_file_path, 'w') as f:
                f.write(environment['contents'])


if __name__ == '__main__':
    cli()
    click.echo()
