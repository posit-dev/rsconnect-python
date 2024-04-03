import shutil
import tempfile
from os.path import exists, join
from unittest import TestCase

from rsconnect.api import RSConnectServer
from rsconnect.exception import RSConnectException
from rsconnect.metadata import (
    AppStore,
    ContentBuildStore,
    ServerStore,
    _normalize_server_url,
)
from rsconnect.models import BuildStatus


class TestServerMetadata(TestCase):
    def setUp(self):
        # Use temporary stores, to keep each test isolated
        self.tempDir = tempfile.mkdtemp()
        self.server_store = ServerStore(base_dir=self.tempDir)
        self.server_store_path = join(self.tempDir, "servers.json")
        self.assertFalse(exists(self.server_store_path))

        self.server_store.set("foo", "http://connect.local", "notReallyAnApiKey", ca_data="/certs/connect")
        self.server_store.set("bar", "http://connect.remote", "differentApiKey", insecure=True)
        self.server_store.set(
            "baz",
            "https://shinyapps.io",
            account_name="some-account",
            token="someToken",
            secret="c29tZVNlY3JldAo=",
        )
        self.assertEqual(len(self.server_store.get_all_servers()), 3, "Unexpected servers after setup")

    def tearDown(self):
        # clean up our temp test directory created with tempfile.mkdtemp()
        shutil.rmtree(self.tempDir)

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

        self.assertEqual(
            self.server_store.get_by_name("baz"),
            dict(
                name="baz",
                url="https://shinyapps.io",
                account_name="some-account",
                token="someToken",
                secret="c29tZVNlY3JldAo=",
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
        self.assertEqual(len(self.server_store.get_all_servers()), 3)
        self.assertFalse(self.server_store.remove_by_url("http://frazzle"))
        self.assertEqual(len(self.server_store.get_all_servers()), 3)

    def test_list(self):
        servers = self.server_store.get_all_servers()
        self.assertEqual(len(servers), 3)
        self.assertEqual(servers[0]["name"], "bar")
        self.assertEqual(servers[0]["url"], "http://connect.remote")
        self.assertEqual(servers[1]["name"], "baz")
        self.assertEqual(servers[1]["url"], "https://shinyapps.io")
        self.assertEqual(servers[2]["name"], "foo")
        self.assertEqual(servers[2]["url"], "http://connect.local")

    def check_resolve_call(self, name, server, api_key, insecure, ca_cert, should_be_from_store):
        server_data = self.server_store.resolve(name, server)

        self.assertEqual(server_data.url, "http://connect.local")
        self.assertEqual(server_data.api_key, "notReallyAnApiKey")
        self.assertEqual(server_data.insecure, False)
        self.assertEqual(server_data.ca_data, "/certs/connect")
        self.assertTrue(server_data.from_store, should_be_from_store)

    def test_resolve_by_name(self):
        self.check_resolve_call("foo", None, None, None, None, True)

    def test_resolve_by_url(self):
        self.check_resolve_call(None, "http://connect.local", None, None, None, True)

    def test_resolve_by_default(self):
        # with multiple entries, server None will not resolve by default
        server_data = self.server_store.resolve(None, None)
        self.assertEqual(server_data.url, None)

        # with only a single entry, server None will resolve to that entry
        self.server_store.remove_by_url("http://connect.remote")
        self.server_store.remove_by_url("https://shinyapps.io")
        self.check_resolve_call(None, None, None, None, None, True)

    def test_resolve_from_args(self):
        name, server = (
            None,
            "https://secured.connect",
        )
        server_data = self.server_store.resolve(name, server)

        self.assertEqual(server_data.url, "https://secured.connect")
        self.assertEqual(server_data.api_key, None)
        self.assertEqual(server_data.insecure, None)
        self.assertEqual(server_data.ca_data, None)
        self.assertFalse(server_data.from_store)

    def test_save_and_load(self):
        temp = tempfile.mkdtemp()
        server_store = ServerStore(base_dir=temp)
        path = join(temp, "servers.json")

        self.assertFalse(exists(path))

        server_store.set("foo", "http://connect.local", api_key="notReallyAnApiKey", ca_data="/certs/connect")

        self.assertTrue(exists(path))

        with open(path, "r") as f:
            data = f.read()

        self.assertIn("foo", data)
        self.assertIn("http://connect.local", data)
        self.assertIn("notReallyAnApiKey", data)
        self.assertIn("/certs/connect", data)

        server_store2 = ServerStore(base_dir=temp)
        self.assertEqual(server_store.get_all_servers(), server_store2.get_all_servers())

    def test_get_path(self):
        self.assertIn("servers.json", self.server_store.get_path())


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
                app_store_version=1,
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
                app_store_version=1,
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
                raise OSError("Mock: path %s in directory %s is not writable" % (path_to_open, self.tempdir))
            return open(path_to_open, mode, *args, **kw)

        path = join(self.tempdir, "rsconnect-python", "notebook.ipynb")
        self.assertFalse(exists(path))
        self.app_store.save(mock_open)
        self.assertFalse(exists(path))

        new_app_store = AppStore(self.nb_path)
        new_app_store.load()
        self.assertEqual(new_app_store._data, self.app_store._data)


class TestHelpers(TestCase):
    def test_normalize_server_url(self):
        self.assertEqual("localhost_3939", _normalize_server_url("https://localhost:3939"))
        self.assertEqual("127_0_0_1_3939", _normalize_server_url("https://127.0.0.1:3939"))
        self.assertEqual("connect_dev", _normalize_server_url("https://connect.dev"))
        self.assertEqual("connect_dev_6443", _normalize_server_url("https://connect.dev:6443"))


class TestBuildMetadata(TestCase):
    def setUp(self):
        self.server_store = ServerStore()
        self.server_store.set("connect", "https://connect.remote:6443", api_key="apiKey", insecure=True)
        self.server = RSConnectServer("https://connect.remote:6443", api_key="apiKey", insecure=True, ca_data=None)
        self.build_store = ContentBuildStore(self.server)
        self.build_store._set("rsconnect_build_running", False)
        self.build_store._set(
            "rsconnect_content",
            {
                "c96db3f3-87a1-4df5-9f58-eb109c397718": {
                    "guid": "c96db3f3-87a1-4df5-9f58-eb109c397718",
                    "bundle_id": "177",
                    "title": "orphan-proc-shiny-test",
                    "name": "orphan-proc-shiny-test",
                    "app_mode": "shiny",
                    "content_url": "https://connect.remote:6443/content/c96db3f3-87a1-4df5-9f58-eb109c397718/",
                    "dashboard_url": "https://connect.remote:6443/connect/#/apps/c96db3f3-87a1-4df5-9f58-eb109c397718",
                    "created_time": "2021-11-04T18:07:12Z",
                    "last_deployed_time": "2021-11-10T19:10:56Z",
                    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
                    "rsconnect_build_status": "NEEDS_BUILD",
                },
                "fe673896-f92a-40cc-be4c-e4872bb90a37": {
                    "guid": "fe673896-f92a-40cc-be4c-e4872bb90a37",
                    "bundle_id": "185",
                    "title": "interactive-rmd",
                    "name": "interactive-rmd",
                    "app_mode": "rmd-shiny",
                    "content_url": "https://connect.remote:6443/content/fe673896-f92a-40cc-be4c-e4872bb90a37/",
                    "dashboard_url": "https://connect.remote:6443/connect/#/apps/fe673896-f92a-40cc-be4c-e4872bb90a37",
                    "created_time": "2021-11-15T15:37:53Z",
                    "last_deployed_time": "2021-11-15T15:37:57Z",
                    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
                    "rsconnect_build_status": "ERROR",
                },
                "a0b6b5a2-5fbe-4293-8310-4f80054bc24f": {
                    "guid": "a0b6b5a2-5fbe-4293-8310-4f80054bc24f",
                    "bundle_id": "184",
                    "title": "stock-report-jupyter",
                    "name": "stock-report-jupyter",
                    "app_mode": "jupyter-static",
                    "content_url": "https://connect.remote:6443/content/a0b6b5a2-5fbe-4293-8310-4f80054bc24f/",
                    "dashboard_url": "https://connect.remote:6443/connect/#/apps/a0b6b5a2-5fbe-4293-8310-4f80054bc24f",
                    "created_time": "2021-11-15T15:27:18Z",
                    "last_deployed_time": "2021-11-15T15:35:27Z",
                    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
                    "rsconnect_build_status": "RUNNING",
                },
                "23315cc9-ed2a-40ad-9e99-e5e49066531a": {
                    "guid": "23315cc9-ed2a-40ad-9e99-e5e49066531a",
                    "bundle_id": "180",
                    "title": "static-rmd",
                    "name": "static-rmd2",
                    "app_mode": "rmd-static",
                    "content_url": "https://connect.remote:6443/content/23315cc9-ed2a-40ad-9e99-e5e49066531a/",
                    "dashboard_url": "https://connect.remote:6443/connect/#/apps/23315cc9-ed2a-40ad-9e99-e5e49066531a",
                    "created_time": "2021-11-15T15:20:58Z",
                    "last_deployed_time": "2021-11-15T15:25:31Z",
                    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
                    "rsconnect_build_status": "COMPLETE",
                    "rsconnect_last_build_time": "2021-12-13T18:10:38Z",
                    "rsconnect_last_build_log": "/logs/localhost_3939/23315cc9-ed2a-40ad-9e99-e5e49066531a/ZUf44zVWHjODv1Rq.log",
                    "rsconnect_build_task_result": {
                        "id": "ZUf44zVWHjODv1Rq",
                        "user_id": 1,
                        "result": {"type": "", "data": None},
                        "finished": True,
                        "code": 0,
                        "error": "",
                    },
                },
                "015143da-b75f-407c-81b1-99c4a724341e": {
                    "guid": "015143da-b75f-407c-81b1-99c4a724341e",
                    "bundle_id": "176",
                    "title": "plumber-async",
                    "name": "plumber-async",
                    "app_mode": "api",
                    "content_url": "https://connect.remote:6443/content/015143da-b75f-407c-81b1-99c4a724341e/",
                    "dashboard_url": "https://connect.remote:6443/connect/#/apps/015143da-b75f-407c-81b1-99c4a724341e",
                    "created_time": "2021-11-01T20:43:32Z",
                    "last_deployed_time": "2021-11-03T17:48:59Z",
                    "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
                    "rsconnect_build_status": "NEEDS_BUILD",
                },
            },
        )

    def test_get_build_logs_dir(self):
        logs_dir = self.build_store.get_build_logs_dir("015143da-b75f-407c-81b1-99c4a724341e")
        self.assertEqual(
            join(self.build_store._base_dir, "logs", "connect_remote_6443", "015143da-b75f-407c-81b1-99c4a724341e"),
            logs_dir,
        )

    def test_get_set_build_running(self):
        self.assertFalse(self.build_store.get_build_running())
        self.build_store.set_build_running(True)
        self.assertTrue(self.build_store.get_build_running())

    def test_add_content_item(self):
        guid = "015143da-b75f-407c-81b1-99c4a724341e"
        content = {
            "bundle_id": "1234",
            "title": "test item",
            "app_mode": "api",
            "dashboard_url": "https://connect.remote:6443/connect/#/apps/%s" % guid,
            "content_url": "https://connect.remote:6443/content/%s/" % guid,
            "guid": guid,
            "name": "test-test-test",
            "last_deployed_time": "2021-10-25T20:21:37Z",
            "created_time": "2021-09-01T15:12:17Z",
            "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
            "other_field": "this should be ignored",
        }
        self.build_store.add_content_item(content)
        content = self.build_store.get_content_item(guid)
        self.assertNotIn("other_field", content)
        self.assertEqual(
            content,
            {
                "bundle_id": "1234",
                "title": "test item",
                "app_mode": "api",
                "dashboard_url": "https://connect.remote:6443/connect/#/apps/%s" % guid,
                "content_url": "https://connect.remote:6443/content/%s/" % guid,
                "guid": guid,
                "name": "test-test-test",
                "last_deployed_time": "2021-10-25T20:21:37Z",
                "created_time": "2021-09-01T15:12:17Z",
                "owner_guid": "edf26318-0027-4d9d-bbbb-54703ebb1855",
            },
        )

    def test_get_content_item(self):
        self.assertIsNotNone(self.build_store.get_content_item("015143da-b75f-407c-81b1-99c4a724341e"))
        with self.assertRaises(RSConnectException):
            self.build_store.get_content_item("not real")
        with self.assertRaises(RSConnectException):
            self.build_store.get_content_item(None)

    def test_remove_content_item(self):
        guid = "015143da-b75f-407c-81b1-99c4a724341e"
        self.build_store.remove_content_item(guid, purge=False)
        items = self.build_store.get_content_items()
        self.assertEqual(4, len(items))
        self.assertNotIn(guid, list(map(lambda x: x["guid"], items)))

    def test_set_content_item_build_status(self):
        guid = "015143da-b75f-407c-81b1-99c4a724341e"
        self.build_store.set_content_item_build_status(guid, BuildStatus.COMPLETE)
        self.assertEqual(BuildStatus.COMPLETE, self.build_store.get_content_item(guid)["rsconnect_build_status"])
        self.build_store.set_content_item_build_status(guid, BuildStatus.ERROR)
        self.assertEqual(BuildStatus.ERROR, self.build_store.get_content_item(guid)["rsconnect_build_status"])

    def test_get_content_items(self):
        self.assertEqual(5, len(self.build_store.get_content_items()))
        self.assertEqual(2, len(self.build_store.get_content_items(status=BuildStatus.NEEDS_BUILD)))
        self.assertEqual(1, len(self.build_store.get_content_items(status=BuildStatus.ERROR)))
