
import tempfile

from unittest import TestCase
from os.path import exists, join

from rsconnect.metadata import ServerStore


class TestServerMetadata(TestCase):
    def setUp(self):
        self.server_store = ServerStore()
        self.server_store.add('foo', 'http://connect.local', 'notReallyAnApiKey', ca_cert='/certs/connect')
        self.server_store.add('bar', 'http://connect.remote', 'differentApiKey', insecure=True)

    def test_add(self):
        self.assertEqual(self.server_store.get('foo'), dict(
            name='foo',
            url='http://connect.local',
            api_key='notReallyAnApiKey',
            insecure=False,
            ca_cert='/certs/connect',
        ))
        
        self.assertEqual(self.server_store.get('bar'), dict(
            name='bar',
            url='http://connect.remote',
            api_key='differentApiKey',
            insecure=True,
            ca_cert=None,
        ))

    def test_remove(self):
        self.server_store.remove('foo')
        self.assertIsNone(self.server_store.get('foo'))
        self.assertIsNotNone(self.server_store.get('bar'))

    def test_resolve_by_name(self):
        server, api_key, insecure, cacert = 'foo', None, None, None
        server, api_key, insecure, cacert = self.server_store.resolve(server, api_key, insecure, cacert)

        self.assertEqual(server, 'http://connect.local')
        self.assertEqual(api_key, 'notReallyAnApiKey')
        self.assertEqual(insecure, False)
        self.assertEqual(cacert, '/certs/connect')

    def test_resolve_by_url(self):
        server, api_key, insecure, cacert = 'http://connect.local', None, None, None
        server, api_key, insecure, cacert = self.server_store.resolve(server, api_key, insecure, cacert)

        self.assertEqual(server, 'http://connect.local')
        self.assertEqual(api_key, 'notReallyAnApiKey')
        self.assertEqual(insecure, False)
        self.assertEqual(cacert, '/certs/connect')

    def test_load_save(self):
        temp = tempfile.mkdtemp()
        server_store = ServerStore(base_dir=temp)
        server_store.add('foo', 'http://connect.local', 'notReallyAnApiKey', ca_cert='/certs/connect')

        path = join(temp, 'servers.json')

        self.assertFalse(exists(path))
        server_store.save()
        self.assertTrue(exists(path))

        with open(path, 'r') as f:
            data = f.read()

        self.assertIn('foo', data)
        self.assertIn('http://connect.local', data)
        self.assertIn('notReallyAnApiKey', data)
        self.assertIn('/certs/connect', data)
