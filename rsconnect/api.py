import logging
import time

from rsconnect.http_support import HTTPResponse, HTTPServer, append_to_path


class RSConnectException(Exception):
    def __init__(self, message):
        super(RSConnectException, self).__init__(message)
        self.message = message


logger = logging.getLogger('rsconnect')


class RSConnect(HTTPServer):
    def __init__(self, url, api_key, disable_tls_check=False, ca_data=None, cookies=None):
        super(RSConnect, self).__init__(append_to_path(url, '__api__'), disable_tls_check, ca_data, cookies)

        if api_key:
            self.key_authorization(api_key)

    def _tweak_response(self, response):
        return response.json_data if response.status and response.status == 200 and response.json_data else response

    def me(self):
        return self.get('me')

    def server_settings(self):
        return self.get('server_settings')

    def app_find(self, filters):
        response = self.get('applications', query_params=filters)

        if response.json_data and response.json_data['count'] > 0:
            return response.json_data['applications']

        return response

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
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            app = self.app_get(app_id)

        if app['title'] != app_title:
            self.app_update(app_id, {'title': app_title})

        app_bundle = self.app_upload(app_id, tarball)
        task_id = self.app_deploy(app_id, app_bundle['id'])['id']

        return {
            'task_id': task_id,
            'app_id': app_id,
            'app_guid': app['guid'],
            'app_url': app['url'],
        }

    def wait_for_task(self, app_id, task_id, log_callback, timeout=None):
        last_status = None
        ending = time.time() + timeout if timeout else 999999999999

        while time.time() < ending:
            time.sleep(0.5)

            task_status = self.task_get(task_id, last_status)
            last_status = self.output_task_log(task_status, last_status, log_callback)

            if task_status['finished']:
                app_config = self.app_config(app_id)
                app_url = app_config.get('config_url')
                return app_url

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


def verify_server(server_address, disable_tls_check, ca_data):
    """
    Verify than a server URL is reachable, active and appears to be running an RStudio Connect
    server.

    :param server_address: the URL of the target Connect server.
    :param disable_tls_check: a flag to disable TLS verification.
    :param ca_data: client side certificate data to use for TLS.
    :return: the server settings from the Connect server.
    """
    with RSConnect(server_address, None, disable_tls_check, ca_data) as server:
        result = server.server_settings()

        if isinstance(result, HTTPResponse):
            if result.exception:
                raise RSConnectException('Exception trying to connect to %s - %s' % (server_address, result.exception))
            elif 400 <= result.status < 500:
                raise RSConnectException('The specified server does not appear to be running RStudio Connect')
            elif result.status >= 500:
                raise RSConnectException('Response from Connect server: %s %s' % (result.status, result.reason))

        return result


def verify_api_key(server_address, api_key, disable_tls_check, ca_data):
    """
    Verify that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param server_address: the URL of the target Connect server.
    :param api_key: the API key to verify.
    :param disable_tls_check: a flag to disable TLS verification.
    :param ca_data: client side certificate data to use for TLS.
    :return: the username of the user to whom the API key belongs.
    """
    with RSConnect(server_address, api_key, disable_tls_check=disable_tls_check, ca_data=ca_data) as api:
        result = api.me()
        if isinstance(result, HTTPResponse):
            if result.json_data and 'code' in result.json_data and result.json_data['code'] == 30:
                raise RSConnectException('The specified API key is not valid.')
            raise RSConnectException('Could not verify the API key: %s %s' % (result.status, result.reason))
        return result['username']


(
    UnknownMode,
    ShinyMode,
    ShinyRmdMode,
    StaticRmdMode,
    StaticMode,
    APIMode,
    TensorFlowModelAPI,
    StaticJupyterMode,
) = range(8)

app_modes = {
    UnknownMode: 'unknown',
    ShinyMode: 'shiny',
    ShinyRmdMode: 'rmd-shiny',
    StaticRmdMode: 'rmd-static',
    StaticMode: 'static',
    APIMode: 'api',
    TensorFlowModelAPI: 'tensorflow-saved-model',
    StaticJupyterMode: 'jupyter-static',
}


def app_data(api, app):
    return {
        'id': app['id'],
        'name': app['name'],
        'title': app['title'],
        'app_mode': app_modes.get(app['app_mode']),
        'config_url': api.app_config(app['id'])['config_url'],
    }


def app_search(uri, api_key, app_title, app_id, disable_tls_check, ca_data):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, ca_data=ca_data) as api:
        data = []
        filters = [('count', 5),
                   ('filter', 'min_role:editor'),
                   ('search', app_title)]

        apps = api.app_find(filters)
        found = False

        for app in apps or []:
            if app['app_mode'] in (StaticMode, StaticJupyterMode):
                data.append(app_data(api, app))
                if app['id'] == app_id:
                    found = True

        if app_id and not found:
            try:
                # offer the current location as an option
                app = api.app_get(app_id)
                if app['app_mode'] in (StaticMode, StaticJupyterMode):
                    data.append(app_data(api, app))
            except RSConnectException:
                logger.exception('Error getting info for previous app_id "%s", skipping', app_id)

        return data
