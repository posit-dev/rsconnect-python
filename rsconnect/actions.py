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
from os.path import basename, exists, dirname
from pprint import pformat

from rsconnect import api
from .bundle import make_notebook_html_bundle, make_notebook_source_bundle
from .environment import EnvironmentException
from .metadata import AppStore

import click
from six.moves.urllib_parse import urlparse

line_width = 45
logger = logging.getLogger('rsconnect')


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
        if not (exists(python) and os.access(python, os.X_OK)):
            raise api.RSConnectException('The file, "%s", does not exist or is not executable.' % python)
        return python

    if 'RETICULATE_PYTHON' in env:
        return env['RETICULATE_PYTHON']

    return sys.executable


def inspect_environment(python, directory, compatibility_mode=False, force_generate=False,
                        check_output=subprocess.check_output):
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    flags = []
    if compatibility_mode:
        flags.append('c')
    if force_generate:
        flags.append('f')
    args = [python, '-m', 'rsconnect.environment']
    if len(flags) > 0:
        args.append('-'+''.join(flags))
    args.append(directory)
    environment_json = check_output(args, universal_newlines=True)
    environment = json.loads(environment_json)
    return environment


def default_title_for_manifest(the_manifest):
    """Produce a default content title from the contents of a manifest"""
    filename = None

    metadata = the_manifest.get('metadata')
    if metadata:
        # noinspection SpellCheckingInspection
        filename = metadata.get('entrypoint') or metadata.get('primary_rmd') or metadata.get('primary_html')
    return default_title(filename or 'manifest.json')


def _verify_server(connect_server):
    """
    Test whether the server identified by the given full URL can be reached and is
    running Connect.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    uri = urlparse(connect_server.url)
    if not uri.netloc:
        raise api.RSConnectException('Invalid server URL: "%s"' % connect_server.url)
    return api.verify_server(connect_server)


def _to_server_check_list(url):
    """
    Build a list of servers to check from the given one.  If the specified server
    appears not to have a scheme, then we'll provide https and http variants to test.

    :param url: the server URL text to start with.
    :return: a list of server strings to test.
    """
    # urlparse will end up with an empty netloc in this case.
    if '//' not in url:
        items = ['https://%s', 'http://%s']
    # urlparse would parse this correctly and end up with an empty scheme.
    elif url.startswith('//'):
        items = ['https:%s', 'http:%s']
    else:
        items = ['%s']

    return [item % url for item in items]


def test_server(connect_server):
    """
    Test whether the given server can be reached and is running Connect.  The server
    may be provided with or without a scheme.  If a scheme is omitted, the server will
    be tested with both `https` and `http` until one of them works.

    :param connect_server: the Connect server information.
    :return: a second server object with any scheme expansions applied and the server
    settings from the server.
    """
    url = connect_server.url
    key = connect_server.api_key
    insecure = connect_server.insecure
    ca_data = connect_server.ca_data
    failures = ['Invalid server URL: %s' % url]
    for test in _to_server_check_list(url):
        try:
            connect_server = api.RSConnectServer(test, key, insecure, ca_data)
            result = _verify_server(connect_server)
            return connect_server, result
        except api.RSConnectException as e:
            failures.append('    %s - %s' % (test, e))

    # In case the user may need https instead of http...
    if len(failures) == 2 and url.startswith('http://'):
        failures.append('    Do you need to use "https://%s?"' % url[7:])

    # If we're here, nothing worked.
    raise api.RSConnectException('\n'.join(failures))


def test_api_key(connect_server):
    """
    Test that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information.
    :return: the username of the user to whom the API key belongs.
    """
    return api.verify_api_key(connect_server)


def gather_server_details(connect_server):
    """
    Builds a dictionary containing the version of RStudio Connect that is running
    and the versions of Python installed there.

    :param connect_server: the Connect server information.
    :return: a three-entry dictionary.  The key 'connect' will refer to the version
    of Connect that was found.  The key `python` will refer to a sequence of version
    strings for all the versions of Python that are installed.  The key `conda` will
    refer to data about whether Connect is configured to support Conda environments.
    """
    def _to_sort_key(text):
        parts = [part.zfill(5) for part in text.split('.')]
        return ''.join(parts)

    server_settings = api.verify_server(connect_server)
    python_settings = api.get_python_info(connect_server)
    python_versions = sorted([item['version'] for item in python_settings['installations']], key=_to_sort_key)
    conda_settings = {
        'supported': python_settings['conda_enabled'] if 'conda_enabled' in python_settings else False
    }
    return {
        'connect': server_settings['version'],
        'python': python_versions,
        'conda': conda_settings
    }


def make_deployment_name():
    """Produce a unique name for this deployment as required by the Connect API.

    This is based on the current unix timestamp. Since the millisecond portion
    is zero on some systems, we add some jitter.

    :return: a default name for a deployment based on the current time.
    """
    timestamp = int(1000 * time.mktime(datetime.now().timetuple())) + random.randint(0, 999)
    return 'deployment-%d' % timestamp


def default_title(file_name):
    """
    Produce a default content title from the given file path.

    :param file_name: the name from which the title will be derived.
    :return: the derived title.
    """
    return basename(file_name).rsplit('.')[0]


def deploy_jupyter_notebook(connect_server, file_name, extra_files, new=False, app_id=None, title=None, static=False,
                            python=None, compatibility_mode=False, force_generate=False, log_callback=None):
    """
    A function to deploy a Jupyter notebook to Connect.  Depending on the files involved
    and network latency, this may take a bit of time.

    :param connect_server: the Connect server information.
    :param file_name: the Jupyter notebook file to deploy.
    :param extra_files: any extra files that should be included in the deploy.
    :param new: a flag to force this as a new deploy.
    :param app_id: the ID of an existing application to deploy new files for.
    :param title: an optional title for the deploy.  If this is not provided, ne will
    be generated.
    :param static: a flag noting whether the notebook should be deployed as a static
    HTML page or as a render-able document with sources.
    :param python: the optional name of a Python executable.
    :param compatibility_mode: force freezing the current environment using pip
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    app_store = AppStore(file_name)
    app_id, deployment_name, deployment_title, app_mode = \
        gather_basic_deployment_info(connect_server, app_store, file_name, new, app_id, title, static)
    python, environment = get_python_env_info(file_name, python, compatibility_mode, force_generate)
    bundle = create_notebook_deployment_bundle(file_name, extra_files, app_mode, python, environment)
    app = deploy_bundle(connect_server, app_id, deployment_name, deployment_title, bundle)
    return spool_deployment_log(connect_server, app, log_callback)


