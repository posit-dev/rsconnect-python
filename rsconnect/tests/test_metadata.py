import tempfile

from unittest import TestCase
from os.path import exists, join

from rsconnect.metadata import AppStore, ServerStore


class TestServerMetadata(TestCase):
    def setUp(self):
        self.server_store = ServerStore()
        self.server_store.set(
            "foo", "http://connect.local", "notReallyAnApiKey", ca_data="/certs/connect"
        )
        self.server_store.set(
            "bar", "http://connect.remote", "differentApiKey", insecure=True
        )

    def test_add(self):
        self.assertEqual(
            self.server_store.get_by_name("foo"),
            dict(
                name="foo",
                url="http://connect.local",
                api_key="notReallyAnApiKey",
                insecure=False,
                ca_cert="/certs/connect",
            ),
        )

        self.assertEqual(
            self.server_store.get_by_name("bar"),
            dict(
                name="bar",
                url="http://connect.remote",
                api_key="differentApiKey",
                insecure=True,
                ca_cert=None,
            ),
        )

    def test_remove_by_name(self):
        self.server_store.remove_by_name("foo")
        self.assertIsNone(self.server_store.get_by_name("foo"))
        self.assertIsNone(self.server_store.get_by_url("http://connect.local"))
        self.assertIsNotNone(self.server_store.get_by_name("bar"))
        self.assertIsNotNone(self.server_store.get_by_url("http://connect.remote"))

    def test_remove_by_url(self):
        self.server_store.remove_by_url("http://connect.local")
        self.assertIsNone(self.server_store.get_by_name("foo"))
        self.assertIsNone(self.server_store.get_by_url("http://connect.local"))
        self.assertIsNotNone(self.server_store.get_by_name("bar"))
        self.assertIsNotNone(self.server_store.get_by_url("http://connect.remote"))

    def test_remove_not_found(self):
        self.assertFalse(self.server_store.remove_by_name("frazzle"))
        self.assertEqual(len(self.server_store.get_all_servers()), 2)
        self.assertFalse(self.server_store.remove_by_url("http://frazzle"))
        self.assertEqual(len(self.server_store.get_all_servers()), 2)

    def test_list(self):
        servers = self.server_store.get_all_servers()
        self.assertEqual(len(servers), 2)
        self.assertEqual(servers[0]["name"], "bar")
        self.assertEqual(servers[0]["url"], "http://connect.remote")
        self.assertEqual(servers[1]["name"], "foo")
        self.assertEqual(servers[1]["url"], "http://connect.local")

    def check_resolve_call(
        self, name, server, api_key, insecure, ca_cert, should_be_from_store
    ):
        server, api_key, insecure, ca_cert, from_store = self.server_store.resolve(
            name, server, api_key, insecure, ca_cert
        )

        self.assertEqual(server, "http://connect.local")
        self.assertEqual(api_key, "notReallyAnApiKey")
        self.assertEqual(insecure, False)
        self.assertEqual(ca_cert, "/certs/connect")
        self.assertTrue(from_store, should_be_from_store)

    def test_resolve_by_name(self):
        self.check_resolve_call("foo", None, None, None, None, True)

    def test_resolve_by_url(self):
        self.check_resolve_call(None, "http://connect.local", None, None, None, True)

    def test_resolve_by_default(self):
        # with multiple entries, server None will not resolve by default
        name, server, api_key, insecure, ca_cert = None, None, None, None, None
        server, api_key, insecure, ca_cert, _ = self.server_store.resolve(
            name, server, api_key, insecure, ca_cert
        )
        self.assertEqual(server, None)

        # with only a single entry, server None will resolve to that entry
        self.server_store.remove_by_url("http://connect.remote")
        self.check_resolve_call(None, None, None, None, None, True)

    def test_resolve_from_args(self):
        name, server, api_key, insecure, ca_cert = (
            None,
            "https://secured.connect",
            "an-api-key",
            True,
            "fake-cert",
        )
        server, api_key, insecure, ca_cert, from_store = self.server_store.resolve(
            name, server, api_key, insecure, ca_cert
        )

        self.assertEqual(server, "https://secured.connect")
        self.assertEqual(api_key, "an-api-key")
        self.assertTrue(insecure)
        self.assertEqual(ca_cert, "fake-cert")
        self.assertFalse(from_store)

    def test_save_and_load(self):
        temp = tempfile.mkdtemp()
        server_store = ServerStore(base_dir=temp)
        path = join(temp, "servers.json")

        self.assertFalse(exists(path))

        server_store.set(
            "foo", "http://connect.local", "notReallyAnApiKey", ca_data="/certs/connect"
        )

        self.assertTrue(exists(path))

        with open(path, "r") as f:
            data = f.read()

        self.assertIn("foo", data)
        self.assertIn("http://connect.local", data)
        self.assertIn("notReallyAnApiKey", data)
        self.assertIn("/certs/connect", data)

        server_store2 = ServerStore(base_dir=temp)
        self.assertEqual(
            server_store.get_all_servers(), server_store2.get_all_servers()
        )

    def test_get_path(self):
        self.assertIn("rsconnect-python", self.server_store.get_path())


