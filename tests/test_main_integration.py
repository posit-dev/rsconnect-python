import json
import unittest

import httpretty
from click.testing import CliRunner

from rsconnect.main import cli

from .utils import apply_common_args

INTEGRATION_GUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def register_uris(connect_server: str):
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/server_settings",
        body=open("tests/testdata/connect-responses/server_settings.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/user",
        body=open("tests/testdata/connect-responses/me.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/oauth/integrations",
        body=open("tests/testdata/connect-responses/list-integrations.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/oauth/integrations/{INTEGRATION_GUID}",
        body=open("tests/testdata/connect-responses/get-integration.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.POST,
        f"{connect_server}/__api__/v1/oauth/integrations",
        body=open("tests/testdata/connect-responses/get-integration.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.PATCH,
        f"{connect_server}/__api__/v1/oauth/integrations/{INTEGRATION_GUID}",
        body=open("tests/testdata/connect-responses/get-integration.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.DELETE,
        f"{connect_server}/__api__/v1/oauth/integrations/{INTEGRATION_GUID}",
        status=204,
        body="",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/oauth/templates",
        body=open("tests/testdata/connect-responses/list-templates.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/oauth/templates/custom",
        body=open("tests/testdata/connect-responses/get-template.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )


class TestIntegrationSubcommand(unittest.TestCase):
    def setUp(self):
        self.connect_server = "http://localhost:3939"
        self.api_key = "testapikey123"

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_list(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(["integration", "list"], server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0]["guid"], INTEGRATION_GUID)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_show(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["integration", "show", "--guid", INTEGRATION_GUID], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(output["guid"], INTEGRATION_GUID)
        self.assertEqual(output["name"], "My OAuth Integration")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_add(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "integration",
                "add",
                "--template",
                "custom",
                "-N",
                "My OAuth Integration",
                "-C",
                "client_id=abc123",
                "-C",
                "client_secret=secret",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(output["template"], "custom")
        body = json.loads(httpretty.last_request().body)
        self.assertEqual(body["template"], "custom")
        self.assertEqual(body["config"]["client_id"], "abc123")
        self.assertEqual(body["config"]["client_secret"], "secret")
        self.assertEqual(body["name"], "My OAuth Integration")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_edit(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "integration",
                "edit",
                "--guid",
                INTEGRATION_GUID,
                "-N",
                "Renamed Integration",
                "-C",
                "client_id=new_id",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        body = json.loads(httpretty.last_request().body)
        self.assertEqual(body["name"], "Renamed Integration")
        self.assertEqual(body["config"]["client_id"], "new_id")
        # Verify merge: existing key preserved from the GET response
        self.assertEqual(body["config"]["client_secret"], "secret")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_edit_name_only(self):
        """Editing only name/description should not fetch existing integration."""
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["integration", "edit", "--guid", INTEGRATION_GUID, "-N", "New Name"],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        body = json.loads(httpretty.last_request().body)
        self.assertEqual(body["name"], "New Name")
        self.assertNotIn("config", body)
        # Verify no GET to the integration endpoint occurred
        integration_gets = [
            r
            for r in httpretty.latest_requests()
            if r.method == "GET" and f"/v1/oauth/integrations/{INTEGRATION_GUID}" in r.path
        ]
        self.assertEqual(len(integration_gets), 0, "Unexpected GET to integration endpoint")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_remove(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["integration", "remove", "--guid", INTEGRATION_GUID], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Deleted integration", result.output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_templates_list(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(["integration", "templates", "list"], server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["id"], "custom")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_templates_show(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["integration", "templates", "show", "--key", "custom"], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(output["id"], "custom")
        self.assertEqual(len(output["fields"]), 2)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_integration_add_with_permissions(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "integration",
                "add",
                "--template",
                "custom",
                "-C",
                "client_id=abc",
                "--allow-user",
                "user-guid-1",
                "--allow-user",
                "user-guid-2",
                "--allow-group",
                "group-guid-1",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        body = json.loads(httpretty.last_request().body)
        self.assertEqual(len(body["permissions"]), 3)
        self.assertEqual(body["permissions"][0], {"user_guid": "user-guid-1", "group_guid": None})
        self.assertEqual(body["permissions"][1], {"user_guid": "user-guid-2", "group_guid": None})
        self.assertEqual(body["permissions"][2], {"user_guid": None, "group_guid": "group-guid-1"})

    def test_integration_add_missing_template(self):
        runner = CliRunner()
        args = apply_common_args(
            ["integration", "add", "-C", "client_id=abc"], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--template", result.output)

    def test_integration_show_missing_guid(self):
        runner = CliRunner()
        args = apply_common_args(["integration", "show"], server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--guid", result.output)
