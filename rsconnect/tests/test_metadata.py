
import tempfile

from unittest import TestCase
from os.path import exists, join

from rsconnect.metadata import AppStore, ServerStore


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


class TestAppMetadata(TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.nb_path = join(self.tempdir, 'notebook.ipynb')

        with open(self.nb_path, 'w'):
            pass

        self.app_store = AppStore(self.nb_path)
        self.app_store.set('http://dev', 123, 'shouldBeAGuid', 'Important Title', 'static')
        self.app_store.set('http://prod', 456, 'anotherFakeGuid', 'Untitled', 'jupyter-static')

    def test_get(self):
        self.assertEqual(self.app_store.get('http://dev'), dict(
            server_url='http://dev',
            app_id=123,
            app_guid='shouldBeAGuid',
            title='Important Title',
            app_mode='static',
        ))

        self.assertEqual(self.app_store.get('http://prod'), dict(
            server_url='http://prod',
            app_id=456,
            app_guid='anotherFakeGuid',
            title='Untitled',
            app_mode='jupyter-static',
        ))

    def test_local_save_load(self):
        path = join(self.tempdir, '.notebook.ipynb.rsconnect.json')
        self.assertFalse(exists(path))
        self.app_store.save()
        self.assertTrue(exists(path))

        with open(path, 'r') as f:
            data = f.read()

        self.assertIn('http://dev', data)
        self.assertIn('123', data)
        self.assertIn('shouldBeAGuid', data)
        self.assertIn('Important Title', data)
        self.assertIn('static', data)

        self.assertIn('http://prod', data)
        self.assertIn('456', data)
        self.assertIn('anotherFakeGuid', data)
        self.assertIn('Untitled', data)
        self.assertIn('jupyter-static', data)

        new_app_store = AppStore(self.nb_path)
        new_app_store.load()
        self.assertEqual(new_app_store.data, self.app_store.data)

    def test_global_save_load(self):
        def mockOpen(path, mode, *args, **kw):
            if path.startswith(self.tempdir) and 'w' in mode:
                raise OSError('Mock: this directory is not writable')
            return open(path, mode, *args, **kw)

        path = join(self.tempdir, '.notebook.ipynb.rsconnect.json')
        self.assertFalse(exists(path))
        self.app_store.save(mockOpen)
        self.assertFalse(exists(path))

        new_app_store = AppStore(self.nb_path)
        new_app_store.load()
        self.assertEqual(new_app_store.data, self.app_store.data)
