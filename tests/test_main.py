import os
import unittest
from os.path import join

from unittest import TestCase
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


class TestMain(TestCase):
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

    # TODO (mslynch): mock shinyapps.io
    @unittest.skip
    def test_add_shinyapps(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "add",
                "--target",
                "shinyapps",
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

    def test_add_shinyapps_missing_options(self):
        original_api_key_value = os.environ.pop("CONNECT_API_KEY")
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
            self.assertEqual(str(result.exception), "--token and --secret must both be provided for shinyapps.io.")
        finally:
            os.environ["CONNECT_API_KEY"] = original_api_key_value
