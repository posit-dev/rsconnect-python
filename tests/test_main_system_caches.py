import json
import unittest

import httpretty
from click.testing import CliRunner

from rsconnect.main import cli

from .utils import apply_common_args

CONNECT_SERVER = "http://localhost:3939"
API_KEY = "testapikey123"

CACHES_PAYLOAD = {"caches": [{"language": "Python", "version": "1.2.3", "image_name": "Local"}]}

PERMISSION_DENIED_BODY = json.dumps({"code": 22, "error": "You don't have permission to perform this operation."})


def register_server_validation_uris(connect_server: str):
    """Register the endpoints that RSConnectExecutor.validate_server() requires."""
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


class TestSystemCachesList(unittest.TestCase):
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_system_caches_list_happy_path(self):
        """Admin can list caches; stdout JSON matches the mocked payload."""
        register_server_validation_uris(CONNECT_SERVER)
        httpretty.register_uri(
            httpretty.GET,
            f"{CONNECT_SERVER}/__api__/v1/system/caches/runtime",
            body=json.dumps(CACHES_PAYLOAD),
            adding_headers={"Content-Type": "application/json"},
        )

        runner = CliRunner()
        args = ["system", "caches", "list"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 0, result.output)
        result_dict = json.loads(result.output)
        self.assertDictEqual(result_dict, CACHES_PAYLOAD)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_system_caches_list_permission_denied(self):
        """A 403 from Connect is surfaced as exit code 1 with the permission message."""
        register_server_validation_uris(CONNECT_SERVER)
        httpretty.register_uri(
            httpretty.GET,
            f"{CONNECT_SERVER}/__api__/v1/system/caches/runtime",
            status=403,
            body=PERMISSION_DENIED_BODY,
            adding_headers={"Content-Type": "application/json"},
        )

        runner = CliRunner()
        args = ["system", "caches", "list"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertRegex(result.output, "You don't have permission to perform this operation.")


class TestSystemCachesDelete(unittest.TestCase):
    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_system_caches_delete_happy_path(self):
        """Admin can delete a cache; exit code 0."""
        register_server_validation_uris(CONNECT_SERVER)
        httpretty.register_uri(
            httpretty.DELETE,
            f"{CONNECT_SERVER}/__api__/v1/system/caches/runtime",
            status=200,
            body=json.dumps(
                {"language": "Python", "version": "1.2.3", "image_name": "Local", "dry_run": False, "task_id": "abc123"}
            ),
            adding_headers={"Content-Type": "application/json"},
        )
        httpretty.register_uri(
            httpretty.GET,
            f"{CONNECT_SERVER}/__api__/v1/tasks/abc123",
            body=json.dumps(
                {
                    "id": "abc123",
                    "output": [],
                    "result": {"type": "", "data": ""},
                    "finished": True,
                    "code": 0,
                    "error": "",
                    "last": 0,
                }
            ),
            adding_headers={"Content-Type": "application/json"},
        )

        runner = CliRunner()
        args = ["system", "caches", "delete", "--language", "Python", "--version", "1.2.3", "--image-name", "Local"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 0, result.output)
        delete_request = next(r for r in httpretty.latest_requests() if r.method == "DELETE")
        body = json.loads(delete_request.body)
        self.assertEqual(body["language"], "Python")
        self.assertEqual(body["version"], "1.2.3")
        self.assertEqual(body["image_name"], "Local")

    def test_system_caches_delete_missing_all_flags(self):
        """Omitting both --language and --version yields exit code 2 (Click validation)."""
        runner = CliRunner()
        args = ["system", "caches", "delete"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertRegex(result.output, "Missing option '--language' / '-l'")

    def test_system_caches_delete_missing_version_flag(self):
        """Providing --language but omitting --version yields exit code 2."""
        runner = CliRunner()
        args = ["system", "caches", "delete", "--language", "Python"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertRegex(result.output, "Missing option '--version' / '-V'")

    def test_system_caches_delete_missing_language_flag(self):
        """Providing --version but omitting --language yields exit code 2."""
        runner = CliRunner()
        args = ["system", "caches", "delete", "--version", "1.2.3"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 2, result.output)
        self.assertRegex(result.output, "Missing option '--language' / '-l'")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_system_caches_delete_permission_denied(self):
        """A 403 from Connect on delete is surfaced as exit code 1 with the permission message."""
        register_server_validation_uris(CONNECT_SERVER)
        httpretty.register_uri(
            httpretty.DELETE,
            f"{CONNECT_SERVER}/__api__/v1/system/caches/runtime",
            status=403,
            body=PERMISSION_DENIED_BODY,
            adding_headers={"Content-Type": "application/json"},
        )

        runner = CliRunner()
        args = ["system", "caches", "delete", "--language", "Python", "--version", "1.2.3", "--image-name", "Local"]
        apply_common_args(args, server=CONNECT_SERVER, key=API_KEY)
        result = runner.invoke(cli, args)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertRegex(result.output, "You don't have permission to perform this operation.")
