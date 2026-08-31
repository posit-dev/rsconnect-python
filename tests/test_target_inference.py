"""Choosing a deploy target: a named target, then deployment history, then the default.

Inference is target-agnostic -- a record may name a Posit Connect server,
shinyapps.io, or Posit Connect Cloud -- so these tests cover all three.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any, Optional
from unittest import mock

import click
import httpretty

from rsconnect import api
from rsconnect.api import ConnectCloudServer, RSConnectExecutor
from rsconnect.environment import fake_module_file_from_directory
from rsconnect.exception import RSConnectException
from rsconnect.main import cli
from rsconnect.metadata import SHINYAPPS_API_URL, AppStore, ServerStore
from rsconnect.models import AppModes

from .target_helpers import (
    API,
    ENV,
    TYPED,
    _commands_defined_in_main,
    _ctx,
    _executor_keywords,
    _register_accounts,
    _register_json,
)


class TestInferenceIsWiredToTheCommands(unittest.TestCase):
    """Check the CLI contracts used by target inference."""

    # `path` is what turns inference on (`infer_target=path is not None`).
    PATHLESS_DEPLOY_COMMANDS = {
        # The server pulls the repository; there is no local deployment record.
        "git",
        "other-content",
    }

    def test_every_deploy_subcommand_passes_the_content_path(self):
        for name, command in _commands_defined_in_main(cli.commands["deploy"]).items():
            with self.subTest(name):
                calls = _executor_keywords(command.callback)
                if name in self.PATHLESS_DEPLOY_COMMANDS:
                    self.assertTrue(all("path" not in call for call in calls))
                    continue
                self.assertTrue(calls, "%s builds no executor" % name)
                for call in calls:
                    self.assertIn("path", call)

    def test_no_content_command_passes_a_path(self):
        for name, command in _commands_defined_in_main(cli.commands["content"]).items():
            subcommands = _commands_defined_in_main(command) if hasattr(command, "commands") else {"": command}
            for sub, subcommand in sorted(subcommands.items()):
                with self.subTest("/".join(filter(None, (name, sub)))):
                    for call in _executor_keywords(subcommand.callback):
                        self.assertNotIn("path", call)

    # Environment-backed options that may affect target selection.
    ENVIRONMENT_VARIABLES = {
        "server": "CONNECT_SERVER",
        "api_key": "CONNECT_API_KEY",
        "insecure": "CONNECT_INSECURE",
        "cacert": "CONNECT_CA_CERTIFICATE",
        "account": ["SHINYAPPS_ACCOUNT"],
        "token": ["SHINYAPPS_TOKEN", "RSCLOUD_TOKEN"],
        "secret": ["SHINYAPPS_SECRET", "RSCLOUD_SECRET"],
        "client_id": "CONNECT_CLOUD_CLIENT_ID",
        "client_secret": "CONNECT_CLOUD_CLIENT_SECRET",
    }

    # These commands support Connect Cloud accounts but not shinyapps.io credentials.
    CLOUD_ONLY_ACCOUNT_COMMANDS = {"notebook", "quarto"}

    def test_the_target_options_are_bound_to_their_environment_variables(self):
        for command in _commands_defined_in_main(cli.commands["deploy"]).values():
            for param in command.params:
                if not isinstance(param, click.Option) or param.name not in self.ENVIRONMENT_VARIABLES:
                    continue
                with self.subTest("%s %s" % (command.name, param.name)):
                    if param.name == "account" and command.name in self.CLOUD_ONLY_ACCOUNT_COMMANDS:
                        self.assertIsNone(param.envvar)
                        continue
                    self.assertEqual(param.envvar, self.ENVIRONMENT_VARIABLES[param.name])

    def test_the_cloud_only_commands_take_no_shinyapps_options(self):
        for name in self.CLOUD_ONLY_ACCOUNT_COMMANDS:
            with self.subTest(name):
                params = {param.name for param in cli.commands["deploy"].commands[name].params}
                self.assertNotIn("token", params)
                self.assertNotIn("secret", params)

    def test_the_deploy_commands_carry_every_one_of_them(self):
        declared = {
            param.name: param.envvar for param in cli.commands["deploy"].commands["shiny"].params if param.envvar
        }
        self.assertEqual(declared, self.ENVIRONMENT_VARIABLES)

    def test_the_connect_cloud_account_variable_is_not_bound_to_an_option(self):
        # -A is shared with shinyapps.io; Connect Cloud reads its variable separately.
        for command in _commands_defined_in_main(cli.commands["deploy"]).values():
            for param in command.params:
                with self.subTest("%s %s" % (command.name, param.name)):
                    envvar = param.envvar or []
                    self.assertNotIn("CONNECT_CLOUD_ACCOUNT", [envvar] if isinstance(envvar, str) else envvar)


class TestRedeployTargetInference(unittest.TestCase):
    """A target, then deployment history, then the default server."""

    def setUp(self):
        env_patch = mock.patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.directory = tempfile.mkdtemp()
        self.store = ServerStore(base_dir=tempfile.mkdtemp())
        store_patch = mock.patch("rsconnect.api.ServerStore", return_value=self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def _record(self, *keys: str) -> None:
        """Write deployment records for this directory."""
        app_store = AppStore(fake_module_file_from_directory(self.directory))
        for key in keys:
            app_store.set(
                key,
                self.directory,
                "https://example.test/app",
                "1",
                "guid-1",
                "T",
                AppModes.PYTHON_SHINY,
            )

    def _connect(self, name: str = "prod", url: str = "https://connect.example.com", default: bool = False) -> None:
        self.store.set(name, url, api_key="key")
        if default:
            self.store.set_default(name)

    def _cloud(
        self,
        name: str = "cloud",
        account: str = "acme",
        account_id: Optional[str] = "acct-1",
        default: bool = False,
    ) -> None:
        self.store.set(
            name,
            API,
            connect_cloud_account_name=account,
            connect_cloud_account_id=account_id,
            connect_cloud_access_token="at",
        )
        if default:
            self.store.set_default(name)

    def _executor(self, **kwargs: Any) -> RSConnectExecutor:
        return RSConnectExecutor(path=self.directory, **kwargs)

    def test_a_connect_record_wins_over_a_cloud_default(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        server = self._executor().remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.url, "https://connect.example.com")
        self.assertEqual(server.api_key, "key")

    def test_a_cloud_record_wins_over_a_connect_default(self):
        self._cloud()
        self._connect(default=True)
        self._record("%s#acct-1" % API)

        executor = self._executor()
        server = executor.remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.account_id, "acct-1")
        self.assertEqual(server.access_token, "at")
        self.assertEqual(server.server_name, "cloud")
        self.assertEqual(executor.record_account, "acct-1")
        self.assertEqual(executor.record_server_key(), "%s#acct-1" % API)

    def test_a_name_keyed_cloud_record_resolves_the_credential(self):
        self._cloud()
        self._connect(default=True)
        self._record("%s#acme" % API)

        executor = self._executor()
        server = executor.remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.account_id, "acct-1")
        self.assertEqual(executor.record_account, "acme")
        self.assertEqual(executor.record_server_key_fallback(), "%s#acme" % API)

    def test_a_shinyapps_record_resolves_its_credential(self):
        self.store.set("shinyapps", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self._connect(default=True)
        self._record(SHINYAPPS_API_URL)

        server = self._executor().remote_server
        assert isinstance(server, api.ShinyappsServer)
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.token, "tok")

    def test_the_reported_target_is_not_announced_before_a_conflict(self):
        self.store.set("shinyapps", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self._connect(default=True)
        self._record(SHINYAPPS_API_URL)

        with mock.patch.object(api.logger, "info") as info:
            with self.assertRaises(RSConnectException):
                self._executor(ctx=_ctx(api_key=TYPED), api_key="key")
        self.assertEqual([call for call in info.call_args_list if "Redeploying to" in str(call)], [])

    def test_a_typed_connect_option_conflicts_with_an_inferred_shinyapps_target(self):
        self.store.set("shinyapps", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self._connect(default=True)
        self._record(SHINYAPPS_API_URL)

        with self.assertRaises(RSConnectException) as context:
            self._executor(ctx=_ctx(api_key=TYPED), api_key="key")
        self.assertIn("may not be passed alongside shinyapps.io", str(context.exception))

    def test_environment_connect_options_do_not_ride_along_to_an_inferred_shinyapps_target(self):
        self.store.set("shinyapps", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self._connect(default=True)
        self._record(SHINYAPPS_API_URL)

        server = self._executor(
            ctx=_ctx(api_key=ENV, insecure=ENV, cacert=ENV),
            api_key="key",
            insecure=True,
            cacert="/no/such/cert",
        ).remote_server
        assert isinstance(server, api.ShinyappsServer)
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.token, "tok")

    def test_a_typed_connect_option_conflicts_with_an_inferred_cloud_target(self):
        self._cloud()
        self._connect(default=True)
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor(ctx=_ctx(api_key=TYPED), api_key="key")
        self.assertIn("may not be passed alongside Posit Connect Cloud", str(context.exception))

        server = self._executor(ctx=_ctx(api_key=ENV), api_key="key").remote_server
        assert isinstance(server, ConnectCloudServer)

    def test_an_inferred_connect_target_still_takes_the_api_key(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        server = self._executor(api_key="typed-key").remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.api_key, "typed-key")

    def test_several_records_are_refused_over_the_default(self):
        self._cloud(default=True)
        self._connect()
        self._record("https://connect.example.com", "%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("it has 2 deployment records", str(context.exception))

    def test_no_records_leave_the_default_server_in_charge(self):
        self._cloud(default=True)
        self._connect()

        server = self._executor().remote_server
        assert isinstance(server, ConnectCloudServer)

    def test_several_servers_without_a_default_are_resolved_by_the_record(self):
        self._cloud()
        self._connect()
        self._record("https://connect.example.com")

        server = self._executor().remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.url, "https://connect.example.com")

    def test_a_divergent_cloud_account_needs_no_default_either(self):
        self._cloud()
        self._connect()
        self._record("%s#acct-2" % API)

        executor = self._executor()
        assert isinstance(executor.remote_server, ConnectCloudServer)
        self.assertEqual(executor.record_account, "acct-2")

    def test_without_a_record_the_target_still_has_to_be_named(self):
        self._cloud()
        self._connect()

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("You must specify one of -n/--name", str(context.exception))

    def test_a_declined_record_without_a_default_says_why(self):
        self._cloud(name="personal")
        self._cloud(name="work", account="team-b", account_id="acct-2")
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        message = str(context.exception)
        self.assertIn("This directory has been deployed before", message)
        self.assertIn("several saved Posit Connect Cloud credentials share the URL", message)
        self.assertIn("Pass -n/--name", message)

    def test_several_records_without_a_default_say_how_many(self):
        self._connect()
        self._cloud()
        self._record("https://connect.example.com", "%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        message = str(context.exception)
        self.assertIn("This directory has been deployed before, but it has 2 deployment records", message)
        self.assertIn("--connect-cloud with -A/--account", message)

    def test_two_records_for_different_cloud_accounts_still_decline(self):
        self._cloud()
        self._record("%s#acct-1" % API, "%s#acct-9" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("it has 2 deployment records", str(context.exception))

    def test_a_name_that_matches_another_accounts_id_declines(self):
        # "%s#acct-2" may be this account's legacy name or another account's id.
        self._cloud(name="cloud", account="acct-2", account_id="9")
        self._record("%s#9" % API, "%s#acct-2" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("it has 2 deployment records", str(context.exception))

    def test_a_record_for_an_unsaved_server_says_so(self):
        self._connect(name="other", url="https://other.example.com")
        self._record("https://gone.example.com")

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("https://gone.example.com, is no longer saved", str(context.exception))

    def test_no_deployment_history_keeps_the_generic_error(self):
        self._cloud(name="personal")
        self._cloud(name="work", account="team-b", account_id="acct-2")

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("You must specify one of -n/--name", str(context.exception))

    def test_one_saved_server_needs_no_default_to_infer_from(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        server = self._executor().remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")

    def test_an_explicit_server_suppresses_inference(self):
        self._cloud()
        self._connect()
        self._record("%s#acct-1" % API)

        server = self._executor(server="https://connect.example.com").remote_server
        assert isinstance(server, api.RSConnectServer)

    def test_an_explicit_nickname_suppresses_inference(self):
        self._cloud()
        self._connect()
        self._record("%s#acct-1" % API)

        server = self._executor(name="prod").remote_server
        assert isinstance(server, api.RSConnectServer)

    def test_an_environment_sourced_server_suppresses_inference(self):
        self._cloud()
        self._connect()
        self._record("%s#acct-1" % API)

        executor = self._executor(ctx=_ctx(server=ENV), server="https://connect.example.com")
        assert isinstance(executor.remote_server, api.RSConnectServer)

    def test_a_lone_account_points_at_the_recorded_credential(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="team-b", ctx=_ctx(account=TYPED))
        message = str(context.exception)
        self.assertIn("-A/--account selects the Posit Connect Cloud account", message)
        self.assertIn('last deployed to "cloud" (Posit Connect Cloud account "acme")', message)
        self.assertIn("try -n cloud -A team-b", message)

    def test_a_lone_account_points_at_a_shinyapps_record_too(self):
        self.store.set("shinyapps", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self._record(SHINYAPPS_API_URL)

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="other", ctx=_ctx(account=TYPED))
        message = str(context.exception)
        self.assertIn("names an account to publish to, not a server", message)
        self.assertIn("https://api.shinyapps.io", message)

    def test_an_exported_account_does_not_block_the_redeploy(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        server = self._executor(account="team-b", ctx=_ctx(account=ENV)).remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")

    def test_an_exported_account_still_conflicts_with_a_default_shinyapps_entry(self):
        self.store.set("sa", SHINYAPPS_API_URL, account_name="acme", token="tok", secret="c2VjcmV0")
        self.store.set_default("sa")

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="other", ctx=_ctx(account=ENV))
        self.assertIn("must all be provided for shinyapps.io", str(context.exception))

    def test_two_exported_account_variables_are_still_not_a_target(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_ACCOUNT": "team-b"}):
            server = self._executor(account="sa-acct", ctx=_ctx(account=ENV)).remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.url, "https://connect.example.com")

    def test_a_typed_account_keeps_its_own_error_rather_than_the_default(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_ACCOUNT": "team-b"}):
            with self.assertRaises(RSConnectException) as context:
                self._executor(account="typed", ctx=_ctx(account=TYPED))
        self.assertIn("names an account to publish to, not a server", str(context.exception))

    def test_a_complete_exported_shinyapps_credential_is_still_a_target(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        server = self._executor(
            account="sa-acct", token="tok", secret="c2VjcmV0", ctx=_ctx(account=ENV, token=ENV, secret=ENV)
        ).remote_server
        assert isinstance(server, api.ShinyappsServer)
        self.assertEqual(server.account_name, "sa-acct")

    def test_a_connect_option_alongside_a_lone_account_keeps_its_own_error(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        for label, option in (("-k/--api-key", dict(api_key="key")), ("-c/--cacert", dict(cacert="/ca.pem"))):
            with self.subTest(label):
                sources = {"account": TYPED}
                sources.update({name: TYPED for name in option})
                with self.assertRaises(RSConnectException) as context:
                    self._executor(account="team-b", ctx=_ctx(**sources), **option)
                message = str(context.exception)
                self.assertNotIn("-A/--account selects", message)
                self.assertIn("may not be passed alongside shinyapps.io options", message)

    def test_a_connect_only_deploy_option_alongside_a_lone_account_suppresses_the_hint(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="team-b", ctx=_ctx(account=TYPED, image=TYPED))
        self.assertNotIn("-A/--account selects", str(context.exception))

    def test_a_lone_account_does_not_resolve_against_the_default_credential(self):
        self._cloud(name="cloud")
        self._cloud(name="work", account="team-b", account_id="acct-2", default=True)
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="other", ctx=_ctx(account=TYPED))
        self.assertIn("several saved Posit Connect Cloud credentials share the URL", str(context.exception))

    def test_a_lone_account_with_a_declined_record_says_why(self):
        self._cloud(name="personal")
        self._cloud(name="work", account="team-b", account_id="acct-2")
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor(account="other", ctx=_ctx(account=TYPED))
        self.assertIn("several saved Posit Connect Cloud credentials share the URL", str(context.exception))

    def test_the_connect_cloud_flag_suppresses_inference(self):
        self._cloud()
        self._connect()
        self._record("https://connect.example.com")

        server = self._executor(use_connect_cloud=True, account="acme").remote_server
        assert isinstance(server, ConnectCloudServer)

    def test_shinyapps_credentials_suppress_inference(self):
        self._connect()
        self._record("https://connect.example.com")

        server = self._executor(
            account="acme", token="tok", secret="c2VjcmV0", ctx=_ctx(token=TYPED, secret=TYPED)
        ).remote_server
        assert isinstance(server, api.ShinyappsServer)
        self.assertEqual(server.account_name, "acme")

    def test_an_environment_sourced_target_is_labelled_as_such(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        with self.assertLogs("rsconnect", level="DEBUG") as captured:
            self._executor(ctx=_ctx(server=ENV), server="https://connect.example.com")
        self.assertIn("-s/--server (from ENVIRONMENT) given", "\n".join(captured.output))

    def test_the_recorded_account_survives_an_exported_one(self):
        # Click still reports -A as environment-sourced after inference replaces it.
        self._cloud()
        self._record("%s#acme" % API)

        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_ACCOUNT": "cloud-acct"}):
            server = self._executor(account="shinyapps-acct", ctx=_ctx(account=ENV)).remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")

    def test_a_lone_cloud_account_variable_does_not_replace_the_recorded_one(self):
        self._cloud()
        self._record("%s#acme" % API)

        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_ACCOUNT": "cloud-acct"}):
            server = self._executor().remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")

    def test_the_connect_cloud_account_variable_does_not_block_the_redeploy(self):
        self._cloud(default=True)
        self._connect()
        self._record("https://connect.example.com")

        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_ACCOUNT": "team-b"}):
            server = self._executor().remote_server
        assert isinstance(server, api.RSConnectServer)
        self.assertEqual(server.url, "https://connect.example.com")

    def test_new_suppresses_inference(self):
        self._cloud()
        self._connect(default=True)
        self._record("%s#acct-1" % API)

        server = self._executor(new=True).remote_server
        assert isinstance(server, api.RSConnectServer)

    def test_several_saved_cloud_credentials_are_refused_over_the_default(self):
        self._cloud(name="personal")
        self._cloud(name="work", account="team-b", account_id="acct-2")
        self._connect(default=True)
        self._record("%s#acct-1" % API)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        message = str(context.exception)
        self.assertIn("several saved Posit Connect Cloud credentials share the URL", message)
        self.assertIn("with -A/--account alongside it", message)

    def test_several_credentials_for_one_url_are_refused_over_the_default(self):
        self.store.set("sa-work", SHINYAPPS_API_URL, account_name="work", token="tok", secret="c2VjcmV0")
        self.store.set("sa-home", SHINYAPPS_API_URL, account_name="home", token="tok", secret="c2VjcmV0")
        self._connect(default=True)
        self._record(SHINYAPPS_API_URL)

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        message = str(context.exception)
        self.assertIn("2 saved credentials share the URL it was last deployed to", message)
        self.assertIn("Pass -n/--name to choose one of them.", message)

    def test_one_connect_server_saved_under_two_nicknames_is_refused_over_the_default(self):
        self._connect(name="prod")
        self._connect(name="prod-copy")
        self._cloud(default=True)
        self._record("https://connect.example.com")

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("2 saved credentials share the URL it was last deployed to", str(context.exception))

    def test_a_record_for_an_unsaved_server_is_refused_over_the_default(self):
        self._connect(default=True)
        self._record("https://gone.example.com")

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("https://gone.example.com, is no longer saved", str(context.exception))

    def test_an_account_keyed_record_for_a_non_cloud_server_is_refused_over_the_default(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com#acct-1")

        with self.assertRaises(RSConnectException) as context:
            self._executor()
        self.assertIn("is not a Posit Connect Cloud one", str(context.exception))

    def test_the_content_commands_do_not_infer_a_target(self):
        self._cloud()
        self._connect(default=True)
        self._record("%s#acct-1" % API)

        server = RSConnectExecutor().remote_server
        assert isinstance(server, api.RSConnectServer)

    def test_the_inferred_target_is_reported(self):
        self._connect()
        self._cloud(default=True)
        self._record("https://connect.example.com")

        with self.assertLogs("rsconnect", level="INFO") as captured:
            self._executor()
        self.assertIn('Redeploying to "prod" (https://connect.example.com)', "\n".join(captured.output))
        self.assertIn("-s/--server", "\n".join(captured.output))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_an_account_the_credential_was_not_saved_with_is_resolved_by_id(self):
        self._cloud()
        self._record("%s#acct-2" % API)

        with self.assertLogs("rsconnect", level="INFO") as captured:
            executor = self._executor()
        server = executor.remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(executor.record_account, "acct-2")
        self.assertIsNone(server.account_id)
        self.assertIn('Redeploying to "cloud" (Posit Connect Cloud)', "\n".join(captured.output))
        self.assertNotIn("acct-2", "\n".join(captured.output))

        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts(
            {"id": "acct-1", "name": "acme", "permissions": ["content:create"]},
            {"id": "acct-2", "name": "team-b", "permissions": ["content:create"]},
        )
        with self.assertLogs("rsconnect", level="INFO") as captured:
            executor.validate_connect_cloud_server()

        self.assertEqual(server.account_name, "team-b")
        self.assertEqual(server.account_id, "acct-2")
        self.assertEqual(executor.record_server_key(), "%s#acct-2" % API)
        self.assertIn('Publishing to the Posit Connect Cloud account "team-b"', "\n".join(captured.output))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_name_keyed_record_for_another_account_is_resolved_by_name(self):
        self._cloud()
        self._record("%s#team-b" % API)

        executor = self._executor()
        self.assertEqual(executor.record_account, "team-b")

        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts(
            {"id": "acct-1", "name": "acme", "permissions": ["content:create"]},
            {"id": "acct-2", "name": "team-b", "permissions": ["content:create"]},
        )
        executor.validate_connect_cloud_server()

        server = executor.remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "team-b")
        self.assertEqual(server.account_id, "acct-2")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_record_naming_the_credentials_own_account_is_confirmed_once(self):
        self._cloud()
        self._record("%s#acct-1" % API)

        executor = self._executor()
        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts(
            {"id": "acct-1", "name": "acme", "permissions": ["content:create"]},
            {"id": "acct-2", "name": "team-b", "permissions": ["content:create"]},
        )
        with mock.patch.object(api.logger, "info") as info:
            executor.validate_connect_cloud_server()

        server = executor.remote_server
        assert isinstance(server, ConnectCloudServer)
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.account_id, "acct-1")
        self.assertEqual([call for call in info.call_args_list if "Publishing to" in str(call)], [])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_key_matching_the_credentials_id_and_another_accounts_name_declines(self):
        # The key may be this account's id or another account's legacy name.
        self._cloud()
        self._record("%s#acct-1" % API)

        executor = self._executor()
        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts(
            {"id": "acct-1", "name": "acme", "permissions": ["content:create"]},
            {"id": "9", "name": "acct-1", "permissions": ["content:create"]},
        )
        with self.assertRaises(RSConnectException) as context:
            executor.validate_connect_cloud_server()
        self.assertIn('names the Posit Connect Cloud account "acct-1"', str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_key_matching_the_credentials_name_and_another_accounts_id_declines(self):
        # The key may be this account's legacy name or another account's id.
        self._cloud()
        self._record("%s#acme" % API)

        executor = self._executor()
        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts(
            {"id": "acct-1", "name": "acme", "permissions": ["content:create"]},
            {"id": "acme", "name": "team-b", "permissions": ["content:create"]},
        )
        with self.assertRaises(RSConnectException) as context:
            executor.validate_connect_cloud_server()
        self.assertIn('names the Posit Connect Cloud account "acme"', str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_an_account_that_no_longer_exists_is_reported(self):
        self._cloud()
        self._record("%s#acct-2" % API)

        executor = self._executor()
        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        _register_accounts({"id": "acct-1", "name": "acme", "permissions": ["content:create"]})
        with self.assertRaises(RSConnectException) as context:
            executor.validate_connect_cloud_server()
        message = str(context.exception)
        self.assertIn('No Posit Connect Cloud account matching "acct-2"', message)
        self.assertIn("You can publish to: acme.", message)
