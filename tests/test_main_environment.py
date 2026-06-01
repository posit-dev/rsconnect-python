import json
import unittest

import httpretty
from click.testing import CliRunner

from rsconnect.main import cli

from .utils import apply_common_args

ENVIRONMENT_GUID = "f1e2d3c4-b5a6-7890-abcd-ef1234567890"


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
        f"{connect_server}/__api__/v1/environments",
        body=open("tests/testdata/connect-responses/list-environments.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}",
        body=open("tests/testdata/connect-responses/get-environment.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.POST,
        f"{connect_server}/__api__/v1/environments",
        body=open("tests/testdata/connect-responses/get-environment.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.PUT,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}",
        body=open("tests/testdata/connect-responses/get-environment.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.DELETE,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}",
        status=204,
        body="",
    )
    httpretty.register_uri(
        httpretty.GET,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}/permissions",
        body=open("tests/testdata/connect-responses/list-environment-permissions.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.POST,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}/permissions",
        body=open("tests/testdata/connect-responses/get-environment-permission.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.DELETE,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}/permissions/perm-1111-2222-3333-444444444444",
        status=204,
        body="",
    )
    httpretty.register_uri(
        httpretty.DELETE,
        f"{connect_server}/__api__/v1/environments/{ENVIRONMENT_GUID}/permissions/perm-5555-6666-7777-888888888888",
        status=204,
        body="",
    )


class TestEnvironmentSubcommand(unittest.TestCase):
    def setUp(self):
        self.connect_server = "http://localhost:3939"
        self.api_key = "testapikey123"

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_list(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(["environment", "list"], server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0]["guid"], ENVIRONMENT_GUID)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_show(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["environment", "show", "--guid", ENVIRONMENT_GUID], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(output["guid"], ENVIRONMENT_GUID)
        self.assertEqual(output["title"], "Python 3.11 Base")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_add(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "environment",
                "add",
                "--image",
                "ghcr.io/rstudio/content-base:r4.4.1-py3.11.9-jammy",
                "--title",
                "Python 3.11 Base",
                "--description",
                "Base image with Python 3.11",
                "--matching",
                "any",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        output = json.loads(result.output)
        self.assertEqual(output["guid"], ENVIRONMENT_GUID)
        # Verify a POST to environments was made with correct body
        post_requests = [
            r
            for r in httpretty.latest_requests()
            if r.method == "POST" and "/v1/environments" in r.path and "/permissions" not in r.path
        ]
        self.assertGreaterEqual(len(post_requests), 1)
        body = json.loads(post_requests[0].body)
        self.assertEqual(body["name"], "ghcr.io/rstudio/content-base:r4.4.1-py3.11.9-jammy")
        self.assertEqual(body["cluster_name"], "Kubernetes")
        self.assertEqual(body["title"], "Python 3.11 Base")
        self.assertEqual(body["description"], "Base image with Python 3.11")
        self.assertEqual(body["matching"], "any")
        # Verify no permission endpoints were called when no --allow-* flags are set
        perm_requests = [r for r in httpretty.latest_requests() if "/permissions" in r.path]
        self.assertEqual(len(perm_requests), 0)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_add_with_permissions(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "environment",
                "add",
                "--image",
                "ghcr.io/rstudio/content-base:r4.4.1-py3.11.9-jammy",
                "--allow-user",
                "user-guid-1",
                "--allow-group",
                "group-guid-1",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        # Verify permission POSTs happened (check bodies, not count — httpretty may duplicate)
        perm_posts = [r for r in httpretty.latest_requests() if r.method == "POST" and "/permissions" in r.path]
        self.assertGreaterEqual(len(perm_posts), 2)
        bodies = [json.loads(r.body) for r in perm_posts]
        user_bodies = [b for b in bodies if b.get("user_guid") == "user-guid-1"]
        group_bodies = [b for b in bodies if b.get("group_guid") == "group-guid-1"]
        self.assertGreaterEqual(len(user_bodies), 1)
        self.assertGreaterEqual(len(group_bodies), 1)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_edit(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "environment",
                "edit",
                "--guid",
                ENVIRONMENT_GUID,
                "--title",
                "Updated Title",
                "--matching",
                "exact",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        # Verify the PUT body merges with existing
        put_requests = [r for r in httpretty.latest_requests() if r.method == "PUT"]
        self.assertGreaterEqual(len(put_requests), 1)
        body = json.loads(put_requests[0].body)
        self.assertEqual(body["title"], "Updated Title")
        self.assertEqual(body["matching"], "exact")
        # Existing fields preserved
        self.assertEqual(body["description"], "Base image with Python 3.11")
        self.assertIn("python", body)
        self.assertIn("r", body)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_edit_with_permissions(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            [
                "environment",
                "edit",
                "--guid",
                ENVIRONMENT_GUID,
                "--allow-user",
                "new-user-guid",
            ],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        # Verify existing permissions were deleted
        perm_deletes = [r for r in httpretty.latest_requests() if r.method == "DELETE" and "/permissions/" in r.path]
        self.assertGreaterEqual(len(perm_deletes), 2)
        # Verify new permission was added
        perm_posts = [r for r in httpretty.latest_requests() if r.method == "POST" and "/permissions" in r.path]
        self.assertGreaterEqual(len(perm_posts), 1)
        body = json.loads(perm_posts[0].body)
        self.assertEqual(body["user_guid"], "new-user-guid")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_edit_no_permissions_untouched(self):
        """Editing without --allow-user/--allow-group should not touch permissions."""
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["environment", "edit", "--guid", ENVIRONMENT_GUID, "--title", "New Title"],
            server=self.connect_server,
            key=self.api_key,
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        # Verify no permission-related requests
        perm_requests = [r for r in httpretty.latest_requests() if "/permissions" in r.path]
        self.assertEqual(len(perm_requests), 0)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_environment_remove(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = apply_common_args(
            ["environment", "remove", "--guid", ENVIRONMENT_GUID], server=self.connect_server, key=self.api_key
        )
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Deleted environment", result.output)

    def test_environment_add_missing_image(self):
        runner = CliRunner()
        args = apply_common_args(["environment", "add"], server="http://localhost:3939", key="testapikey123")
        result = runner.invoke(cli, args)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--image", result.output)

    def test_environment_show_missing_guid(self):
        runner = CliRunner()
        args = apply_common_args(["environment", "show"], server="http://localhost:3939", key="testapikey123")
        result = runner.invoke(cli, args)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--guid", result.output)
