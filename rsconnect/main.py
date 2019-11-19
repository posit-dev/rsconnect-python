
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
from .environment import EnvironmentException
from .bundle import make_source_bundle


line_width = 45
debug = False

click.echo()

@contextlib.contextmanager
def CLIFeedback(label):
    if label:
        pad = line_width - len(label)
        click.secho(label + '... ' + ' ' * pad, nl=False, fg='bright_white')

    def passed():
        if label:
            click.secho('[', nl=False, fg='bright_white')
            click.secho('OK', fg='bright_green', nl=False)
            click.secho(']', fg='bright_white')

    def failed(err):
        if label:
            click.secho('[', nl=False, fg='bright_white')
            click.secho('ERROR', fg='red', nl=False)
            click.secho(']', fg='bright_white')
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
        if debug:
            traceback.print_exc()
        failed('Internal error: ' + str(exc))


def which_python(python, env=os.environ):
    if python:
        return python

    if 'RETICULATE_PYTHON' in env:
        return env['RETICULATE_PYTHON']

    return sys.executable


def inspect_environment(python, dir, check_output=subprocess.check_output):
    environment_json = check_output([python, '-m', 'rsconnect.environment', dir], universal_newlines=True)
    environment = json.loads(environment_json)
    return environment


def make_deployment_name():
    timestamp = int(1000 * time.mktime(datetime.now().timetuple()))
    return 'deployment-%d' % timestamp


def read_cert(cacert):
    if cacert:
        with open(cacert, 'rb') as f:
            return f.read()
    else:
        return None


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
@click.option('--debug', '_debug', is_flag=True, help='Print detailed error messages on failure.')
@click.argument('file')
@click.argument('extra_files', nargs=-1)
def deploy(server, api_key, app_id, title, python, insecure, cacert, _debug, file, extra_files):
    global debug
    debug = _debug

    click.secho('Deploying %s to %s' % (file, server), fg='bright_white')

    with CLIFeedback('Checking server address'):
        uri = urlparse(server)

    if not exists(file):
        click.secho('Could not find file %s' % file, fg='bright_red')
        sys.exit(1)

    deployment_name = make_deployment_name()
    if not title:
        title = basename(file).rsplit('.')[0]

    with CLIFeedback('Inspecting python environment'):
        python = which_python(python)
        environment = inspect_environment(python, dirname(file))
        if debug:
            click.echo('Python: %s' % python)
            click.echo('Environment: %s' % pformat(environment))

    with CLIFeedback('Creating deployment bundle'):
        bundle = make_source_bundle(file, environment, extra_files)

    with CLIFeedback('Uploading bundle'):
        cadata = read_cert(cacert)
        app = api.deploy(uri, api_key, app_id, deployment_name, title, bundle, insecure, cadata)

        task_id = app['task_id']

    click.secho('\nDeployment log:', fg='bright_white')
    last_status = None

    while True:
        time.sleep(0.5)

        with CLIFeedback(''):
            task_status = api.task_get(uri, api_key, task_id, last_status, app['cookies'], insecure, cadata)

            if task_status['last_status'] != last_status:
                for line in task_status['status']:
                    click.secho(line)
                    last_status = task_status['last_status']

            if task_status['finished']:
                exit_code = task_status['code']
                if exit_code != 0:
                    click.secho('Task exited with status %d.' % exit_code, fg='bright_red')
                    sys.exit(1)

                click.secho('Deployment completed successfully.', fg='bright_white')
                app_config = api.app_config(uri, api_key, app['app_id'], insecure, cadata)
                app_url = app_config['config_url']
                click.secho('App URL: %s' % app_url, fg='bright_white')
                break


@cli.command()
@click.option('--server', help='Connect server URL')
@click.option('--api-key', help='Connect server API key')
@click.option('--insecure', is_flag=True, help='Disable TLS certification validation.')
@click.option('--cacert', help='Path to trusted TLS CA certificate.')
@click.option('--debug', '_debug', is_flag=True, help='Print detailed error messages on failure.')
def ping(server, api_key, insecure, cacert, _debug):
    global debug
    debug = _debug

    with CLIFeedback('Pinging %s' % server):
        cadata = read_cert(cacert)
        api.verify_server(server, insecure, cadata)
    
    if api_key:
        with CLIFeedback('Verifying API key'):
            uri = urlparse(server)
            api.verify_api_key(uri, api_key, insecure, cacert)

cli()
click.echo()
