"""
This file provides an HTTP API (wrapped around the standard library via six) tailored to
our needs.
"""
import json
import logging
import socket
import ssl

from rsconnect import VERSION
from six.moves import http_client as http
from six.moves.http_cookies import SimpleCookie
from six.moves.urllib_parse import urlparse, urlencode, urljoin


logger = logging.getLogger('rsconnect')
_user_agent = "rsconnect-python/%s" % VERSION


# noinspection PyUnusedLocal,PyUnresolvedReferences
def _create_plain_connection(host_name, port, disable_tls_check, ca_data):
    """
    This function is used to create a plain HTTP connection.  Note that the 3rd and 4th
    parameters are ignored; they are present to make the signature match the companion
    function for creating SSL connections.

    :param host_name: the name of the host to connect to.
    :param port:  the port to connect to.
    :param disable_tls_check: notes whether TLS verification should be disabled (ignored).
    :param ca_data: Any certificate authority information to use (ignored).
    :return: a plain HTTP connection.
    """
    return http.HTTPConnection(host_name, port=(port or http.HTTP_PORT), timeout=10)


# noinspection PyUnresolvedReferences
def _create_ssl_connection(host_name, port, disable_tls_check, ca_data):
    """
    This function is used to create a TLS encrypted HTTP connection (SSL).

    :param host_name: the name of the host to connect to.
    :param port:  the port to connect to.
    :param disable_tls_check: notes whether TLS verification should be disabled.
    :param ca_data: Any certificate authority information to use.
    :return: a TLS HTTPS connection.
    """
    if ca_data is not None and disable_tls_check:
        raise ValueError("Cannot both disable TLS checking and provide a custom certificate")
    if ca_data is not None:
        return http.HTTPSConnection(host_name, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl.create_default_context(cadata=ca_data))
    elif disable_tls_check:
        # noinspection PyProtectedMember
        return http.HTTPSConnection(host_name, port=(port or http.HTTPS_PORT), timeout=10,
                                    context=ssl._create_unverified_context())
    else:
        return http.HTTPSConnection(host_name, port=(port or http.HTTPS_PORT), timeout=10)


def append_to_url(url, path):
    """
    This is a helper function for appending a path to a URL.  The main purpose is to make sure
    one and only one slash ends up between them.

    :param url: the URL to append the path to.
    :param path: the path to append.
    :return: the result of the append.
    """
    if url.endswith('/') and path.startswith('/'):
        url += path[1:]
    elif not (url.endswith('/') or path.startswith('/')):
        url = url + '/' + path
    else:
        url += path
    return url


class HTTPResponse(object):
    """
    This class represents the result of executing an HTTP request.
    """
    def __init__(self, response=None, exception=None):
        """
        This constructs an HTTPResponse object.  One and only one of the arguments will
        be None.

        :param response: the response object, if no exception occurred.
        :param exception: the exception, if one occurred.
        """
        self._response = response
        self.exception = exception
        self.content_type = None
        self.json_data = None
        self.response_body = None

        if response is not None:
            self.status = response.status
            self.reason = response.reason
            self.content_type = response.getheader('Content-Type')
            self.response_body = response.read().decode('utf-8')

            if self.content_type.startswith('application/json'):
                self.json_data = json.loads(self.response_body)


class HTTPServer(object):
    """
    This class provides the means to simply and directly invoke HTTP requests against a
    server.
    """
    def __init__(self, url, disable_tls_check=False, ca_data=None, cookies=None):
        """
        Constructs an HTTPServer object.

        :param url: the base URL to interact with.  This may be just a scheme and server
        or may also include a root path to which all HTTP calls are relative to.
        :param disable_tls_check: notes whether TLS validation should be enforced.  Only
        relevant on HTTPS URLs.
        :param ca_data: any certificate authority data to use in specifying client side
        certificates.
        :param cookies: an optional cookie jar.
        """
        self._url = urlparse(url)

        if self._url.scheme not in _connection_factory:
            raise ValueError('The "%s" URL scheme is not supported.' % self._url.scheme)

        self._disable_tls_check = disable_tls_check
        self._ca_data = ca_data
        self._cookies = [] if cookies is None else cookies
        self._headers = {'User-Agent': _user_agent}
        self._conn = None

        self._inject_cookies()

    def authorization(self, auth_text):
        self._headers['Authorization'] = auth_text

    def key_authorization(self, api_key):
        self.authorization('Key %s' % api_key)

    def _get_full_url(self, uri):
        return append_to_url(self._url, uri)

    def __enter__(self):
        factory = _connection_factory[self._url.scheme]
        self._conn = factory(self._url.hostname, self._url.port, self._disable_tls_check, self._ca_data)
        return self

    def __exit__(self, *args):
        if self._conn is not None:
            self.conn.close()
            self.conn = None

    def get(self, path, query_params=None):
        return self.request('GET', path, query_params)

    def post(self, path, query_params=None, body=None):
        return self.request('POST', path, query_params, body)

    def request(self, method, path, query_params=None, body=None, maximum_redirects=5):
        url = self._get_full_url(path)
        extra_headers = None
        if isinstance(body, dict):
            body = json.dumps(body).encode('utf-8')
            extra_headers = {'Content-Type': 'application/json; charset=utf-8'}
        return self._do_request(method, url, query_params, body, maximum_redirects, extra_headers)

    def _do_request(self, method, url, query_params, body, maximum_redirects, extra_headers=None):
        full_url = url
        if query_params is not None:
            full_url = '%s?%s' % (url, urlencode(query_params))
        headers = self._headers.copy()
        if extra_headers is not None:
            headers.update(extra_headers)
        conn = None

        try:
            conn = _connection_factory[self._url.scheme](self._url.hostname, self._url.port)

            logger.debug('Performing: %s %s' % (method, full_url))

            conn.request(method, full_url, body, headers)

            response = conn.getresponse()

            # Handle any redirects.
            if 300 <= response.status < 400:
                if maximum_redirects == 0:
                    raise http.CannotSendRequest('Too many redirects')

                location = response.getheader('Location')
                next_url = urljoin(self._url, location)

                logger.warning('Redirected to: %s' % next_url)

                return self._do_request(method, next_url, query_params, body, maximum_redirects - 1)

            self._handle_set_cookie(response)

            return self._tweak_response(HTTPResponse(response=response))
        except (http.HTTPException, IOError, OSError, socket.error, socket.herror, socket.gaierror,
                socket.timeout) as exception:
            return HTTPResponse(exception=exception)
        finally:
            if conn is not None:
                conn.close()

    # noinspection PyMethodMayBeStatic
    def _tweak_response(self, response):
        return response

    def _handle_set_cookie(self, response):
        headers = filter(lambda h: h[0].lower() == 'set-cookie', response.getheaders())

        for header in headers:
            cookie = SimpleCookie(header[1])
            for morsel in cookie.values():
                self._cookies.append((dict(key=morsel.key, value=morsel.value)))

        self._inject_cookies()

    def _inject_cookies(self):
        if self._cookies:
            self._headers['Cookie'] = '; '.join(['%s="%s"' % (kv['key'], kv['value']) for kv in self._cookies])
        elif 'Cookie' in self._headers:
            del self._headers['Cookie']


_connection_factory = {
    'http': _create_plain_connection,
    'https': _create_ssl_connection
}
