import os
import json
import shutil
import tarfile
import unittest
from click.testing import CliRunner

from rsconnect.admin_main import cli
from rsconnect import VERSION
from rsconnect.models import BuildStatus

from .utils import (
    apply_common_args,
    require_api_key,
    require_connect
)

# run these tests in the order they are defined
#  because we are integration testing the state file
unittest.TestLoader.sortTestMethodsUsing = None

_bundle_download_dest = "download.tar.gz"
_content_guids = [
    "015143da-b75f-407c-81b1-99c4a724341e",
    "4ffc819c-065c-420c-88eb-332db1133317",
    "bcc74209-3a81-4b9c-acd5-d24a597c256c",
]
_test_build_dir = "rsconnect-build-test"


class TestAdminMain(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(_bundle_download_dest):
            os.remove(_bundle_download_dest)
        if os.path.exists(_test_build_dir):
            shutil.rmtree(_test_build_dir, ignore_errors=True)

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
        args = ["content", "describe", "-g", _content_guids[0], "-g", _content_guids[1]]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        response = json.loads(result.output)
        self.assertIn('id', response[0])
        self.assertIn('id', response[1])
        self.assertEqual(response[0]['guid'], _content_guids[0])
        self.assertEqual(response[1]['guid'], _content_guids[1])

    def test_content_download_bundle(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        runner = CliRunner()
        args = ["content", "download-bundle", "-g", _content_guids[1], "-o", _bundle_download_dest]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        with tarfile.open(_bundle_download_dest, mode='r:gz') as tgz:
            self.assertIsNotNone(tgz.extractfile('manifest.json').read())

    def test_build(self):
        connect_server = require_connect(self)
        api_key = require_api_key(self)
        runner = CliRunner()

        # add a content item
        args = ["build", "add", "-g", _content_guids[0]]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(os.path.exists('%s/build.json' % _test_build_dir))

        # list the "tracked" content
        args = ["build", "ls", "-g", _content_guids[0]]
        apply_common_args(args, server=connect_server, key=api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertTrue(len(listing) == 1)
        self.assertEqual(listing[0]['guid'], _content_guids[0])
        self.assertEqual(listing[0]['bundle_id'], "176")
        self.assertEqual(listing[0]['rsconnect_build_status'], BuildStatus.NEEDS_BUILD)

        # run the build
        # args = ["build", "run", "--debug"]
        # apply_common_args(args, server=connect_server, key=api_key)
        # result = runner.invoke(cli, args)
        # self.assertEqual(result.exit_code, 0, result.output)

        # # check that the build succeeded
        # args = ["build", "ls", "-g", _content_guids[0]]
        # apply_common_args(args, server=connect_server, key=api_key)
        # result = runner.invoke(cli, args)
        # self.assertEqual(result.exit_code, 0, result.output)
        # listing = json.loads(result.output)
        # self.assertTrue(len(listing) == 1)
        # self.assertEqual(listing[0]['rsconnect_build_status'], BuildStatus.COMPLETE)


    def test_build_history(self):
        pass

    def test_build_logs(self):
        pass

    def test_build_rm(self):
        pass

    # TODO: Test abort signal handling by setting the poll_wait and sending ^C
    #   while a build is running.
    def test_build_abort(self):
        pass
