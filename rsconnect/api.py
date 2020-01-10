import json
import logging
import re
import socket
import time
import ssl

from os.path import join, dirname
from six.moves import http_client as http
from six.moves.urllib_parse import urlparse, urlencode, urljoin
from six.moves.http_cookies import SimpleCookie

VERSION = open(join(dirname(__file__), 'version.txt'), 'r').read().strip()
USER_AGENT = "rsconnect-python/%s" % VERSION


class RSConnectException(Exception):
    def __init__(self, message):
        super(RSConnectException, self).__init__(message)
        self.message = message


logger = logging.getLogger('rsconnect')


def url_path_join(*parts):
    joined = '/'.join(parts)
    return re.sub('/+', '/', joined)


def wait_until(predicate, timeout, period=0.1):
    """
    Run <predicate> every <period> seconds until it returns True or until
    <timeout> seconds have passed.

    Returns True if <predicate> returns True before <timeout> elapses, False
    otherwise.
    """
    ending = time.time() + timeout
    while time.time() < ending:
        if predicate():
            return True
        time.sleep(period)
    return False


settings_path = '__api__/server_settings'
max_redirects = 5


def https_helper(hostname, port, disable_tls_check, ca_data):
    if ca_data is not None and disable_tls_check:
        raise Exception("Cannot both disable TLS checking and provide a custom certificate")
    if ca_data is not None:
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl.create_default_context(cadata=ca_data))
    elif disable_tls_check:
        # noinspection PyProtectedMember
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl._create_unverified_context())
    else:
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10)


def verify_server(server_address, disable_tls_check, ca_data):
    server_url = urljoin(server_address, settings_path)
    return _verify_server(server_url, max_redirects, disable_tls_check, ca_data)


def _verify_server(server_address, maximum_redirects, disable_tls_check, ca_data):
    """
    Verifies that a server is present at the given address.
    Assumes that `__api__/server_settings` is accessible from the jupyter server.
    :returns address
    :raises Base Exception with string error, or errors from HTTP(S)Connection
    """
    r = urlparse(server_address)
    conn = None
    try:
        if r.scheme == 'http':
            conn = http.HTTPConnection(r.hostname, port=(r.port or http.HTTP_PORT), timeout=10)
        else:
            conn = https_helper(r.hostname, r.port, disable_tls_check, ca_data)

        conn.request('GET', server_address, headers={'User-Agent': USER_AGENT})
        response = conn.getresponse()

        if response.status == 404:
            raise RSConnectException('The specified server does not appear to be running RStudio Connect')
        elif response.status >= 400:
            err = 'Response from Connect server: %s %s' % (response.status, response.reason)
            raise Exception(err)
        elif response.status >= 300:
            # process redirects now so we don't have to later
            target = response.getheader('Location')
            logger.warning('Redirected to: %s' % target)

            if maximum_redirects > 0:
                return _verify_server(urljoin(server_address, target), maximum_redirects - 1, disable_tls_check,
                                      ca_data)
            else:
                err = 'Too many redirects'
                raise Exception(err)
        else:
            content_type = response.getheader('Content-Type')
            if not content_type.startswith('application/json'):
                err = 'Unexpected Content-Type %s from %s' % (content_type, server_address)
                raise Exception(err)

    except (http.HTTPException, OSError, socket.error) as exc:
        raise RSConnectException(str(exc))
    finally:
        if conn is not None:
            conn.close()

    if server_address.endswith(settings_path):
        return server_address[:-len(settings_path)]
    else:
        return server_address


