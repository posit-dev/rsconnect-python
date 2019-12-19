
import contextlib
import json
import logging
import os
import random
import sys
import subprocess
import time
import traceback
from datetime import datetime
from os.path import abspath, basename, dirname, exists, join, splitext
from pprint import pformat

import click
from six.moves.urllib_parse import urlparse

from . import api
from .environment import EnvironmentException
from .bundle import (
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_source_manifest,
    manifest_add_buffer,
    manifest_add_file)
from .metadata import ServerStore, AppStore

line_width = 45
server_store = ServerStore()
server_store.load()
logging.basicConfig()


@contextlib.contextmanager
def CLIFeedback(label):
    """Context manager for OK/ERROR feedback from the CLI.

    If the enclosed block succeeds, OK will be emitted.
    If it fails, ERROR will be emitted.
    Errors will also be classified as operational errors (prefixed with 'Error')
    vs. internal errors (prefixed with 'Internal Error'). In verbose mode,
    tracebacks will be emitted for internal errors.
    """
    if label:
        pad = line_width - len(label)
        click.secho(label + '... ' + ' ' * pad, nl=False, fg='bright_white')

    def passed():
        if label:
            click.secho('[OK]', fg='bright_green')

    def failed(err):
        if label:
            click.secho('[ERROR]', fg='red')
        click.secho(str(err), fg='bright_red')
        sys.exit(1)

    try:
        yield
        passed()
    except api.RSConnectException as exc:
        failed('Error: ' + exc.message)
    except EnvironmentException as exc:
        failed('Error: ' + str(exc))
    except Exception as exc:
        if click.get_current_context('verbose'):
            traceback.print_exc()
        failed('Internal error: ' + str(exc))


def set_verbosity(verbose):
    """Set the verbosity level based on a passed flag

    :param verbose: boolean specifying verbose or not
    """
    logger = logging.getLogger('rsconnect')
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
        return python

    if 'RETICULATE_PYTHON' in env:
        return env['RETICULATE_PYTHON']

    return sys.executable


def inspect_environment(python, dir, check_output=subprocess.check_output):
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    environment_json = check_output([python, '-m', 'rsconnect.environment', dir], universal_newlines=True)
    environment = json.loads(environment_json)
    return environment


def make_deployment_name():
    """Produce a unique name for this deployment as required by the Connect API.

    This is based on the current unix timestamp. Since the millisecond portion
    is zero on some systems, we add some jitter.
    """
    timestamp = int(1000 * time.mktime(datetime.now().timetuple())) + random.randint(0, 999)
    return 'deployment-%d' % timestamp


def default_title(filename):
    """Produce a default content title from the file path"""
    return basename(filename).rsplit('.')[0]


def default_title_for_manifest(manifest):
    """Produce a default content title from the contents of a manifest"""
    filename = None

    metadata = manifest.get('metadata')
    if metadata:
        filename = metadata.get('entrypoint') or metadata.get('primary_rmd') or metadata.get('primary_html')
    return default_title(filename or 'manifest.json')


def do_ping(server, api_key, insecure, cadata):
    """Test the given server URL to see if it's running Connect.

    If api_key is set, also validate the API key.
    Raises an exception on failure, otherwise returns None.
    """
    with CLIFeedback('Checking %s' % server):
        uri = urlparse(server)
        if not uri.netloc:
            raise api.RSConnectException('Invalid server URL: "%s"' % server)
        api.verify_server(server, insecure, cadata)
    
    if api_key:
        with CLIFeedback('Verifying API key'):
            uri = urlparse(server)
            api.verify_api_key(uri, api_key, insecure, cadata)


@click.group(no_args_is_help=True)
def cli():
    pass


