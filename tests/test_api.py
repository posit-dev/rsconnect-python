from unittest import TestCase
from .utils import (
    require_api_key,
    require_connect,
)
from rsconnect.api import RSConnectClient, RSConnectExecutor, _to_server_check_list


class TestAPI(TestCase):
    def test_executor_init(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
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
        connect_server = require_connect(self)
        api_key = require_api_key(self)
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
