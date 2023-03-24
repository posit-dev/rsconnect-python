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
