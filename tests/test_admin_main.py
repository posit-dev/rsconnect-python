import json
from unittest import TestCase
from click.testing import CliRunner

from rsconnect.admin_main import cli
from rsconnect import VERSION

from .utils import (
    apply_common_args,
    require_api_key,
    require_connect
)

_content_guids = [
    "015143da-b75f-407c-81b1-99c4a724341e",
    "4ffc819c-065c-420c-88eb-332db1133317",
    "bcc74209-3a81-4b9c-acd5-d24a597c256c",
]

class TestAdminMain(TestCase):

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(VERSION, result.output)

    def test_content_search(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        runner = CliRunner()
        args = ["content", "search"]
        apply_common_args(args, server=connect_server, key=api_key)
        print(args)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        response = json.loads(result.output)
        self.assertIsNotNone(response, result.output)
        self.assertEqual(len(response), 3, result.output)

    def test_content_describe(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        runner = CliRunner()
        args = ["content", "describe", "-g", _content_guids[0], "--guid", _content_guids[1]]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        response = json.loads(result.output)
        self.assertIn('id', response[0])
        self.assertIn('id', response[1])
        self.assertEqual(response[0]['guid'], _content_guids[0])
        self.assertEqual(response[1]['guid'], _content_guids[1])
