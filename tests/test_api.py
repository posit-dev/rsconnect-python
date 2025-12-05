import io
import json
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

import httpretty
import pytest

from rsconnect.api import (
    PositClient,
    RSConnectClient,
    RSConnectExecutor,
    RSConnectServer,
    ShinyappsServer,
    ShinyappsService,
    SPCSConnectServer,
)
from rsconnect.exception import DeploymentFailedException, RSConnectException

from .utils import require_api_key, require_connect


class TestAPI(TestCase):
    def test_executor_init(self):
        connect_server = require_connect()
        api_key = require_api_key()
        ce = RSConnectExecutor(None, None, connect_server, api_key, True, None)
        self.assertEqual(ce.remote_server.url, connect_server)

    def test_output_task_log(self):
        first_task = {
            "output": ["line 1", "line 2", "line 3"],
            "last": 3,
            "finished": False,
            "code": 0,
        }
        output = []

        RSConnectClient.output_task_log(first_task, output.append)
        self.assertEqual(["line 1", "line 2", "line 3"], output)

        second_task = {
            "output": ["line 4"],
            "last": 4,
            "finished": True,
            "code": 0,
        }
        RSConnectClient.output_task_log(second_task, output.append)
        self.assertEqual(["line 1", "line 2", "line 3", "line 4"], output)

    def test_make_deployment_name(self):
        connect_server = require_connect()
        api_key = require_api_key()
        ce = RSConnectExecutor(None, None, connect_server, api_key, True, None)
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


class TestSystemRuntimeCachesAPI(TestCase):
    # RSConnectExecutor.runtime_caches returns the resulting JSON from the server.
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_client_system_caches_runtime_list(self):
        ce = RSConnectExecutor(None, None, "http://test-server/", "api_key")
        mocked_response = {
            "caches": [
                {"language": "R", "version": "3.6.3", "image_name": "Local"},
                {"language": "Python", "version": "5.6.7", "image_name": "teapot.bak"},
            ]
        }
        httpretty.register_uri(
            httpretty.GET,
            "http://test-server/__api__/v1/system/caches/runtime",
            body=json.dumps(mocked_response),
            status=200,
            forcing_headers={"Content-Type": "application/json"},
        )
        result = ce.runtime_caches
        self.assertDictEqual(result, mocked_response)

    # RSConnectExecutor.delete_runtime_cache() dry run returns expected request
    # RSConnectExecutor.delete_runtime_cache() dry run prints expected messages
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_executor_delete_runtime_cache_dry_run(self):
        ce = RSConnectExecutor(None, None, "http://test-server/", "api_key")
        mocked_output = {"language": "Python", "version": "1.2.3", "image_name": "teapot", "task_id": None}

        httpretty.register_uri(
            httpretty.DELETE,
            "http://test-server/__api__/v1/system/caches/runtime",
            body=json.dumps(mocked_output),
            status=200,
            forcing_headers={"Content-Type": "application/json"},
        )

        captured_output = io.StringIO()
        sys.stdout = captured_output
        result, task = ce.delete_runtime_cache(language="Python", version="1.2.3", image_name="teapot", dry_run=True)
        sys.stdout = sys.__stdout__

        # Print expectations
        output_lines = captured_output.getvalue().splitlines()
        self.assertEqual(output_lines[0], "Dry run finished")

        # Result expectations
        self.assertDictEqual(mocked_output, result)
        self.assertEqual(task, None)

    # RSConnectExecutor.delete_runtime_cache() wet run returns expected request
    # RSConnectExecutor.delete_runtime_cache() wet run prints expected messages
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_executor_delete_runtime_cache_wet_run(self):
        ce = RSConnectExecutor(None, None, "http://test-server/", "api_key")
        mocked_delete_output = {
            "language": "Python",
            "version": "1.2.3",
            "image_name": "teapot",
            "task_id": "this_is_a_task_id",
        }
        httpretty.register_uri(
            httpretty.DELETE,
            "http://test-server/__api__/v1/system/caches/runtime",
            body=json.dumps(mocked_delete_output),
            status=200,
            forcing_headers={"Content-Type": "application/json"},
        )

        mocked_task = {
            "id": "this_is_a_task_id",
            "user_id": 1,
            "output": ["Removing runtime cache"],
            "result": {"type": "", "data": None},
            "finished": True,
            "code": 0,
            "error": "",
            "last": 1,
        }
        expected_task = {
            "id": "this_is_a_task_id",
            "user_id": 1,
            "output": ["Removing runtime cache"],
            "status": ["Removing runtime cache"],
            "result": {"type": "", "data": None},
            "finished": True,
            "code": 0,
            "error": "",
            "last": 1,
            "last_status": 1,
        }
        httpretty.register_uri(
            httpretty.GET,
            "http://test-server/__api__/v1/tasks/this_is_a_task_id",
            body=json.dumps(mocked_task),
            status=200,
            forcing_headers={"Content-Type": "application/json"},
        )

        captured_output = io.StringIO()
        sys.stdout = captured_output
        result, task = ce.delete_runtime_cache(language="Python", version="1.2.3", image_name="teapot", dry_run=False)
        sys.stdout = sys.__stdout__

        # Print expectations
        # TODO: *We* don't print anything here anymore. Unsure how to capture log messages from Connect.
        # output_lines = captured_output.getvalue().splitlines()
        # self.assertEqual(output_lines[0], "Cache deletion finished")

        # Result expectations
        self.assertDictEqual(mocked_delete_output, result)
        # mocked task plus backwards-compatible fields for rsconnect-jupyter
        self.assertDictEqual(expected_task, task)

    # RSConnectExecutor.delete_runtime_cache() raises the correct error
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_executor_delete_runtime_cache_error(self):
        ce = RSConnectExecutor(None, None, "http://test-server/", "api_key")
        mocked_delete_output = {"code": 4, "error": "Cache does not exist", "payload": None}
        httpretty.register_uri(
            httpretty.DELETE,
            "http://test-server/__api__/v1/system/caches/runtime",
            body=json.dumps(mocked_delete_output),
            status=404,
            forcing_headers={"Content-Type": "application/json"},
        )

        with self.assertRaisesRegex(RSConnectException, "Cache does not exist"):
            ce.delete_runtime_cache(language="Python", version="1.2.3", image_name="teapot", dry_run=False)


