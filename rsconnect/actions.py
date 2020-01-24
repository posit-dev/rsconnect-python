import contextlib
import json
import logging
import os
import time
import traceback
from datetime import datetime
import random
import sys
import subprocess
from os.path import basename

from rsconnect import api
from .environment import EnvironmentException

import click
from six.moves.urllib_parse import urlparse

line_width = 45


@contextlib.contextmanager
def cli_feedback(label):
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


def inspect_environment(python, directory, check_output=subprocess.check_output):
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    environment_json = check_output([python, '-m', 'rsconnect.environment', directory], universal_newlines=True)
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


def default_title_for_manifest(the_manifest):
    """Produce a default content title from the contents of a manifest"""
    filename = None

    metadata = the_manifest.get('metadata')
    if metadata:
        # noinspection SpellCheckingInspection
        filename = metadata.get('entrypoint') or metadata.get('primary_rmd') or metadata.get('primary_html')
    return default_title(filename or 'manifest.json')


def verify_server(server, insecure, ca_data):
    uri = urlparse(server)
    if not uri.netloc:
        raise api.RSConnectException('Invalid server URL: "%s"' % server)
    api.verify_server(server, insecure, ca_data)


def verify_api_key(server, api_key, insecure, ca_data):
    uri = urlparse(server)
    api.verify_api_key(uri, api_key, insecure, ca_data)


def do_ping(server, api_key, insecure, ca_data):
    """Test the given server URL to see if it's running Connect.

    If api_key is set, also validate the API key.
    Raises an exception on failure, otherwise returns None.
    """
    with cli_feedback('Checking %s' % server):
        uri = urlparse(server)
        if not uri.scheme:
            try:
                verify_server('https://'+server, insecure, ca_data)
                server = 'https://'+server
            except api.RSConnectException:
                try:
                    verify_server('http://'+server, insecure, ca_data)
                    server = 'http://'+server
                except api.RSConnectException as e2:
                    raise api.RSConnectException('Invalid server URL: "%s" - %s' % (server, e2))
        else:
            verify_server(server, insecure, ca_data)

    if api_key:
        with cli_feedback('Verifying API key'):
            verify_api_key(server, api_key, insecure, ca_data)
    return server
