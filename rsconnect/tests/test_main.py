import os
from os.path import join

from unittest import TestCase
from click.testing import CliRunner

from .test_data_util import get_dir
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

    def optional_target(self, default):
        return os.environ.get('CONNECT_DEPLOY_TARGET', default)

    def optional_cadata(self, default=None):
        return os.environ.get('CONNECT_CADATA_FILE', default)

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['version'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(VERSION, result.output)

    def test_ping(self):
        connect_server = self.require_connect()
        runner = CliRunner()
        result = runner.invoke(cli, ['test', '-s', connect_server])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

    def test_ping_api_key(self):
        connect_server = self.require_connect()
        api_key = self.require_api_key()
        runner = CliRunner()
        result = runner.invoke(cli, ['test', '-s', connect_server, '-k', api_key])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)

    def test_deploy(self):
        connect_server = self.require_connect()
        api_key = self.require_api_key()
        target = self.optional_target(get_dir(join('pip1', 'dummy.ipynb')))
        cadata_file = self.optional_cadata(None)
        runner = CliRunner()
        args = ['deploy', 'notebook', '-s', connect_server, '-k', api_key]
        if cadata_file is not None:
            args.append(['--cacert', cadata_file])
        args.append(target)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("OK", result.output)


