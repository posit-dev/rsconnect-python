import os

from unittest import TestCase
from click.testing import CliRunner
from ..main import cli
from rsconnect import VERSION


class TestMain(TestCase):
    def require_connect(self):
        connect_server = os.environ.get('CONNECT_SERVER', None)
        if connect_server is None:
            self.skipTest('Set CONNECT_SERVER to test this function.')
        return connect_server

    def require_api_key(self):
        connect_api_key = os.environ.get('CONNECT_API_KEY', None)
        if connect_api_key is None:
            self.skipTest('Set CONNECT_API_KEY to test this function.')
        return connect_api_key

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['version'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn(VERSION, result.output)

    def test_ping(self):
        connect_server = self.require_connect()
        runner = CliRunner()
        result = runner.invoke(cli, ['test', '-s', connect_server])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("OK", result.output)

    def test_ping_api_key(self):
        connect_server = self.require_connect()
        api_key = self.require_api_key()
        runner = CliRunner()
        result = runner.invoke(cli, ['test', '-s', connect_server, '-k', api_key])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("OK", result.output)



