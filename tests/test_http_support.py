from unittest import TestCase

from rsconnect.http_support import (
    _connection_factory,
    _user_agent,
    _create_ssl_connection,
    append_to_path,
    HTTPServer,
    CookieJar,
)


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
        # Cookies are session credentials; the jar logs names only.
        jar = CookieJar()
        with self.assertLogs("rsconnect", level="DEBUG") as captured:
            jar.store_cookies(FakeSetCookieResponse(["session=s3ssionv4lue"]))
            header = jar.get_cookie_header_value()

        self.assertEqual(header, "session=s3ssionv4lue")
        log_text = "\n".join(captured.output)
        self.assertNotIn("s3ssionv4lue", log_text)
        self.assertIn("session", log_text)


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