@cli.command(help='Add a server')
@click.option('--name', '-n', required=True, help='Server nickname')
@click.option('--server', '-s', required=True, help='Connect server URL')
@click.option('--api-key','-k',required=True, help='Connect server API key')
@click.option('--insecure', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', type=click.File(), help='Path to trusted TLS CA certificate.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
def add(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)
    with CLIFeedback(''):
        old_server = server_store.get(name)

        # server must be pingable to be added
        cadata = cacert and cacert.read()
        do_ping(server, api_key, insecure, cadata)
        server_store.add(name, server, api_key, insecure, cadata)
        server_store.save()

        if old_server is None:
            click.echo('Added server "%s" with URL %s' % (name, server))
        else:
            click.echo('Replaced server "%s" with URL %s' % (name, server))


@cli.command(help='Remove a server')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
@click.argument('server')
def remove(server, verbose):
    set_verbosity(verbose)
    with CLIFeedback(''):
        if server_store.get(server) is None:
            click.echo('Server "%s" was not found' % server)
        else:
            server_store.remove(server)
            server_store.save()
            click.echo('Removed server "%s"' % server)


@cli.command('list', help='List saved servers')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
def list_servers(verbose):
    set_verbosity(verbose)
    with CLIFeedback(''):
        servers = server_store.list()

        click.echo('Server information from %s' % server_store.get_path())

        if not servers:
            click.echo('No servers are saved. To add a server, see `rsconnect add --help`.')
        else:
            click.echo()
            for server in servers:
                click.echo('Server "%s"' % server['name'])
                click.echo('    URL: %s' % server['url'])
                if server['api_key']:
                    click.echo('    API key is saved')
                if server['insecure']:
                    click.echo('    Insecure mode (TLS certificate validation disabled)')
                if server['ca_cert']:
                    click.echo('    TLS certificate file: %s' % server['ca_cert'])
                click.echo()


@cli.command(help='Show saved information about the specified deployment')
@click.argument('file', type=click.Path(exists=True))
def info(file):
    with CLIFeedback(''):
        app_store = AppStore(file)
        app_store.load()
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
            click.echo('Loaded deployment information from %s' % app_store.get_path())

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


@cli.command(help='Show the version of rsconnect-python')
def version():
    with CLIFeedback(''):
        version_file = join(dirname(__file__), 'version.txt')
        with open(version_file, 'r') as f:
            version = f.read().strip()
            click.echo(version)


@cli.command(help='Verify a Connect server URL')
@click.option('--server', '-s', required=True, envvar='CONNECT_SERVER', help='Connect server URL')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY', help='Connect server API key')
@click.option('--insecure', envvar='CONNECT_INSECURE', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', envvar='CONNECT_CA_CERTIFICATE', type=click.File(), help='Path to trusted TLS CA certificate.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
def test(server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)
    do_ping(server, api_key, insecure, cacert and cacert.read())


@cli.group(no_args_is_help=True)
def deploy():
    pass


@deploy.command(name='notebook', help='Deploy content to RStudio Connect')
@click.option('--server', '-s', envvar='CONNECT_SERVER', help='Connect server URL or saved server name')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY', help='Connect server API key')
@click.option('--static', is_flag=True, help='Deployed a static, pre-rendered notebook. Static notebooks cannot be re-run on the server.')
@click.option('--new', '-n', is_flag=True, help='Force a new deployment, even if there is saved metadata from a previous deployment.')
@click.option('--app-id', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename)')
@click.option('--python', type=click.Path(exists=True), help='Path to python interpreter whose environment should be used. The python environment must have the rsconnect package installed.')
@click.option('--insecure', envvar='CONNECT_INSECURE', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', envvar='CONNECT_CA_CERTIFICATE', type=click.File(), help='Path to trusted TLS CA certificate.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True))
@click.argument('extra_files', nargs=-1, type=click.Path())
def deploy_notebook(server, api_key, static, new, app_id, title, python, insecure, cacert, verbose, file, extra_files):
    set_verbosity(verbose)
    logger = logging.getLogger('rsconnect')
    if server:
        click.secho('Deploying %s to server "%s"' % (file, server), fg='bright_white')
    else:
        click.secho('Deploying %s' % file, fg='bright_white')

    with CLIFeedback('Checking arguments'):
        app_store = AppStore(file)
        app_store.load()

        server, api_key, insecure, cadata = server_store.resolve(server, api_key, insecure, cacert and cacert.read())
        uri = urlparse(server)
        if not uri.netloc:
            raise api.RSConnectException('Invalid server URL: "%s"' % server)

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

        api_client = api.RSConnect(uri, api_key, [], insecure, cadata)

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

    with CLIFeedback('Inspecting python environment'):
        python = which_python(python)
        logger.debug('Python: %s' % python)
        environment = inspect_environment(python, dirname(file))
        logger.debug('Environment: %s' % pformat(environment))

    with CLIFeedback('Creating deployment bundle'):
        if app_mode == 'static':
            try:
                bundle = make_notebook_html_bundle(file, python)
            except subprocess.CalledProcessError as exc:
                # Jupyter rendering failures are often due to 
                # user code failing, vs. an internal failure of rsconnect-python.
                raise api.RSConnectException(str(exc))
        else:
            bundle = make_notebook_source_bundle(file, environment, extra_files)

    with CLIFeedback('Uploading bundle'):
        app = api_client.deploy(app_id, deployment_name, title, bundle)

    with CLIFeedback('Saving deployment data'):
        app_store.set(server, abspath(file), app['app_url'], app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()

    with CLIFeedback(''):
        click.secho('\nDeployment log:', fg='bright_white')
        app_url = api_client.wait_for_task(app['app_id'], app['task_id'], click.echo)
        click.secho('Deployment completed successfully.\nApp URL: %s' % app_url, fg='bright_white')

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(server, abspath(file), app_url, app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()


@deploy.command(name='manifest', help='Deploy content to RStudio Connect using an existing manifest.json file')
@click.option('--server', '-s', envvar='CONNECT_SERVER', help='Connect server URL or saved server name')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY', help='Connect server API key')
@click.option('--new', '-n', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment.'
              )
@click.option('--app-id', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename)')
@click.option('--insecure', envvar='CONNECT_INSECURE', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='Path to trusted TLS CA certificate.'
              )
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True))
def deploy_manifest(server, api_key, new, app_id, title, insecure, cacert, verbose, file):
    set_verbosity(verbose)
    if server:
        click.secho('Deploying %s to server "%s"' % (file, server), fg='bright_white')
    else:
        click.secho('Deploying %s' % file, fg='bright_white')

    with CLIFeedback('Checking arguments'):
        app_store = AppStore(file)
        app_store.load()

        server, api_key, insecure, cadata = server_store.resolve(server, api_key, insecure, cacert and cacert.read())
        uri = urlparse(server)
        if not uri.netloc:
            raise api.RSConnectException('Invalid server URL: "%s"' % server)

        if basename(file) != 'manifest.json':
            raise api.RSConnectException(
                'The deploy manifest command requires an existing '
                'manifest.json file to be provided on the command line.')

        with open(file, 'r') as f:
            manifest = json.load(f)

        deployment_name = make_deployment_name()
        if not title:
            title = default_title_for_manifest(manifest)

        app_mode = manifest['metadata']['appmode']

        if new:
            if app_id is not None:
                raise api.RSConnectException('Cannot specify both --new and --app-id.')
        elif app_id is None:
            # Possible redeployment - check for saved metadata.
            # Use the saved app information unless overridden by the user.
            app_id, title, app_mode = app_store.resolve(server, app_id, title, app_mode)
    
        api_client = api.RSConnect(uri, api_key, [], insecure, cadata)

    with CLIFeedback('Creating deployment bundle'):
        bundle = make_manifest_bundle(file)

    with CLIFeedback('Uploading bundle'):
        app = api_client.deploy(app_id, deployment_name, title, bundle)

    with CLIFeedback('Saving deployment data'):
        app_store.set(server, abspath(file), app['app_url'], app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()

    with CLIFeedback(''):
        click.secho('\nDeployment log:', fg='bright_white')
        app_url = api_client.wait_for_task(app['app_id'], app['task_id'], click.echo)
        click.secho('Deployment completed successfully.\nApp URL: %s' % app_url, fg='bright_white')

        # save the config URL, replacing the old app URL we got during deployment
        # (which is the Open Solo URL).
        app_store.set(server, abspath(file), app_url, app['app_id'], app['app_guid'], title, app_mode)
        app_store.save()


@deploy.command(name='help', help='Show help on how to deploy other content to RStudio Connect')
def deploy_help():
    print(
        'To deploy a Shiny app or R Markdown document,\n'
        'use the rsconnect package in the RStudio IDE. Or,\n'
        'use rsconnect::writeManifest to create a manifest.json file\n'
        'and deploy that using this tool with the command\n'
        '"rsconnect deploy manifest".')


@cli.command(help='Create a manifest.json file for a notebook, for later deployment')
@click.option('--force', '-f', is_flag=True, help='Replace manifest.json, if it exists.')
@click.option('--python', type=click.Path(exists=True),
              help='Path to python interpreter whose environment should be used. ' +
                   'The python environment must have the rsconnect package installed.'
              )
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True))
@click.argument('extra_files', nargs=-1, type=click.Path())
def manifest(force, python, verbose, file, extra_files):
    set_verbosity(verbose)
    with CLIFeedback('Checking arguments'):
        if not file.endswith('.ipynb'):
            raise api.RSConnectException('Can only create a manifest for a Jupyter Notebook (.ipynb file).')

        base_dir = dirname(file)

        manifest_path = join(base_dir, 'manifest.json')
        if exists(manifest_path) and not force:
            raise api.RSConnectException('manifest.json already exists. Use --force to overwrite.')

    with CLIFeedback('Inspecting python environment'):
        python = which_python(python)
        environment = inspect_environment(python, dirname(file))
        environment_filename = environment['filename']
        if verbose:
            click.echo('Python: %s' % python)
            click.echo('Environment: %s' % pformat(environment))

    with CLIFeedback('Creating manifest.json'):
        notebook_filename = basename(file)
        manifest = make_source_manifest(notebook_filename, environment, 'jupyter-static')
        manifest_add_file(manifest, notebook_filename, base_dir)
        manifest_add_buffer(manifest, environment_filename, environment['contents'])

        for rel_path in extra_files:
            manifest_add_file(manifest, rel_path, base_dir)

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

    environment_file_path = join(base_dir, environment_filename)
    if exists(environment_file_path):
        click.echo('%s already exists and will not be overwritten.' % environment_filename)
    else:
        with CLIFeedback('Creating %s' % environment_filename):
            with open(environment_file_path, 'w') as f:
                f.write(environment['contents'])


cli()
click.echo()
