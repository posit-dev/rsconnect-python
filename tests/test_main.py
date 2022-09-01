import json
import os
import shutil
from os.path import join

from unittest import TestCase

import httpretty
from click.testing import CliRunner

from .utils import (
    apply_common_args,
    optional_ca_data,
    optional_target,
    get_dir,
    get_manifest_path,
    get_api_path,
    require_api_key,
    require_connect,
)
from rsconnect.main import cli
from rsconnect import VERSION


def _error_to_response(error):
    """
    HTTPretty is unable to show errors resulting from callbacks, so this method attempts to raise failure visibility by
    passing the return back through HTTP.
    """
    return [500, {}, str(error)]


def _load_json(data):
    if isinstance(data, bytes):
        return json.loads(data.decode())
    return json.loads(data)


class TestMain(TestCase):
    def setUp(self):
        shutil.rmtree("test-home", ignore_errors=True)
        os.environ["HOME"] = "test-home"

    def require_connect(self):
        connect_server = os.environ.get("CONNECT_SERVER", None)
        if connect_server is None:
            self.skipTest("Set CONNECT_SERVER to test this function.")
        return connect_server

    def require_api_key(self):
        connect_api_key = os.environ.get("CONNECT_API_KEY", None)
        if connect_api_key is None:
            self.skipTest("Set CONNECT_API_KEY to test this function.")
        return connect_api_key

    @staticmethod
    def optional_target(default):
        return os.environ.get("CONNECT_DEPLOY_TARGET", default)

    @staticmethod
    def optional_ca_data(default=None):
        # noinspection SpellCheckingInspection
        return os.environ.get("CONNECT_CADATA_FILE", default)

    # noinspection SpellCheckingInspection
    def create_deploy_args(self, deploy_command, target):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        cadata_file = optional_ca_data(None)
        args = ["deploy", deploy_command]
        apply_common_args(args, server=connect_server, key=api_key, cacert=cadata_file)
        args.append(target)
        return args

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(VERSION, result.output)

    def test_ping(self):
        connect_server = self.require_connect()
        runner = CliRunner()
        result = runner.invoke(cli, ["details", "-s", connect_server])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

    def test_ping_api_key(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        runner = CliRunner()
        args = ["details"]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

    def test_deploy(self):
        target = optional_target(get_dir(join("pip1", "dummy.ipynb")))
        runner = CliRunner()
        args = self.create_deploy_args("notebook", target)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)

    # noinspection SpellCheckingInspection
    def test_deploy_manifest(self):
        target = optional_target(get_manifest_path("shinyapp"))
        runner = CliRunner()
        args = self.create_deploy_args("manifest", target)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)

    # noinspection SpellCheckingInspection
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_deploy_manifest_shinyapps(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/users/me",
            body=open("tests/testdata/shinyapps-responses/get-user.json", "r").read(),
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/applications"
            "?filter=name:like:shinyapp&offset=0&count=100&use_advanced_filters=true",
            body=open("tests/testdata/shinyapps-responses/get-applications.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/accounts/",
            body=open("tests/testdata/shinyapps-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_application_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                self.assertDictEqual(parsed_request, {"account": 82069, "name": "myapp", "template": "shiny"})
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/shinyapps-responses/create-application.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/applications/",
            body=post_application_callback,
            status=200,
        )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                self.assertDictEqual(
                    parsed_request,
                    {
                        "application": 8442,
                        "content_type": "application/x-tar",
                    },
                )
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/shinyapps-responses/create-bundle.json", "r").read(),
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
                self.assertDictEqual(parsed_request, {"status": "ready"})
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
            body=open("tests/testdata/shinyapps-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                self.assertDictEqual(parsed_request, {"bundle": 12640, "rebuild": False})
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.shinyapps.io/v1/tasks/333"},
                open("tests/testdata/shinyapps-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.shinyapps.io/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.shinyapps.io/v1/tasks/333",
            body=open("tests/testdata/shinyapps-responses/get-task.json", "r").read(),
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
        ]
        try:
            result = runner.invoke(cli, args)
            self.assertEqual(result.exit_code, 0, result.output)
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_deploy_manifest_cloud(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)

        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/users/me",
            body=open("tests/testdata/shinyapps-responses/get-user.json", "r").read(),
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/applications"
            "?filter=name:like:shinyapp&offset=0&count=100&use_advanced_filters=true",
            body=open("tests/testdata/shinyapps-responses/get-applications.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )
        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/accounts/",
            body=open("tests/testdata/shinyapps-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_output_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                self.assertDictEqual(parsed_request, {"name": "myapp", "space_id": None, "project_id": None})
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/shinyapps-responses/create-output.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/applications/8442",
            body=open("tests/testdata/shinyapps-responses/get-output-application.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        httpretty.register_uri(
            httpretty.POST,
            "https://api.rstudio.cloud/v1/outputs/",
            body=post_output_callback,
        )

        def post_bundle_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            del parsed_request["checksum"]
            del parsed_request["content_length"]
            try:
                self.assertDictEqual(
                    parsed_request,
                    {
                        "application": 8442,
                        "content_type": "application/x-tar",
                    },
                )
            except AssertionError as e:
                return _error_to_response(e)
            return [
                201,
                {"Content-Type": "application/json"},
                open("tests/testdata/shinyapps-responses/create-bundle.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.rstudio.cloud/v1/bundles",
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
                self.assertDictEqual(parsed_request, {"status": "ready"})
            except AssertionError as e:
                return _error_to_response(e)
            return [303, {"Location": "https://api.rstudio.cloud/v1/bundles/12640"}, ""]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.rstudio.cloud/v1/bundles/12640/status",
            body=post_bundle_status_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/bundles/12640",
            body=open("tests/testdata/shinyapps-responses/get-accounts.json", "r").read(),
            adding_headers={"Content-Type": "application/json"},
            status=200,
        )

        def post_deploy_callback(request, uri, response_headers):
            parsed_request = _load_json(request.body)
            try:
                self.assertDictEqual(parsed_request, {"bundle": 12640, "rebuild": False})
            except AssertionError as e:
                return _error_to_response(e)
            return [
                303,
                {"Location": "https://api.rstudio.cloud/v1/tasks/333"},
                open("tests/testdata/shinyapps-responses/post-deploy.json", "r").read(),
            ]

        httpretty.register_uri(
            httpretty.POST,
            "https://api.rstudio.cloud/v1/applications/8442/deploy",
            body=post_deploy_callback,
        )

        httpretty.register_uri(
            httpretty.GET,
            "https://api.rstudio.cloud/v1/tasks/333",
            body=open("tests/testdata/shinyapps-responses/get-task.json", "r").read(),
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
        ]
        try:
            result = runner.invoke(cli, args)
            self.assertEqual(result.exit_code, 0, result.output)
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
        self.assertEqual(result.exit_code, 0, result.output)

    def test_add_connect(self):
        connect_server = self.require_connect()
        api_key = self.require_api_key()
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "--name", "my-connect", "--server", connect_server, "--api-key", api_key])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

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
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("shinyapps.io credential", result.output)

        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_add_shinyapps(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY", None)
        original_server_value = os.environ.pop("CONNECT_SERVER", None)
        try:
            httpretty.register_uri(
                httpretty.GET, "https://api.rstudio.cloud/v1/users/me", body='{"id": 1000}', status=200
            )

            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "add",
                    "--account",
                    "some-account",
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
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("RStudio Cloud credential", result.output)

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
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertEqual(
                str(result.exception),
                "-A/--account, -T/--token, and -S/--secret must all be provided for shinyapps.io.",
            )
        finally:
            if original_api_key_value:
                os.environ["CONNECT_API_KEY"] = original_api_key_value
            if original_server_value:
                os.environ["CONNECT_SERVER"] = original_server_value
