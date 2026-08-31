"""Target-specific option validation, once a stored entry has been resolved.

The command line alone cannot say which service a nickname or default server
names, so these checks run after resolution rather than in
validate_connection_options.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from rsconnect import api, validation
from rsconnect.api import ConnectCloudClient, RSConnectExecutor
from rsconnect.exception import RSConnectException
from rsconnect.main import cli
from rsconnect.metadata import SHINYAPPS_API_URL, ServerStore

from .target_helpers import (
    DEFAULT,
    ENV,
    TYPED,
    _cloud_entry,
    _cloud_server,
    _ctx,
    _deploy_option_flags,
    _setup_remote_server,
)


class TestConnectOptionsAgainstAResolvedEntry(unittest.TestCase):
    """Validate target-specific options after resolving a stored entry."""

    def setUp(self):
        env_patch = mock.patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.store = ServerStore(base_dir=tempfile.mkdtemp())
        self.store.set("sa", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        store_patch = mock.patch("rsconnect.api.ServerStore", return_value=self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_a_typed_api_key_is_refused(self):
        with self.assertRaises(RSConnectException) as context:
            RSConnectExecutor(path=tempfile.mkdtemp(), name="sa", api_key="key", ctx=_ctx(api_key=TYPED))
        self.assertIn("may not be passed alongside shinyapps.io", str(context.exception))

    def test_an_exported_api_key_is_dropped(self):
        executor = RSConnectExecutor(path=tempfile.mkdtemp(), name="sa", api_key="key", ctx=_ctx(api_key=ENV))
        server = executor.remote_server
        assert isinstance(server, api.ShinyappsServer)
        self.assertEqual(server.url, SHINYAPPS_API_URL)
        self.assertEqual(server.token, "tok")

    def test_a_typed_snowflake_connection_is_reported_as_an_spcs_option(self):
        with self.assertRaises(RSConnectException) as context:
            RSConnectExecutor(
                path=tempfile.mkdtemp(),
                server=SHINYAPPS_API_URL,
                snowflake_connection_name="dev",
                ctx=_ctx(snowflake_connection_name=TYPED),
            )
        self.assertIn("SPCS options (--snowflake-connection-name", str(context.exception))

    def test_a_connect_entry_is_not_treated_as_shinyapps(self):
        self.store.set("prod", "https://connect.example.com", api_key="stored-key")

        executor = RSConnectExecutor(
            path=tempfile.mkdtemp(),
            server="https://connect.example.com",
            account="sa-acct",
            token="sa-tok",
            secret="c2VjcmV0",
            ctx=_ctx(server=ENV, account=ENV, token=ENV, secret=ENV),
        )
        server = executor.remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.url, "https://connect.example.com")
        self.assertEqual(server.api_key, "stored-key")

    def test_an_exported_certificate_is_not_read(self):
        executor = RSConnectExecutor(
            path=tempfile.mkdtemp(), name="sa", cacert="/nonexistent/ca.pem", ctx=_ctx(cacert=ENV)
        )
        assert isinstance(executor.remote_server, api.ShinyappsServer)


class TestConnectOnlyDeployOptions(unittest.TestCase):
    """Deploy options that configure Posit Connect features Connect Cloud does not
    have. Connect Cloud ignores them, so they are rejected rather than accepted and
    dropped."""

    OPTIONS = validation._CONNECT_ONLY_DEPLOY_OPTIONS

    def test_the_list_covers_every_connect_only_option(self):
        # Dropping an entry starts accepting that option on Connect Cloud, and would
        # otherwise just remove its coverage from the tests below.
        self.assertEqual(
            set(self.OPTIONS),
            {
                "image",
                "disable_env_management",
                "env_management_py",
                "env_management_r",
                "env_management_node",
                "node",
                "draft",
                "metadata",
            },
        )

    def test_the_labels_name_options_the_deploy_commands_really_have(self):
        declared = _deploy_option_flags()
        for param, label in self.OPTIONS.items():
            with self.subTest(param):
                self.assertEqual(declared.get(param), {frozenset(label.split("/"))})

    def test_each_is_rejected_with_the_flag(self):
        for param, label in self.OPTIONS.items():
            with self.subTest(param):
                with self.assertRaises(RSConnectException) as context:
                    _setup_remote_server(ctx=_ctx(**{param: TYPED}), account_name="acme", use_connect_cloud=True)
                message = str(context.exception)
                self.assertIn(label, message)
                self.assertIn("may not be passed alongside Posit Connect Cloud", message)

    def test_each_is_rejected_for_a_saved_cloud_nickname(self):
        # A nickname is only known to name a Connect Cloud credential after the
        # store lookup, which is why this is checked in the executor.
        for param, label in self.OPTIONS.items():
            with self.subTest(param):
                with self.assertRaises(RSConnectException) as context:
                    _setup_remote_server(
                        ctx=_ctx(**{param: TYPED}), resolve=_cloud_entry(connect_cloud_access_token="at"), name="cloud"
                    )
                self.assertIn(label, str(context.exception))

    def test_defaulted_options_are_accepted(self):
        # --disable-env-management-py inverts to False when given and the shorthand
        # sets the same parameters without being their source, so what the user
        # typed can only be read from the parameter source.
        _cloud_server(ctx=_ctx(image=DEFAULT, env_management_py=DEFAULT), account_name="acme", use_connect_cloud=True)

    def test_a_connect_target_still_accepts_them(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key")
        executor = _setup_remote_server(ctx=_ctx(image=TYPED), store=store, name="prod")
        self.assertIsInstance(executor.remote_server, api.RSConnectServer)

    def test_draft_at_the_deploy_step_does_not_cite_a_connect_version(self):
        # The CLI rejects --draft before this, but a programmatic caller has no
        # click context to judge, and a Connect version says nothing to a target
        # with no draft step.
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.client = mock.Mock(spec=ConnectCloudClient)
        with self.assertRaises(RSConnectException) as context:
            executor.should_deploy_as_draft(draft=True, no_verify=False)
        message = str(context.exception)
        self.assertIn("only supported by Posit Connect", message)
        self.assertNotIn("2025.06.0", message)

    def test_a_same_named_argument_is_not_one_of_these_options(self):
        # `environment add` takes a positional IMAGE, so a Connect Cloud nickname
        # must reach that command's own "requires a Posit Connect server" error
        # rather than be told it passed -I/--image.
        command = cli.commands["environment"].commands["add"]
        with command.make_context("add", ["my-image:1.0", "-n", "cloud"]) as ctx:
            self.assertEqual(validation.typed_connect_only_deploy_options(ctx), [])