class RSConnectClientTestCase(TestCase):
    def test_deploy_existing_application_with_failure(self):
        with patch.object(RSConnectClient, "__init__", lambda _, server, cookies, timeout: None):
            client = RSConnectClient(Mock(), Mock(), Mock())
            client.app_get = Mock(side_effect=RSConnectException(""))
            client._server = Mock(spec=RSConnectServer)
            app_id = Mock()
            with self.assertRaises(RSConnectException):
                client.deploy(app_id, app_name=None, app_title=None, title_is_default=None, tarball=None)


class ShinyappsServiceTestCase(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cloud_client = Mock(spec=PositClient)
        server = ShinyappsServer("https://api.posit.cloud", "the_account", "the_token", "the_secret")
        self.service = ShinyappsService(self.cloud_client, server)

    def test_do_deploy(self):
        bundle_id = 1
        app_id = 2
        task_id = 3

        self.cloud_client.deploy_application.return_value = {"id": task_id}

        self.service.do_deploy(bundle_id, app_id)

        self.cloud_client.set_bundle_status.assert_called_with(bundle_id, "ready")
        self.cloud_client.deploy_application.assert_called_with(bundle_id, app_id)
        self.cloud_client.wait_until_task_is_successful.assert_called_with(task_id)

    def test_do_deploy_failure(self):
        bundle_id = 1
        app_id = 2
        task_id = 3
        build_task_id = 4

        self.cloud_client.deploy_application.return_value = {"id": task_id}
        self.cloud_client.wait_until_task_is_successful.side_effect = DeploymentFailedException("uh oh")
        self.cloud_client.get_shinyapps_build_task.return_value = {"tasks": [{"id": build_task_id}]}
        task_logs_response = Mock()
        task_logs_response.response_body = "here's why it failed"
        self.cloud_client.get_task_logs.return_value = task_logs_response

        with pytest.raises(DeploymentFailedException):
            self.service.do_deploy(bundle_id, app_id)

        self.cloud_client.set_bundle_status.assert_called_with(bundle_id, "ready")
        self.cloud_client.deploy_application.assert_called_with(bundle_id, app_id)
        self.cloud_client.wait_until_task_is_successful.assert_called_with(task_id)
        self.cloud_client.get_shinyapps_build_task.assert_called_with(task_id)
        self.cloud_client.get_task_logs.assert_called_with(build_task_id)


class SPCSConnectServerTestCase(TestCase):
    def test_init(self):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        assert server.url == "https://spcs.example.com"
        assert server.remote_name == "Posit Connect (SPCS)"
        assert server.snowflake_connection_name == "example_connection"
        assert server.api_key == "test-api-key"

    @patch("rsconnect.api.SPCSConnectServer.token_endpoint")
    def test_token_endpoint(self, mock_token_endpoint):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        mock_token_endpoint.return_value = "https://example.snowflakecomputing.com/"
        endpoint = server.token_endpoint()
        assert endpoint == "https://example.snowflakecomputing.com/"

    @patch("rsconnect.api.get_parameters")
    def test_token_endpoint_with_account(self, mock_get_parameters):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        mock_get_parameters.return_value = {"account": "test_account"}
        endpoint = server.token_endpoint()
        assert endpoint == "https://test_account.snowflakecomputing.com/"
        mock_get_parameters.assert_called_once_with("example_connection")

    @patch("rsconnect.api.get_parameters")
    def test_token_endpoint_with_none_params(self, mock_get_parameters):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        mock_get_parameters.return_value = None
        with pytest.raises(RSConnectException, match="No Snowflake connection found."):
            server.token_endpoint()

    @patch("rsconnect.api.get_parameters")
    def test_fmt_payload(self, mock_get_parameters):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        mock_get_parameters.return_value = {
            "account": "test_account",
            "role": "test_role",
            "authenticator": "SNOWFLAKE_JWT",
        }

        with patch("rsconnect.api.generate_jwt") as mock_generate_jwt:
            mock_generate_jwt.return_value = "mocked_jwt"
            payload = server.fmt_payload()

            assert (
                payload["body"]
                == "scope=session%3Arole%3Atest_role+spcs.example.com&assertion=mocked_jwt&grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"  # noqa
            )
            assert payload["headers"] == {"Content-Type": "application/x-www-form-urlencoded"}
            assert payload["path"] == "/oauth/token"

            mock_get_parameters.assert_called_once_with("example_connection")
            mock_generate_jwt.assert_called_once_with("example_connection")

    @patch("rsconnect.api.get_parameters")
    def test_fmt_payload_with_none_params(self, mock_get_parameters):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")
        mock_get_parameters.return_value = None
        with pytest.raises(RSConnectException, match="No Snowflake connection found."):
            server.fmt_payload()

    @patch("rsconnect.api.HTTPServer")
    @patch("rsconnect.api.SPCSConnectServer.token_endpoint")
    @patch("rsconnect.api.SPCSConnectServer.fmt_payload")
    def test_exchange_token_success(self, mock_fmt_payload, mock_token_endpoint, mock_http_server):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")

        # Mock the HTTP request
        mock_server_instance = mock_http_server.return_value
        mock_response = Mock()
        mock_response.status = 200
        mock_response.response_body = "token_data"
        mock_server_instance.request.return_value = mock_response

        # Mock the token endpoint and payload
        mock_token_endpoint.return_value = "https://example.snowflakecomputing.com/"
        mock_fmt_payload.return_value = {
            "body": "mocked_payload_body",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "path": "/oauth/token",
        }

        # Call the method
        result = server.exchange_token()

        # Verify the results
        assert result == "token_data"
        mock_http_server.assert_called_once_with(url="https://example.snowflakecomputing.com/")
        mock_server_instance.request.assert_called_once_with(
            method="POST",
            body="mocked_payload_body",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            path="/oauth/token",
        )

    @patch("rsconnect.api.HTTPServer")
    @patch("rsconnect.api.SPCSConnectServer.token_endpoint")
    @patch("rsconnect.api.SPCSConnectServer.fmt_payload")
    def test_exchange_token_error_status(self, mock_fmt_payload, mock_token_endpoint, mock_http_server):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")

        # Mock the HTTP request with error status
        mock_server_instance = mock_http_server.return_value
        mock_response = Mock()
        mock_response.status = 401
        mock_response.full_uri = "https://example.snowflakecomputing.com/oauth/token"
        mock_response.reason = "Unauthorized"
        mock_server_instance.request.return_value = mock_response

        # Mock the token endpoint and payload
        mock_token_endpoint.return_value = "https://example.snowflakecomputing.com/"
        mock_fmt_payload.return_value = {
            "body": "mocked_payload_body",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "path": "/oauth/token",
        }

        # Call the method and verify it raises the expected exception
        with pytest.raises(RSConnectException, match="Failed to exchange Snowflake token"):
            server.exchange_token()

    @patch("rsconnect.api.HTTPServer")
    @patch("rsconnect.api.SPCSConnectServer.token_endpoint")
    @patch("rsconnect.api.SPCSConnectServer.fmt_payload")
    def test_exchange_token_empty_response(self, mock_fmt_payload, mock_token_endpoint, mock_http_server):
        server = SPCSConnectServer("https://spcs.example.com", "test-api-key", "example_connection")

        # Mock the HTTP request with empty response body
        mock_server_instance = mock_http_server.return_value
        mock_response = Mock()
        mock_response.status = 200
        mock_response.response_body = None
        mock_server_instance.request.return_value = mock_response

        # Mock the token endpoint and payload
        mock_token_endpoint.return_value = "https://example.snowflakecomputing.com/"
        mock_fmt_payload.return_value = {
            "body": "mocked_payload_body",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "path": "/oauth/token",
        }

        # Call the method and verify it raises the expected exception
        with pytest.raises(
            RSConnectException, match="Failed to exchange Snowflake token: Token exchange returned empty response"
        ):
            server.exchange_token()
