from unittest import TestCase

from rsconnect.http_support import _connection_factory,  _user_agent, _create_ssl_connection, append_to_path, HTTPServer


class TestHTTPSupport(TestCase):
    def test_connection_factory_map(self):
        self.assertEqual(len(_connection_factory), 2)
        self.assertIn('http', _connection_factory)
        self.assertIn('https', _connection_factory)
        self.assertNotEqual(_connection_factory['http'], _connection_factory['https'])

    def test_create_ssl_checks(self):
        with self.assertRaises(ValueError):
            _create_ssl_connection(None, None, True, 'fake')

    def test_append_to_path(self):
        self.assertEqual(append_to_path('path/', '/sub'), 'path/sub')
        self.assertEqual(append_to_path('path', 'sub'), 'path/sub')
        self.assertEqual(append_to_path('path/', 'sub'), 'path/sub')
        self.assertEqual(append_to_path('path', '/sub'), 'path/sub')

    def test_HTTPServer_instantiation_error(self):
        with self.assertRaises(ValueError):
            HTTPServer('ftp://example.com')

    def test_header_stuff(self):
        server = HTTPServer('http://example.com')

        server.authorization('Basic user:pw')

        self.assertEqual(len(server._headers), 2)
        self.assertIn('User-Agent', server._headers)
        self.assertEqual(server._headers['User-Agent'], _user_agent)
        self.assertIn('Authorization', server._headers)
        self.assertEqual(server._headers['Authorization'], 'Basic user:pw')

        server.key_authorization('my-api-key')

        self.assertEqual(len(server._headers), 2)
        self.assertIn('User-Agent', server._headers)
        self.assertEqual(server._headers['User-Agent'], _user_agent)
        self.assertIn('Authorization', server._headers)
        self.assertEqual(server._headers['Authorization'], 'Key my-api-key')
