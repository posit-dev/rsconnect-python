import logging
import time
from _ssl import SSLError

from rsconnect.http_support import HTTPResponse, HTTPServer, append_to_path


class RSConnectException(Exception):
    def __init__(self, message):
        super(RSConnectException, self).__init__(message)
        self.message = message


logger = logging.getLogger('rsconnect')


class RSConnectServer(object):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the Connect server.
    """
    def __init__(self, url, api_key, insecure=False, ca_data=None):
        self.url = url
        self.api_key = api_key
        self.insecure = insecure
        self.ca_data = ca_data

    def handle_bad_response(self, response):
        if isinstance(response, HTTPResponse):
            if response.exception:
                raise RSConnectException('Exception trying to connect to %s - %s' % (self.url, response.exception))
            # Sometimes an ISP will respond to an unknown server name by returning a friendly
            # search page so trap that since we know we're expecting JSON from Connect.  This
            # also catches all error conditions which we will report as "not running Connect".
            else:
                if response.json_data and 'error' in response.json_data:
                    raise RSConnectException('The Connect server reported an error: %s' % response.json_data['error'])
                raise RSConnectException('The specified server does not appear to be running RStudio Connect')


class RSConnect(HTTPServer):
    def __init__(self, server, cookies=None):
        super(RSConnect, self).__init__(append_to_path(server.url, '__api__'), server.insecure, server.ca_data, cookies)
        self._server = server

        if server.api_key:
            self.key_authorization(server.api_key)

    def _tweak_response(self, response):
        return response.json_data if response.status and response.status == 200 and response.json_data else response

    def me(self):
        return self.get('me')

    def server_settings(self):
        return self.get('server_settings')

    def python_settings(self):
        return self.get('v1/server_settings/python')

    def app_search(self, filters):
        return self.get('applications', query_params=filters)

    def app_create(self, name):
        return self.post('applications', body={'name': name})

    def app_get(self, app_id):
        return self.get('applications/%s' % app_id)

    def app_upload(self, app_id, tarball):
        return self.post('applications/%s/upload' % app_id, body=tarball)

    def app_update(self, app_id, updates):
        return self.post('applications/%s' % app_id, body=updates)

    def app_deploy(self, app_id, bundle_id=None):
        return self.post('applications/%s/deploy' % app_id, body={'bundle': bundle_id})

    def app_publish(self, app_id, access):
        return self.post('applications/%s' % app_id, body={
            'access_type': access,
            'id': app_id,
            'needs_config': False
        })

    def app_config(self, app_id):
        return self.get('applications/%s/config' % app_id)

    def task_get(self, task_id, first_status=None):
        params = None
        if first_status is not None:
            params = {'first_status': first_status}
        return self.get('tasks/%s' % task_id, query_params=params)

    def deploy(self, app_id, app_name, app_title, tarball):
        if app_id is None:
            # create an app if id is not provided
            app = self.app_create(app_name)
            self._server.handle_bad_response(app)
            app_id = app['id']
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            app = self.app_get(app_id)
            self._server.handle_bad_response(app)

        if app['title'] != app_title:
            self._server.handle_bad_response(self.app_update(app_id, {'title': app_title}))

        app_bundle = self.app_upload(app_id, tarball)

        self._server.handle_bad_response(app_bundle)

        task_id = self.app_deploy(app_id, app_bundle['id'])['id']

        self._server.handle_bad_response(task_id)

        return {
            'task_id': task_id,
            'app_id': app_id,
            'app_guid': app['guid'],
            'app_url': app['url'],
        }

    def wait_for_task(self, app_id, task_id, log_callback, timeout=None):
        last_status = None
        ending = time.time() + timeout if timeout else 999999999999

        if log_callback is None:
            log_lines = []
            log_callback = log_lines.append
        else:
            log_lines = None

        while time.time() < ending:
            time.sleep(0.5)

            task_status = self.task_get(task_id, last_status)
            last_status = self.output_task_log(task_status, last_status, log_callback)

            if task_status['finished']:
                app_config = self.app_config(app_id)
                app_url = app_config.get('config_url')
                return app_url, log_lines

        raise RSConnectException('Task timed out after %d seconds' % timeout)

    @staticmethod
    def output_task_log(task_status, last_status, log_callback):
        """Pipe any new output through the log_callback.

        Returns an updated last_status which should be passed into
        the next call to output_task_log.

        Raises RSConnectException on task failure.
        """
        new_last_status = last_status
        if task_status['last_status'] != last_status:
            for line in task_status['status']:
                log_callback(line)
            new_last_status = task_status['last_status']

        if task_status['finished']:
            exit_code = task_status['code']
            if exit_code != 0:
                raise RSConnectException('Task exited with status %d.' % exit_code)

        return new_last_status


def verify_server(connect_server):
    """
    Verify that the given server information represents a Connect instance that is
    reachable, active and appears to be actually running RStudio Connect.  If the
    check is successful, the server settings for the Connect server is returned.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    try:
        with RSConnect(connect_server) as client:
            result = client.server_settings()
            connect_server.handle_bad_response(result)
            return result
    except SSLError as ssl_error:
        raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)


