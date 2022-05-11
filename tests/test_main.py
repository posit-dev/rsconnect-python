import os
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
from rsconnect.exception import RSConnectException
from rsconnect.main import cli, _validate_deploy_to_args, server_store
from rsconnect import VERSION


class TestMain(TestCase):
    def test_validate_deploy_to_args(self):
        server_store.set("fake", "http://example.com", None)

        try:
            with self.assertRaises(RSConnectException):
                _validate_deploy_to_args("name", "url", None, False, None)

            with self.assertRaises(RSConnectException):
                _validate_deploy_to_args(None, None, None, False, None)

            with self.assertRaises(RSConnectException):
                _validate_deploy_to_args("fake", None, None, False, None)
        finally:
            server_store.remove_by_name("fake")

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
        self.assertIn("OK", result.output)

    # noinspection SpellCheckingInspection
    def test_deploy_manifest(self):
        target = optional_target(get_manifest_path("shinyapp"))
        runner = CliRunner()
        args = self.create_deploy_args("manifest", target)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

    def test_deploy_api(self):
        target = optional_target(get_api_path("flask"))
        runner = CliRunner()
        args = self.create_deploy_args("api", target)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)
