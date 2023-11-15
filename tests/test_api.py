from unittest import TestCase
from unittest.mock import Mock, patch, call
import json

import httpretty
import sys
import io

import pytest

from rsconnect.exception import RSConnectException, DeploymentFailedException
from rsconnect.models import AppModes
from .utils import (
    require_api_key,
    require_connect,
)
from rsconnect.api import (
    RSConnectClient,
    RSConnectExecutor,
    RSConnectServer,
    _to_server_check_list,
    CloudService,
    PositClient,
    CloudServer,
    ShinyappsServer,
    ShinyappsService,
)


class TestAPI(TestCase):
    def test_executor_init(self):
        connect_server = require_connect()
        api_key = require_api_key()
        ce = RSConnectExecutor(None, None, connect_server, api_key, True, None)
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
        ce.delete_runtime_cache(language="Python", version="1.2.3", image_name="teapot", dry_run=True)
        sys.stdout = sys.__stdout__

        # Print expectations
        output_lines = captured_output.getvalue().splitlines()
        self.assertEqual(output_lines[0], "Dry run finished")

        # Result expectations
        self.assertDictEqual(mocked_output, ce.state["result"])

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

        mocked_task_status = {
            "id": "this_is_a_task_id",
            "user_id": 1,
            "status": ["Removing runtime cache"],
            "result": {"type": "", "data": None},
            "finished": True,
            "code": 0,
            "error": "",
            "last_status": 1,
        }
        httpretty.register_uri(
            httpretty.GET,
            "http://test-server/__api__/tasks/this_is_a_task_id",
            body=json.dumps(mocked_task_status),
            status=200,
            forcing_headers={"Content-Type": "application/json"},
        )

        captured_output = io.StringIO()
        sys.stdout = captured_output
        ce.delete_runtime_cache(language="Python", version="1.2.3", image_name="teapot", dry_run=False)
        sys.stdout = sys.__stdout__

        # Print expectations
        # TODO: *We* don't print anything here anymore. Unsure how to capture log messages from Connect.
        # output_lines = captured_output.getvalue().splitlines()
        # self.assertEqual(output_lines[0], "Cache deletion finished")

        # Result expectations
        self.assertDictEqual(mocked_task_status, ce.state["task_status"])

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
            client.app_get = Mock(return_value=Mock())
            client._server = Mock(spec=RSConnectServer)
            client._server.handle_bad_response = Mock(side_effect=RSConnectException(""))
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


