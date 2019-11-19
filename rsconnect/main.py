
import contextlib
import json
import os
import sys
import subprocess
import time
import traceback
from datetime import datetime
from os.path import basename, dirname, exists
from pprint import pformat

import click
from six.moves.urllib_parse import urlparse

from . import api
from .bundle import make_source_bundle


line_width = 60
@contextlib.contextmanager
def CLIFeedback(label, debug):
    click.echo(label + '... ', nl=False)

    def passed():
        click.echo('[', nl=False)
        click.secho('OK   ', fg='green', nl=False)
        click.echo(']')

    def failed(err):
        click.echo('[', nl=False)
        click.secho('ERROR', fg='red', nl=False)
        click.echo(']')
        click.secho(str(err), fg='red')

    try:
        yield
        passed()
    except RSConnectException as exc:
        failed('Error: ' + exc.message)
    except EnvironmentException as exc:
        failed('Error: ' + str(exc))
    except Exception as exc:
        if debug:
            traceback.print_exc()
        failed('Internal error: ' + str(exc))


def which_python(python, env=os.environ):
    if python:
        click.echo('Using packages from specified python: %s' % click.format_filename(python))
        return python

    reticulate_python = env.get('RETICULATE_PYTHON')
    if reticulate_python:
        click.echo('Using packages from RETICULATE_PYTHON: %s' % click.format_filename(reticulate_python))
        return reticulate_python

    click.echo('Using packages from current python: %s' % click.format_filename(sys.executable))
    return sys.executable


def inspect_environment(python, dir, check_output=subprocess.check_output):
    environment_json = check_output([python, '-m', 'rsconnect.environment', dir], universal_newlines=True)
    environment = json.loads(environment_json)
    return environment


def make_deployment_name():
    timestamp = int(1000 * time.mktime(datetime.now().timetuple()))
    return 'deployment-%d' % timestamp


@click.group()
def cli():
    pass

@cli.command()
@click.option('--server', help='Connect server URL')
@click.option('--api-key', help='Connect server API key')
@click.option('--app-id', type=int, help='Existing app ID to replace')
@click.option('--title', help='Title of the content (default is the same as the filename)')
@click.option('--python', help='Path to python interpreter whose environment should be used. The python environment must have the rsconnect package installed.')
@click.option('--insecure', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', help='Path to trusted TLS CA certificate.')
@click.option('--no-browser', is_flag=True, help='Do not open the app after deployment.')
@click.option('--debug', is_flag=True, help='Print detailed error messages on failure.')
@click.argument('file')
@click.argument('extra_files', nargs=-1)
def deploy(server, api_key, app_id, title, python, insecure, cacert, no_browser, debug, file, extra_files):
    click.echo('Deploying %s to %s' % (file, server))

    try:
        uri = urlparse(server)
    except:
        if debug:
            traceback.print_exc()
        click.echo('Could not parse the specified server URL (%s)' % server)
        click.echo('Make sure that the --server option is specified.')
        sys.exit(1)

    if not exists(file):
        click.echo('Could not find file %s.' % file)
        sys.exit(1)

    deployment_name = make_deployment_name()

    try:
        python = which_python(python)
        environment = inspect_environment(python, dirname(file))
        if debug:
            print('Environment: %s' % pformat(environment))
    except EnvironmentException as exc:
        click.echo('Environment inspection failed: %s' % str(exc))
        click.echo('Ensure that the correct python is being used,')
        click.echo('and that it has the rsconnect package installed.')
        sys.exit(1)
    except:
        if debug:
            traceback.print_exc()
        click.echo('Environment inspection failed with an internal error: %s' % str(exc))
        sys.exit(1)

    try:
        bundle = make_source_bundle(file, environment, extra_files)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        click.echo('Bundle creation failed: %s' % str(exc))
        sys.exit(1)

    try:
        app = api.deploy(uri, api_key, app_id, deployment_name, title, bundle, insecure, cacert)
    except api.RSConnectException as exc:
        click.echo('Deployment failed: %s' % exc.message)
        sys.exit(1)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        click.echo('Deployment failed with an internal error: %s' % str(exc))
        sys.exit(1)

    task_id = app['task_id']
    if not no_browser:
        #click.launch(...)


@cli.command()
@click.option('--server', help='Connect server URL')
@click.option('--api-key', help='Connect server API key')
@click.option('--insecure', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', help='Path to trusted TLS CA certificate.')
@click.option('--debug', is_flag=True, help='Print detailed error messages on failure.')
def ping(server, api_key, insecure, cacert, debug):
    click.echo('Pinging server %s... ' % server, nl=False)
    try:
        api.verify_server(server, insecure, cacert)
    except api.RSConnectException as exc:
        click.echo('Server verification failed: %s' % exc.message)
        sys.exit(1)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        click.echo('Server verification failed with an internal error: %s' % str(exc))
        sys.exit(1)
    
    click.echo('OK')

    if api_key:
        click.echo('Verifying API key... ', nl=False)
        try:
            uri = urlparse(server)
        except:
            if debug:
                traceback.print_exc()
            click.echo('Could not parse the specified server URL (%s)' % server)
            click.echo('Make sure that the --server option is specified.')
            sys.exit(1)

        try:
            api.verify_api_key(uri, api_key, insecure, cacert)
        except api.RSConnectException as exc:
            click.echo('API key verification failed: %s' % exc.message)
            sys.exit(1)
        except Exception as exc:
            if debug:
                traceback.print_exc()
            click.echo('API key verification failed with an internal error: %s' % str(exc))
            sys.exit(1)
        
        click.echo('OK')

cli()
