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


def _verify_server(server, insecure, ca_data):
    """
    Test whether the server identified by the given full URL can be reached and is
    running Connect.

    :param server: the full URL of the server to test.
    :param insecure: a flag to disable TLS verification.
    :param ca_data: client side certificate data to use for TLS.
    :return: the server settings from the Connect server.
    """
    uri = urlparse(server)
    if not uri.netloc:
        raise api.RSConnectException('Invalid server URL: "%s"' % server)
    return api.verify_server(server, insecure, ca_data)


def test_api_key(server, api_key, insecure, ca_data):
    """
    Test that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param server: the full URL of the target Connect server.
    :param api_key: the API key to verify.
    :param insecure: a flag to disable TLS verification.
    :param ca_data: client side certificate data to use for TLS.
    :return: the username of the user to whom the API key belongs.
    """
    return api.verify_api_key(server, api_key, insecure, ca_data)


def _to_server_check_list(server):
    """
    Build a list of servers to check from the given one.  If the specified server
    appears not to have a scheme, then we'll provide https and http variants to test.

    :param server: the server text to start with.
    :return: a list of server strings to test.
    """
    # urlparse will end up with an empty netloc in this case.
    if '//' not in server:
        items = ['https://%s', 'http://%s']
    # urlparse would parse this correctly and end up with an empty scheme.
    elif server.startswith('//'):
        items = ['https:%s', 'http:%s']
    else:
        items = ['%s']

    return [item % server for item in items]


def test_server(server, insecure, ca_data):
    """
    Test whether the given server can be reached and is running Connect.  The server
    may be provided with or without a scheme.  If a scheme is omitted, the server will
    be tested with both `https` and `http` until one of them works.

    :param server: the server to test.
    :param insecure: a flag to disable TLS verification.
    :param ca_data: client side certificate data to use for TLS.
    :return: the full server URL and the server settings from the server.
    """
    failures = ['Invalid server URL: %s' % server]
    for test in _to_server_check_list(server):
        try:
            result = _verify_server(test, insecure, ca_data)
            return test, result
        except api.RSConnectException as e:
            failures.append('    %s - %s' % (test, e))

    # In case the user may need https instead of http...
    if len(failures) == 2 and server.startswith('http://'):
        failures.append('    Do you need to use "https://%s?"' % server[7:])

    # If we're here, nothing worked.
    raise api.RSConnectException('\n'.join(failures))
