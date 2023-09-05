import json
import os
import shutil
from os.path import join
from unittest import TestCase


import httpretty
import pytest
import click
from click.testing import CliRunner

from rsconnect.json_web_token import SECRET_KEY_ENV

from .utils import (
    apply_common_args,
    optional_ca_data,
    optional_target,
    get_dir,
    get_manifest_path,
    get_api_path,
    require_api_key,
    require_connect,
    has_jwt_structure,
)
from rsconnect.main import cli, env_management_callback
from rsconnect import VERSION


def _error_to_response(error):
    """
    HTTPretty is unable to show errors resulting from callbacks, so this method attempts to raise failure visibility by
    passing the return back through HTTP.
    """
    return [555, {}, str(error)]


def _load_json(data):
    if isinstance(data, bytes):
        return json.loads(data.decode())
    return json.loads(data)


class TestMain:
    def setup_method(self):
        shutil.rmtree("test-home", ignore_errors=True)
        os.environ["HOME"] = "test-home"

    @staticmethod
    def optional_target(default):
        return os.environ.get("CONNECT_DEPLOY_TARGET", default)

    @staticmethod
    def optional_ca_data(default=None):
        # noinspection SpellCheckingInspection
        return os.environ.get("CONNECT_CADATA_FILE", default)

    # noinspection SpellCheckingInspection
    def create_deploy_args(self, deploy_command, target):
        connect_server = require_connect()
        api_key = require_api_key()
        cadata_file = optional_ca_data(None)
        args = ["deploy", deploy_command]
        apply_common_args(args, server=connect_server, key=api_key, cacert=cadata_file)
        args.append(target)
        return args

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0, result.output
        assert VERSION in result.output

    def test_ping(self):
        connect_server = require_connect()
        runner = CliRunner()
        result = runner.invoke(cli, ["details", "-s", connect_server])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_ping_api_key(self):
        connect_server = require_connect()
        api_key = require_api_key()
        runner = CliRunner()
        args = ["details"]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_deploy(self):
        target = optional_target(get_dir(join("pip1", "dummy.ipynb")))
        runner = CliRunner()
        args = self.create_deploy_args("notebook", target)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output

    # noinspection SpellCheckingInspection
    def test_deploy_manifest(self):
        target = optional_target(get_manifest_path("shinyapp"))
        runner = CliRunner()
        args = self.create_deploy_args("manifest", target)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output

    # noinspection SpellCheckingInspection
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_deploy_manifest_shinyapps(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/users/me",
            body=open("tests/testdata/rstudio-responses/get-user.json", "r").read(),
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/applications"
            "?filter=name:like:shinyapp&offset=0&count=100&use_advanced_filters=true",
            body=open("tests/testdata/rstudio-responses/get-applications.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/accounts/",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_application_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"account": 82069, "name": "myapp", "template": "shiny"}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/application.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/applications/",
            body=post_application_callback,
            status=200,
        )

        def post_application_property_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"value": "private"}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {},
                b"",
            ]

        httpretty.register_uri(
            httpretty.PUT,
            "https://api.shinyapps.io/v1/applications/8442/properties/application.visibility",
            body=post_application_property_callback,
            status=200,
        )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                assert parsed_request == {
                    "application": 8442,
                    "content_type": "application/x-tar",
                }
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-bundle.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/bundles",
            body=post_bundle_callback,
        )

        httpretty.register_uri(
            httpretty.PUT,
            "https://lucid-uploads-staging.s3.amazonaws.com/bundles/application-8442/"
            "6c9ed0d91ee9426687d9ac231d47dc83.tar.gz"
            "?AWSAccessKeyId=theAccessKeyId"
            "&Signature=dGhlU2lnbmF0dXJlCg%3D%3D"
            "&content-md5=D1blMI4qTiI3tgeUOYXwkg%3D%3D"
            "&content-type=application%2Fx-tar"
            "&x-amz-security-token=dGhlVG9rZW4K"
            "&Expires=1656715153",
            body="",
        )

        def post_bundle_status_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"status": "ready"}
            except AssertionError as e:
                return _error_to_response(e)
            return [303, {"Location": "https://api.shinyapps.io/v1/bundles/12640"}, ""]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/bundles/12640/status",
            body=post_bundle_status_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/bundles/12640",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"bundle": 12640, "rebuild": False}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.shinyapps.io/v1/tasks/333"},
                open("tests/testdata/rstudio-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/tasks/333",
            body=open("tests/testdata/rstudio-responses/get-task.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        runner = CliRunner()
        args = [
            "deploy",
            "manifest",
            get_manifest_path("shinyapp"),
            "--account",
            "some-account",
            "--token",
            "someToken",
            "--secret",
            "c29tZVNlY3JldAo=",
            "--title",
            "myApp",
            "--visibility",
            "private"
        ]
        try:
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_deploy_manifest_shinyapps(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/users/me",
            body=open("tests/testdata/rstudio-responses/get-user.json", "r").read(),
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/applications"
            "?filter=name:like:shinyapp&offset=0&count=100&use_advanced_filters=true",
            body=open("tests/testdata/rstudio-responses/get-applications.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/accounts/",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/applications/8442",
            body=open("tests/testdata/rstudio-responses/application.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_application_property_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"value": "private"}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {},
                b"",
            ]

        httpretty.register_uri(
            httpretty.PUT,
            "https://api.shinyapps.io/v1/applications/8442/properties/application.visibility",
            body=post_application_property_callback,
            status=200,
        )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                assert parsed_request == {
                    "application": 8442,
                    "content_type": "application/x-tar",
                }
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-bundle.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/bundles",
            body=post_bundle_callback,
        )

        httpretty.register_uri(
            httpretty.PUT,
            "https://lucid-uploads-staging.s3.amazonaws.com/bundles/application-8442/"
            "6c9ed0d91ee9426687d9ac231d47dc83.tar.gz"
            "?AWSAccessKeyId=theAccessKeyId"
            "&Signature=dGhlU2lnbmF0dXJlCg%3D%3D"
            "&content-md5=D1blMI4qTiI3tgeUOYXwkg%3D%3D"
            "&content-type=application%2Fx-tar"
            "&x-amz-security-token=dGhlVG9rZW4K"
            "&Expires=1656715153",
            body="",
        )

        def post_bundle_status_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"status": "ready"}
            except AssertionError as e:
                return _error_to_response(e)
            return [303, {"Location": "https://api.shinyapps.io/v1/bundles/12640"}, ""]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/bundles/12640/status",
            body=post_bundle_status_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/bundles/12640",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"bundle": 12640, "rebuild": False}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.shinyapps.io/v1/tasks/333"},
                open("tests/testdata/rstudio-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/tasks/333",
            body=open("tests/testdata/rstudio-responses/get-task.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        runner = CliRunner()
        args = [
            "deploy",
            "manifest",
            get_manifest_path("shinyapp"),
            "--account",
            "some-account",
            "--token",
            "someToken",
            "--secret",
            "c29tZVNlY3JldAo=",
            "--title",
            "myApp",
            "--visibility",
            "private",
            "--app-id",
            "8442",
        ]
        try:
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value


    @httpretty.activate(verbose=True, allow_net_connect=False)
    @pytest.mark.parametrize(
        "project_application_id,project_id",
        [(None, None), ("444", 555)],
        ids=["without associated project", "with associated project"],
    )
    def test_deploy_manifest_cloud(self, project_application_id, project_id):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)
        if project_application_id:
            os.environ["LUCID_APPLICATION_ID"] = project_application_id

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/users/me",
            body=open("tests/testdata/rstudio-responses/get-user.json", "r").read(),
            status=200,
        )
        if project_application_id:
            httpretty.register_uri(
                httpretty.GET,
                "https://api.posit.cloud/v1/applications/444",
                body=open("tests/testdata/rstudio-responses/get-project-application.json", "r").read(),
                adding_headers={"Content-Type": "application/json"},
                status=200,
            )
            httpretty.register_uri(
                httpretty.GET,
                "https://api.posit.cloud/v1/content/555",
                body=open("tests/testdata/rstudio-responses/get-content.json", "r").read(),
                adding_headers={"Content-Type": "application/json"},
                status=200,
            )
            httpretty.register_uri(
                httpretty.GET,
                "https://api.posit.cloud/v1/content/1",
                body=open("tests/testdata/rstudio-responses/create-output.json", "r").read(),
                adding_headers={"Content-Type": "application/json"},
                status=200,
            )

        def post_output_callback(request, uri, response_headers):
            space_id = 917733 if project_application_id else None
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {
                    "name": "myapp",
                    "space": space_id,
                    "project": project_id,
                    "application_type": "connect",
                }
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-output.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/applications/8442",
            body=open("tests/testdata/rstudio-responses/get-output-application.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/outputs/",
            body=post_output_callback,
        )

        httpretty.register_uri(
            httpretty.PATCH,
            "https://api.posit.cloud/v1/outputs/1",
            body=open("tests/testdata/rstudio-responses/create-output.json", "r").read(),
            status=200,
        )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                assert parsed_request == {
                    "application": 8442,
                    "content_type": "application/x-tar",
                }
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-bundle.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/bundles",
            body=post_bundle_callback,
        )

        httpretty.register_uri(
            httpretty.PUT,
            "https://lucid-uploads-staging.s3.amazonaws.com/bundles/application-8442/"
            "6c9ed0d91ee9426687d9ac231d47dc83.tar.gz"
            "?AWSAccessKeyId=theAccessKeyId"
            "&Signature=dGhlU2lnbmF0dXJlCg%3D%3D"
            "&content-md5=D1blMI4qTiI3tgeUOYXwkg%3D%3D"
            "&content-type=application%2Fx-tar"
            "&x-amz-security-token=dGhlVG9rZW4K"
            "&Expires=1656715153",
            body="",
        )

        def post_bundle_status_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"status": "ready"}
            except AssertionError as e:
                return _error_to_response(e)
            return [303, {"Location": "https://api.posit.cloud/v1/bundles/12640"}, ""]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/bundles/12640/status",
            body=post_bundle_status_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/bundles/12640",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"bundle": 12640, "rebuild": False}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.posit.cloud/v1/tasks/333"},
                open("tests/testdata/rstudio-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/tasks/333",
            body=open("tests/testdata/rstudio-responses/get-task.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        runner = CliRunner()
        args = [
            "deploy",
            "manifest",
            get_manifest_path("shinyapp"),
            "--server",
            "rstudio.cloud",
            "--account",
            "some-account",
            "--token",
            "someToken",
            "--secret",
            "c29tZVNlY3JldAo=",
            "--title",
            "myApp",
            "--visibility",
            "public"
        ]
        try:
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value
            if project_application_id:
                del os.environ["LUCID_APPLICATION_ID"]

    @httpretty.activate(verbose=True, allow_net_connect=False)
    @pytest.mark.parametrize(
        "command,arg",

        [
            [
                "manifest",
                get_manifest_path("static", parent="py3"),
            ],
            [
                "html",
                join(os.path.dirname(__file__), "testdata", "py3", "static"),
            ],
        ],
        ids=["using manifest", "using html"],
    )
    def test_deploy_static_cloud(self, command, arg):
        """
        Verify that an app with app_mode as static can deploy to cloud.
        """
        shutil.rmtree(os.path.join(arg, 'rsconnect-python'), ignore_errors=True)

        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/users/me",
            body=open("tests/testdata/rstudio-responses/get-user.json", "r").read(),
            status=200,
        )

        def post_output_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"name": "myapp", "space": None, "project": None, "application_type": "static"}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-output.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/applications/8442",
            body=open("tests/testdata/rstudio-responses/get-output-application.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        if True:
            httpretty.register_uri(
                httpretty.POST,
                "https://api.posit.cloud/v1/outputs/",
                body=post_output_callback,
            )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                assert parsed_request == {
                    "application": 8442,
                    "content_type": "application/x-tar",
                }
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/rstudio-responses/create-bundle.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/bundles",
            body=post_bundle_callback,
        )

        httpretty.register_uri(
            httpretty.PUT,
            "https://lucid-uploads-staging.s3.amazonaws.com/bundles/application-8442/"
            "6c9ed0d91ee9426687d9ac231d47dc83.tar.gz"
            "?AWSAccessKeyId=theAccessKeyId"
            "&Signature=dGhlU2lnbmF0dXJlCg%3D%3D"
            "&content-md5=D1blMI4qTiI3tgeUOYXwkg%3D%3D"
            "&content-type=application%2Fx-tar"
            "&x-amz-security-token=dGhlVG9rZW4K"
            "&Expires=1656715153",
            body="",
        )

        def post_bundle_status_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"status": "ready"}
            except AssertionError as e:
                return _error_to_response(e)
            return [303, {"Location": "https://api.posit.cloud/v1/bundles/12640"}, ""]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/bundles/12640/status",
            body=post_bundle_status_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/bundles/12640",
            body=open("tests/testdata/rstudio-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                assert parsed_request == {"bundle": 12640, "rebuild": False}
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.posit.cloud/v1/tasks/333"},
                open("tests/testdata/rstudio-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.posit.cloud/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.posit.cloud/v1/tasks/333",
            body=open("tests/testdata/rstudio-responses/get-task.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        runner = CliRunner()
        args = [
            "deploy",
            command,
            arg,
            "--server",
            "rstudio.cloud",
            "--account",
            "some-account",
            "--token",
            "someToken",
            "--secret",
            "c29tZVNlY3JldAo=",
            "--title",
            "myApp",
        ]
        try:
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    def test_deploy_api(self):
        target = optional_target(get_api_path("flask"))
        runner = CliRunner()
        args = self.create_deploy_args("api", target)
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output

    def test_add_connect(self):
        connect_server = require_connect()
        api_key = require_api_key()
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--name", "my-connect", "--server", connect_server, "--api-key", api_key])
        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_add_shinyapps(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)
        try:
            httpretty.register_uri(
                httpretty.GET, "https://api.shinyapps.io/v1/users/me", body='{"id": 1000}', status=200
            )

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "add",
                    "--account",
                    "some-account",
                    "--name",
                    "my-shinyapps",
                    "--token",
                    "someToken",
                    "--secret",
                    "c29tZVNlY3JldAo=",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "shinyapps.io credential" in result.output

        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_add_cloud(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)
        try:
            httpretty.register_uri(
                httpretty.GET, "https://api.posit.cloud/v1/users/me", body='{"id": 1000}', status=200
            )

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "add",
                    "--name",
                    "my-cloud",
                    "--token",
                    "someToken",
                    "--secret",
                    "c29tZVNlY3JldAo=",
                    "--server",
                    "rstudio.cloud",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Posit Cloud credential" in result.output

        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    def test_add_shinyapps_missing_options(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)
        try:
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "add",
                    "--name",
                    "my-shinyapps",
                    "--token",
                    "someToken",
                ],
            )
            assert result.exit_code == 1, result.output
            assert (
                str(result.exception)
                == "-A/--account, -T/--token, and -S/--secret must all be provided for shinyapps.io."
            )
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value


    def test_env_management_callback(self):
        ctx = click.Context(cli)

        # env_management is always False when --disable-env-management is True
        ctx.params = {'disable_env_management': True}
        assert env_management_callback(ctx, None, None) is False
        assert env_management_callback(ctx, None, True) is False
        assert env_management_callback(ctx, None, False) is False

        # (env_management == not value) when --disable-env-management is None
        ctx.params = {'disable_env_management': None}
        assert env_management_callback(ctx, None, None) is None
        assert env_management_callback(ctx, None, True) is False
        assert env_management_callback(ctx, None, False) is True


class TestBootstrap(TestCase):
    def setUp(self):
        self.mock_server = "http://localhost:8080"
        self.mock_uri = "http://localhost:8080/__api__/v1/experimental/bootstrap"
        self.jwt_keypath = "tests/testdata/jwt/secret.key"
        self.jwt_env_secret = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU="

        self.default_cli_args = [
            "bootstrap",
            "--server",
            self.mock_server,
            "--jwt-keypath",
            self.jwt_keypath,
            "--insecure",
        ]

    def create_bootstrap_mock_callback(self, status, json_data):
        def request_callback(request, uri, response_headers):

            # verify auth header is sent correctly
            authorization = request.headers.get("Authorization")
            auth_split = authorization.split(" ")
            self.assertEqual(len(auth_split), 2)
            self.assertEqual(auth_split[0], "Connect-Bootstrap")
            self.assertTrue(has_jwt_structure(auth_split[1]))

            # verify uri
            self.assertEqual(uri, self.mock_uri)

            return [status, {"Content-Type": "application/json"}, json.dumps(json_data)]

        return request_callback

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap(self):
        """
        Normal initial-admin operation
        """

        callback = self.create_bootstrap_mock_callback(200, {"api_key": "testapikey123"})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)

        self.assertEqual(result.exit_code, 0, result.output)

        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/success.json", "r").read())
        self.assertEqual(json_output, expected_output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_env_var(self):
        """
        Normal initial-admin operation if secret key is configured using an environment variable
        """
        cli_args = [
            "bootstrap",
            "--server",
            self.mock_server,
            "--insecure",
        ]

        callback = self.create_bootstrap_mock_callback(200, {"api_key": "testapikey123"})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        os.environ[SECRET_KEY_ENV] = self.jwt_env_secret

        runner = CliRunner()
        result = runner.invoke(cli, cli_args)

        self.assertEqual(result.exit_code, 0, result.output)

        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/success.json", "r").read())
        self.assertEqual(json_output, expected_output)

        del os.environ[SECRET_KEY_ENV]

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_misc_error(self):
        """
        Fail reasonably if response indicates some non-standard error
        """

        callback = self.create_bootstrap_mock_callback(500, {})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)

        self.assertEqual(result.exit_code, 0, result.output)

        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/other_error.json", "r").read())
        self.assertEqual(json_output, expected_output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_not_found_error(self):
        """
        Fail reasonablly if response indicates 404 not found
        """

        callback = self.create_bootstrap_mock_callback(404, {})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)

        self.assertEqual(result.exit_code, 0, result.output)

        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/not_found_error.json", "r").read())
        self.assertEqual(json_output, expected_output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_forbidden_error(self):
        """
        Fail reasonably if response indicates a forbidden error
        """

        callback = self.create_bootstrap_mock_callback(403, {})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)

        self.assertEqual(result.exit_code, 0, result.output)
        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/forbidden_error.json", "r").read())

        self.assertEqual(json_output, expected_output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_unauthorized(self):
        """
        Fail reasonably if response indicates that request is unauthorized
        """

        callback = self.create_bootstrap_mock_callback(401, {})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)

        self.assertEqual(result.exit_code, 0, result.output)

        json_output = json.loads(result.output)
        expected_output = json.loads(open("tests/testdata/initial-admin-responses/unauthorized_error.json", "r").read())

        self.assertEqual(json_output, expected_output)

    def test_bootstrap_help(self):
        """
        Help parameter should complete without erroring
        """

        runner = CliRunner()
        result = runner.invoke(cli, ["bootstrap", "--help"])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_boostrap_invalid_jwt_path(self):
        """
        Fail reasonably if jwt does not exist at provided path
        """

        runner = CliRunner()
        result = runner.invoke(cli, ["bootstrap", "--server", "http://host:port", "--jwt-keypath", "this/is/invalid"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(result.output, "Error: Keypath does not exist.\n")

    def test_bootstrap_invalid_server(self):
        """
        Fail reasonably if server URL is formatted incorrectly
        """

        runner = CliRunner()
        result = runner.invoke(cli, ["bootstrap", "--server", "123.some.ip.address", "--jwt-keypath", self.jwt_keypath])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.output, "Error: Server URL expected to begin with transfer protocol (ex. http/https).\n"
        )

    def test_boostrap_missing_jwt_option(self):
        """
        If jwt keyfile is not specified, it needs to be set using an environment variable
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["bootstrap", "--server", "http://a_server"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.output, "Error: Must specify secret key using either a keyfile or environment variable.\n"
        )

    def test_bootstrap_conflicting_jwt_option(self):
        """
        If jwt keyfile is specified, it cannot also be set using an environment variable
        """

        os.environ[SECRET_KEY_ENV] = "a_value"
        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args)
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.output, "Error: Cannot specify secret key using both a keyfile and environment variable.\n"
        )

        del os.environ[SECRET_KEY_ENV]

    def test_bootstrap_invalid_env_secret_key(self):
        """
        If jwt env variable is specified, it needs to be a valid base64-encoded value
        """

        os.environ[SECRET_KEY_ENV] = "a_value"
        runner = CliRunner()
        result = runner.invoke(cli, ["bootstrap", "--server", "http://a_server"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(
            result.output,
            "Error: Unable to decode base64 data from environment variable: CONNECT_BOOTSTRAP_SECRETKEY\n",
        )

        del os.environ[SECRET_KEY_ENV]

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_bootstrap_raw_output(self):
        """
        Verify we can get the API key as raw output
        """

        expected_api_key = "apikey123"
        callback = self.create_bootstrap_mock_callback(200, {"api_key": expected_api_key})

        httpretty.register_uri(
            httpretty.POST,
            self.mock_uri,
            body=callback,
        )

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args + ["--raw"])

        self.assertEqual(result.exit_code, 0, result.output)

        self.assertEqual(result.output, expected_api_key + "\n")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_boostrap_raw_output_nonsuccess(self):
        """
        Verify behavior on non-200 response
        """

        callback = self.create_bootstrap_mock_callback(500, {})

        httpretty.register_uri(httpretty.POST, self.mock_uri, body=callback)

        runner = CliRunner()
        result = runner.invoke(cli, self.default_cli_args + ["--raw"])

        self.assertEqual(result.exit_code, 0, result.output)

        self.assertEqual(result.output, "\n")
