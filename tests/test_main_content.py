import os
import json
import shutil
import tarfile
import unittest

import httpretty
from click.testing import CliRunner

from rsconnect.main import cli
from rsconnect import VERSION
from rsconnect.api import RSConnectServer
from rsconnect.models import BuildStatus
from rsconnect.metadata import ContentBuildStore, _normalize_server_url

from .utils import apply_common_args

_bundle_download_dest = "download.tar.gz"
_test_build_dir = "rsconnect-build-test"

def register_uris(connect_server: str):
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/server_settings" % (connect_server),
        body=open("tests/testdata/connect-responses/server_settings.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/me" % (connect_server),
        body=open("tests/testdata/connect-responses/me.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/v1/content" % (connect_server),
        body=open("tests/testdata/connect-responses/list-content.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/v1/content/7d59c5c7-c4a7-4950-acc3-3943b7192bc4" % (connect_server),
        body=open("tests/testdata/connect-responses/describe-content-1.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/v1/content/ab497e4b-b706-4ae7-be49-228979a95eb4" % (connect_server),
        body=open("tests/testdata/connect-responses/describe-content-2.json", "r").read(),
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/v1/content/7d59c5c7-c4a7-4950-acc3-3943b7192bc4/bundles/92/download" % (connect_server),
        body=open("tests/testdata/bundle.tar.gz", "rb").read(),
        adding_headers={"Content-Type": "application/tar+gzip"},
    )
    httpretty.register_uri(
        httpretty.POST,
        f"%s/__api__/v1/content/7d59c5c7-c4a7-4950-acc3-3943b7192bc4/build" % (connect_server),
        body='{"task_id": "1234"}',
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/tasks/1234" % (connect_server),
        body="""{
            "id": "1234",
            "user_id": 0,
            "status": ["status1", "status2", "status3"],
            "result": {"type": "", "data": ""},
            "finished": true,
            "code": 0,
            "error": "",
            "last_status": 0
        }""",
        adding_headers={"Content-Type": "application/json"},
    )
    httpretty.register_uri(
        httpretty.GET,
        f"%s/__api__/applications/7d59c5c7-c4a7-4950-acc3-3943b7192bc4/config" % (connect_server),
        body="""{
            "config_url": "http://localhost:3939/connect/#/apps/7d59c5c7-c4a7-4950-acc3-3943b7192bc4",
            "logs_url": "http://localhost:3939/connect/#/apps/7d59c5c7-c4a7-4950-acc3-3943b7192bc4/logs"
        }""",
        adding_headers={"Content-Type": "application/json"},
    )

class TestContentSubcommand(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(_bundle_download_dest):
            os.remove(_bundle_download_dest)
        if os.path.exists(_test_build_dir):
            shutil.rmtree(_test_build_dir, ignore_errors=True)

    def setUp(self):
        self.connect_server = "http://localhost:3939"
        self.api_key = "testapikey123"

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(VERSION, result.output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_content_search(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = ["content", "search"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        response = json.loads(result.output)
        self.assertIsNotNone(response, result.output)
        self.assertEqual(len(response), 4, result.output)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_content_describe(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = ["content", "describe",
                "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4",
                "-g", "ab497e4b-b706-4ae7-be49-228979a95eb4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        response = json.loads(result.output)
        self.assertIn("id", response[0])
        self.assertIn("id", response[1])
        self.assertEqual(response[0]["guid"], "7d59c5c7-c4a7-4950-acc3-3943b7192bc4")
        self.assertEqual(response[1]["guid"], "ab497e4b-b706-4ae7-be49-228979a95eb4")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_content_download_bundle(self):
        register_uris(self.connect_server)
        runner = CliRunner()
        args = ["content", "download-bundle",
                "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4",
                "-o", _bundle_download_dest]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        with tarfile.open(_bundle_download_dest, mode="r:gz") as tgz:
            manifest = json.loads(tgz.extractfile("manifest.json").read())
            self.assertIn("metadata", manifest)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_build(self):
        register_uris(self.connect_server)
        runner = CliRunner()

        # add a content item
        args = ["content", "build", "add", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(
            os.path.exists("%s/%s.json" % (_test_build_dir, _normalize_server_url(self.connect_server)))
        )

        # list the "tracked" content
        args = ["content", "build", "ls", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertTrue(len(listing) == 1)
        self.assertEqual(listing[0]["guid"], "7d59c5c7-c4a7-4950-acc3-3943b7192bc4")
        self.assertEqual(listing[0]["bundle_id"], "92")
        self.assertEqual(listing[0]["rsconnect_build_status"], BuildStatus.NEEDS_BUILD)

        # run the build
        args = ["content", "build", "run", "--debug"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)

        # check that the build succeeded
        args = ["content", "build", "ls", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertTrue(len(listing) == 1)
        self.assertEqual(listing[0]["rsconnect_build_status"], BuildStatus.COMPLETE)

    def test_build_retry(self):
        register_uris(self.connect_server)
        runner = CliRunner()

        # add a content item
        args = ["content", "build", "add", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(
            os.path.exists("%s/%s.json" % (_test_build_dir, _normalize_server_url(self.connect_server)))
        )

        # list the "tracked" content
        args = ["content", "build", "ls", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertTrue(len(listing) == 1)
        self.assertEqual(listing[0]["guid"], "7d59c5c7-c4a7-4950-acc3-3943b7192bc4")
        self.assertEqual(listing[0]["bundle_id"], "92")
        self.assertEqual(listing[0]["rsconnect_build_status"], BuildStatus.NEEDS_BUILD)

        # set the content build status to RUNNING so it looks like it was interrupted
        # and the cleanup did not have time to finish, otherwise it would be marked as ABORTED
        store = ContentBuildStore(RSConnectServer(self.connect_server, self.api_key))
        store.set_content_item_build_status("7d59c5c7-c4a7-4950-acc3-3943b7192bc4", BuildStatus.RUNNING)

        # run the build
        args = ["content", "build", "run", "--retry"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)

        # check that the build succeeded
        args = ["content", "build", "ls", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertTrue(len(listing) == 1)
        self.assertEqual(listing[0]["rsconnect_build_status"], BuildStatus.COMPLETE)

    def test_build_rm(self):
        register_uris(self.connect_server)
        runner = CliRunner()

        # remove a content item
        args = ["content", "build", "rm", "-g", "7d59c5c7-c4a7-4950-acc3-3943b7192bc4"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)

        # check that it was removed
        args = ["content", "build", "ls"]
        apply_common_args(args, server=self.connect_server, key=self.api_key)
        result = runner.invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        listing = json.loads(result.output)
        self.assertEqual(len(listing), 0, result.output)