class RSConnect:
    def __init__(self, uri, api_key, cookies=None, disable_tls_check=False, ca_data=None):
        if cookies is None:
            cookies = []
        if disable_tls_check and (ca_data is not None):
            raise Exception("Cannot both disable TLS checking and provide custom certificate data")
        self.path_prefix = uri.path or '/'
        self.api_key = api_key
        self.conn = None
        self.mk_conn = lambda: http.HTTPConnection(uri.hostname, port=uri.port, timeout=10)
        if uri.scheme == 'https':
            self.mk_conn = lambda: https_helper(uri.hostname, uri.port, disable_tls_check, ca_data)
        self.http_headers = {
            'Authorization': 'Key %s' % self.api_key,
        }
        self.cookies = cookies
        self._inject_cookies(cookies)
        self.conn = self.mk_conn()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.conn.close()
        self.conn = None

    def request(self, method, path, *args, **kwargs):
        request_path = url_path_join(self.path_prefix, path)
        logger.debug('Performing: %s %s' % (method, request_path))
        kwargs['headers']['User-Agent'] = USER_AGENT
        try:
            self.conn.request(method, request_path, *args, **kwargs)
            return self.json_response()
        except http.HTTPException as e:
            raise RSConnectException(str(e))
        except (IOError, OSError) as e:
            raise RSConnectException(str(e))
        except (socket.error, socket.herror, socket.gaierror) as e:
            raise RSConnectException(str(e))
        except socket.timeout:
            raise RSConnectException('Connection timed out')

    def _handle_set_cookie(self, response):
        headers = filter(lambda h: h[0].lower() == 'set-cookie', response.getheaders())
        values = []

        for header in headers:
            cookie = SimpleCookie(header[1])
            for morsel in cookie.values():
                values.append((dict(key=morsel.key, value=morsel.value)))

        self.cookies = values
        self._inject_cookies(values)

    def _inject_cookies(self, cookies):
        if cookies:
            self.http_headers['Cookie'] = '; '.join(['%s="%s"' % (kv['key'], kv['value']) for kv in cookies])
        elif 'Cookie' in self.http_headers:
            del self.http_headers['Cookie']

    def json_response(self):
        response = self.conn.getresponse()

        self._handle_set_cookie(response)
        raw = response.read().decode('utf-8')

        if response.status >= 500:
            # noinspection PyBroadException
            try:
                message = json.loads(raw)['error']
            except Exception:
                message = 'Unexpected response code: %d' % response.status
            raise RSConnectException(message)
        elif response.status >= 400:
            data = json.loads(raw)
            raise RSConnectException(data['error'])
        else:
            data = json.loads(raw)
            return data

    def me(self):
        return self.request('GET', '__api__/me', None, headers=self.http_headers)

    def app_find(self, filters):
        params = urlencode(filters)
        data = self.request('GET', '__api__/applications?' + params, None, headers=self.http_headers)
        if data['count'] > 0:
            return data['applications']

    def app_create(self, name):
        params = json.dumps({'name': name})
        return self.request('POST', '__api__/applications', params, headers=self.http_headers)

    def app_get(self, app_id):
        return self.request('GET', '__api__/applications/%s' % app_id, None, headers=self.http_headers)

    def app_upload(self, app_id, tarball):
        return self.request('POST', '__api__/applications/%s/upload' % app_id, tarball, headers=self.http_headers)

    def app_update(self, app_id, updates):
        params = json.dumps(updates)
        return self.request('POST', '__api__/applications/%s' % app_id, params, headers=self.http_headers)

    def app_deploy(self, app_id, bundle_id=None):
        params = json.dumps({'bundle': bundle_id})
        return self.request('POST', '__api__/applications/%s/deploy' % app_id, params, headers=self.http_headers)

    def app_publish(self, app_id, access):
        params = json.dumps({
            'access_type': access,
            'id': app_id,
            'needs_config': False
        })
        return self.request('POST', '__api__/applications/%s' % app_id, params, headers=self.http_headers)

    def app_config(self, app_id):
        return self.request('GET', '__api__/applications/%s/config' % app_id, None, headers=self.http_headers)

    def task_get(self, task_id, first_status=None):
        url = '__api__/tasks/%s' % task_id
        if first_status is not None:
            url += '?first_status=%d' % first_status
        return self.request('GET', url, None, headers=self.http_headers)

    def deploy(self, app_id, app_name, app_title, tarball):
        if app_id is None:
            # create an app if id is not provided
            app = self.app_create(app_name)
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            app = self.app_get(app_id)

        if app['title'] != app_title:
            self.app_update(app['id'], {'title': app_title})

        app_bundle = self.app_upload(app['id'], tarball)
        task_id = self.app_deploy(app['id'], app_bundle['id'])['id']

        return {
            'task_id': task_id,
            'app_id': app['id'],
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


def verify_api_key(uri, api_key, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, ca_data=cadata) as api:
        api.me()


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
