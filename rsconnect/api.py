import json
import logging
import re
import socket
import time
import ssl

from six.moves import http_client as http
from six.moves.urllib_parse import urlparse, urlencode, urljoin
from six.moves.http_cookies import SimpleCookie


class RSConnectException(Exception):
    def __init__(self, message):
        super(RSConnectException, self).__init__(message)
        self.message = message


logger = logging.getLogger('rsconnect')
logger.setLevel(logging.INFO)


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

def https_helper(hostname, port, disable_tls_check, cadata):
    if cadata is not None and disable_tls_check:
        raise Exception("Cannot both disable TLS checking and provide a custom certificate")
    if cadata is not None:
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl.create_default_context(cadata=cadata))
    elif disable_tls_check:
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl._create_unverified_context())
    else:
        return http.HTTPSConnection(hostname, port=(port or http.HTTPS_PORT), timeout=10)

def verify_server(server_address, disable_tls_check, cadata):
    server_url = urljoin(server_address, settings_path)
    return _verify_server(server_url, max_redirects, disable_tls_check, cadata)

def _verify_server(server_address, max_redirects, disable_tls_check, cadata):
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
            conn = https_helper(r.hostname, r.port, disable_tls_check, cadata)

        conn.request('GET', server_address)
        response = conn.getresponse()

        if response.status >= 400:
            err = 'Response from Connect server: %s %s' % (response.status, response.reason)
            raise Exception(err)
        elif response.status >= 300:
            # process redirects now so we don't have to later
            target = response.getheader('Location')
            logger.warning('Redirected to: %s' % target)

            if max_redirects > 0:
                return _verify_server(urljoin(server_address, target), max_redirects - 1)
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
    def __init__(self, uri, api_key, cookies=[], disable_tls_check=False, cadata=None):
        if disable_tls_check and (cadata is not None):
            raise Exception("Cannot both disable TLS checking and provide custom certificate data")
        self.path_prefix = uri.path or '/'
        self.api_key = api_key
        self.conn = None
        self.mk_conn = lambda: http.HTTPConnection(uri.hostname, port=uri.port, timeout=10)
        if uri.scheme == 'https':
            self.mk_conn = lambda: https_helper(uri.hostname, uri.port, disable_tls_check, cadata)
        self.http_headers = {
            'Authorization': 'Key %s' % self.api_key,
        }
        self.cookies = cookies
        self._inject_cookies(cookies)

    def __enter__(self):
        self.conn = self.mk_conn()
        return self

    def __exit__(self, *args):
        self.conn.close()
        self.conn = None

    def request(self, method, path, *args, **kwargs):
        request_path = url_path_join(self.path_prefix, path)
        logger.debug('Performing: %s %s' % (method, request_path))
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
            logger.error('Received HTTP 500: %s', raw)
            try:
                message = json.loads(raw)['error']
            except:
                message = 'Unexpected response code: %d' % (response.status)
            raise RSConnectException(message)
        elif response.status >= 400:
            data = json.loads(raw)
            raise RSConnectException(data['error'])
        else:
            data = json.loads(raw)
            return data

    def me(self):
        return self.request('GET', '__api__/me', None, self.http_headers)

    def app_find(self, filters):
        params = urlencode(filters)
        data = self.request('GET', '__api__/applications?' + params, None, self.http_headers)
        if data['count'] > 0:
            return data['applications']

    def app_create(self, name):
        params = json.dumps({'name': name})
        return self.request('POST', '__api__/applications', params, self.http_headers)

    def app_get(self, app_id):
        return self.request('GET', '__api__/applications/%d' % app_id, None, self.http_headers)

    def app_upload(self, app_id, tarball):
        return self.request('POST', '__api__/applications/%d/upload' % app_id, tarball, self.http_headers)

    def app_update(self, app_id, updates):
        params = json.dumps(updates)
        return self.request('POST', '__api__/applications/%d' % app_id, params, self.http_headers)

    def app_deploy(self, app_id, bundle_id = None):
        params = json.dumps({'bundle': bundle_id})
        return self.request('POST', '__api__/applications/%d/deploy' % app_id, params, self.http_headers)

    def app_publish(self, app_id, access):
        params = json.dumps({
            'access_type': access,
            'id': app_id,
            'needs_config': False
        })
        return self.request('POST', '__api__/applications/%d' % app_id, params, self.http_headers)

    def app_config(self, app_id):
        return self.request('GET', '__api__/applications/%d/config' % app_id, None, self.http_headers)

    def task_get(self, task_id, first_status=None):
        url = '__api__/tasks/%s' % task_id
        if first_status is not None:
            url += '?first_status=%d' % first_status
        return self.request('GET', url, None, self.http_headers)


def wait_for_task(api, task_id, timeout, period=1.0):
    last_status = None
    ending = time.time() + timeout

    while time.time() < ending:
        task_status = api.task_get(task_id, first_status=last_status)

        if task_status['last_status'] != last_status:
            # we've gotten an updated status, reset timer
            logger.info('Deployment status: %s', task_status['status'])
            ending = time.time() + timeout
            last_status = task_status['last_status']

        if task_status['finished']:
            return task_status

        time.sleep(period)
    return None


def deploy(uri, api_key, app_id, app_name, app_title, tarball, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        if app_id is None:
            # create an app if id is not provided
            app = api.app_create(app_name)
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            app = api.app_get(app_id)

        if app['title'] != app_title:
            api.app_update(app['id'], {'title': app_title})

        app_bundle = api.app_upload(app['id'], tarball)
        task_id = api.app_deploy(app['id'], app_bundle['id'])['id']

        return {
            'task_id': task_id,
            'app_id': app['id'],
            'cookies': api.cookies,
        }


def task_get(uri, api_key, task_id, last_status, cookies, disable_tls_check, cadata):
    with RSConnect(uri, api_key, cookies, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        return api.task_get(task_id, first_status=last_status)


def app_config(uri, api_key, app_id, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        return api.app_config(app_id)


def verify_api_key(uri, api_key, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        try:
            api.me()
            return True
        except RSConnectException:
            return False

APP_MODE_STATIC = 4
APP_MODE_JUPYTER_STATIC = 7

app_modes = {
    APP_MODE_STATIC: 'static',
    APP_MODE_JUPYTER_STATIC: 'jupyter-static',
}


def app_search(uri, api_key, app_title, app_id, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        data = []

        filters = [('count', 5),
                   ('filter', 'min_role:editor'),
                   ('search', app_title)]

        apps = api.app_find(filters)
        found = False

        def app_data(app):
            return {
                'id': app['id'],
                'name': app['name'],
                'title': app['title'],
                'app_mode': app_modes.get(app['app_mode']),
                'config_url': api.app_config(app['id'])['config_url'],
            }

        for app in apps or []:
            if app['app_mode'] in (APP_MODE_STATIC, APP_MODE_JUPYTER_STATIC):
                data.append(app_data(app))
                if app['id'] == app_id:
                    found = True

        if app_id and not found:
            try:
                # offer the current location as an option
                app = api.app_get(app_id)
                if app['app_mode'] in (APP_MODE_STATIC, APP_MODE_JUPYTER_STATIC):
                    data.append(app_data(app))
            except RSConnectException:
                logger.exception('Error getting info for previous app_id "%s", skipping', app_id)

        return data


def app_get(uri, api_key, app_id, disable_tls_check, cadata):
    with RSConnect(uri, api_key, disable_tls_check=disable_tls_check, cadata=cadata) as api:
        return api.app_get(app_id)