def gather_basic_deployment_info(connect_server, app_store, file_name, new, app_id, title, static):
    """
    Helps to gather the necessary info for performing a deployment.

    :param connect_server: the Connect server information.
    :param app_store: the store for the specified file
    :param file_name: the primary file being deployed.
    :param new: a flag noting whether we should force a new deployment.
    :param app_id: the ID of the app to redeploy.
    :param title: an optional title.  If this isn't specified, a default title will
    be generated.
    :param static: a flag to note whether a static document should be deployed.
    :return: the app ID, name, title and mode for the deployment.
    """
    deployment_name = make_deployment_name()
    deployment_title = title or default_title(file_name)

    if app_id is not None:
        # Don't read app metadata if app-id is specified. Instead, we need
        # to get this from Connect.
        app = api.get_app_info(connect_server, app_id)
        app_mode = api.app_modes.get(app.get('app_mode', 0), 'unknown')

        logger.debug('Using app mode from app %s: %s' % (app_id, app_mode))
    elif static:
        app_mode = 'static'
    else:
        app_mode = 'jupyter-static'

    if not new and app_id is None:
        # Possible redeployment - check for saved metadata.
        # Use the saved app information unless overridden by the user.
        app_id, title, app_mode = app_store.resolve(connect_server.url, app_id, title, app_mode)
        if static and app_mode != 'static':
            raise api.RSConnectException('Cannot change app mode to "static" once deployed. '
                                         'Use --new to create a new deployment.')

    return app_id, deployment_name, deployment_title, app_mode


def get_python_env_info(file_name, python, compatibility_mode, force_generate):
    """
    Gathers the python and environment information relating to the specified file
    with an eye to deploy it.

    :param file_name: the primary file being deployed.
    :param python: the optional name of a Python executable.
    :param compatibility_mode: force freezing the current environment using pip
    instead of conda, when conda is not supported on RStudio Connect (version<=1.8.0).
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :return: information about the version of Python in use plus some environmental
    stuff.
    """
    python = which_python(python)
    logger.debug('Python: %s' % python)
    environment = inspect_environment(python, dirname(file_name), compatibility_mode=compatibility_mode,
                                      force_generate=force_generate)
    logger.debug('Environment: %s' % pformat(environment))

    return python, environment


def create_notebook_deployment_bundle(file_name, extra_files, app_mode, python, environment):
    """
    Create an in-memory bundle, ready to deploy.

    :param file_name: the primary file being deployed.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param app_mode: the mode of the app being deployed.
    :param python: information about the version of Python being used.
    :param environment: environmental information.
    :return: the bundle.
    """
    if app_mode == 'static':
        try:
            return make_notebook_html_bundle(file_name, python)
        except subprocess.CalledProcessError as exc:
            # Jupyter rendering failures are often due to
            # user code failing, vs. an internal failure of rsconnect-python.
            raise api.RSConnectException(str(exc))
    else:
        return make_notebook_source_bundle(file_name, environment, extra_files)


def deploy_bundle(connect_server, app_id, name, title, bundle):
    """
    Deploys the specified bundle.

    :param connect_server: the Connect server information.
    :param app_id: the ID of the app to deploy, if this is a redeploy.
    :param name: the name for the deploy.
    :param title: the title for the deploy.
    :param bundle: the bundle to deploy.
    :return: application information about the deploy.  This includes the ID of the
    task that may be queried for deployment progress.
    """
    return api.do_bundle_deploy(connect_server, app_id, name, title, bundle)


def spool_deployment_log(connect_server, app, log_callback):
    """
    Helper for spooling the deployment log for an app.

    :param connect_server: the Connect server information.
    :param app: the app that was returned by the deploy_bundle function.
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    return api.emit_task_log(connect_server, app['app_id'], app['task_id'], log_callback)
