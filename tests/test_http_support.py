import threading
import time
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer as _TestHTTPServer
from typing import Any, Generator, cast
from unittest import TestCase

from rsconnect.http_support import (
    _connection_factory,
    _user_agent,
    _create_ssl_connection,
    append_to_path,
    CookieJar,
    HTTPResponse,
    HTTPServer,
)


class _DeadlineHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/slow-headers":
            for part in (
                b"HTTP/1.0 200 OK\r\n",
                b"Content-Length: 0\r\n",
                b"Content-Type: application/json\r\n",
                b"\r\n",
            ):
                if not self._send(part):
                    return
                time.sleep(0.14)
        elif self.path == "/slow-body":
            if not self._send(b"HTTP/1.0 200 OK\r\nContent-Length: 8\r\nContent-Type: application/json\r\n\r\n"):
                return
            for byte in b"12345678":
                if not self._send(bytes((byte,))):
                    return
                time.sleep(0.08)
        else:
            self._send(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}")

    def _send(self, data: bytes) -> bool:
        try:
            self.connection.sendall(data)
        except OSError:
            return False
        return True

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def _deadline_test_server() -> Generator[str, None, None]:
    server = _TestHTTPServer(("127.0.0.1", 0), _DeadlineHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError("HTTP test server thread did not stop.")


class TestHTTPSupport(TestCase):
    def test_connection_factory_map(self):
        self.assertEqual(len(_connection_factory), 2)
        self.assertIn("http", _connection_factory)
        self.assertIn("https", _connection_factory)
        self.assertNotEqual(_connection_factory["http"], _connection_factory["https"])

    def test_create_ssl_checks(self):
        with self.assertRaises(ValueError):
            _create_ssl_connection(None, None, True, "fake")

    def test_append_to_path(self):
        self.assertEqual(append_to_path("path/", "/sub"), "path/sub")
        self.assertEqual(append_to_path("path", "sub"), "path/sub")
        self.assertEqual(append_to_path("path/", "sub"), "path/sub")
        self.assertEqual(append_to_path("path", "/sub"), "path/sub")

    def test_HTTPServer_instantiation_error(self):
        with self.assertRaises(ValueError):
            HTTPServer("ftp://example.com")

    def test_request_timeout_override_does_not_change_the_default(self):
        from unittest.mock import patch

        with patch("rsconnect.http_support.get_request_timeout", return_value=37):
            with HTTPServer("http://example.com", request_timeout=0.25) as bounded:
                self.assertEqual(bounded._conn.timeout, 0.25)
            with HTTPServer("http://example.com") as ordinary:
                self.assertEqual(ordinary._conn.timeout, 37)

    def test_expired_request_deadline_prevents_network_io(self):
        import socket
        from unittest.mock import patch

        with patch("rsconnect.http_support.time.monotonic", return_value=100):
            with HTTPServer("http://example.com", request_deadline=99) as server:
                with patch.object(server._conn, "request") as send:
                    response = server.get("/settings")
        self.assertIsInstance(response.exception, socket.timeout)
        send.assert_not_called()

    def test_deadline_updates_an_existing_socket_for_each_request(self):
        from unittest.mock import Mock, patch

        clock = [100]
        with patch("rsconnect.http_support.time.monotonic", side_effect=lambda: clock[0]):
            with HTTPServer("http://example.com", request_timeout=20, request_deadline=110) as server:
                transport = server._conn
                transport.sock = Mock()
                reply = Mock()
                reply.status = 200
                reply.read.return_value = b"{}"
                reply.getheaders.return_value = []
                reply.getheader.return_value = "application/json"
                with patch.object(transport, "request"):
                    with patch.object(transport, "getresponse", return_value=reply):
                        server.get("/first")
                        self.assertEqual(transport.timeout, 10)
                        transport.sock.settimeout.assert_called_with(10)
                        clock[0] = 107
                        server.get("/next")
                        self.assertEqual(transport.timeout, 3)
                        transport.sock.settimeout.assert_called_with(3)
                transport.sock = None

    def test_deadline_uses_remaining_time_when_request_timeout_is_disabled(self):
        from unittest.mock import Mock, patch

        with patch("rsconnect.http_support.time.monotonic", return_value=100):
            with patch("rsconnect.http_support.get_request_timeout", return_value=0):
                with HTTPServer("http://example.com", request_deadline=110) as server:
                    transport = cast(Any, server._conn)
                    reply = Mock()
                    reply.status = 200
                    reply.reason = "OK"
                    reply.read.return_value = b"{}"
                    reply.getheaders.return_value = []
                    reply.getheader.return_value = "application/json"
                    with patch.object(transport, "request"):
                        with patch.object(transport, "getresponse", return_value=reply):
                            server.get("/settings")
                    self.assertEqual(transport.timeout, 10)

    def test_no_deadline_keeps_http_connection_call_shapes(self):
        from unittest.mock import Mock, patch

        with HTTPServer("http://example.com") as server:
            transport = cast(Any, server._conn)
            reply = Mock()
            reply.status = 200
            reply.reason = "OK"
            reply.read.return_value = b"{}"
            reply.getheaders.return_value = []
            reply.getheader.return_value = "application/json"
            with patch("rsconnect.http_support.threading.Timer", side_effect=AssertionError):
                with patch.object(transport, "request") as send:
                    with patch.object(transport, "getresponse", return_value=reply) as receive:
                        response = cast(HTTPResponse, server.get("/settings"))

            send.assert_called_once_with("GET", "/settings", None, {"User-Agent": _user_agent})
            receive.assert_called_once_with()
            reply.read.assert_called_once_with()
            self.assertEqual(response.status, 200)

    def test_completed_token_response_survives_deadline_and_prevents_another_request(self):
        import socket
        from unittest.mock import Mock, patch

        for timer_fired in (False, True):
            clock = [100]
            with self.subTest(timer_fired=timer_fired), ExitStack() as stack:
                stack.enter_context(patch("rsconnect.http_support.time.monotonic", side_effect=lambda: clock[0]))
                server = stack.enter_context(HTTPServer("http://example.com", request_deadline=110))
                timer = stack.enter_context(patch("rsconnect.http_support.threading.Timer"))
                interrupt = stack.enter_context(patch("rsconnect.http_support._interrupt_socket"))
                transport = cast(Any, server._conn)
                transport.sock = Mock()
                reply = Mock()
                reply.status = 200
                reply.reason = "OK"
                reply.getheaders.return_value = []
                reply.getheader.return_value = "application/json"

                def read_completed_body():
                    clock[0] = 111
                    if timer_fired:
                        timer.call_args.args[1]()
                    return b'{"access_token":"completed-token","refresh_token":"saved-refresh"}'

                reply.read.side_effect = read_completed_body
                send = stack.enter_context(patch.object(transport, "request"))
                stack.enter_context(patch.object(transport, "getresponse", return_value=reply))
                response = cast(HTTPResponse, server.get("/token"))
                next_response = cast(HTTPResponse, server.get("/accounts"))

                self.assertIsNone(response.exception)
                self.assertEqual(
                    response.json_data,
                    {"access_token": "completed-token", "refresh_token": "saved-refresh"},
                )
                self.assertIsInstance(next_response.exception, socket.timeout)
                self.assertEqual(send.call_count, 1)
                self.assertEqual(interrupt.call_count, int(timer_fired))
                timer.return_value.cancel.assert_called_once_with()
                timer.return_value.join.assert_called_once_with()
                transport.sock = None

    def test_deadline_interrupts_slow_response_headers(self):
        import socket

        with _deadline_test_server() as url:
            deadline = time.monotonic() + 0.2
            with HTTPServer(url, request_timeout=1, request_deadline=deadline) as server:
                started = time.monotonic()
                response = cast(HTTPResponse, server.get("/slow-headers"))
                elapsed = time.monotonic() - started

        self.assertIsInstance(response.exception, socket.timeout)
        self.assertLess(elapsed, 0.35)

    def test_deadline_interrupts_http10_slow_body_and_joins_timer(self):
        import socket
        from unittest.mock import patch

        timers: list[threading.Timer] = []

        class TrackingTimer(threading.Timer):
            def start(self) -> None:
                timers.append(self)
                super().start()

        with _deadline_test_server() as url:
            with patch("rsconnect.http_support.threading.Timer", new=TrackingTimer):
                deadline = time.monotonic() + 0.2
                with HTTPServer(url, request_timeout=1, request_deadline=deadline) as server:
                    started = time.monotonic()
                    response = cast(HTTPResponse, server.get("/slow-body"))
                    elapsed = time.monotonic() - started

        self.assertIsInstance(response.exception, socket.timeout)
        self.assertLess(elapsed, 0.45)
        self.assertEqual(len(timers), 1)
        self.assertFalse(timers[0].is_alive())

    def test_deadline_timer_is_opt_in_and_cancelled_after_success(self):
        from unittest.mock import patch

        timers: list[threading.Timer] = []

        class TrackingTimer(threading.Timer):
            def start(self) -> None:
                timers.append(self)
                super().start()

        with _deadline_test_server() as url:
            with patch("rsconnect.http_support._interrupt_socket") as interrupt:
                with patch("rsconnect.http_support.threading.Timer", new=TrackingTimer):
                    with HTTPServer(url) as ordinary:
                        response = cast(HTTPResponse, ordinary.get("/quick"))
                    self.assertEqual(response.status, 200)
                    self.assertEqual(timers, [])

                    with HTTPServer(url, request_deadline=time.monotonic() + 2) as bounded:
                        response = cast(HTTPResponse, bounded.get("/quick"))
                    self.assertEqual(response.status, 200)

                interrupt.assert_not_called()

        self.assertEqual(len(timers), 1)
        self.assertFalse(timers[0].is_alive())

    def test_header_stuff(self):
        server = HTTPServer("http://example.com")
        self.assertIsNone(server.get_authorization())

        server.authorization("Basic user:pw")
        self.assertEqual(server.get_authorization(), "Basic user:pw")

        self.assertEqual(len(server._headers), 2)
        self.assertIn("User-Agent", server._headers)
        self.assertEqual(server._headers["User-Agent"], _user_agent)
        self.assertIn("Authorization", server._headers)
        self.assertEqual(server._headers["Authorization"], "Basic user:pw")

        server.key_authorization("my-api-key")
        self.assertEqual(server.get_authorization(), "Key my-api-key")

        self.assertEqual(len(server._headers), 2)
        self.assertIn("User-Agent", server._headers)
        self.assertEqual(server._headers["User-Agent"], _user_agent)
        self.assertIn("Authorization", server._headers)
        self.assertEqual(server._headers["Authorization"], "Key my-api-key")

        server.bootstrap_authorization("my.jwt.token")
        self.assertEqual(server.get_authorization(), "Connect-Bootstrap my.jwt.token")

        self.assertEqual(len(server._headers), 2)
        self.assertIn("User-Agent", server._headers)
        self.assertEqual(server._headers["User-Agent"], _user_agent)
        self.assertIn("Authorization", server._headers)
        self.assertEqual(server._headers["Authorization"], "Connect-Bootstrap my.jwt.token")


class FakeSetCookieResponse(object):
    def __init__(self, data):
        self._data = [("Set-Cookie", term) for term in data]

    def getheaders(self):
        return self._data


class TestCookieJar(TestCase):
    def test_basic_stuff(self):
        jar = CookieJar()
        jar.store_cookies(FakeSetCookieResponse(["my-cookie=my-value", "my-2nd-cookie=my-other-value"]))
        self.assertEqual(
            jar.get_cookie_header_value(),
            "my-cookie=my-value; my-2nd-cookie=my-other-value",
        )

    def test_from_dict(self):
        jar = CookieJar.from_dict({"keys": ["name"], "content": {"name": "value"}})
        self.assertEqual(jar.get_cookie_header_value(), "name=value")

    def test_from_dict_errors(self):
        with self.assertRaises(ValueError) as info:
            CookieJar.from_dict("bogus")
        self.assertEqual(str(info.exception), "Input must be a dictionary.")

        test_data = [
            {"content": {"a": "b"}},
            {"keys": ["a"]},
            {"keys": ["b"], "content": {"a": "b"}},
        ]
        for data in test_data:
            with self.assertRaises(ValueError) as info:
                CookieJar.from_dict(data)
            self.assertEqual(str(info.exception), "Cookie data is mismatched.")

    def test_as_dict(self):
        jar = CookieJar()
        jar.store_cookies(FakeSetCookieResponse(["my-cookie=my-value", "my-2nd-cookie=my-other-value"]))
        self.assertEqual(
            jar.as_dict(),
            {
                "keys": ["my-cookie", "my-2nd-cookie"],
                "content": {"my-cookie": "my-value", "my-2nd-cookie": "my-other-value"},
            },
        )

    def test_cookie_values_do_not_reach_the_debug_log(self):
        # Cookie names can carry credentials too; diagnostics expose only the count.
        jar = CookieJar()
        cookie_name = "echoed-refresh-token-name"
        cookie_value = "echoed-refresh-token-value"
        with self.assertLogs("rsconnect", level="DEBUG") as captured:
            jar.store_cookies(FakeSetCookieResponse([f"{cookie_name}={cookie_value}"]))
            header = jar.get_cookie_header_value()

        self.assertEqual(header, f"{cookie_name}={cookie_value}")
        self.assertEqual(jar.as_dict(), {"keys": [cookie_name], "content": {cookie_name: cookie_value}})
        log_text = "\n".join(captured.output)
        self.assertNotIn(cookie_name, log_text)
        self.assertNotIn(cookie_value, log_text)
        self.assertIn("1 cookie(s)", log_text)


class TestDebugLogRedaction(TestCase):
    """Credential material must not reach the debug (-vv) log."""

    def test_form_encoded_credentials_are_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = "grant_type=client_credentials&client_id=abc&client_secret=hunter2&scope=vivid"
        redacted = _redacted_body_for_log(body)
        self.assertNotIn("hunter2", str(redacted))
        self.assertIn("client_secret=<redacted>", str(redacted))
        self.assertIn("client_id=abc", str(redacted))
        self.assertIn("scope=vivid", str(redacted))

    def test_bytes_bodies_are_redacted_too(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = b"grant_type=refresh_token&refresh_token=r3fr3sh&client_id=abc"
        redacted = _redacted_body_for_log(body)
        self.assertNotIn("r3fr3sh", str(redacted))
        self.assertIn("refresh_token=<redacted>", str(redacted))

    def test_json_token_response_is_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = '{"access_token": "AAA", "refresh_token": "RRR", "token_type": "bearer"}'
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("AAA", redacted)
        self.assertNotIn("RRR", redacted)
        self.assertIn('"token_type": "bearer"', redacted)

    def test_json_secret_values_are_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = '{"secrets": [{"name": "MY_VAR", "value": "s3cret"}]}'
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("s3cret", redacted)
        self.assertIn('"name": "MY_VAR"', redacted)

    def test_authorization_code_exchange_body_is_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = (
            "grant_type=authorization_code&client_id=abc&code=authc0de"
            "&redirect_uri=http%3A%2F%2Flocalhost%3A9999%2Fcallback&code_verifier=v3rifier"
        )
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("authc0de", redacted)
        self.assertNotIn("v3rifier", redacted)
        self.assertIn("code=<redacted>", redacted)
        self.assertIn("code_verifier=<redacted>", redacted)
        self.assertIn("grant_type=authorization_code", redacted)
        self.assertIn("client_id=abc", redacted)

    def test_token_exchange_subject_token_is_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = (
            "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange"
            "&subject_token_type=urn%3Aietf%3Aparams%3Aoauth%3Atoken-type%3Aid_token"
            "&subject_token=oidc.jwt.value"
        )
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("oidc.jwt.value", redacted)
        self.assertIn("subject_token=<redacted>", redacted)
        self.assertIn("subject_token_type=urn", redacted)

    def test_bootstrap_api_key_response_is_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = '{"api_key": "fr3shAdminKey"}'
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("fr3shAdminKey", redacted)
        self.assertIn('"api_key": "<redacted>"', redacted)

    def test_json_error_codes_stay_readable(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = '{"error": "An object with that name already exists.", "code": 26}'
        redacted = str(_redacted_body_for_log(body))
        self.assertIn('"error": "An object with that name already exists."', redacted)
        self.assertIn('"code": 26', redacted)

    def test_streams_are_left_alone(self):
        from io import BytesIO

        from rsconnect.http_support import _redacted_body_for_log

        stream = BytesIO(b"client_secret=hunter2")
        self.assertIs(_redacted_body_for_log(stream), stream)

    def test_authorization_header_is_redacted(self):
        from rsconnect.http_support import _redacted_header_for_log

        self.assertEqual(_redacted_header_for_log("Authorization", "Bearer AAA"), "Bearer <redacted>")
        self.assertEqual(_redacted_header_for_log("authorization", "Key my-api-key"), "Key <redacted>")
        self.assertEqual(_redacted_header_for_log("Set-Cookie", "session=abc"), "<redacted>")
        self.assertEqual(_redacted_header_for_log("Content-Type", "application/json"), "application/json")

    def test_all_credential_headers_are_redacted(self):
        # shinyapps.io signs requests with X-Auth-Token/X-Auth-Signature and SPCS
        # sends the API key as X-RSC-Authorization; none may reach the -vv log.
        from rsconnect.http_support import _redacted_header_for_log

        self.assertEqual(_redacted_header_for_log("X-Auth-Token", "tok3n"), "<redacted>")
        self.assertEqual(_redacted_header_for_log("x-rsc-authorization", "my-api-key"), "<redacted>")
        # The signature is the first token of the value, so no scheme survives.
        self.assertEqual(_redacted_header_for_log("X-Auth-Signature", "deadbeef; version=1"), "<redacted>")

    def test_cookie_values_with_spaces_leave_no_first_token(self):
        from rsconnect.http_support import _redacted_header_for_log

        self.assertEqual(_redacted_header_for_log("Cookie", "session=abc; other=def"), "<redacted>")

    def test_oauth_error_fields_and_redirect_location_are_redacted_in_http_logs(self):
        from unittest.mock import Mock, patch

        location = (
            "/callback?refresh%5Ftoken=redirect-secret"
            "#access%5Ftoken=fragment-secret&error_description=location-secret&tab=summary"
        )
        body = '{"error":"invalid_grant","error_description":"description-secret","user_code":"code-secret"}'

        def make_response(status, response_body, headers, reason):
            response = Mock()
            response.status = status
            response.reason = reason
            response.read.return_value = response_body
            response.getheaders.return_value = headers
            header_values = {key.lower(): value for key, value in headers}
            response.getheader.side_effect = lambda key, default=None: header_values.get(key.lower(), default)
            return response

        redirect = make_response(302, b"", [("Location", location)], "reason-secret")
        final = make_response(
            200,
            body.encode(),
            [("Content-Type", "application/json"), ("X-Debug-Context", "ordinary-debug-context")],
            "reason-secret",
        )

        with HTTPServer("http://example.com") as server:
            transport = cast(Any, server._conn)
            with self.assertLogs("rsconnect", level="DEBUG") as captured:
                with patch.object(transport, "request") as send:
                    with patch.object(transport, "getresponse", side_effect=[redirect, final]):
                        response = cast(HTTPResponse, server.get("/start"))

        log_text = "\n".join(captured.output)
        for secret in (
            "redirect-secret",
            "location-secret",
            "description-secret",
            "code-secret",
            "reason-secret",
            "fragment-secret",
        ):
            self.assertNotIn(secret, log_text)
        self.assertIn("Content-Type: application/json", log_text)
        self.assertIn("X-Debug-Context: ordinary-debug-context", log_text)
        self.assertIn(
            "Redirected to: http://example.com/callback?refresh%5Ftoken=<redacted>"
            "#access%5Ftoken=<redacted>&error_description=<redacted>&tab=summary",
            log_text,
        )
        self.assertIn('"error_description": "<redacted>"', log_text)
        self.assertIn('"user_code": "<redacted>"', log_text)
        self.assertEqual(send.call_args_list[1].args[1], location)
        self.assertEqual(response.reason, "reason-secret")
        self.assertEqual(response.response_body, body)
        self.assertEqual(
            response.json_data,
            {
                "error": "invalid_grant",
                "error_description": "description-secret",
                "user_code": "code-secret",
            },
        )

    def test_oauth_redirect_destination_is_suppressed_without_changing_routing(self):
        from unittest.mock import Mock, patch

        location = "http://example.com/opaque/path-refresh-token?resume=opaque-query-token"
        request_target = "/opaque/path-refresh-token?resume=opaque-query-token"

        def make_response(status, body, headers, reason):
            response = Mock()
            response.status = status
            response.reason = reason
            response.read.return_value = body
            response.getheaders.return_value = headers
            header_values = {key.lower(): value for key, value in headers}
            response.getheader.side_effect = lambda key, default=None: header_values.get(key.lower(), default)
            return response

        redirect = make_response(302, b"", [("Location", location)], "reason-refresh-token")
        final = make_response(200, b"{}", [("Content-Type", "application/json")], "final-reason-refresh-token")

        with HTTPServer("http://example.com") as server:
            server._suppress_oauth_response_logging = True
            transport = cast(Any, server._conn)
            with self.assertLogs("rsconnect", level="DEBUG") as captured:
                with patch.object(transport, "request") as send:
                    with patch.object(transport, "getresponse", side_effect=[redirect, final]):
                        response = cast(HTTPResponse, server.post("/oauth/start", body=b"payload"))

        log_text = "\n".join(captured.output)
        for secret in ("path-refresh-token", "opaque-query-token", "reason-refresh-token"):
            self.assertNotIn(secret, log_text)
        self.assertIn("Following HTTP redirect", log_text)
        self.assertEqual(send.call_args_list[0].args[:3], ("POST", "/oauth/start", b"payload"))
        self.assertEqual(send.call_args_list[1].args[:3], ("GET", request_target, b"payload"))
        self.assertEqual(response.full_uri, request_target)
        self.assertEqual(response.reason, "final-reason-refresh-token")
        self.assertEqual(response.response_body, "{}")

    def test_oauth_response_body_suppression_keeps_response_data_unchanged(self):
        from unittest.mock import Mock, patch

        secret = "echoed-refresh-token"
        body = f'{{"error":"{secret}","error_description":"{secret}"}}'
        content_type = f"application/json; debug={secret}"
        reply = Mock()
        reply.status = 503
        reply.reason = "reason-secret"
        reply.read.return_value = body.encode()
        reply.getheaders.return_value = [("Content-Type", content_type), ("X-Debug-Context", secret)]
        header_values = {key.lower(): value for key, value in reply.getheaders.return_value}
        reply.getheader.side_effect = lambda key, default=None: header_values.get(key.lower(), default)

        with HTTPServer("http://example.com") as server:
            server._suppress_oauth_response_logging = True
            transport = cast(Any, server._conn)
            with self.assertLogs("rsconnect", level="DEBUG") as captured:
                with patch.object(transport, "request"):
                    with patch.object(transport, "getresponse", return_value=reply):
                        response = cast(HTTPResponse, server.get("/oauth/token"))

        log_text = "\n".join(captured.output)
        self.assertIn("Response: 503", log_text)
        self.assertIn("<OAuth response headers omitted>", log_text)
        self.assertIn("<OAuth response body omitted>", log_text)
        self.assertNotIn(secret, log_text)
        self.assertNotIn("X-Debug-Context", log_text)
        self.assertNotIn("reason-secret", log_text)
        self.assertEqual(response.reason, "reason-secret")
        self.assertEqual(response.content_type, content_type)
        self.assertEqual(response._response.getheader("Content-Type"), content_type)
        self.assertEqual(response._response.getheader("X-Debug-Context"), secret)
        self.assertEqual(response.response_body, body)
        self.assertEqual(response.json_data, {"error": secret, "error_description": secret})

    def test_malformed_json_is_logged_as_a_placeholder(self):
        from unittest.mock import Mock, patch

        from rsconnect.http_support import _redacted_body_for_log

        body = '{"error_description":"malformed-secret", "broken": "'
        self.assertEqual(_redacted_body_for_log(body), "<invalid JSON>")

        reply = Mock()
        reply.status = 400
        reply.reason = "Bad Request"
        reply.read.return_value = body.encode()
        reply.getheaders.return_value = [("Content-Type", "application/json")]
        reply.getheader.side_effect = lambda key, default=None: (
            "application/json" if key.lower() == "content-type" else default
        )

        with HTTPServer("http://example.com") as server:
            transport = cast(Any, server._conn)
            with self.assertLogs("rsconnect", level="DEBUG") as captured:
                with patch.object(transport, "request"):
                    with patch.object(transport, "getresponse", return_value=reply):
                        response = cast(HTTPResponse, server.get("/token"))

        log_text = "\n".join(captured.output)
        self.assertIn("<invalid JSON>", log_text)
        self.assertNotIn("malformed-secret", log_text)
        self.assertEqual(response.response_body, body)
        self.assertIsNone(response.json_data)

    def test_bad_status_line_text_is_not_logged_with_a_traceback(self):
        from http.client import BadStatusLine
        from unittest.mock import patch

        failure = BadStatusLine("refresh-token-in-status-line")
        with HTTPServer("http://example.com") as server:
            transport = cast(Any, server._conn)
            with self.assertLogs("rsconnect", level="DEBUG") as captured:
                with patch.object(transport, "request"):
                    with patch.object(transport, "getresponse", side_effect=failure):
                        response = cast(HTTPResponse, server.get("/token"))

        log_text = "\n".join(captured.output)
        self.assertNotIn("refresh-token-in-status-line", log_text)
        self.assertNotIn("Traceback", log_text)
        self.assertIn("BadStatusLine", log_text)
        self.assertIs(response.exception, failure)

    def test_a_connection_failure_response_has_a_none_status(self):
        # Exception-only responses used to have no status attribute at all, so
        # status checks crashed with AttributeError before reaching the
        # connection-error handling.
        from rsconnect.http_support import HTTPResponse

        response = HTTPResponse("https://example.com/x", exception=OSError("connection refused"))
        self.assertIsNone(response.status)
        self.assertIsNone(response.reason)

    def test_json_redaction_survives_escaped_quotes(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = '{"secrets": [{"name": "V", "value": "with \\" quote and tail"}]}'
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("quote and tail", redacted)
        self.assertIn("<redacted>", redacted)

    def test_presigned_url_query_is_redacted(self):
        from rsconnect.http_support import _redacted_uri_for_log

        uri = (
            "/bucket/bundle.tar.gz?X-Amz-Credential=AKIA%2F123&X-Amz-Signature=deadbeef"
            "&X-Amz-Security-Token=tok123&X-Amz-Expires=300"
        )
        redacted = _redacted_uri_for_log(uri)
        self.assertNotIn("deadbeef", redacted)
        self.assertNotIn("tok123", redacted)
        self.assertNotIn("AKIA", redacted)
        self.assertIn("X-Amz-Expires=300", redacted)

    def test_encoded_query_names_are_redacted_without_rewriting_other_parameters(self):
        from rsconnect.http_support import _redacted_uri_for_log

        uri = "/path?keep=%2f+value&refresh%5Ftoken=echoed-secret&X-Amz%2dSignature=signature-secret&tail=a+b#section"
        self.assertEqual(
            _redacted_uri_for_log(uri),
            "/path?keep=%2f+value&refresh%5Ftoken=<redacted>&X-Amz%2dSignature=<redacted>&tail=a+b#section",
        )

    def test_encoded_fragment_fields_are_redacted_with_and_without_a_query(self):
        from rsconnect.http_support import _redacted_uri_for_log

        for prefix in ("/callback", "/callback?keep=%2f+value"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    _redacted_uri_for_log(prefix + "#refresh%5Ftoken=fragment-secret&tab=a+b"),
                    prefix + "#refresh%5Ftoken=<redacted>&tab=a+b",
                )
                self.assertEqual(_redacted_uri_for_log(prefix + "#ordinary-section"), prefix + "#ordinary-section")

    def test_queryless_uri_text_and_fragment_credentials_remain_redacted(self):
        from rsconnect.http_support import _redacted_uri_for_log

        self.assertEqual(_redacted_uri_for_log("account token=plain-secret"), "account token=<redacted>")
        self.assertEqual(
            _redacted_uri_for_log("/callback#refresh_token=fragment-secret"),
            "/callback#refresh_token=<redacted>",
        )

    def test_azure_sas_sig_param_is_redacted(self):
        # Azure-style presigned URLs carry the signature in a bare "sig" param.
        from rsconnect.http_support import _redacted_uri_for_log

        uri = "/bucket/bundle.tar.gz?sv=2024-01-01&sig=Sw%2Fabc123&se=2026-08-13"
        redacted = _redacted_uri_for_log(uri)
        self.assertNotIn("abc123", redacted)
        self.assertIn("sig=<redacted>", redacted)
        self.assertIn("sv=2024-01-01", redacted)
        self.assertIn("se=2026-08-13", redacted)

    def test_uri_redaction_is_case_insensitive(self):
        from rsconnect.http_support import _redacted_uri_for_log

        self.assertNotIn("hunter2", _redacted_uri_for_log("/path?TOKEN=hunter2&x=1"))

    def test_presigned_urls_inside_json_string_values_are_redacted(self):
        from rsconnect.http_support import _redacted_body_for_log

        body = (
            '{"next_revision": {"id": "r1", "source_bundle_upload_url": '
            '"https://up.example/b?token=signed-cred&X-Amz-Signature=deadbeef"}}'
        )
        redacted = str(_redacted_body_for_log(body))
        self.assertNotIn("signed-cred", redacted)
        self.assertNotIn("deadbeef", redacted)
        self.assertIn("up.example", redacted)