def verify_api_key(connect_server):
    """
    Verify that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information, including the API key to test.
    :return: the username of the user to whom the API key belongs.
    """
    with RSConnect(connect_server) as client:
        result = client.me()
        if isinstance(result, HTTPResponse):
            if result.json_data and 'code' in result.json_data and result.json_data['code'] == 30:
                raise RSConnectException('The specified API key is not valid.')
            raise RSConnectException('Could not verify the API key: %s %s' % (result.status, result.reason))
        return result['username']


def get_python_info(connect_server):
    """
    Return information about versions of Python that are installed on the indicated
    Connect server.

    :param connect_server: the Connect server information.
    :return: the Python installation information from Connect.
    """
    with RSConnect(connect_server) as client:
        result = client.python_settings()
        connect_server.handle_bad_response(result)
        return result


def get_app_info(connect_server, app_id):
    """
    Return information about an application that has been created in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get info for.
    :return: the Python installation information from Connect.
    """
    with RSConnect(connect_server) as client:
        result = client.app_get(app_id)
        connect_server.handle_bad_response(result)
        return result


def do_bundle_deploy(connect_server, app_id, name, title, bundle):
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
    with RSConnect(connect_server) as client:
        result = client.deploy(app_id, name, title, bundle)
        connect_server.handle_bad_response(result)
        return result


def emit_task_log(connect_server, app_id, task_id, log_callback, timeout=None):
    """
    Helper for spooling the deployment log for an app.

    :param connect_server: the Connect server information.
    :param app_id: the ID of the app that was deployed.
    :param task_id: the ID of the task that is tracking the deployment of the app..
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :param timeout: an optional timeout for the wait operation.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    with RSConnect(connect_server) as client:
        result = client.wait_for_task(app_id, task_id, log_callback, timeout)
        connect_server.handle_bad_response(result)
        return result


def _gather_existing_app_names(connect_server, name):
    """
    Retrieves all the app names that start with the given default name.

    :param connect_server: the Connect server information.
    :param name: the default name for an app.
    :return: the list of existing names that start with the proposed one.
    """
    with RSConnect(connect_server) as client:
        filters = {
            'search': name,
            'count': 100
        }
        existing_names = []
        count = 0
        finished = False

        # First, we need to gather all the names that are similar to what our default is.
        while not finished:
            result = client.app_search(filters)
            connect_server.handle_bad_response(result)
            count = count + result['count']
            existing_names.extend([app['name'] for app in result['applications']])

            if count < result['total']:
                filters = {
                    'start': count,
                    'count': 100,
                    'cont': result['continuation']
                }
            else:
                finished = True

    return existing_names


def find_unique_name(connect_server, name):
    """
    Poll through existing apps to see if anything with a similar name exists.
    If so, start appending numbers until a unique name is found.

    :param connect_server: the Connect server information.
    :param name: the default name for an app.
    :return: the name, potentially with a suffixed number to guarantee uniqueness.
    """
    existing_names = _gather_existing_app_names(connect_server, name)

    if name in existing_names:
        suffix = 1
        test = '%s%d' % (name, suffix)
        while test in existing_names:
            suffix = suffix + 1
            test = '%s%d' % (name, suffix)
        name = test

    return name
