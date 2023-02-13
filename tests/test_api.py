from unittest import TestCase
from unittest.mock import Mock, patch

from rsconnect.exception import RSConnectException
from .utils import (
    require_api_key,
    require_connect,
)
from rsconnect.api import RSConnectClient, RSConnectExecutor, RSConnectServer, _to_server_check_list


class TestAPI(TestCase):
    def test_executor_init(self):
        connect_server = require_connect()
        api_key = require_api_key()
        ce = RSConnectExecutor(None, connect_server, api_key, True, None)
        self.assertEqual(ce.remote_server.url, connect_server)

    def test_output_task_log(self):
        lines = ["line 1", "line 2", "line 3"]
        task_status = {
            "status": lines,
            "last_status": 3,
            "finished": True,
            "code": 0,
        }
        output = []

        self.assertEqual(RSConnectClient.output_task_log(task_status, 0, output.append), 3)
        self.assertEqual(lines, output)

        task_status["last_status"] = 4
        task_status["status"] = ["line 4"]
        self.assertEqual(RSConnectClient.output_task_log(task_status, 3, output.append), 4)

        self.assertEqual(len(output), 4)
        self.assertEqual(output[3], "line 4")

    def test_to_server_check_list(self):
        a_list = _to_server_check_list("no-scheme")

        self.assertEqual(a_list, ["https://no-scheme", "http://no-scheme"])

        a_list = _to_server_check_list("//no-scheme")

        self.assertEqual(a_list, ["https://no-scheme", "http://no-scheme"])

        a_list = _to_server_check_list("scheme://no-scheme")

        self.assertEqual(a_list, ["scheme://no-scheme"])

    def test_make_deployment_name(self):
        connect_server = require_connect()
        api_key = require_api_key()
        ce = RSConnectExecutor(None, connect_server, api_key, True, None)
        self.assertEqual(ce.make_deployment_name("title", False), "title")
        self.assertEqual(ce.make_deployment_name("Title", False), "title")
        self.assertEqual(ce.make_deployment_name("My Title", False), "my_title")
        self.assertEqual(ce.make_deployment_name("My  Title", False), "my_title")
        self.assertEqual(ce.make_deployment_name("My _ Title", False), "my_title")
        self.assertEqual(ce.make_deployment_name("My-Title", False), "my-title")
        # noinspection SpellCheckingInspection
        self.assertEqual(ce.make_deployment_name("M\ry\n \tT\u2103itle", False), "my_title")
        self.assertEqual(ce.make_deployment_name("\r\n\t\u2103", False), "___")
        self.assertEqual(ce.make_deployment_name("\r\n\tR\u2103", False), "__r")

    def test_connect_authorization_header(self):
        jwt_connect_server = RSConnectServer("http://test-server", None, bootstrap_jwt="123.456.789")
        jwt_connect_client = RSConnectClient(jwt_connect_server)
        self.assertEqual(jwt_connect_client.get_authorization(), "Connect-Bootstrap 123.456.789")

        api_key_connect_server = RSConnectServer("http://test-server", "api_key")
        api_key_connect_client = RSConnectClient(api_key_connect_server)
        self.assertEqual(api_key_connect_client.get_authorization(), "Key api_key")

        none_connect_server = RSConnectServer("http://test-server", None)
        none_connect_client = RSConnectClient(none_connect_server)
        self.assertEqual(none_connect_client.get_authorization(), None)


class RSConnectClientTestCase(TestCase):
    def test_deploy_existing_application_with_failure(self):
        with patch.object(RSConnectClient, "__init__", lambda _, server, cookies, timeout: None):
            client = RSConnectClient(Mock(), Mock(), Mock())
            client.app_get = Mock(return_value=Mock())
            client._server = Mock(spec=RSConnectServer)
            client._server.handle_bad_response = Mock(side_effect=RSConnectException(""))
            app_id = Mock()
            with self.assertRaises(RSConnectException):
                client.deploy(app_id, app_name=None, app_title=None, title_is_default=None, tarball=None)