class TestAppMetadata(TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        self.nb_path = join(self.tempdir, "notebook.ipynb")

        with open(self.nb_path, "w"):
            pass

        self.app_store = AppStore(self.nb_path)
        self.app_store.set(
            "http://dev",
            "/path/to/file",
            "http://dev/apps/123",
            123,
            "shouldBeAGuid",
            "Important Title",
            "static",
        )
        self.app_store.set(
            "http://prod",
            "/path/to/file",
            "http://prod/apps/456",
            456,
            "anotherFakeGuid",
            "Untitled",
            "jupyter-static",
        )

    def test_get(self):
        self.assertEqual(
            self.app_store.get("http://dev"),
            dict(
                server_url="http://dev",
                app_url="http://dev/apps/123",
                app_id=123,
                app_guid="shouldBeAGuid",
                title="Important Title",
                app_mode="static",
                filename="/path/to/file",
            ),
        )

        self.assertEqual(
            self.app_store.get("http://prod"),
            dict(
                server_url="http://prod",
                app_url="http://prod/apps/456",
                app_id=456,
                app_guid="anotherFakeGuid",
                title="Untitled",
                app_mode="jupyter-static",
                filename="/path/to/file",
            ),
        )

    def test_local_save_load(self):
        path = join(self.tempdir, "rsconnect-python", "notebook.json")
        self.assertTrue(exists(path))

        with open(path, "r") as f:
            data = f.read()

        self.assertIn("http://dev", data)
        self.assertIn("http://dev/apps/123", data)
        self.assertIn("123", data)
        self.assertIn("shouldBeAGuid", data)
        self.assertIn("Important Title", data)
        self.assertIn("static", data)
        self.assertIn("/path/to/file", data)

        self.assertIn("http://prod", data)
        self.assertIn("http://prod/apps/456", data)
        self.assertIn("456", data)
        self.assertIn("anotherFakeGuid", data)
        self.assertIn("Untitled", data)
        self.assertIn("jupyter-static", data)

        new_app_store = AppStore(self.nb_path)
        new_app_store.load()
        self.assertEqual(new_app_store._data, self.app_store._data)

    def test_global_save_load(self):
        def mock_open(path_to_open, mode, *args, **kw):
            if path_to_open.startswith(self.tempdir) and "w" in mode:
                raise OSError(
                    "Mock: path %s in directory %s is not writable"
                    % (path_to_open, self.tempdir)
                )
            return open(path_to_open, mode, *args, **kw)

        path = join(self.tempdir, "rsconnect-python", "notebook.ipynb")
        self.assertFalse(exists(path))
        self.app_store.save(mock_open)
        self.assertFalse(exists(path))

        new_app_store = AppStore(self.nb_path)
        new_app_store.load()
        self.assertEqual(new_app_store._data, self.app_store._data)