class CloudServiceTestCase(TestCase):
    def setUp(self):
        self.cloud_client = Mock(spec=PositClient)
        self.server = CloudServer("https://api.posit.cloud", "the_account", "the_token", "the_secret")
        self.project_application_id = "20"
        self.cloud_service = CloudService(
            cloud_client=self.cloud_client, server=self.server, project_application_id=self.project_application_id
        )

    def test_prepare_new_deploy_python_shiny(self):
        app_id = None
        app_name = "my app"
        bundle_size = 5000
        bundle_hash = "the_hash"
        app_mode = AppModes.PYTHON_SHINY

        self.cloud_client.get_application.return_value = {
            "content_id": 2,
        }
        self.cloud_client.get_content.return_value = {
            "space_id": 1000,
        }
        self.cloud_client.create_output.return_value = {
            "id": 1,
            "source_id": 10,
            "url": "https://posit.cloud/content/1",
        }
        self.cloud_client.create_bundle.return_value = {
            "id": 100,
            "presigned_url": "https://presigned.url",
            "presigned_checksum": "the_checksum",
        }

        prepare_deploy_result = self.cloud_service.prepare_deploy(
            app_id=app_id,
            app_name=app_name,
            bundle_size=bundle_size,
            bundle_hash=bundle_hash,
            app_mode=app_mode,
            app_store_version=1,
        )

        self.cloud_client.get_application.assert_called_with(self.project_application_id)
        self.cloud_client.get_content.assert_called_with(2)
        self.cloud_client.create_output.assert_called_with(
            name=app_name, application_type="connect", project_id=2, space_id=1000, render_by=None
        )
        self.cloud_client.create_bundle.assert_called_with(10, "application/x-tar", bundle_size, bundle_hash)

        assert prepare_deploy_result.app_id == 1
        assert prepare_deploy_result.application_id == 10
        assert prepare_deploy_result.app_url == "https://posit.cloud/content/1"
        assert prepare_deploy_result.bundle_id == 100
        assert prepare_deploy_result.presigned_url == "https://presigned.url"
        assert prepare_deploy_result.presigned_checksum == "the_checksum"

    def test_prepare_new_deploy_static_quarto(self):
        cloud_client = Mock(spec=PositClient)
        server = CloudServer("https://api.posit.cloud", "the_account", "the_token", "the_secret")
        project_application_id = "20"
        cloud_service = CloudService(
            cloud_client=cloud_client, server=server, project_application_id=project_application_id
        )

        app_id = None
        app_name = "my app"
        bundle_size = 5000
        bundle_hash = "the_hash"
        app_mode = AppModes.STATIC_QUARTO

        cloud_client.get_application.return_value = {
            "content_id": 2,
        }
        cloud_client.get_content.return_value = {
            "space_id": 1000,
        }
        cloud_client.create_output.return_value = {
            "id": 1,
            "source_id": 10,
            "url": "https://posit.cloud/content/1",
        }
        cloud_client.create_bundle.return_value = {
            "id": 100,
            "presigned_url": "https://presigned.url",
            "presigned_checksum": "the_checksum",
        }

        cloud_service.prepare_deploy(
            app_id=app_id,
            app_name=app_name,
            bundle_size=bundle_size,
            bundle_hash=bundle_hash,
            app_mode=app_mode,
            app_store_version=1,
        )

        cloud_client.get_application.assert_called_with(project_application_id)
        cloud_client.get_content.assert_called_with(2)
        cloud_client.create_output.assert_called_with(
            name=app_name, application_type="static", project_id=2, space_id=1000, render_by="server"
        )

    def test_prepare_redeploy(self):
        app_id = 1
        app_name = "my app"
        bundle_size = 5000
        bundle_hash = "the_hash"
        app_mode = AppModes.PYTHON_SHINY

        self.cloud_client.get_content.return_value = {"id": 1, "source_id": 10, "url": "https://posit.cloud/content/1"}
        self.cloud_client.get_application.return_value = {"id": 10, "content_id": 200}
        self.cloud_client.create_bundle.return_value = {
            "id": 100,
            "presigned_url": "https://presigned.url",
            "presigned_checksum": "the_checksum",
        }

        prepare_deploy_result = self.cloud_service.prepare_deploy(
            app_id=app_id,
            app_name=app_name,
            bundle_size=bundle_size,
            bundle_hash=bundle_hash,
            app_mode=app_mode,
            app_store_version=1,
        )
        self.cloud_client.get_content.assert_called_with(1)
        self.cloud_client.create_bundle.assert_called_with(10, "application/x-tar", bundle_size, bundle_hash)
        self.cloud_client.update_output.assert_called_with(1, {"project": 200})

        assert prepare_deploy_result.app_id == 1
        assert prepare_deploy_result.application_id == 10
        assert prepare_deploy_result.app_url == "https://posit.cloud/content/1"
        assert prepare_deploy_result.bundle_id == 100
        assert prepare_deploy_result.presigned_url == "https://presigned.url"
        assert prepare_deploy_result.presigned_checksum == "the_checksum"

    def test_prepare_redeploy_static(self):
        app_id = 1
        app_name = "my app"
        bundle_size = 5000
        bundle_hash = "the_hash"
        app_mode = AppModes.STATIC

        self.cloud_client.get_content.return_value = {"id": 1, "source_id": 10, "url": "https://posit.cloud/content/1"}
        self.cloud_client.get_application.return_value = {"id": 10, "content_id": 200}
        self.cloud_client.create_revision.return_value = {
            "application_id": 11,
        }
        self.cloud_client.create_bundle.return_value = {
            "id": 100,
            "presigned_url": "https://presigned.url",
            "presigned_checksum": "the_checksum",
        }

        prepare_deploy_result = self.cloud_service.prepare_deploy(
            app_id=app_id,
            app_name=app_name,
            bundle_size=bundle_size,
            bundle_hash=bundle_hash,
            app_mode=app_mode,
            app_store_version=1,
        )
        self.cloud_client.get_content.assert_called_with(1)
        self.cloud_client.create_revision.assert_called_with(1)
        self.cloud_client.create_bundle.assert_called_with(11, "application/x-tar", bundle_size, bundle_hash)
        self.cloud_client.update_output.assert_called_with(1, {"project": 200})

        assert prepare_deploy_result.app_id == 1
        assert prepare_deploy_result.application_id == 11
        assert prepare_deploy_result.app_url == "https://posit.cloud/content/1"
        assert prepare_deploy_result.bundle_id == 100
        assert prepare_deploy_result.presigned_url == "https://presigned.url"
        assert prepare_deploy_result.presigned_checksum == "the_checksum"

    def test_prepare_redeploy_preversioned_app_store(self):
        app_id = 10
        app_name = "my app"
        bundle_size = 5000
        bundle_hash = "the_hash"
        app_mode = AppModes.PYTHON_SHINY

        self.cloud_client.get_application.return_value = {
            "id": 10,
            "content_id": 1,
        }
        self.cloud_client.get_content.return_value = {"id": 1, "source_id": 10, "url": "https://posit.cloud/content/1"}
        self.cloud_client.create_bundle.return_value = {
            "id": 100,
            "presigned_url": "https://presigned.url",
            "presigned_checksum": "the_checksum",
        }

        prepare_deploy_result = self.cloud_service.prepare_deploy(
            app_id=app_id,
            app_name=app_name,
            bundle_size=bundle_size,
            bundle_hash=bundle_hash,
            app_mode=app_mode,
            app_store_version=None,
        )
        # first call is to get the current project id, second call is to get the application
        self.cloud_client.get_application.assert_has_calls([call(self.project_application_id), call(app_id)])
        self.cloud_client.get_content.assert_called_with(1)
        self.cloud_client.create_bundle.assert_called_with(10, "application/x-tar", bundle_size, bundle_hash)
        self.cloud_client.update_output.assert_called_with(1, {"project": 1})

        assert prepare_deploy_result.app_id == 1
        assert prepare_deploy_result.application_id == 10
        assert prepare_deploy_result.app_url == "https://posit.cloud/content/1"
        assert prepare_deploy_result.bundle_id == 100
        assert prepare_deploy_result.presigned_url == "https://presigned.url"
        assert prepare_deploy_result.presigned_checksum == "the_checksum"

    def test_do_deploy(self):
        bundle_id = 1
        app_id = 2
        task_id = 3

        self.cloud_client.deploy_application.return_value = {"id": task_id}

        self.cloud_service.do_deploy(bundle_id, app_id)

        self.cloud_client.set_bundle_status.assert_called_with(bundle_id, "ready")
        self.cloud_client.deploy_application.assert_called_with(bundle_id, app_id)
        self.cloud_client.wait_until_task_is_successful.assert_called_with(task_id)

    def test_do_deploy_failure(self):
        bundle_id = 1
        app_id = 2
        task_id = 3

        self.cloud_client.deploy_application.return_value = {"id": task_id}
        self.cloud_client.wait_until_task_is_successful.side_effect = DeploymentFailedException("uh oh")
        task_logs_response = Mock()
        task_logs_response.response_body = "here's why it failed"
        self.cloud_client.get_task_logs.return_value = task_logs_response

        with pytest.raises(DeploymentFailedException):
            self.cloud_service.do_deploy(bundle_id, app_id)

        self.cloud_client.set_bundle_status.assert_called_with(bundle_id, "ready")
        self.cloud_client.deploy_application.assert_called_with(bundle_id, app_id)
        self.cloud_client.wait_until_task_is_successful.assert_called_with(task_id)
        self.cloud_client.get_task_logs.assert_called_with(task_id)
