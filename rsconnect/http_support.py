"""
HTTP support wrappers and utility functions
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
from http import client as http
from http.cookies import SimpleCookie
from typing import IO, Any, Dict, List, Mapping, Optional, Tuple, Union, cast
from urllib.parse import urlencode, urljoin, urlparse
from warnings import warn

from . import VERSION
from .log import logger
from .timeouts import get_request_timeout

# A union type that describes types that can be converted to and from JSON.
JsonData = Union[
    str,
    int,
    float,
    bool,
    None,
    List["JsonData"],
    Tuple["JsonData"],
    Dict[str, "JsonData"],
]

_user_agent = "rsconnect-python/%s" % VERSION


# noinspection PyUnusedLocal,PyUnresolvedReferences
def _create_plain_connection(
    host_name: str,
    port: Optional[int],
    disable_tls_check: bool,
    ca_data: Optional[str | bytes],
):
    """
    This function is used to create a plain HTTP connection.  Note that the 3rd and 4th
    parameters are ignored; they are present to make the signature match the companion
    function for creating SSL connections.

    :param host_name: the name of the host to connect to.
    :param port:  the port to connect to.
    :param disable_tls_check: notes whether TLS verification should be disabled (ignored).
    :param ca_data: any certificate authority information to use (ignored).
    :return: a plain HTTP connection.
    """
    timeout = get_request_timeout()
    logger.debug(f"The HTTPConnection timeout is set to '{timeout}' seconds")
    return http.HTTPConnection(host_name, port=(port or http.HTTP_PORT), timeout=timeout)


def _get_proxy():
    proxyURL = os.getenv("https_proxy", os.getenv("HTTPS_PROXY"))
    if not proxyURL:
        return None, None, None, None
    parsed = urlparse(proxyURL)
    if parsed.scheme not in ["https"]:
        warn("HTTPS_PROXY scheme is not using https")
    redacted_url = "{}://".format(parsed.scheme)
    if parsed.username:
        redacted_url += "{}:{}@".format(parsed.username, "REDACTED")
    redacted_url += "{}:{}".format(parsed.hostname, parsed.port or 8080)
    logger.info("Using custom proxy server {}".format(redacted_url))
    return parsed.username, parsed.password, parsed.hostname, parsed.port or 8080


def _get_proxy_headers(*args: object, **kwargs: object):
    proxyHeaders = None
    proxyUsername, proxyPassword, _, _ = _get_proxy()
    if proxyUsername and proxyPassword:
        credentials = "{}:{}".format(proxyUsername, proxyPassword)
        credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
        proxyHeaders = {"Proxy-Authorization": "Basic {}".format(credentials)}
    return proxyHeaders


# noinspection PyUnresolvedReferences
def _create_ssl_connection(
    host_name: str,
    port: Optional[int],
    disable_tls_check: bool,
    ca_data: Optional[str | bytes],
):
    """
    This function is used to create a TLS encrypted HTTP connection (SSL).

    :param host_name: the name of the host to connect to.
    :param port:  the port to connect to.
    :param disable_tls_check: notes whether TLS verification should be disabled.
    :param ca_data: any certificate authority information to use.
    :param timeout: the timeout value to use for socket operations.
    :return: a TLS HTTPS connection.
    """
    if ca_data is not None and disable_tls_check:
        raise ValueError("Cannot both disable TLS checking and provide a custom certificate")

    no_proxy = os.environ.get("no_proxy", os.environ.get("NO_PROXY", "#"))
    if any([host_name.endswith(host) for host in no_proxy.split(",")]):
        proxyHost, proxyPort = None, None
    else:
        _, _, proxyHost, proxyPort = _get_proxy()
    headers = _get_proxy_headers()
    timeout = get_request_timeout()
    logger.debug(f"The HTTPSConnection timeout is set to '{timeout}' seconds")
    if ca_data is not None:
        return http.HTTPSConnection(
            host_name,
            port=(port or http.HTTPS_PORT),
            timeout=timeout,
            context=ssl.create_default_context(cadata=ca_data),
        )
    elif disable_tls_check:
        if proxyHost is not None:
            tmp = http.HTTPSConnection(
                proxyHost,
                port=proxyPort,
                timeout=timeout,
                context=ssl._create_unverified_context(),
            )
            tmp.set_tunnel(host_name, (port or http.HTTPS_PORT), headers=headers)
        else:
            tmp = http.HTTPSConnection(
                host_name,
                port=(port or http.HTTPS_PORT),
                timeout=timeout,
                context=ssl._create_unverified_context(),
            )
        return tmp
    else:
        if proxyHost is not None:
            tmp = http.HTTPSConnection(proxyHost, port=proxyPort, timeout=timeout)
            tmp.set_tunnel(host_name, (port or http.HTTPS_PORT), headers=headers)
        else:
            tmp = http.HTTPSConnection(host_name, port=(port or http.HTTPS_PORT), timeout=timeout)
        return tmp


def append_to_path(uri: str, path: str):
    """
    This is a helper function for appending a path to a URI (i.e, just the path portion
    of a full URL).  The main purpose is to make sure one and only one slash ends up between them.

    :param uri: the URI to append the path to.
    :param path: the path to append.
    :return: the result of the append.
    """
    if uri.endswith("/") and path.startswith("/"):
        uri += path[1:]
    elif not (uri.endswith("/") or path.startswith("/")):
        uri = uri + "/" + path
    else:
        uri += path
    return uri


class HTTPResponse(object):
    """
    This class represents the result of executing an HTTP request.
    """

    def __init__(
        self,
        full_uri: str,
        response: Optional[http.HTTPResponse] = None,
        body: Optional[str | bytes] = None,
        exception: Optional[Exception] = None,
    ):
        """
        This constructs an HTTPResponse object.  One and only one of the arguments will
        be None.

        :param full_uri: the URI being accessed.
        :param response: the response object, if no exception occurred.
        :param body: the body of the response, as a string.
        :param exception: the exception, if one occurred.
        """
        self._response = response
        self.full_uri = full_uri
        self.exception = exception
        self.content_type: str | None = None
        self.json_data: JsonData = None
        self.response_body = body

        if response is not None:
            self.status = response.status
            self.reason = response.reason
            self.content_type = response.getheader("Content-Type")
            if (
                self.content_type
                and self.content_type.startswith("application/json")
                and self.response_body is not None
                and len(self.response_body) > 0
            ):
                self.json_data = json.loads(self.response_body)


class HTTPServer(object):
    """
    This class provides the means to simply and directly invoke HTTP requests against a
    server.
    """

    def __init__(
        self,
        url: str,
        disable_tls_check: bool = False,
        ca_data: Optional[str | bytes] = None,
        cookies: Optional[CookieJar] = None,
    ):
        """
        Constructs an HTTPServer object.

        :param url: the base URL to interact with.  This may be just a scheme and server
        or may also include a root path to which all HTTP calls are relative to.
        :param disable_tls_check: notes whether TLS validation should be enforced.  Only
        relevant on HTTPS URLs.
        :param ca_data: any certificate authority data to use in specifying client side
        certificates.
        :param cookies: an optional cookie jar.  Must be of type `CookieJar` defined in this
        same file (i.e., not the one Python provides).
        """
        self._url = urlparse(url)

        if self._url.scheme not in _connection_factory:
            raise ValueError('The "%s" URL scheme is not supported.' % self._url.scheme)

        self._disable_tls_check = disable_tls_check
        self._ca_data = ca_data
        self._cookies = cookies if cookies is not None else CookieJar()
        self._headers = {"User-Agent": _user_agent}
        self._conn = None
        self._proxy_headers = _get_proxy_headers()

        self._inject_cookies()

    def authorization(self, auth_text: str):
        self._headers["Authorization"] = auth_text

    def get_authorization(self):
        if "Authorization" not in self._headers:
            return None

        return self._headers["Authorization"]

    def key_authorization(self, key: str):
        self.authorization("Key %s" % key)

    def bootstrap_authorization(self, key: str):
        self.authorization("Connect-Bootstrap %s" % key)

    def _get_full_path(self, path: str):
        return append_to_path(self._url.path, path)

    def __enter__(self):
        if self._url.hostname is None:
            raise ValueError("The URL does not contain a hostname.")

        factory = _connection_factory[self._url.scheme]
        self._conn = factory(
            self._url.hostname,
            self._url.port,
            self._disable_tls_check,
            self._ca_data,
        )
        return self

    def __exit__(self, *args: object):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def get(
        self,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        decode_response: bool = True,
    ) -> JsonData | HTTPResponse:
        return self.request("GET", path, query_params, decode_response=decode_response)

    def post(
        self,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        body: str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None = None,
    ) -> JsonData | HTTPResponse:
        return self.request("POST", path, query_params, body)

    def patch(
        self,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        body: str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None = None,
    ) -> JsonData | HTTPResponse:
        return self.request("PATCH", path, query_params, body)

    def put(
        self,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        body: str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None = None,
        headers: Optional[Mapping[str, str]] = None,
        decode_response: bool = True,
    ) -> JsonData | HTTPResponse:
        if headers is None:
            headers = {}
        return self.request(
            "PUT", path, query_params=query_params, body=body, headers=headers, decode_response=decode_response
        )

    def delete(
        self,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        body: str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None = None,
        decode_response: bool = True,
    ) -> JsonData | HTTPResponse:
        return self.request("DELETE", path, query_params, body, decode_response=decode_response)

    def request(
        self,
        method: str,
        path: str,
        query_params: Optional[Mapping[str, JsonData]] = None,
        body: str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None = None,
        maximum_redirects: int = 5,
        decode_response: bool = True,
        headers: Optional[Mapping[str, str]] = None,
    ) -> JsonData | HTTPResponse:
        path = self._get_full_path(path)
        extra_headers = headers or {}
        if isinstance(body, (Mapping, list)):
            body = json.dumps(body).encode("utf-8")
            extra_headers = {"Content-Type": "application/json; charset=utf-8"}
        extra_headers = {**extra_headers, **self.get_extra_headers(path, method, body)}
        return self._do_request(method, path, query_params, body, maximum_redirects, extra_headers, decode_response)

    def get_extra_headers(self, url: str, method: str, body: str | bytes | IO[bytes] | None) -> dict[str, str]:
        return {}

    def _do_request(
        self,
        method: str,
        path: str,
        query_params: Optional[Mapping[str, JsonData]],
        body: str | bytes | IO[bytes] | None,
        maximum_redirects: int,
        extra_headers: dict[str, str],
        decode_response: bool = True,
    ) -> JsonData | HTTPResponse:
        full_uri = path
        if query_params is not None:
            full_uri = "%s?%s" % (path, urlencode(query_params, doseq=True))
        headers = self._headers.copy()
        if self._proxy_headers:
            headers.update(self._proxy_headers)
        if extra_headers is not None:
            headers.update(extra_headers)
        local_connection = False

        try:
            if logger.is_debugging():
                logger.debug("Request: %s %s" % (method, full_uri))
                logger.debug("Headers:")
                for key, value in headers.items():
                    logger.debug("--> %s: %s" % (key, value))

            # if we weren't called under a `with` statement, we'll need to manage the
            # connection here.
            if self._conn is None:
                self.__enter__()
                local_connection = True

            # At this point we know that self._conn is not None.
            conn = cast(Union[http.HTTPConnection, http.HTTPSConnection], self._conn)

            try:
                conn.request(method, full_uri, body, headers)

                response = conn.getresponse()
                response_body = response.read()
                if decode_response:
                    response_body = response_body.decode("utf-8").strip()

                if logger.is_debugging():
                    logger.debug("Response: %s %s" % (response.status, response.reason))
                    logger.debug("Headers:")
                    for key, value in response.getheaders():
                        logger.debug("--> %s: %s" % (key, value))
                    logger.debug("--> %s" % response_body)
            finally:
                if local_connection:
                    self.__exit__()

            # Handle any redirects.
            if 300 <= response.status < 400:
                if maximum_redirects == 0:
                    raise http.CannotSendRequest("Too many redirects")

                location = response.getheader("Location")

                if location is None:
                    raise http.CannotSendRequest("Redirect response missing Location header")

                # Assume the redirect location will always be on the same domain.
                if location.startswith("http"):
                    parsed_location = urlparse(location)
                    if parsed_location.query:
                        next_url = "{}?{}".format(parsed_location.path, parsed_location.query)
                    else:
                        next_url = parsed_location.path
                else:
                    next_url = location

                logger.debug("--> Redirected to: %s" % urljoin(self._url.geturl(), location))

                redirect_extra_headers = self.get_extra_headers(next_url, "GET", body)
                return self._do_request(
                    "GET",
                    next_url,
                    query_params,
                    body,
                    maximum_redirects - 1,
                    {**extra_headers, **redirect_extra_headers},
                )

            self._handle_set_cookie(response)

            return self._tweak_response(HTTPResponse(full_uri, response=response, body=response_body))
        except (
            http.HTTPException,
            ssl.CertificateError,
            IOError,
            OSError,
            socket.error,
            socket.herror,
            socket.gaierror,
            socket.timeout,
        ) as exception:
            logger.debug("An exception occurred processing the HTTP request.", exc_info=True)
            return HTTPResponse(full_uri, exception=exception)

    # noinspection PyMethodMayBeStatic
    def _tweak_response(self, response: HTTPResponse) -> JsonData | HTTPResponse:
        return response

    def _handle_set_cookie(self, response: http.HTTPResponse):
        self._cookies.store_cookies(response)
        self._inject_cookies()

    def _inject_cookies(self):
        if len(self._cookies) > 0:
            self._headers["Cookie"] = self._cookies.get_cookie_header_value()
        elif "Cookie" in self._headers:
            del self._headers["Cookie"]


class CookieJar(object):
    @staticmethod
    def from_dict(source: dict[str, Any]):
        if not isinstance(source, dict):
            raise ValueError("Input must be a dictionary.")
        keys = source.get("keys", [])
        content = source.get("content", {})
        if len(keys) != len(content):
            raise ValueError("Cookie data is mismatched.")
        for key in keys:
            if key not in content:
                raise ValueError("Cookie data is mismatched.")
        result = CookieJar()
        result._keys = keys
        result._content = content
        return result

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._content: dict[str, str] = {}
        self._reference = SimpleCookie()

    def store_cookies(self, response: http.HTTPResponse):
        headers = filter(lambda h: h[0].lower() == "set-cookie", response.getheaders())

        for header in headers:
            cookie = SimpleCookie(header[1])
            for morsel in cookie.values():
                if morsel.key not in self._keys:
                    self._keys.append(morsel.key)
                self._content[morsel.key] = morsel.value
                logger.debug("--> Set cookie %s: %s" % (morsel.key, morsel.value))

        logger.debug("CookieJar contents: %s\n%s" % (self._keys, self._content))

    def get_cookie_header_value(self):
        result = "; ".join(["%s=%s" % (key, self._reference.value_encode(self._content[key])[1]) for key in self._keys])
        logger.debug("Cookie: %s" % result)
        return result

    def as_dict(self):
        return {"keys": list(self._keys), "content": self._content.copy()}

    def __len__(self):
        return len(self._keys)


_connection_factory = {
    "http": _create_plain_connection,
    "https": _create_ssl_connection,
}
