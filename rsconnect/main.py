import json
import logging
import os
import subprocess

from os.path import abspath, basename, dirname, exists, join, splitext
from pprint import pformat

import click
from six.moves.urllib_parse import urlparse

from rsconnect.actions import set_verbosity, cli_feedback, which_python, inspect_environment, do_ping, \
    make_deployment_name, default_title, default_title_for_manifest
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
server_store.load()
logging.basicConfig()


@click.group(no_args_is_help=True)
def cli():
    pass


# noinspection SpellCheckingInspection
@cli.command(help='Add a server')
@click.option('--name', '-n', required=True, help='Server nickname')
@click.option('--server', '-s', required=True, help='Connect server URL')
@click.option('--api-key', '-k', required=True, help='Connect server API key')
@click.option('--insecure', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', type=click.File(), help='Path to trusted TLS CA certificate.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
def add(name, server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)
    with cli_feedback(''):
        old_server = server_store.get(name)

        # server must be pingable to be added
        ca_data = cacert and cacert.read()
        real_server = do_ping(server, api_key, insecure, ca_data)
        server_store.add(name, real_server, api_key, insecure, ca_data)
        server_store.save()

        if old_server is None:
            click.echo('Added server "%s" with URL %s' % (name, real_server))
        else:
            click.echo('Replaced server "%s" with URL %s' % (name, real_server))


@cli.command(help='Remove a server')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
@click.argument('server')
def remove(server, verbose):
    set_verbosity(verbose)
    with cli_feedback(''):
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
    with cli_feedback(''):
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
    with cli_feedback(''):
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
    click.echo(api.VERSION)


# noinspection SpellCheckingInspection
@cli.command(help='Verify a Connect server URL')
@click.option('--server', '-s', required=True, envvar='CONNECT_SERVER', help='Connect server URL')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY', help='Connect server API key')
@click.option('--insecure', envvar='CONNECT_INSECURE', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='Path to trusted TLS CA certificate.')
@click.option('--verbose', '-v', is_flag=True, help='Print detailed messages')
def test(server, api_key, insecure, cacert, verbose):
    set_verbosity(verbose)
    do_ping(server, api_key, insecure, cacert and cacert.read())


@cli.group(no_args_is_help=True, help="Deploy content to RStudio Connect")
def deploy():
    pass


# noinspection SpellCheckingInspection,DuplicatedCode
@deploy.command(name='notebook', help='Deploy content to RStudio Connect')
@click.option('--server', '-s', envvar='CONNECT_SERVER', help='Connect server URL or saved server name')
@click.option('--api-key', '-k', envvar='CONNECT_API_KEY', help='Connect server API key')
@click.option('--static', is_flag=True,
              help='Deployed a static, pre-rendered notebook. Static notebooks cannot be re-run on the server.')
@click.option('--new', '-n', is_flag=True,
              help='Force a new deployment, even if there is saved metadata from a previous deployment.')
@click.option('--app-id', help='Existing app ID or GUID to replace. Cannot be used with --new.')
@click.option('--title', '-t', help='Title of the content (default is the same as the filename)')
@click.option('--python', type=click.Path(exists=True),
              help='Path to python interpreter whose environment should be used. '
                   'The python environment must have the rsconnect package installed.')
@click.option('--insecure', envvar='CONNECT_INSECURE', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', envvar='CONNECT_CA_CERTIFICATE', type=click.File(),
              help='Path to trusted TLS CA certificate.')
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

    with cli_feedback('Checking arguments'):
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

    with cli_feedback('Inspecting python environment'):
        python = which_python(python)
        logger.debug('Python: %s' % python)
        environment = inspect_environment(python, dirname(file))
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
@deploy.command(name='manifest', short_help='Deploy content to RStudio Connect using an existing manifest.json file')
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

    with cli_feedback('Checking arguments'):
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

        api_client = api.RSConnect(uri, api_key, [], insecure, cadata)

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


@deploy.command(name='help', help='Show help on how to deploy other content to RStudio Connect')
def deploy_help():
    print(
        'To deploy a Shiny app or R Markdown document,\n'
        'use the rsconnect package in the RStudio IDE. Or,\n'
        'use rsconnect::writeManifest to create a manifest.json file\n'
        'and deploy that using this tool with the command\n'
        '"rsconnect deploy manifest".')


@cli.group(name="write-manifest", no_args_is_help=True,
           help="Create a manifest.json file for later deployment from git")
def manifest():
    pass


@manifest.command(name="notebook", help='Create a manifest.json file for a notebook, for later deployment')
@click.option('--force', '-f', is_flag=True, help='Replace manifest.json, if it exists.')
@click.option('--python', type=click.Path(exists=True),
              help='Path to python interpreter whose environment should be used. ' +
                   'The python environment must have the rsconnect package installed.'
              )
@click.option('--verbose', '-v', 'verbose', is_flag=True, help='Print detailed messages')
@click.argument('file', type=click.Path(exists=True))
@click.argument('extra_files', nargs=-1, type=click.Path())
def manifest_notebook(force, python, verbose, file, extra_files):
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
        environment = inspect_environment(python, dirname(file))
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


cli()
click.echo()
