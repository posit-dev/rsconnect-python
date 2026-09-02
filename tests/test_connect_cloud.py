from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from typing import Any, Dict, Optional
from unittest import mock

import click
import httpretty
from click.core import ParameterSource
from click.testing import CliRunner

from rsconnect import api, connect_cloud
from rsconnect.api import (
    ConnectCloudClient,
    ConnectCloudServer,
    ConnectCloudService,
    RSConnectClient,
    RSConnectExecutor,
)
from rsconnect.environment import fake_module_file_from_directory
from rsconnect.exception import DeploymentFailedException, RSConnectException
from rsconnect.http_support import HTTPResponse, HTTPServer
from rsconnect.log import VERBOSE
from rsconnect.main import cli
from rsconnect.metadata import AppStore, ServerData, ServerStore
from rsconnect.models import AppModes
from rsconnect.oauth import InvalidClientError, InvalidGrantError
from rsconnect import validation
from rsconnect.validation import validate_connection_options

from .utils import failing_keyring

ENV = ParameterSource.ENVIRONMENT
TYPED = ParameterSource.COMMANDLINE
DEFAULT = ParameterSource.DEFAULT


class TestConnectCloudEnvironments(unittest.TestCase):
    def test_default_environment_is_production(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connect_cloud.environment_name(), "production")
            self.assertEqual(connect_cloud.urls().api, "https://api.connect.posit.cloud/v1")
            self.assertEqual(connect_cloud.urls().ui, "https://connect.posit.cloud")
            self.assertEqual(connect_cloud.urls().auth, "https://login.posit.cloud")
            self.assertEqual(connect_cloud.urls().logs, "https://logs.connect.posit.cloud/v1")

    def test_environment_selected_by_env_var(self):
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}, clear=True):
            self.assertEqual(connect_cloud.environment_name(), "staging")
            self.assertEqual(connect_cloud.urls().api, "https://api.staging.connect.posit.cloud/v1")

    def test_development_shares_staging_auth_host(self):
        # Not a copy/paste slip: development has no auth service of its own.
        self.assertEqual(
            connect_cloud.urls("development").auth,
            connect_cloud.urls("staging").auth,
        )

    def test_unknown_environment_is_rejected(self):
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "nope"}, clear=True):
            with self.assertRaises(RSConnectException) as context:
                connect_cloud.environment_name()
        message = str(context.exception)
        self.assertIn("nope", message)
        self.assertIn("production", message)

    def test_every_environment_is_fully_populated(self):
        for name in ("production", "staging", "development"):
            urls = connect_cloud.urls(name)
            for field in urls._fields:
                value = getattr(urls, field)
                self.assertTrue(value.startswith("https://"), f"{name}.{field} = {value!r}")

    def test_client_id_per_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connect_cloud.client_id("production"), "rsconnect-python")
            self.assertEqual(connect_cloud.client_id("staging"), "rsconnect-python-staging")

    def test_oauth_client_id_env_var_overrides(self):
        with mock.patch.dict(os.environ, {connect_cloud.OAUTH_CLIENT_ID_ENV_VAR: "custom-client"}, clear=True):
            self.assertEqual(connect_cloud.client_id("production"), "custom-client")

    def test_oauth_client_id_var_is_distinct_from_service_account_var(self):
        # CONNECT_CLOUD_CLIENT_ID is a user's service account credential, passed
        # with --client-id. It must not change which OAuth client the CLI is.
        with mock.patch.dict(os.environ, {"CONNECT_CLOUD_CLIENT_ID": "service-account"}, clear=True):
            self.assertEqual(connect_cloud.client_id("production"), "rsconnect-python")


class TestConnectCloudUrls(unittest.TestCase):
    def test_oauth_metadata_shape(self):
        metadata = connect_cloud.urls("production").oauth_metadata()
        self.assertEqual(
            metadata,
            {
                "device_authorization_endpoint": "https://login.posit.cloud/oauth/device/authorize",
                "token_endpoint": "https://login.posit.cloud/oauth/token",
            },
        )

    def test_content_url(self):
        url = connect_cloud.urls("production").content_url("acme-analytics", "8f3c1e2a")
        self.assertEqual(url, "https://connect.posit.cloud/acme-analytics/content/8f3c1e2a")

    def test_is_connect_cloud_url(self):
        self.assertTrue(connect_cloud.is_connect_cloud_url("connect.posit.cloud"))
        self.assertTrue(connect_cloud.is_connect_cloud_url("https://api.connect.posit.cloud/v1"))
        self.assertTrue(connect_cloud.is_connect_cloud_url("https://api.staging.connect.posit.cloud/v1"))
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://connect.example.com"))
        self.assertFalse(connect_cloud.is_connect_cloud_url(None))

    def test_is_connect_cloud_url_tolerates_trailing_slash_and_case(self):
        self.assertTrue(connect_cloud.is_connect_cloud_url("https://api.connect.posit.cloud/v1/"))
        self.assertTrue(connect_cloud.is_connect_cloud_url("HTTPS://API.CONNECT.POSIT.CLOUD/v1"))
        self.assertTrue(connect_cloud.is_connect_cloud_url("connect.posit.cloud/"))
        self.assertTrue(connect_cloud.is_connect_cloud_url("Connect.Posit.Cloud"))
        # The path itself is still case-sensitive and must match exactly.
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://api.connect.posit.cloud/V1"))
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://api.connect.posit.cloud/v1/extra"))
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://api.connect.posit.cloud/v1?x=1"))

    def test_resolve_url_canonicalizes_recognized_variants(self):
        # A trailing-slash variant must be stored as the exact API URL, or the
        # saved server would not map back to its environment.
        self.assertEqual(
            connect_cloud.resolve_url("https://api.staging.connect.posit.cloud/v1/"),
            "https://api.staging.connect.posit.cloud/v1",
        )
        self.assertEqual(connect_cloud.resolve_url("connect.posit.cloud/"), "https://api.connect.posit.cloud/v1")
        self.assertEqual(connect_cloud.resolve_url("https://connect.example.com/"), "https://connect.example.com/")

    def test_is_connect_cloud_url_matches_exactly_not_by_substring(self):
        # The removed Posit Cloud support matched "posit.cloud" anywhere in the
        # URL, which would also match a lookalike host.
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://connect.posit.cloud.example.com"))
        self.assertFalse(connect_cloud.is_connect_cloud_url("https://evil-connect.posit.cloud.attacker.test"))
        self.assertFalse(connect_cloud.is_connect_cloud_url("connect.posit.cloud.example.com"))

    def test_resolve_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(connect_cloud.resolve_url("connect.posit.cloud"), "https://api.connect.posit.cloud/v1")
            self.assertEqual(connect_cloud.resolve_url(None), "https://api.connect.posit.cloud/v1")
            # An explicit URL is passed through unchanged.
            self.assertEqual(
                connect_cloud.resolve_url("https://api.dev.connect.posit.cloud/v1"),
                "https://api.dev.connect.posit.cloud/v1",
            )

    def test_resolve_url_follows_selected_environment(self):
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}, clear=True):
            self.assertEqual(
                connect_cloud.resolve_url("connect.posit.cloud"),
                "https://api.staging.connect.posit.cloud/v1",
            )


class TestConnectCloudAuth(unittest.TestCase):
    def test_device_login_requests_vivid_scope(self):
        with mock.patch("rsconnect.connect_cloud.login_with_device_code") as login:
            login.return_value = {"access_token": "at", "refresh_token": "rt"}
            result = connect_cloud.login_interactive("production")

        self.assertEqual(result, {"access_token": "at", "refresh_token": "rt"})
        kwargs = login.call_args.kwargs
        self.assertEqual(kwargs["scope"], "vivid")
        self.assertEqual(kwargs["client_id"], "rsconnect-python")
        self.assertEqual(
            kwargs["metadata"]["device_authorization_endpoint"],
            "https://login.posit.cloud/oauth/device/authorize",
        )

    def test_client_credentials_login_requests_vivid_scope(self):
        with mock.patch("rsconnect.connect_cloud.request_client_credentials_token") as request:
            request.return_value = {"access_token": "at"}
            result = connect_cloud.login_client_credentials("cid", "csecret", "production")

        self.assertEqual(result, {"access_token": "at"})
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["scope"], "vivid")
        self.assertEqual(kwargs["client_id"], "cid")
        self.assertEqual(kwargs["client_secret"], "csecret")
        self.assertEqual(kwargs["token_endpoint"], "https://login.posit.cloud/oauth/token")

    def test_device_login_opens_a_browser_by_default(self):
        # Matches `rsconnect login` for Connect, and the browser we already open
        # after a successful deploy.
        with mock.patch("rsconnect.connect_cloud.login_with_device_code") as login:
            login.return_value = {"access_token": "at"}
            connect_cloud.login_interactive("production")
        self.assertNotIn("open_browser", login.call_args.kwargs)

    def test_refresh_requests_vivid_scope(self):
        with mock.patch("rsconnect.connect_cloud.refresh_access_token") as refresh:
            refresh.return_value = {"access_token": "new"}
            connect_cloud.refresh("rt", "production")

        kwargs = refresh.call_args.kwargs
        self.assertEqual(kwargs["scope"], "vivid")
        self.assertEqual(kwargs["refresh_token"], "rt")


class TestConnectCloudServer(unittest.TestCase):
    def test_defaults_url_to_selected_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            server = ConnectCloudServer("acme", access_token="at")
        self.assertEqual(server.url, "https://api.connect.posit.cloud/v1")
        self.assertEqual(server.remote_name, "Posit Connect Cloud")
        self.assertEqual(server.account_name, "acme")
        self.assertEqual(server.access_token, "at")
        self.assertIsNone(server.client_secret)

    def test_explicit_url_wins(self):
        server = ConnectCloudServer("acme", access_token="at", url="https://api.dev.connect.posit.cloud/v1")
        self.assertEqual(server.url, "https://api.dev.connect.posit.cloud/v1")

    def test_normalizes_pseudo_server_name(self):
        # Mirrors ShinyappsServer accepting "shinyapps.io".
        with mock.patch.dict(os.environ, {}, clear=True):
            server = ConnectCloudServer("acme", url="connect.posit.cloud")
        self.assertEqual(server.url, "https://api.connect.posit.cloud/v1")

    def test_carries_client_credentials(self):
        server = ConnectCloudServer("acme", client_id="cid", client_secret="csecret")
        self.assertEqual(server.client_id, "cid")
        self.assertEqual(server.client_secret, "csecret")

    def test_is_not_a_posit_server(self):
        # ShinyappsServer/PositServer means HMAC token+secret auth. Connect Cloud
        # uses OAuth, and the isinstance dispatch in RSConnectExecutor relies on
        # these being unrelated.
        from rsconnect.api import PositServer

        self.assertNotIsInstance(ConnectCloudServer("acme"), PositServer)


class TestConnectCloudServerStore(unittest.TestCase):
    def setUp(self):
        self.store = ServerStore(base_dir=tempfile.mkdtemp())

    def test_stores_prefixed_fields(self):
        self.store.set(
            "cloud",
            "https://api.connect.posit.cloud/v1",
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="csecret",
        )
        self.assertEqual(
            self.store.get_by_name("cloud"),
            {
                "name": "cloud",
                "url": "https://api.connect.posit.cloud/v1",
                "connect_cloud_account_name": "acme",
                "connect_cloud_client_id": "cid",
                "connect_cloud_client_secret": "csecret",
            },
        )

    def test_omits_absent_optional_fields(self):
        self.store.set(
            "cloud",
            "https://api.connect.posit.cloud/v1",
            connect_cloud_account_name="acme",
        )
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertNotIn("connect_cloud_client_secret", entry)
        self.assertNotIn("connect_cloud_access_token", entry)

    def test_not_confused_with_shinyapps(self):
        # The shinyapps.io branch keys off `account_name`; Connect Cloud must not
        # fall into it, which is why its field is prefixed.
        self.store.set(
            "cloud",
            "https://api.connect.posit.cloud/v1",
            connect_cloud_account_name="acme",
            connect_cloud_access_token="at",
        )
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertNotIn("account_name", entry)
        self.assertNotIn("token", entry)
        self.assertNotIn("secret", entry)

    def test_shinyapps_entry_is_unaffected(self):
        self.store.set(
            "sa",
            "https://api.shinyapps.io",
            account_name="me",
            token="tok",
            secret="sec",
        )
        self.assertEqual(
            self.store.get_by_name("sa"),
            {
                "name": "sa",
                "url": "https://api.shinyapps.io",
                "account_name": "me",
                "token": "tok",
                "secret": "sec",
            },
        )

    def test_resolve_round_trips_connect_cloud_fields(self):
        self.store.set(
            "cloud",
            "https://api.connect.posit.cloud/v1",
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="csecret",
            connect_cloud_access_token="at",
            connect_cloud_refresh_token="rt",
        )
        data = self.store.resolve("cloud", None)
        self.assertTrue(data.from_store)
        self.assertEqual(data.connect_cloud_account_name, "acme")
        self.assertEqual(data.connect_cloud_client_id, "cid")
        self.assertEqual(data.connect_cloud_client_secret, "csecret")
        self.assertEqual(data.connect_cloud_access_token, "at")
        self.assertEqual(data.connect_cloud_refresh_token, "rt")

    def test_resolve_leaves_connect_cloud_fields_unset_for_other_targets(self):
        self.store.set("prod", "https://connect.example.com", api_key="key")
        data = self.store.resolve("prod", None)
        self.assertIsNone(data.connect_cloud_account_name)
        self.assertIsNone(data.connect_cloud_access_token)


API = "https://api.connect.posit.cloud/v1"


def _json_body(request):
    return json.loads(request.body.decode("utf-8"))


def _ctx(**sources: ParameterSource) -> click.Context:
    """A click context recording where each named parameter's value came from.

    Each name is declared as an option, since validation distinguishes options
    from same-named arguments.
    """
    params: list[click.Parameter] = [click.Option(["--%s" % param.replace("_", "-")]) for param in sources]
    ctx = click.Context(click.Command("deploy", params=params))
    for param, source in sources.items():
        ctx.set_parameter_source(param, source)  # pyright: ignore[reportAttributeAccessIssue]
    return ctx


def _deploy_option_flags() -> Dict[str, set[frozenset[str]]]:
    """The flags each `deploy` subcommand option is spelled with, by parameter name."""
    flags: Dict[str, set[frozenset[str]]] = {}
    for command in cli.commands["deploy"].commands.values():
        for param in command.params:
            if isinstance(param, click.Option) and param.name:
                flags.setdefault(param.name, set()).add(frozenset(param.opts + param.secondary_opts))
    return flags


def _json_response(payload: Any, status: int = 200) -> Any:
    return httpretty.Response(
        body=json.dumps(payload), adding_headers={"Content-Type": "application/json"}, status=status
    )


def _register_json(method: Any, url: str, payload: Any, status: int = 200) -> None:
    httpretty.register_uri(
        method, url, body=json.dumps(payload), adding_headers={"Content-Type": "application/json"}, status=status
    )


def _register_pages(url: str, *pages: Any) -> None:
    httpretty.register_uri(httpretty.GET, url, responses=[_json_response(p) for p in pages])


def _register_accounts(*accounts: Any) -> None:
    _register_json(httpretty.GET, f"{API}/accounts", {"data": list(accounts), "total": len(accounts)})


def _cloud_entry(**fields: Any) -> ServerData:
    """A resolved store entry for a saved Connect Cloud server named "cloud"."""
    fields.setdefault("connect_cloud_account_name", "acme")
    return ServerData("cloud", API, True, **fields)


def _store_with_cloud_entry(**fields: Any) -> ServerStore:
    """A temp-dir ServerStore holding one saved Connect Cloud server named "cloud"."""
    store = ServerStore(base_dir=tempfile.mkdtemp())
    fields.setdefault("connect_cloud_account_name", "acme")
    fields.setdefault("connect_cloud_access_token", "at")
    store.set("cloud", API, **fields)
    return store


def _setup_remote_server(
    ctx: Optional[click.Context] = None,
    store: Optional[ServerStore] = None,
    resolve: Optional[ServerData] = None,
    default: Optional[ServerData] = None,
    has_cloud_account: Optional[bool] = None,
    environ: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> RSConnectExecutor:
    """Run setup_remote_server on a bare executor with the store interactions mocked.

    `store` replaces the ServerStore the executor opens; `resolve` short-circuits
    the lookup with a prepared entry; `default` additionally makes that entry the
    default server. `environ` replaces os.environ for the call.
    """
    executor = RSConnectExecutor.__new__(RSConnectExecutor)
    executor.logger = None
    executor.ctx = None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(api.RSConnectExecutor, "setup_client"))
        if store is not None:
            stack.enter_context(mock.patch("rsconnect.api.ServerStore", return_value=store))
        if default is not None:
            resolve = default
            stack.enter_context(mock.patch.object(ServerStore, "get_default", return_value={"name": default.name}))
        if resolve is not None:
            stack.enter_context(mock.patch.object(ServerStore, "resolve", return_value=resolve))
        if has_cloud_account is not None:
            stack.enter_context(
                mock.patch.object(ServerStore, "has_connect_cloud_account", return_value=has_cloud_account)
            )
        if environ is not None:
            stack.enter_context(mock.patch.dict(os.environ, environ, clear=True))
        executor.setup_remote_server(ctx=ctx, **kwargs)
    return executor


def _cloud_server(**kwargs: Any) -> ConnectCloudServer:
    """Like _setup_remote_server, but returns the resulting ConnectCloudServer."""
    server = _setup_remote_server(**kwargs).remote_server
    assert isinstance(server, ConnectCloudServer)
    return server


def _validate_options(ctx: Optional[click.Context] = None, **overrides: Any) -> None:
    """validate_connection_options with --connect-cloud set and everything else absent."""
    options: Dict[str, Any] = dict(
        url=None,
        api_key=None,
        insecure=False,
        cacert=None,
        account_name=None,
        token=None,
        secret=None,
        connect_cloud=True,
    )
    options.update(overrides)
    return validate_connection_options(ctx=ctx, **options)


def _skip_account_check(test):
    """Stop `add` verifying the account name against GET /accounts.

    Used by tests concerned with storage and CLI wiring rather than with the
    verification itself, which has its own tests.
    """
    patch = mock.patch.object(
        ConnectCloudClient,
        "get_account_by_name",
        return_value={"id": "acct-1", "name": "acme"},
    )
    patch.start()
    test.addCleanup(patch.stop)


class FakeKeyring:
    """A stand-in for the keyring module, backed by a dict."""

    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self):
        self.passwords: Dict[Any, str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def get_password(self, service: str, username: str) -> Optional[str]:
        return self.passwords.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.passwords:
            raise self.errors.PasswordDeleteError()
        del self.passwords[(service, username)]


def _use_fake_keyring(test: unittest.TestCase) -> FakeKeyring:
    """Give one test a working keyring; conftest makes it unavailable by default."""
    fake = FakeKeyring()
    patch = mock.patch.dict(sys.modules, {"keyring": fake, "keyring.errors": fake.errors})
    patch.start()
    test.addCleanup(patch.stop)
    return fake


class CliTestCase(unittest.TestCase):
    """A CliRunner against a temporary server store and a clean environment."""

    skip_account_check = True

    def setUp(self):
        self.runner = CliRunner()
        # Commands write through the module-level store, so point it at a temp dir.
        self.store = ServerStore(base_dir=tempfile.mkdtemp())
        store_patch = mock.patch("rsconnect.main.server_store", self.store)
        store_patch.start()
        self.addCleanup(store_patch.stop)
        env_patch = mock.patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        if self.skip_account_check:
            _skip_account_check(self)

    def _mock_device_login(self):
        patch = mock.patch(
            "rsconnect.connect_cloud.login_with_device_code",
            return_value={"access_token": "at", "refresh_token": "rt"},
        )
        login = patch.start()
        self.addCleanup(patch.stop)
        return login


class TestConnectCloudClient(unittest.TestCase):
    def setUp(self):
        self.server = ConnectCloudServer("acme", access_token="at", refresh_token="rt")
        self.client = ConnectCloudClient(self.server)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_sends_bearer_token(self):
        _register_json(httpretty.GET, f"{API}/users/me", {"id": "u1"})
        with self.client:
            self.client.get_current_user()
        self.assertEqual(httpretty.last_request().headers["Authorization"], "Bearer at")

    def test_a_connection_failure_is_reported_not_crashed(self):
        # A failed connection produces an HTTPResponse holding only the exception;
        # the 401-refresh check must pass it through to handle_bad_response, which
        # raises the "could not connect" error, rather than crash on a missing status.
        from rsconnect.http_support import HTTPResponse, HTTPServer

        failure = HTTPResponse(f"{API}/users/me", exception=OSError("connection refused"))
        self.assertIsNone(failure.status)
        with mock.patch.object(HTTPServer, "request", return_value=failure):
            with self.assertRaises(RSConnectException) as context:
                self.client.get_current_user()
        self.assertIn("Could not connect", str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_accounts_follows_pagination(self):
        _register_pages(
            f"{API}/accounts",
            {"data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}], "total": 3},
            {"data": [{"id": "3", "name": "c"}], "total": 3},
        )
        with self.client:
            accounts = self.client.get_accounts()

        self.assertEqual([a["name"] for a in accounts], ["a", "b", "c"])
        first, second = httpretty.latest_requests()[-2:]
        self.assertEqual(first.querystring["offset"], ["0"])
        self.assertEqual(first.querystring["limit"], ["100"])
        self.assertEqual(first.querystring["has_user_role"], ["true"])
        self.assertEqual(second.querystring["offset"], ["2"])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_accounts_pages_when_total_is_omitted(self):
        # `total` is optional in the response. Treating a missing one as the end of the
        # list returned only the first page, and callers then reported accounts that
        # exist as missing.
        _register_pages(
            f"{API}/accounts",
            {"data": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}]},
            {"data": [{"id": "3", "name": "c"}]},
            {"data": []},
        )
        with self.client:
            accounts = self.client.get_accounts()

        self.assertEqual([a["name"] for a in accounts], ["a", "b", "c"])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_account_by_name_finds_a_later_page_without_a_total(self):
        _register_pages(
            f"{API}/accounts",
            {"data": [{"id": "1", "name": "a", "permissions": ["content:create"]}]},
            {"data": [{"id": "2", "name": "wanted", "permissions": ["content:create"]}]},
            {"data": []},
        )
        with self.client:
            self.assertEqual(self.client.get_account_by_name("wanted")["id"], "2")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_accounts_stops_on_empty_page(self):
        _register_json(httpretty.GET, f"{API}/accounts", {"data": [], "total": 7})
        with self.client:
            self.assertEqual(self.client.get_accounts(), [])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_account_by_name_reports_missing_account(self):
        _register_accounts({"id": "1", "name": "other"})
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_account_by_name("acme")
        self.assertIn("acme", str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_deleted_content_is_surfaced_as_404(self):
        _register_json(httpretty.GET, f"{API}/contents/c1", {"id": "c1", "state": "deleted"})
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_content("c1")
        self.assertEqual(context.exception.status, 404)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_create_content_payload(self):
        _register_json(httpretty.POST, f"{API}/contents", {"id": "c1", "next_revision": {"id": "r1"}})
        with self.client:
            content = self.client.create_content(
                account_id="acct-1",
                title="My App",
                content_type="shiny",
                app_mode="python-shiny",
                primary_file="app.py",
                secrets=[{"name": "FOO", "value": "bar"}],
            )

        self.assertEqual(content["id"], "c1")
        self.assertEqual(
            _json_body(httpretty.last_request()),
            {
                "account_id": "acct-1",
                "title": "My App",
                "next_revision": {
                    "source_type": "bundle",
                    "content_type": "shiny",
                    "app_mode": "python-shiny",
                    "primary_file": "app.py",
                },
                "secrets": [{"name": "FOO", "value": "bar"}],
            },
        )

    def _create_content(self, **kwargs):
        """POST /contents with the always-required arguments; returns the request body."""
        _register_json(httpretty.POST, f"{API}/contents", {"id": "c1", "next_revision": {"id": "r1"}})
        with self.client:
            self.client.create_content(
                account_id="acct-1",
                title="My App",
                content_type="shiny",
                app_mode="python-shiny",
                primary_file="app.py",
                **kwargs,
            )
        return _json_body(httpretty.last_request())

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_create_content_with_access_sets_the_visibility(self):
        self.assertEqual(self._create_content(access="private")["access"], "private")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_create_content_without_access_takes_the_server_default(self):
        self.assertNotIn("access", self._create_content())

    def _update_content(self, **kwargs):
        """PATCH /contents/c1 with the always-required arguments; returns the request body."""
        _register_json(httpretty.PATCH, f"{API}/contents/c1", {"id": "c1", "next_revision": {"id": "r2"}})
        with self.client:
            self.client.update_content(
                "c1", primary_file="app.py", app_mode="python-shiny", content_type="shiny", **kwargs
            )
        return _json_body(httpretty.last_request())

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_sends_the_whole_revision_override_set(self):
        # Omitted overrides keep the content's stored value, so all three go every
        # time or a redeploy of a different kind of content keeps the old ones.
        body = self._update_content()
        self.assertEqual(
            body["revision_overrides"],
            {"primary_file": "app.py", "app_mode": "python-shiny", "content_type": "shiny"},
        )
        self.assertEqual(httpretty.last_request().querystring["new_bundle"], ["true"])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_without_secrets_leaves_them_alone(self):
        # The API replaces the whole secret set with whatever is sent, so a deploy
        # without -E must omit the field entirely or it deletes existing secrets.
        self.assertNotIn("secrets", self._update_content())

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_with_secrets_replaces_them(self):
        body = self._update_content(secrets=[{"name": "FOO", "value": "bar"}])
        self.assertEqual(body["secrets"], [{"name": "FOO", "value": "bar"}])

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_with_title_replaces_it(self):
        self.assertEqual(self._update_content(title="New Title")["title"], "New Title")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_without_title_leaves_it_alone(self):
        self.assertNotIn("title", self._update_content())

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_with_access_sets_the_visibility(self):
        self.assertEqual(self._update_content(access="private")["access"], "private")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_without_access_leaves_the_visibility_alone(self):
        self.assertNotIn("access", self._update_content())

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_update_content_without_new_bundle(self):
        self._update_content(new_bundle=False)
        self.assertNotIn("new_bundle", httpretty.last_request().querystring)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_publish(self):
        httpretty.register_uri(httpretty.POST, f"{API}/contents/c1/publish", body="", status=204)
        with self.client:
            self.client.publish("c1")
        self.assertEqual(httpretty.last_request().path, "/v1/contents/c1/publish")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_revision(self):
        _register_json(httpretty.GET, f"{API}/revisions/r1", {"id": "r1", "status": "building", "publish_result": None})
        with self.client:
            revision = self.client.get_revision("r1")
        self.assertEqual(revision["status"], "building")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_upload_bundle_posts_gzip_without_auth(self):
        upload_url = "https://uploads.example.com/bundle?sig=abc"
        httpretty.register_uri(httpretty.POST, "https://uploads.example.com/bundle", body="", status=200)

        self.client.upload_bundle(upload_url, b"tarball-bytes")

        request = httpretty.last_request()
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.headers["Content-Type"], "application/gzip")
        # The presigned URL carries its own credentials.
        self.assertIsNone(request.headers.get("Authorization"))
        self.assertEqual(request.querystring["sig"], ["abc"])
        self.assertEqual(request.body, b"tarball-bytes")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_upload_bundle_raises_on_failure(self):
        httpretty.register_uri(httpretty.POST, "https://uploads.example.com/bundle", body="nope", status=403)
        with self.assertRaises(RSConnectException):
            self.client.upload_bundle("https://uploads.example.com/bundle", b"x")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_upload_failure_does_not_leak_the_sig_param(self):
        httpretty.register_uri(httpretty.POST, "https://uploads.example.com/bundle", body="nope", status=403)
        with self.assertRaises(RSConnectException) as context:
            self.client.upload_bundle("https://uploads.example.com/bundle?sig=topsecret", b"x")
        self.assertNotIn("topsecret", str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_get_publish_logs_uses_scoped_channel_token(self):
        _register_json(httpretty.POST, f"{API}/authorization", {"token": "channel-token"})
        _register_json(
            httpretty.GET,
            "https://logs.connect.posit.cloud/v1/logs/chan-1",
            {"data": [{"timestamp": 1700000000000000, "level": "INFO", "message": "hi"}]},
        )

        with self.client:
            entries = self.client.get_publish_logs("chan-1")

        self.assertEqual([e["message"] for e in entries], ["hi"])
        auth_request, logs_request = httpretty.latest_requests()[-2:]
        self.assertEqual(
            _json_body(auth_request),
            {"resource_type": "log_channel", "resource_id": "chan-1", "permission": "revision.logs:read"},
        )
        # The logs host takes the scoped channel token, not the account token.
        self.assertEqual(logs_request.headers["Authorization"], "Bearer channel-token")
        self.assertEqual(logs_request.querystring["traversal_direction"], ["backward"])


class TestConnectCloudClientTokenRefresh(unittest.TestCase):
    def _get_user_with_refresh(self, server, mock_target, token_response):
        """Serve a 401 then a 200, driving a request through the refresh-and-retry
        path with the named rsconnect.connect_cloud function mocked; returns the mock."""
        httpretty.register_uri(
            httpretty.GET,
            f"{API}/users/me",
            responses=[httpretty.Response(body="", status=401), _json_response({"id": "u1"})],
        )
        client = ConnectCloudClient(server)
        with mock.patch(f"rsconnect.connect_cloud.{mock_target}") as refresher:
            refresher.return_value = token_response
            with client:
                client.get_current_user()
        return refresher

    def _get_user_with_refresh_failure(self, server, mock_target, error):
        """Serve a 401 with the named rsconnect.connect_cloud function raising `error`.

        Returns the exception that reached the caller, so a test can tell an
        actionable refresh failure from the original 401 passing through.
        """
        httpretty.register_uri(
            httpretty.GET,
            f"{API}/users/me",
            responses=[httpretty.Response(body="", status=401), _json_response({"id": "u1"})],
        )
        client = ConnectCloudClient(server)
        with mock.patch(f"rsconnect.connect_cloud.{mock_target}", side_effect=error):
            with client:
                with self.assertRaises(RSConnectException) as raised:
                    client.get_current_user()
        return raised.exception

    def _save_entry(self, name="cloud", **fields):
        """Persist a saved entry and point the client's write-back store at it."""
        self._base_dir = tempfile.mkdtemp()
        store = ServerStore(base_dir=self._base_dir)
        fields.setdefault("connect_cloud_account_name", "acme")
        store.set(name, API, **fields)
        store.save()
        # The client imports ServerStore inside the function, so patch it at its source.
        patch = mock.patch("rsconnect.metadata.ServerStore", lambda: ServerStore(base_dir=self._base_dir))
        patch.start()
        self.addCleanup(patch.stop)

    def _stored_entry(self):
        entry = ServerStore(base_dir=self._base_dir).get_by_name("cloud")
        assert entry is not None
        return entry

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_401_refreshes_with_refresh_token_and_retries_once(self):
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt")
        refresh = self._get_user_with_refresh(server, "refresh", {"access_token": "fresh", "refresh_token": "rt2"})

        refresh.assert_called_once()
        self.assertEqual(server.access_token, "fresh")
        self.assertEqual(server.refresh_token, "rt2")
        self.assertEqual(httpretty.last_request().headers["Authorization"], "Bearer fresh")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_401_uses_client_credentials_when_available(self):
        server = ConnectCloudServer("acme", access_token="stale", client_id="cid", client_secret="csecret")
        # RFC 6749 4.4.3: no refresh token comes back from a client-credentials grant.
        login = self._get_user_with_refresh(server, "login_client_credentials", {"access_token": "fresh"})

        # The environment comes from the server, not from the ambient env var.
        login.assert_called_once_with("cid", "csecret", "production")
        self.assertEqual(server.access_token, "fresh")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_401_retries_only_once(self):
        httpretty.register_uri(httpretty.GET, f"{API}/users/me", body="", status=401)
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt")
        client = ConnectCloudClient(server)

        with mock.patch("rsconnect.connect_cloud.refresh") as refresh:
            refresh.return_value = {"access_token": "fresh"}
            with client:
                with self.assertRaises(RSConnectException):
                    client.get_current_user()

        refresh.assert_called_once()
        self.assertEqual(len(httpretty.latest_requests()), 2)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_401_without_any_credential_does_not_retry(self):
        httpretty.register_uri(httpretty.GET, f"{API}/users/me", body="", status=401)
        client = ConnectCloudClient(ConnectCloudServer("acme", access_token="stale"))

        with client:
            with self.assertRaises(RSConnectException):
                client.get_current_user()

        self.assertEqual(len(httpretty.latest_requests()), 1)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_refreshed_token_is_written_back_to_the_store(self):
        self._save_entry(connect_cloud_refresh_token="rt")
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="cloud")
        self._get_user_with_refresh(server, "refresh", {"access_token": "fresh", "refresh_token": "rt2"})

        entry = self._stored_entry()
        self.assertEqual(entry["connect_cloud_access_token"], "fresh")
        self.assertEqual(entry["connect_cloud_refresh_token"], "rt2")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_refresh_does_not_graft_environment_credentials_onto_the_entry(self):
        # An interactively created entry has no client credentials. If the shell
        # happens to export CONNECT_CLOUD_CLIENT_ID/SECRET, a refresh may *use*
        # them, but persisting them would silently convert the entry into a
        # service-account credential.
        self._save_entry(connect_cloud_refresh_token="rt")
        server = ConnectCloudServer(
            "acme",
            access_token="stale",
            refresh_token="rt",
            client_id="env-client-id",
            client_secret="env-client-secret",
            server_name="cloud",
        )
        self._get_user_with_refresh(server, "login_client_credentials", {"access_token": "fresh"})

        entry = self._stored_entry()
        self.assertEqual(entry["connect_cloud_access_token"], "fresh")
        self.assertNotIn("connect_cloud_client_id", entry)
        self.assertNotIn("connect_cloud_client_secret", entry)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_refresh_does_not_repoint_the_entry_at_another_account(self):
        # A deploy can publish to a different account on the same login, so the
        # in-memory account is not necessarily the one the entry was saved for.
        self._save_entry(
            connect_cloud_account_name="alice",
            connect_cloud_account_id="acct-alice",
            connect_cloud_refresh_token="rt",
        )
        server = ConnectCloudServer("team-x", access_token="stale", refresh_token="rt", server_name="cloud")
        self._get_user_with_refresh(server, "refresh", {"access_token": "fresh", "refresh_token": "rt2"})

        entry = self._stored_entry()
        self.assertEqual(entry["connect_cloud_account_name"], "alice")
        self.assertEqual(entry["connect_cloud_account_id"], "acct-alice")
        self.assertEqual(entry["connect_cloud_access_token"], "fresh")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_refresh_does_not_persist_client_credentials_from_the_environment(self):
        # --client-id/--client-secret default from the environment and beat the store,
        # so the in-memory credential is not necessarily the saved one either.
        self._save_entry(connect_cloud_client_id="saved-cid", connect_cloud_client_secret="saved-secret")
        server = ConnectCloudServer(
            "acme",
            access_token="stale",
            client_id="env-cid",
            client_secret="env-secret",
            server_name="cloud",
        )
        self._get_user_with_refresh(server, "login_client_credentials", {"access_token": "fresh"})

        entry = self._stored_entry()
        self.assertEqual(entry["connect_cloud_client_id"], "saved-cid")
        self.assertEqual(entry["connect_cloud_client_secret"], "saved-secret")
        self.assertEqual(entry["connect_cloud_access_token"], "fresh")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_an_expired_refresh_token_clears_the_stored_tokens_and_says_how_to_reauthenticate(self):
        self._save_entry(
            connect_cloud_account_id="acct-1",
            connect_cloud_access_token="stale",
            connect_cloud_refresh_token="rt",
        )
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="cloud")
        exception = self._get_user_with_refresh_failure(server, "refresh", InvalidGrantError("token expired"))

        self.assertIn("session has expired", exception.message)
        self.assertIn("rsconnect add --connect-cloud -n cloud -A acme", exception.message)
        entry = self._stored_entry()
        self.assertNotIn("connect_cloud_access_token", entry)
        self.assertNotIn("connect_cloud_refresh_token", entry)
        # Only the tokens go: the entry is still the credential to re-authenticate.
        self.assertEqual(entry["name"], "cloud")
        self.assertEqual(entry["connect_cloud_account_name"], "acme")
        self.assertEqual(entry["connect_cloud_account_id"], "acct-1")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_an_expired_refresh_token_is_reported_without_a_saved_entry(self):
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt")
        with mock.patch("rsconnect.metadata.ServerStore") as store:
            exception = self._get_user_with_refresh_failure(server, "refresh", InvalidGrantError())

        store.assert_not_called()
        self.assertIn("session has expired", exception.message)
        self.assertIn("rsconnect add --connect-cloud -n <nickname> -A acme", exception.message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_the_reauthentication_command_names_the_saved_entrys_account(self):
        # The run may be publishing to another account on the same login;
        # re-adding must not repoint the nickname at it.
        self._save_entry(connect_cloud_account_name="alice", connect_cloud_refresh_token="rt")
        server = ConnectCloudServer("team-x", access_token="stale", refresh_token="rt", server_name="cloud")
        exception = self._get_user_with_refresh_failure(server, "refresh", InvalidGrantError())

        self.assertIn("-A alice", exception.message)
        self.assertNotIn("team-x", exception.message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_the_reauthentication_command_keeps_a_non_production_server(self):
        # Without the URL, the suggested add would authenticate against production.
        staging_api = "https://api.staging.connect.posit.cloud/v1"
        httpretty.register_uri(httpretty.GET, f"{staging_api}/users/me", body="", status=401)
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", url=staging_api)
        client = ConnectCloudClient(server)

        with mock.patch("rsconnect.connect_cloud.refresh", side_effect=InvalidGrantError()):
            with client:
                with self.assertRaises(RSConnectException) as raised:
                    client.get_current_user()

        self.assertIn("-s %s" % staging_api, raised.exception.message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_the_reauthentication_command_quotes_values_that_need_it(self):
        self._save_entry(name="my cloud", connect_cloud_account_name="acme", connect_cloud_refresh_token="rt")
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="my cloud")
        exception = self._get_user_with_refresh_failure(server, "refresh", InvalidGrantError())

        self.assertIn("-n 'my cloud' -A acme", exception.message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_rejected_service_account_secret_is_reported_and_the_entry_is_left_alone(self):
        self._save_entry(
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="csecret",
            connect_cloud_access_token="stale",
        )
        server = ConnectCloudServer(
            "acme", access_token="stale", client_id="cid", client_secret="csecret", server_name="cloud"
        )
        exception = self._get_user_with_refresh_failure(server, "login_client_credentials", InvalidClientError())

        self.assertIn("service account credential was rejected", exception.message)
        self.assertIn("https://login.posit.cloud/identity/credentials", exception.message)
        self.assertIn(
            "rsconnect add --connect-cloud -n cloud -A acme --client-id <id> --client-secret <secret>",
            exception.message,
        )
        entry = self._stored_entry()
        self.assertEqual(entry["connect_cloud_client_secret"], "csecret")
        self.assertEqual(entry["connect_cloud_access_token"], "stale")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_transient_refresh_failure_leaves_the_original_401_and_warns(self):
        self._save_entry(connect_cloud_access_token="stale", connect_cloud_refresh_token="rt")
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="cloud")

        with self.assertLogs("rsconnect", level="WARNING") as captured:
            exception = self._get_user_with_refresh_failure(
                server, "refresh", RSConnectException("Could not connect to https://login.posit.cloud")
            )

        self.assertIn("401", exception.message)
        self.assertIn("token refresh failed", "\n".join(captured.output))
        self.assertEqual(self._stored_entry()["connect_cloud_refresh_token"], "rt")
        self.assertEqual(len(httpretty.latest_requests()), 1)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_rejected_cli_oauth_client_is_not_reported_as_an_expired_session(self):
        # invalid_client on the refresh-token path is about this CLI's own OAuth
        # client, not a credential the user can re-save.
        self._save_entry(connect_cloud_access_token="stale", connect_cloud_refresh_token="rt")
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="cloud")

        with self.assertLogs("rsconnect", level="WARNING"):
            exception = self._get_user_with_refresh_failure(server, "refresh", InvalidClientError())

        self.assertIn("401", exception.message)
        self.assertEqual(self._stored_entry()["connect_cloud_refresh_token"], "rt")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_invalid_grant_from_a_client_credentials_grant_leaves_the_original_401(self):
        server = ConnectCloudServer("acme", access_token="stale", client_id="cid", client_secret="csecret")

        with self.assertLogs("rsconnect", level="WARNING"):
            exception = self._get_user_with_refresh_failure(
                server, "login_client_credentials", InvalidGrantError("no grant")
            )

        self.assertIn("401", exception.message)


class TestConnectCloudStreamBodyRetry(unittest.TestCase):
    """The retry-once skeleton is shared with the Posit Connect client, so a streamed
    body is rewound before the retry here too rather than arriving empty."""

    def _attempt_bodies(self, body: Any, server: Optional[ConnectCloudServer] = None, read: bool = True) -> list[Any]:
        """The body each attempt was given, read out when `read`, with refresh stubbed."""
        client = ConnectCloudClient(server or ConnectCloudServer("acme", access_token="stale", refresh_token="rt"))
        seen: list[Any] = []

        def fake_request(
            _self: Any,
            method: str,
            path: str,
            query_params: Any = None,
            body: Any = None,
            maximum_redirects: int = 5,
            decode_response: bool = True,
            headers: Any = None,
        ) -> Any:
            seen.append(body.read() if read and hasattr(body, "read") else body)
            response = mock.Mock(spec=HTTPResponse)
            response.status = 401 if len(seen) == 1 else 200
            return response

        with mock.patch.object(HTTPServer, "request", fake_request):
            with mock.patch.object(client, "_attempt_token_refresh", return_value=True):
                client.request("POST", "/contents", body=body)
        return seen

    def _retry_bodies(self, body: Any) -> list[Any]:
        return self._attempt_bodies(body)

    def test_a_seekable_stream_is_rewound(self):
        self.assertEqual(self._retry_bodies(io.BytesIO(b"payload")), [b"payload", b"payload"])

    def test_a_stream_is_left_alone_when_there_is_nothing_to_refresh_with(self):
        # No refresh token and no service account credential: nothing can be minted,
        # so the request is sent once and its body is neither buffered nor rewound.
        stream = io.BytesIO(b"payload")
        seen = self._attempt_bodies(stream, server=ConnectCloudServer("acme", access_token="at"), read=False)

        self.assertEqual(seen, [stream])

    def test_a_stream_that_cannot_seek_is_read_into_memory(self):
        class NonSeekableStream(io.RawIOBase):
            def __init__(self, data: bytes):
                self._data = data

            def read(self, size: int = -1) -> bytes:
                data, self._data = self._data, b""
                return data

            def readable(self) -> bool:
                return True

            def seekable(self) -> bool:
                return False

        self.assertEqual(self._retry_bodies(NonSeekableStream(b"payload")), [b"payload", b"payload"])


class TestConnectCloudAdd(CliTestCase):
    """CLI-level tests for `rsconnect add -s connect.posit.cloud`."""

    def test_add_interactive_stores_tokens(self):
        self._mock_device_login()
        result = self.runner.invoke(
            cli, ["add", "--name", "cloud", "--server", "connect.posit.cloud", "--account", "acme"]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            self.store.get_by_name("cloud"),
            {
                "name": "cloud",
                "url": "https://api.connect.posit.cloud/v1",
                "connect_cloud_account_name": "acme",
                "connect_cloud_account_id": "acct-1",
                "connect_cloud_access_token": "at",
                "connect_cloud_refresh_token": "rt",
            },
        )
        self.assertIn("Posit Connect Cloud", result.output)

    def test_add_says_where_the_credentials_went_without_a_keyring(self):
        self._mock_device_login()
        result = self.runner.invoke(cli, ["add", "-n", "cloud", "--connect-cloud", "-A", "acme"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("keyring not available", result.output)

    def test_add_falls_back_to_the_file_when_no_keyring_backend_is_usable(self):
        # A CI runner has keyring installed with nothing behind it, which is the case
        # the servers.json fallback exists for; it used to abort the command instead.
        self._mock_device_login()
        with failing_keyring():
            result = self.runner.invoke(cli, ["add", "-n", "cloud", "--connect-cloud", "-A", "acme"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("keyring not available", result.output)
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertEqual(entry["connect_cloud_access_token"], "at")
        self.assertEqual(entry["connect_cloud_refresh_token"], "rt")

    def test_a_deploy_reads_the_credentials_back_without_a_keyring_backend(self):
        self._mock_device_login()
        with failing_keyring():
            self.runner.invoke(cli, ["add", "-n", "cloud", "--connect-cloud", "-A", "acme"])
            data = self.store.resolve("cloud", None)

        self.assertEqual(data.connect_cloud_access_token, "at")
        self.assertEqual(data.connect_cloud_refresh_token, "rt")

    def test_a_stale_ca_certificate_env_var_does_not_block_add(self):
        # CONNECT_CA_CERTIFICATE pointing at a missing file used to fail at CLI
        # parsing (click Path(exists=True)), before the Cloud target was known.
        self._mock_device_login()
        with mock.patch.dict(os.environ, {"CONNECT_CA_CERTIFICATE": "/nonexistent/ca.pem"}):
            result = self.runner.invoke(cli, ["add", "-n", "cloud", "--connect-cloud", "-A", "acme"])

        self.assertEqual(result.exit_code, 0, result.output)

    def test_add_explicit_environment_url_pins_the_environment(self):
        # An explicitly typed staging API URL must authenticate against staging's
        # auth host even when CONNECT_CLOUD_ENVIRONMENT is unset; previously the
        # URL was replaced with the pseudo-name and the ambient environment won.
        login = self._mock_device_login()
        result = self.runner.invoke(
            cli,
            ["add", "-n", "cc", "-s", "https://api.staging.connect.posit.cloud/v1", "-A", "acme"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = login.call_args.kwargs
        self.assertEqual(kwargs["url"], "https://login.staging.posit.cloud")
        self.assertEqual(kwargs["client_id"], "rsconnect-python-staging")
        self.assertEqual(self.store.get_by_name("cc")["url"], "https://api.staging.connect.posit.cloud/v1")

    def test_add_flag_discards_a_stray_connect_server(self):
        # A CONNECT_SERVER pointing at some other target must not be stored as
        # the Connect Cloud URL when --connect-cloud selects the target.
        self._mock_device_login()
        result = self.runner.invoke(
            cli,
            ["add", "-n", "cc", "--connect-cloud", "-A", "acme"],
            env={"CONNECT_SERVER": "https://connect.example.com"},
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.store.get_by_name("cc")["url"], "https://api.connect.posit.cloud/v1")

    def test_add_flag_discards_an_environment_sourced_cloud_url(self):
        # --connect-cloud beats CONNECT_SERVER even when that variable holds a
        # Connect Cloud URL for another environment; only a *typed* -s pins one.
        login = self._mock_device_login()
        result = self.runner.invoke(
            cli,
            ["add", "-n", "cc", "--connect-cloud", "-A", "acme"],
            env={"CONNECT_SERVER": "https://api.staging.connect.posit.cloud/v1"},
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.store.get_by_name("cc")["url"], "https://api.connect.posit.cloud/v1")
        self.assertEqual(login.call_args.kwargs["url"], "https://login.posit.cloud")

    def test_add_client_credentials_stores_credentials(self):
        with mock.patch("rsconnect.connect_cloud.request_client_credentials_token") as request:
            request.return_value = {"access_token": "at"}
            result = self.runner.invoke(
                cli,
                [
                    "add",
                    "--name",
                    "cloud",
                    "--server",
                    "connect.posit.cloud",
                    "--account",
                    "acme",
                    "--client-id",
                    "cid",
                    "--client-secret",
                    "csecret",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertEqual(entry["connect_cloud_client_id"], "cid")
        self.assertEqual(entry["connect_cloud_client_secret"], "csecret")
        self.assertEqual(entry["connect_cloud_access_token"], "at")
        # RFC 6749 4.4.3: no refresh token is issued for client credentials.
        self.assertNotIn("connect_cloud_refresh_token", entry)

    def test_add_requires_account(self):
        result = self.runner.invoke(cli, ["add", "--name", "cloud", "--server", "connect.posit.cloud"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("-A/--account is required for Posit Connect Cloud", result.output)

    def test_add_rejects_shinyapps_credentials(self):
        result = self.runner.invoke(
            cli,
            [
                "add",
                "--name",
                "cloud",
                "--server",
                "connect.posit.cloud",
                "--account",
                "acme",
                "--token",
                "tok",
                "--secret",
                "sec",
            ],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("shinyapps.io options", result.output)

    def test_add_rejects_connect_api_key(self):
        result = self.runner.invoke(
            cli,
            ["add", "--name", "cloud", "--server", "connect.posit.cloud", "--account", "acme", "--api-key", "key"],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("may not be passed", result.output)

    def test_add_rejects_half_a_service_account_credential(self):
        result = self.runner.invoke(
            cli,
            [
                "add",
                "--name",
                "cloud",
                "--server",
                "connect.posit.cloud",
                "--account",
                "acme",
                "--client-id",
                "cid",
            ],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("--client-id and --client-secret must be provided together", result.output)

    def test_client_credentials_rejected_without_connect_cloud_server(self):
        result = self.runner.invoke(
            cli,
            [
                "add",
                "--name",
                "other",
                "--server",
                "https://connect.example.com",
                "--api-key",
                "key",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
            ],
        )
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("require --connect-cloud or -s/--server connect.posit.cloud", result.output)

    def test_exported_client_credentials_do_not_block_another_target(self):
        # CI is told to export these, and they are unused for a non-cloud target, so
        # they must not conflict with an explicitly named server. Only a typed
        # credential does (see the test above).
        with mock.patch.dict(
            os.environ,
            {"CONNECT_CLOUD_CLIENT_ID": "cid", "CONNECT_CLOUD_CLIENT_SECRET": "csecret"},
        ):
            with mock.patch("rsconnect.main.test_server") as test_server:
                test_server.return_value = (
                    api.RSConnectServer("https://connect.example.com", "key"),
                    None,
                )
                with mock.patch("rsconnect.main.test_api_key", return_value="user"):
                    result = self.runner.invoke(
                        cli,
                        ["add", "--name", "other", "--server", "https://connect.example.com", "--api-key", "key"],
                    )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("require --connect-cloud", result.output)

    def test_add_honors_selected_environment(self):
        self._mock_device_login()
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}):
            result = self.runner.invoke(
                cli, ["add", "--name", "cloud", "--server", "connect.posit.cloud", "--account", "acme"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertEqual(entry["url"], "https://api.staging.connect.posit.cloud/v1")


class TestConnectCloudEnvironmentIsPinnedToTheServer(unittest.TestCase):
    """A saved server keeps its own environment, whatever the env var says later."""

    def test_environment_for_url(self):
        self.assertEqual(connect_cloud.environment_for_url("https://api.connect.posit.cloud/v1"), "production")
        self.assertEqual(connect_cloud.environment_for_url("https://api.staging.connect.posit.cloud/v1"), "staging")
        self.assertEqual(connect_cloud.environment_for_url("https://api.dev.connect.posit.cloud/v1"), "development")
        # A URL saved before resolve_url canonicalized still maps to its environment.
        self.assertEqual(connect_cloud.environment_for_url("https://api.staging.connect.posit.cloud/v1/"), "staging")

    def test_unknown_url_falls_back_to_the_selected_environment(self):
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}, clear=True):
            self.assertEqual(connect_cloud.environment_for_url("https://example.com"), "staging")

    def test_server_records_its_environment(self):
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}, clear=True):
            server = ConnectCloudServer("acme", url=connect_cloud.SERVER_NAME)
        self.assertEqual(server.environment, "staging")
        self.assertEqual(server.url, "https://api.staging.connect.posit.cloud/v1")

    def test_saved_staging_server_ignores_a_later_production_env_var(self):
        # The bug this guards: a staging server whose content URLs, logs host and
        # token refresh all silently pointed at production.
        server = ConnectCloudServer("acme", url="https://api.staging.connect.posit.cloud/v1")
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "production"}):
            self.assertEqual(server.environment, "staging")
            self.assertEqual(server.urls().ui, "https://staging.connect.posit.cloud")
            self.assertEqual(server.urls().auth, "https://login.staging.posit.cloud")
            self.assertEqual(server.urls().logs, "https://logs.staging.connect.posit.cloud/v1")

    def test_content_url_uses_the_servers_environment(self):
        server = ConnectCloudServer("acme", url="https://api.staging.connect.posit.cloud/v1")
        client = mock.Mock(spec=ConnectCloudClient)
        client.get_accounts.return_value = [{"id": "acct-1", "name": "acme"}]
        service = ConnectCloudService(client, server)

        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "production"}):
            url = service.content_url("c1", "acct-1")

        self.assertEqual(url, "https://staging.connect.posit.cloud/acme/content/c1")

    def test_executor_keeps_an_explicit_environment_url_with_the_flag(self):
        # --connect-cloud plus a typed staging API URL must stay on staging, not
        # be replaced by the pseudo-name and follow CONNECT_CLOUD_ENVIRONMENT.
        server = _cloud_server(
            environ={},
            url="https://api.staging.connect.posit.cloud/v1",
            account_name="acme",
            use_connect_cloud=True,
        )
        self.assertEqual(server.url, "https://api.staging.connect.posit.cloud/v1")
        self.assertEqual(server.environment, "staging")

    def test_executor_flag_overrides_an_environment_sourced_cloud_url(self):
        # A staging URL arriving via CONNECT_SERVER must not survive the flag;
        # only a typed -s does (previous test).
        server = _cloud_server(
            ctx=_ctx(server=ENV),
            environ={},
            url="https://api.staging.connect.posit.cloud/v1",
            account_name="acme",
            use_connect_cloud=True,
        )
        self.assertEqual(server.url, "https://api.connect.posit.cloud/v1")
        self.assertEqual(server.environment, "production")

    def test_typed_connect_options_are_rejected_for_a_saved_cloud_nickname(self):
        # -n resolves to a Connect Cloud entry only after the store lookup, so
        # incompatible options must be re-checked then, not silently dropped.
        entry = _cloud_entry(connect_cloud_access_token="at")
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(resolve=entry, name="cloud", api_key="typed-key")
        self.assertIn("may not be passed alongside Posit Connect Cloud", str(context.exception))

    def test_env_sourced_connect_options_are_ignored_for_a_saved_cloud_nickname(self):
        # A CONNECT_API_KEY exported for another target is just the environment.
        entry = _cloud_entry(connect_cloud_access_token="at")
        _cloud_server(ctx=_ctx(api_key=ENV), resolve=entry, name="cloud", api_key="env-key")

    def test_a_half_supplied_credential_never_mixes_with_the_entrys_pair(self):
        # CONNECT_CLOUD_CLIENT_ID exported without its secret must not combine
        # with the entry's stored secret into a pair that never existed; the
        # stored pair wins and the lone half is ignored.
        entry = _cloud_entry(
            connect_cloud_client_id="stored-id",
            connect_cloud_client_secret="stored-secret",
            connect_cloud_access_token="saved-at",
            connect_cloud_refresh_token="saved-rt",
        )
        server = _cloud_server(ctx=_ctx(client_id=ENV), resolve=entry, name="cloud", client_id="env-id-alone")

        self.assertEqual(server.client_id, "stored-id")
        self.assertEqual(server.client_secret, "stored-secret")
        self.assertEqual(server.access_token, "saved-at")
        self.assertEqual(server.server_name, "cloud")

    def test_supplied_credentials_that_differ_from_the_entry_are_a_new_identity(self):
        # Explicit --client-id/--client-secret that differ from the saved entry's
        # must not ride on the entry's tokens (they belong to whoever created the
        # entry) and must not write back to it afterwards.
        entry = _cloud_entry(connect_cloud_access_token="saved-at", connect_cloud_refresh_token="saved-rt")
        # Typed --client-id with -n is rejected by validation, so credentials
        # alongside a nickname can only arrive from the environment - model that.
        server = _cloud_server(
            ctx=_ctx(client_id=ENV, client_secret=ENV),
            resolve=entry,
            name="cloud",
            client_id="other-id",
            client_secret="other-secret",
        )

        self.assertIsNone(server.access_token)
        self.assertIsNone(server.refresh_token)
        self.assertIsNone(server.server_name)
        self.assertEqual(server.client_id, "other-id")

    def test_matching_credentials_keep_the_entrys_tokens(self):
        entry = _cloud_entry(
            connect_cloud_client_id="same-id",
            connect_cloud_client_secret="same-secret",
            connect_cloud_access_token="saved-at",
            connect_cloud_refresh_token="saved-rt",
        )
        server = _cloud_server(
            ctx=_ctx(client_id=ENV, client_secret=ENV),
            resolve=entry,
            name="cloud",
            client_id="same-id",
            client_secret="same-secret",
        )

        self.assertEqual(server.access_token, "saved-at")
        self.assertEqual(server.server_name, "cloud")

    def test_refresh_uses_the_servers_environment(self):
        server = ConnectCloudServer(
            "acme", access_token="stale", refresh_token="rt", url="https://api.staging.connect.posit.cloud/v1"
        )
        client = ConnectCloudClient(server)
        with mock.patch("rsconnect.connect_cloud.refresh") as refresh:
            refresh.return_value = {"access_token": "fresh"}
            with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "production"}):
                client._attempt_token_refresh()
        refresh.assert_called_once_with("rt", "staging")


class TestEnvironmentSourcedAccountIsScopedToItsTarget(unittest.TestCase):
    """-A/--account is shared with shinyapps.io, whose environment variable is
    SHINYAPPS_ACCOUNT. A value exported for shinyapps.io CI must not retarget a
    Connect Cloud deploy; Connect Cloud's own variable is CONNECT_CLOUD_ACCOUNT."""

    def _server(self, ctx, account_name, environ, saved=True):
        return _cloud_server(
            ctx=ctx,
            resolve=_cloud_entry(connect_cloud_access_token="at"),
            has_cloud_account=saved,
            environ=environ,
            url="connect.posit.cloud",
            account_name=account_name,
        )

    def test_env_sourced_shinyapps_account_does_not_retarget_a_cloud_deploy(self):
        server = self._server(_ctx(account=ENV), "shinyapps-acct", {"SHINYAPPS_ACCOUNT": "shinyapps-acct"})
        self.assertEqual(server.account_name, "acme")

    def test_connect_cloud_account_env_var_selects_the_account(self):
        server = self._server(_ctx(account=ENV), "shinyapps-acct", {"CONNECT_CLOUD_ACCOUNT": "cloud-acct"})
        self.assertEqual(server.account_name, "cloud-acct")

    def test_a_typed_account_still_wins(self):
        server = self._server(_ctx(account=TYPED), "typed-acct", {"CONNECT_CLOUD_ACCOUNT": "cloud-acct"})
        self.assertEqual(server.account_name, "typed-acct")

    def test_shinyapps_account_alone_does_not_satisfy_the_account_requirement(self):
        with self.assertRaises(RSConnectException) as context:
            self._server(_ctx(account=ENV), "shinyapps-acct", {"SHINYAPPS_ACCOUNT": "shinyapps-acct"}, saved=False)
        self.assertIn("-A/--account is required", str(context.exception))

    def test_env_shinyapps_credentials_do_not_block_or_merge_into_a_nickname_deploy(self):
        # SHINYAPPS_* exported for CI elsewhere used to make any -n deploy fail
        # with a name/option conflict; and once allowed through, the values must
        # not merge into the resolved entry (an env account would retarget a
        # Connect Cloud nickname).
        server = _cloud_server(
            ctx=_ctx(account=ENV, token=ENV, secret=ENV),
            resolve=_cloud_entry(connect_cloud_access_token="at"),
            environ={
                "SHINYAPPS_ACCOUNT": "shinyapps-acct",
                "SHINYAPPS_TOKEN": "shinyapps-token",
                "SHINYAPPS_SECRET": "shinyapps-secret",
            },
            name="cloud",
            account_name="shinyapps-acct",
            token="shinyapps-token",
            secret="shinyapps-secret",
        )
        self.assertEqual(server.account_name, "acme")

    def test_a_typed_shinyapps_token_still_conflicts_with_a_nickname(self):
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(ctx=_ctx(token=TYPED), name="cloud", token="typed-token")
        self.assertIn("cannot be specified in conjunction", str(context.exception))


class TestNicknameWithATypedAccount(unittest.TestCase):
    """-A alongside -n is only meaningful for Connect Cloud, where the nickname
    names the credential and -A the account to publish to. For every other target
    the nickname already names the account, so the combination is a conflict --
    judged after resolution, since only the store knows which target it is."""

    def test_a_typed_account_selects_the_target_account_of_a_cloud_nickname(self):
        server = _cloud_server(
            ctx=_ctx(account=TYPED),
            resolve=_cloud_entry(connect_cloud_account_id="acct-acme", connect_cloud_access_token="at"),
            name="cloud",
            account_name="typed-acct",
        )
        self.assertEqual(server.account_name, "typed-acct")
        self.assertEqual(server.access_token, "at")
        # The saved id belongs to the saved account, so publishing elsewhere resolves
        # the name against the server instead.
        self.assertIsNone(server.account_id)

    def test_a_typed_account_still_conflicts_with_a_connect_nickname(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key")
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(ctx=_ctx(account=TYPED), store=store, name="prod", account_name="typed-acct")
        self.assertIn("cannot be specified in conjunction", str(context.exception))

    def test_a_typed_account_cannot_borrow_a_shinyapps_nicknames_credentials(self):
        # The nickname's token and secret belong to its own account, so a typed -A
        # must not deploy somewhere else with them.
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(
                ctx=_ctx(account=TYPED),
                resolve=ServerData(
                    "shiny",
                    "https://api.shinyapps.io",
                    True,
                    account_name="saved-acct",
                    token="saved-token",
                    secret="saved-secret",
                ),
                name="shiny",
                account_name="other-acct",
            )
        self.assertIn("cannot be specified in conjunction", str(context.exception))

    def test_connect_options_with_a_cloud_nickname_are_reported_against_connect_cloud(self):
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(
                ctx=_ctx(account=TYPED, insecure=TYPED),
                resolve=_cloud_entry(connect_cloud_access_token="at"),
                name="cloud",
                account_name="typed-acct",
                insecure=True,
            )
        self.assertIn("alongside Posit Connect Cloud", str(context.exception))


class TestDefaultServerAccountDeferral(unittest.TestCase):
    """With a default server, -A cannot be judged until the default resolves:
    it selects the Connect Cloud account when the default is Cloud, and is the
    incomplete shinyapps.io credential set otherwise."""

    _connect_entry = ServerData(
        "production",
        "https://connect.example.com",
        True,
        api_key="stored-key",
    )
    _shinyapps_entry = ServerData(
        "shiny",
        "https://api.shinyapps.io",
        True,
        account_name="stored-acct",
        token="stored-token",
        secret="stored-secret",
    )

    def _default_deploy(self, entry, ctx=None, environ=None, **kwargs):
        return _setup_remote_server(ctx=ctx, default=entry, environ=environ or {}, **kwargs)

    def test_a_typed_account_selects_the_cloud_account_on_the_default_login(self):
        executor = self._default_deploy(_cloud_entry(connect_cloud_access_token="at"), account_name="other-acct")
        assert isinstance(executor.remote_server, ConnectCloudServer)
        self.assertEqual(executor.remote_server.account_name, "other-acct")

    def test_connect_cloud_account_env_var_applies_to_the_default_server(self):
        executor = self._default_deploy(
            _cloud_entry(connect_cloud_access_token="at"), environ={"CONNECT_CLOUD_ACCOUNT": "env-acct"}
        )
        assert isinstance(executor.remote_server, ConnectCloudServer)
        self.assertEqual(executor.remote_server.account_name, "env-acct")

    def test_env_shinyapps_account_does_not_retarget_the_default_cloud_server(self):
        executor = self._default_deploy(
            _cloud_entry(connect_cloud_access_token="at"),
            ctx=_ctx(account=ENV),
            environ={"SHINYAPPS_ACCOUNT": "shinyapps-acct"},
            account_name="shinyapps-acct",
        )
        assert isinstance(executor.remote_server, ConnectCloudServer)
        self.assertEqual(executor.remote_server.account_name, "acme")

    def test_a_lone_account_is_still_rejected_when_the_default_is_connect(self):
        with self.assertRaises(RSConnectException) as context:
            self._default_deploy(self._connect_entry, account_name="some-acct")
        self.assertIn("must all be provided", str(context.exception))

    def test_a_lone_account_cannot_borrow_a_default_shinyapps_entrys_credentials(self):
        # The deferred all-or-nothing check judges what the user supplied; the
        # default entry's token and secret must not combine with a typed -A to
        # deploy a different account with borrowed credentials.
        with self.assertRaises(RSConnectException) as context:
            self._default_deploy(self._shinyapps_entry, account_name="other-acct")
        self.assertIn("must all be provided", str(context.exception))

    def test_an_env_api_key_does_not_conflict_with_a_typed_account(self):
        # CONNECT_API_KEY exported for a Connect server elsewhere is just the
        # environment; with a default Cloud server, -A selects the account.
        executor = self._default_deploy(
            _cloud_entry(connect_cloud_access_token="at"),
            ctx=_ctx(api_key=ENV),
            account_name="other-acct",
            api_key="env-key",
        )
        assert isinstance(executor.remote_server, ConnectCloudServer)
        self.assertEqual(executor.remote_server.account_name, "other-acct")

    def test_an_exported_ca_certificate_does_not_fail_a_cloud_deploy(self):
        # CONNECT_CA_CERTIFICATE exported for a Connect server is only read for
        # non-Cloud targets, so an unreadable path cannot block a Cloud deploy.
        executor = self._default_deploy(
            _cloud_entry(connect_cloud_access_token="at"), ctx=_ctx(cacert=ENV), cacert="/nonexistent/ca.pem"
        )
        assert isinstance(executor.remote_server, ConnectCloudServer)

    def test_the_certificate_is_still_read_for_a_connect_deploy(self):
        with mock.patch.object(api, "read_certificate_file", return_value=b"cert-bytes") as read:
            executor = self._default_deploy(self._connect_entry, cacert="/etc/ca.pem", api_key="typed-key")
        read.assert_called_once_with("/etc/ca.pem")
        assert isinstance(executor.remote_server, api.RSConnectServer)
        self.assertEqual(executor.remote_server.ca_data, b"cert-bytes")


class TestConnectCloudAccountVerification(unittest.TestCase):
    def setUp(self):
        self.client = ConnectCloudClient(ConnectCloudServer("acme", access_token="at"))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_unknown_account_lists_the_available_ones(self):
        _register_accounts({"id": "1", "name": "alpha"}, {"id": "2", "name": "beta"})
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_account_by_name("typo")

        message = str(context.exception)
        self.assertIn('No Posit Connect Cloud account named "typo"', message)
        self.assertIn("alpha, beta", message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_no_accounts_at_all(self):
        _register_accounts()
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_account_by_name("anything")
        self.assertIn("do not have publish access to any", str(context.exception))

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_view_only_account_is_rejected(self):
        # Without this the failure surfaces later as a raw error from POST /contents.
        _register_accounts({"id": "1", "name": "acme", "permissions": ["content:read"]})
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_account_by_name("acme")

        message = str(context.exception)
        self.assertIn('You have access to the Posit Connect Cloud account "acme"', message)
        self.assertIn("do not have permission to publish to it", message)

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_a_publishable_account_resolves(self):
        _register_accounts({"id": "1", "name": "acme", "permissions": ["content:read", "content:create"]})
        with self.client:
            self.assertEqual(self.client.get_account_by_name("acme")["id"], "1")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_an_account_without_a_permissions_field_resolves(self):
        # The field is optional, and the server enforces the permission regardless,
        # so its absence must not deny a publish the server would accept.
        _register_accounts({"id": "1", "name": "acme"})
        with self.client:
            self.assertEqual(self.client.get_account_by_name("acme")["id"], "1")

    @httpretty.activate(verbose=True, allow_net_connect=False)
    def test_the_suggestions_exclude_accounts_that_cannot_publish(self):
        # The list is effectively the set of valid -A values.
        _register_accounts(
            {"id": "1", "name": "publishable", "permissions": ["content:create"]},
            {"id": "2", "name": "view-only", "permissions": ["content:read"]},
            {"id": "3", "name": "unknown-permissions"},
        )
        with self.client:
            with self.assertRaises(RSConnectException) as context:
                self.client.get_account_by_name("typo")

        message = str(context.exception)
        self.assertIn("You can publish to: publishable, unknown-permissions.", message)
        self.assertNotIn("view-only", message)


class TestConnectCloudAddVerifiesAccount(CliTestCase):
    skip_account_check = False

    def _add(self, account):
        with mock.patch("rsconnect.connect_cloud.request_client_credentials_token") as request:
            request.return_value = {"access_token": "at"}
            return self.runner.invoke(
                cli,
                [
                    "add",
                    "--name",
                    "cloud",
                    "--connect-cloud",
                    "--account",
                    account,
                    "--client-id",
                    "cid",
                    "--client-secret",
                    "csecret",
                ],
            )

    def test_a_bad_account_name_fails_at_add_time(self):
        # A token proves the credentials are good but says nothing about the
        # account, so a typo used to surface only at deploy time.
        with mock.patch.object(
            ConnectCloudClient,
            "get_accounts",
            return_value=[{"id": "1", "name": "real-account"}],
        ):
            result = self._add("typo-account")

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("real-account", result.output)
        self.assertIsNone(self.store.get_by_name("cloud"), "nothing should be stored on failure")

    def test_a_good_account_name_is_stored(self):
        with mock.patch.object(
            ConnectCloudClient,
            "get_accounts",
            return_value=[{"id": "1", "name": "acme"}],
        ):
            result = self._add("acme")

        self.assertEqual(result.exit_code, 0, result.output)
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertEqual(entry["connect_cloud_account_name"], "acme")

    def test_a_view_only_account_fails_at_add_time(self):
        with mock.patch.object(
            ConnectCloudClient,
            "get_accounts",
            return_value=[{"id": "1", "name": "acme", "permissions": ["content:read"]}],
        ):
            result = self._add("acme")

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("do not have permission to publish", result.output)
        self.assertIsNone(self.store.get_by_name("cloud"), "nothing should be stored on failure")


class TestConnectCloudAppModes(unittest.TestCase):
    def test_supported_modes_map_to_content_types(self):
        cases = {
            AppModes.JUPYTER_NOTEBOOK: "jupyter",
            AppModes.PYTHON_SHINY: "shiny",
            AppModes.SHINY: "shiny",
            AppModes.STREAMLIT_APP: "streamlit",
            AppModes.DASH_APP: "dash",
            AppModes.BOKEH_APP: "bokeh",
            AppModes.STATIC_QUARTO: "quarto",
            AppModes.SHINY_QUARTO: "quarto",
            AppModes.RMD: "rmarkdown",
            AppModes.SHINY_RMD: "rmarkdown",
            AppModes.STATIC: "static",
        }
        for mode, expected in cases.items():
            self.assertEqual(AppModes.get_connect_cloud_content_type(mode), expected, mode.name())
            self.assertTrue(AppModes.supported_by_connect_cloud(mode), mode.name())

    def test_unsupported_modes(self):
        # Flask/FastAPI/Plumber were removed from the backend's content type enum;
        # Gradio, Panel, Voila, TensorFlow and Node.js were never there.
        for mode in (
            AppModes.PYTHON_API,
            AppModes.PYTHON_FASTAPI,
            AppModes.PLUMBER,
            AppModes.PYTHON_GRADIO,
            AppModes.PYTHON_PANEL,
            AppModes.JUPYTER_VOILA,
            AppModes.TENSORFLOW,
            AppModes.NODE_JS,
        ):
            self.assertIsNone(AppModes.get_connect_cloud_content_type(mode), mode.name())
            self.assertFalse(AppModes.supported_by_connect_cloud(mode), mode.name())

    def test_content_types_are_the_eight_the_api_accepts(self):
        self.assertEqual(
            sorted(set(AppModes._connect_cloud_content_types.values())),
            ["bokeh", "dash", "jupyter", "quarto", "rmarkdown", "shiny", "static", "streamlit"],
        )


def _bundle_with_manifest(metadata, files=None, manifest_path="manifest.json"):
    """A minimal gzipped bundle containing just a manifest.json."""
    body = {"version": 1, "metadata": metadata}
    if files is not None:
        body["files"] = {name: {"checksum": "0"} for name in files}
    manifest = json.dumps(body).encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buffer) as tar:
        info = tarfile.TarInfo(manifest_path)
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
    buffer.seek(0)
    return buffer


class TestConnectCloudPrimaryFile(unittest.TestCase):
    def _executor(self, bundle, path="/deploys/some-project", quarto_inputs=None):
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.bundle = bundle
        executor.path = path
        executor.quarto_inputs = quarto_inputs
        return executor

    def test_reads_entrypoint_from_manifest(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "python-shiny", "entrypoint": "app.py"}))
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app.py")

    def test_module_entrypoint_resolves_to_the_file(self):
        # Python app manifests carry "module" or "module:object" (bundle.validate_entry_point),
        # but Connect Cloud fails the publish unless it is given the file itself.
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-streamlit", "entrypoint": "app1"},
                files=["app1.py", "requirements.txt", "data.csv"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app1.py")

    def test_module_object_entrypoint_resolves_to_the_file(self):
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-api", "entrypoint": "app:app"},
                files=["app.py", "requirements.txt"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app.py")

    def test_dotted_module_entrypoint_resolves_to_the_nested_file(self):
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-dash", "entrypoint": "src.app"},
                files=["src/app.py", "requirements.txt"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "src/app.py")

    def test_entrypoint_that_is_a_listed_file_is_used_as_is(self):
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "jupyter-static", "entrypoint": "notebook.ipynb"},
                files=["notebook.ipynb", "requirements.txt"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "notebook.ipynb")

    def test_r_shiny_manifest_without_entrypoint_infers_app_r(self):
        # R manifests record no entrypoint for Shiny content; Connect infers the
        # conventional file names, so the fallback must too.
        executor = self._executor(_bundle_with_manifest({"appmode": "shiny"}, files=["app.R", "data.csv"]))
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app.R")

    def test_r_shiny_manifest_without_entrypoint_infers_server_r(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "shiny"}, files=["server.R", "ui.R"]))
        self.assertEqual(executor.primary_file_for_connect_cloud(), "server.R")

    def test_shiny_express_entrypoint_resolves_to_the_source_file(self):
        # Express manifests wrap the file in a synthetic module entrypoint with
        # the file name escaped to a variable name (app.py -> app_2e_py).
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-shiny", "entrypoint": "shiny.express.app:app_2e_py"},
                files=["app.py", "requirements.txt"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app.py")

    def test_shiny_express_entrypoint_with_escaped_underscores(self):
        from rsconnect.shiny_express import escape_to_var_name

        entrypoint = "shiny.express.app:" + escape_to_var_name("my_app.py")
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-shiny", "entrypoint": entrypoint},
                files=["my_app.py"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "my_app.py")

    def test_quarto_manifest_without_entrypoint_prefers_index_qmd(self):
        # Generated Quarto manifests record no entrypoint at all.
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["about.qmd", "index.qmd", "_quarto.yml"])
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "index.qmd")

    def test_quarto_manifest_with_a_single_document_uses_it(self):
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-shiny"}, files=["report.qmd", "requirements.txt"])
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "report.qmd")

    def test_quarto_standalone_deploy_uses_its_own_file(self):
        # A single-document deploy knows its file from the deploy path, whatever
        # the format — Quarto renders .ipynb and .Rmd too, not just .qmd.
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "quarto-static"},
                files=["analysis.ipynb", "helper.qmd", "requirements.txt"],
            ),
            path="/deploys/project/analysis.ipynb",
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "analysis.ipynb")

    def test_quarto_project_with_index_ipynb(self):
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["index.ipynb", "requirements.txt"])
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "index.ipynb")

    def test_quarto_manifest_with_a_single_rmd_input(self):
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["report.Rmd", "README.md"])
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "report.Rmd")

    def test_quarto_project_with_a_sole_markdown_input(self):
        # Quarto renders plain .md; a README does not count as the document.
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["notes.md", "README.md", "_quarto.yml"])
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "notes.md")

    def test_quarto_project_with_only_a_readme_is_still_ambiguous(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "quarto-static"}, files=["README.md"]))
        with self.assertRaises(RSConnectException):
            executor.primary_file_for_connect_cloud()

    def test_ambiguous_quarto_manifest_is_reported(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "quarto-static"}, files=["a.qmd", "b.qmd"]))
        with self.assertRaises(RSConnectException) as context:
            executor.primary_file_for_connect_cloud()
        self.assertIn("primary file", str(context.exception))

    def test_multi_input_project_without_index_uses_quarto_render_order(self):
        # A directory project with several documents and no index.* used to fail;
        # `quarto inspect` reports the inputs in render order, so the first one wins.
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["a.qmd", "b.qmd", "zebra.qmd"]),
            quarto_inputs=["zebra.qmd", "a.qmd", "b.qmd"],
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "zebra.qmd")

    def test_render_order_inputs_missing_from_the_bundle_are_skipped(self):
        # An input excluded from the bundle (e.g. via --exclude) cannot be the
        # primary file Connect Cloud is told about.
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["a.qmd", "b.qmd"]),
            quarto_inputs=["excluded.qmd", "b.qmd", "a.qmd"],
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "b.qmd")

    def test_render_order_resolves_several_markdown_inputs(self):
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["notes.md", "extra.md", "_quarto.yml"]),
            quarto_inputs=["notes.md", "extra.md"],
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "notes.md")

    def test_an_index_file_still_outranks_the_render_order(self):
        executor = self._executor(
            _bundle_with_manifest({"appmode": "quarto-static"}, files=["about.qmd", "index.qmd"]),
            quarto_inputs=["about.qmd", "index.qmd"],
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "index.qmd")

    def test_unresolvable_entrypoint_is_returned_unchanged(self):
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-shiny", "entrypoint": "mystery"},
                files=["other.py"],
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "mystery")

    def test_falls_back_to_primary_rmd_and_html(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "rmd-static", "primary_rmd": "report.Rmd"}))
        self.assertEqual(executor.primary_file_for_connect_cloud(), "report.Rmd")

        executor = self._executor(_bundle_with_manifest({"appmode": "static", "primary_html": "index.html"}))
        self.assertEqual(executor.primary_file_for_connect_cloud(), "index.html")

    def test_leaves_the_bundle_readable(self):
        bundle = _bundle_with_manifest({"appmode": "python-shiny", "entrypoint": "app.py"})
        position = bundle.tell()
        executor = self._executor(bundle)
        executor.primary_file_for_connect_cloud()
        self.assertEqual(bundle.tell(), position)
        self.assertTrue(bundle.read())

    def test_manifest_nested_in_a_single_directory_is_found(self):
        # Downloaded bundles may store everything under one top-level directory,
        # the same layout read_bundle_manifest tolerates.
        executor = self._executor(
            _bundle_with_manifest(
                {"appmode": "python-shiny", "entrypoint": "app.py"},
                manifest_path="bundle/manifest.json",
            )
        )
        self.assertEqual(executor.primary_file_for_connect_cloud(), "app.py")

    def test_reports_a_missing_entrypoint(self):
        executor = self._executor(_bundle_with_manifest({"appmode": "static"}))
        with self.assertRaises(RSConnectException) as context:
            executor.primary_file_for_connect_cloud()
        self.assertIn("primary file", str(context.exception))


class TestConnectCloudService(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock(spec=ConnectCloudClient)
        self.server = ConnectCloudServer("acme", access_token="at")
        self.service = ConnectCloudService(self.client, self.server)
        # Happy-path responses; tests override the pieces they are about.
        # The account-ownership check resolves the target account on the update
        # path too, so give it a stable answer by default.
        self.client.get_account_by_name.return_value = {"id": "acct-1", "name": "acme"}
        self.client.get_accounts.return_value = [{"id": "acct-1", "name": "acme"}]
        self.client.get_content.return_value = {
            "id": "c1",
            "account_id": "acct-1",
            "current_revision": {"id": "r0"},
        }
        self.client.create_content.return_value = {
            "id": "c1",
            "account_id": "acct-1",
            "title": "My App",
            "next_revision": {"id": "r1", "source_bundle_upload_url": "https://up.example/1"},
        }
        self.client.update_content.return_value = {
            "id": "c1",
            "account_id": "acct-1",
            "next_revision": {"id": "r2", "source_bundle_upload_url": "https://up.example/2"},
        }

    def _prepare_deploy(self, **overrides):
        kwargs = dict(
            app_id=None, app_name="my-app", title="My App", app_mode=AppModes.PYTHON_SHINY, primary_file="app.py"
        )
        kwargs.update(overrides)
        return self.service.prepare_deploy(**kwargs)

    def test_prepare_deploy_creates_content_when_no_app_id(self):
        result = self._prepare_deploy(env_vars={"FOO": "bar"})

        self.client.create_content.assert_called_once()
        kwargs = self.client.create_content.call_args.kwargs
        self.assertEqual(kwargs["content_type"], "shiny")
        self.assertEqual(kwargs["primary_file"], "app.py")
        self.assertEqual(kwargs["secrets"], [{"name": "FOO", "value": "bar"}])
        self.client.update_content.assert_not_called()

        self.assertEqual(result.content_id, "c1")
        self.assertEqual(result.revision_id, "r1")
        self.assertEqual(result.upload_url, "https://up.example/1")
        self.assertEqual(result.app_url, "https://connect.posit.cloud/acme/content/c1")

    def test_prepare_deploy_without_env_vars_does_not_touch_secrets(self):
        # env_vars is empty when no -E was given; the PATCH must then omit
        # secrets entirely (None) so existing ones are not deleted.
        self._prepare_deploy(app_id="c1", env_vars={})
        self.assertIsNone(self.client.update_content.call_args.kwargs["secrets"])

    def test_prepare_deploy_updates_existing_content(self):
        result = self._prepare_deploy(app_id="c1")

        self.client.create_content.assert_not_called()
        self.client.update_content.assert_called_once()
        self.assertEqual(result.revision_id, "r2")

    def test_prepare_deploy_patches_content_whose_first_publish_failed(self):
        # A failed first publish leaves content with no current_revision and a stale
        # next_revision that still carries the old primary_file and secrets. The
        # PATCH must happen anyway, or the retry replays the stale revision.
        self.client.get_content.return_value = {
            "id": "c1",
            "account_id": "acct-1",
            "current_revision": None,
            "next_revision": {"id": "r1", "source_bundle_upload_url": "https://up.example/stale"},
        }
        self.client.update_content.return_value = {
            "id": "c1",
            "account_id": "acct-1",
            "next_revision": {"id": "r2", "source_bundle_upload_url": "https://up.example/fresh"},
        }

        result = self._prepare_deploy(app_id="c1")

        self.client.create_content.assert_not_called()
        self.client.update_content.assert_called_once()
        self.assertEqual(result.revision_id, "r2")
        self.assertEqual(result.upload_url, "https://up.example/fresh")

    def test_prepare_deploy_sends_the_visibility_as_the_content_access(self):
        self._prepare_deploy(visibility="private")
        self.assertEqual(self.client.create_content.call_args.kwargs["access"], "private")

        self._prepare_deploy(app_id="c1", visibility="public")
        self.assertEqual(self.client.update_content.call_args.kwargs["access"], "public")

    def test_prepare_deploy_without_a_visibility_does_not_send_access(self):
        # No -V leaves new content on the server's default and keeps a redeploy
        # from overwriting a visibility set in the Connect Cloud interface.
        self._prepare_deploy()
        self.assertIsNone(self.client.create_content.call_args.kwargs["access"])

        self._prepare_deploy(app_id="c1")
        self.assertIsNone(self.client.update_content.call_args.kwargs["access"])

    def test_prepare_deploy_updates_the_title_only_when_explicit(self):
        self._prepare_deploy(app_id="c1")
        self.assertIsNone(self.client.update_content.call_args.kwargs["title"])

        self._prepare_deploy(app_id="c1", update_title=True)
        self.assertEqual(self.client.update_content.call_args.kwargs["title"], "My App")

    def test_content_url_resolves_a_renamed_account(self):
        # The saved account name can be stale after a rename; the id is what
        # survives, so the URL is built from the name the id currently maps to.
        self.server.account_id = "acct-1"
        self.client.get_accounts.return_value = [{"id": "acct-1", "name": "acme-renamed"}]
        url = self.service.content_url("c1", "acct-1")
        self.assertEqual(url, "https://connect.posit.cloud/acme-renamed/content/c1")

    def test_prepare_deploy_refuses_content_owned_by_another_account(self):
        # One token can publish to several accounts, so a stale or copied record
        # can point at another account's content; updating it would silently
        # ignore the account being published to.
        self.client.get_content.return_value = {
            "id": "c1",
            "account_id": "acct-other",
            "current_revision": {"id": "r0"},
        }
        self.client.create_content.return_value = {
            "id": "c2",
            "account_id": "acct-1",
            "next_revision": {"id": "r1", "source_bundle_upload_url": "https://up.example/1"},
        }

        result = self._prepare_deploy(app_id="c1")

        self.client.update_content.assert_not_called()
        self.client.create_content.assert_called_once()
        self.assertEqual(result.content_id, "c2")

    def test_prepare_deploy_recreates_deleted_content(self):
        self.client.get_content.side_effect = RSConnectException("gone", status=404)
        self.client.create_content.return_value = {
            "id": "c2",
            "account_id": "acct-1",
            "next_revision": {"id": "r1", "source_bundle_upload_url": "https://up.example/1"},
        }

        result = self._prepare_deploy(app_id="c1")

        self.client.create_content.assert_called_once()
        self.assertEqual(result.content_id, "c2")

    def test_prepare_deploy_rejects_an_explicit_app_id_that_no_longer_exists(self):
        # A typed --app-id names content the user expects to replace; quietly
        # creating new content instead would produce an unintended duplicate.
        self.client.get_content.side_effect = RSConnectException("gone", status=404)

        with self.assertRaises(RSConnectException) as context:
            self._prepare_deploy(app_id="c1", app_id_is_explicit=True)

        self.assertIn("does not exist", str(context.exception))
        self.assertIn("--app-id", str(context.exception))
        self.client.create_content.assert_not_called()

    def test_prepare_deploy_rejects_an_explicit_app_id_in_another_account(self):
        self.client.get_content.return_value = {
            "id": "c1",
            "account_id": "acct-other",
            "current_revision": {"id": "r0"},
        }

        with self.assertRaises(RSConnectException) as context:
            self._prepare_deploy(app_id="c1", app_id_is_explicit=True)

        self.assertIn("different Posit Connect Cloud account", str(context.exception))
        self.client.update_content.assert_not_called()
        self.client.create_content.assert_not_called()

    def test_prepare_deploy_uses_a_saved_account_id_without_a_lookup(self):
        self.service = ConnectCloudService(
            self.client, ConnectCloudServer("acme", access_token="at", account_id="acct-1")
        )

        result = self._prepare_deploy()

        self.assertEqual(self.client.create_content.call_args.kwargs["account_id"], "acct-1")
        self.client.get_account_by_name.assert_not_called()
        # The content URL still resolves the owner's *name* by id, because the
        # saved name can be stale after an account rename.
        self.assertEqual(result.app_url, "https://connect.posit.cloud/acme/content/c1")

    def test_prepare_deploy_resolves_the_account_when_no_id_is_saved(self):
        # Servers saved before the id was recorded still work.
        self._prepare_deploy()

        self.client.get_account_by_name.assert_called_once_with("acme")
        self.assertEqual(self.client.create_content.call_args.kwargs["account_id"], "acct-1")

    def test_content_url_still_resolves_an_account_that_is_not_the_one_saved(self):
        # Team-owned content carries a different account id, which has to be looked up.
        server = ConnectCloudServer("acme", access_token="at", account_id="acct-1")
        service = ConnectCloudService(self.client, server)
        self.client.get_accounts.return_value = [
            {"id": "acct-1", "name": "acme"},
            {"id": "acct-2", "name": "team-analytics"},
        ]

        self.assertEqual(
            service.content_url("c1", "acct-2"),
            "https://connect.posit.cloud/team-analytics/content/c1",
        )
        self.client.get_accounts.assert_called_once()

    def test_prepare_deploy_rejects_unsupported_app_mode(self):
        with self.assertRaises(RSConnectException) as context:
            self._prepare_deploy(app_name="my-api", title="My API", app_mode=AppModes.PYTHON_FASTAPI)
        self.assertIn("does not support", str(context.exception))

    def test_content_url_resolves_a_team_account(self):
        # Content can live in a team account, not the authenticating one.
        self.client.get_accounts.return_value = [
            {"id": "acct-1", "name": "acme"},
            {"id": "acct-2", "name": "team-analytics"},
        ]
        url = self.service.content_url("c1", "acct-2")
        self.assertEqual(url, "https://connect.posit.cloud/team-analytics/content/c1")

    def test_content_url_failure_does_not_propagate(self):
        # A URL we cannot build must not mask an otherwise successful deploy.
        self.client.get_accounts.side_effect = RSConnectException("boom")
        self.assertEqual(self.service.content_url("c1", "acct-2"), "")

    def test_wait_for_publish_returns_on_success(self):
        self.client.get_revision.side_effect = [
            {"id": "r1", "status": "building", "publish_result": None},
            {"id": "r1", "status": "publishing", "publish_result": None},
            {"id": "r1", "status": "published", "publish_result": "success"},
        ]
        with mock.patch("rsconnect.api.time.sleep"):
            revision = self.service.wait_for_publish("r1")
        self.assertEqual(revision["publish_result"], "success")

    def test_wait_for_publish_tolerates_unknown_status(self):
        # The server can add states without us knowing about them.
        self.client.get_revision.side_effect = [
            {"id": "r1", "status": "some-new-state", "publish_result": None},
            {"id": "r1", "status": "published", "publish_result": "success"},
        ]
        with mock.patch("rsconnect.api.time.sleep"):
            self.service.wait_for_publish("r1")

    def test_wait_for_publish_reports_failure_with_logs(self):
        self.client.get_revision.return_value = {
            "id": "r1",
            "status": "building",
            "publish_result": "failure",
            "publish_error_details": "build failed",
            "publish_log_channel": "chan-1",
        }
        self.client.get_publish_logs.return_value = [{"timestamp": 1700000000000000, "message": "boom"}]

        with mock.patch("rsconnect.api.time.sleep"):
            with self.assertRaises(DeploymentFailedException) as context:
                self.service.wait_for_publish("r1")

        self.assertIn("build failed", str(context.exception))
        self.client.get_publish_logs.assert_called_once_with("chan-1")

    def test_log_failure_does_not_mask_publish_failure(self):
        self.client.get_revision.return_value = {
            "id": "r1",
            "publish_result": "failure",
            "publish_log_channel": "chan-1",
        }
        self.client.get_publish_logs.side_effect = RSConnectException("no logs for you")

        with mock.patch("rsconnect.api.time.sleep"):
            with self.assertRaises(DeploymentFailedException):
                self.service.wait_for_publish("r1")

    def test_wait_for_publish_times_out(self):
        self.client.get_revision.return_value = {"id": "r1", "status": "building", "publish_result": None}
        with mock.patch("rsconnect.api.time.sleep"):
            with self.assertRaises(RSConnectException) as context:
                self.service.wait_for_publish("r1", timeout=0)
        self.assertIn("Timed out", str(context.exception))


class TestConnectCloudDeployRecordsContentEarly(unittest.TestCase):
    """Connect Cloud cannot look content up by name, so the local deployment record is
    the only way back to a content item. It has to be written before publishing."""

    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.app_path = os.path.join(tempdir.name, "app.py")
        self.server = ConnectCloudServer("acme", access_token="at")

    def _executor(self, app_id=None, visibility=None):
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.remote_server = self.server
        executor.client = mock.MagicMock(spec=ConnectCloudClient)
        executor.app_mode = AppModes.PYTHON_SHINY
        executor.visibility = visibility
        executor.app_id = app_id
        executor.app_id_is_explicit = app_id is not None
        executor.app_store = AppStore(self.app_path)
        executor.path = self.app_path
        executor.deployment_name = "my-app"
        executor.title = "My App"
        executor.title_is_default = True
        executor.env_vars = None
        executor.deployed_info = None
        executor.logger = None
        executor.bundle = _bundle_with_manifest({"appmode": "python-shiny", "entrypoint": "app.py"})
        return executor

    def _service(self):
        service = mock.Mock(spec=ConnectCloudService)
        service.prepare_deploy.return_value = api.ConnectCloudDeployResult(
            content_id="c1",
            revision_id="r1",
            upload_url="https://up.example/1",
            app_url="https://connect.posit.cloud/acme/content/c1",
            title="My App",
        )
        return service

    def _saved_app_id(self):
        # Records are scoped by account, not just the shared API URL.
        key = "%s#%s" % (self.server.url, self.server.account_name)
        return AppStore(self.app_path).resolve(key, None, AppModes.PYTHON_SHINY)[0]

    def test_publish_failure_still_records_the_content_id(self):
        executor = self._executor()
        service = self._service()
        service.do_deploy.side_effect = DeploymentFailedException("publish failed")

        with mock.patch.object(api, "ConnectCloudService", return_value=service):
            with self.assertRaises(DeploymentFailedException):
                executor.deploy_bundle()

        self.assertEqual(self._saved_app_id(), "c1")

    def test_a_retry_after_a_failed_publish_reuses_the_content(self):
        self.test_publish_failure_still_records_the_content_id()

        executor = self._executor()
        executor.new = False
        executor.validate_app_mode(AppModes.PYTHON_SHINY)
        self.assertEqual(executor.app_id, "c1")

        service = self._service()
        with mock.patch.object(api, "ConnectCloudService", return_value=service):
            with mock.patch.object(api.webbrowser, "open_new"):
                executor.deploy_bundle()

        self.assertEqual(service.prepare_deploy.call_args.kwargs["app_id"], "c1")

    def test_the_record_is_written_before_the_bundle_is_uploaded(self):
        executor = self._executor()
        service = self._service()
        seen = []
        service.upload_bundle.side_effect = lambda *args: seen.append(self._saved_app_id())

        with mock.patch.object(api, "ConnectCloudService", return_value=service):
            with mock.patch.object(api.webbrowser, "open_new"):
                executor.deploy_bundle()

        self.assertEqual(seen, ["c1"])

    def test_the_visibility_reaches_prepare_deploy(self):
        executor = self._executor(visibility="private")
        service = self._service()

        with mock.patch.object(api, "ConnectCloudService", return_value=service):
            with mock.patch.object(api.webbrowser, "open_new"):
                executor.deploy_bundle()

        self.assertEqual(service.prepare_deploy.call_args.kwargs["visibility"], "private")

    def test_upload_failure_still_records_the_content_id(self):
        executor = self._executor()
        service = self._service()
        service.upload_bundle.side_effect = RSConnectException("upload failed")

        with mock.patch.object(api, "ConnectCloudService", return_value=service):
            with self.assertRaises(RSConnectException):
                executor.deploy_bundle()

        self.assertEqual(self._saved_app_id(), "c1")


class TestConnectCloudRecordKey(unittest.TestCase):
    """Deployment records must be scoped by account, not just the shared API URL."""

    def _executor(self, server):
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.remote_server = server
        return executor

    def test_connect_cloud_key_includes_the_account(self):
        executor = self._executor(ConnectCloudServer("acme"))
        self.assertEqual(executor.record_server_key(), "https://api.connect.posit.cloud/v1#acme")

    def test_the_account_id_is_preferred_over_the_renamable_name(self):
        executor = self._executor(ConnectCloudServer("acme", account_id="acct-1"))
        self.assertEqual(executor.record_server_key(), "https://api.connect.posit.cloud/v1#acct-1")
        self.assertEqual(executor.record_server_key_fallback(), "https://api.connect.posit.cloud/v1#acme")

    def test_no_fallback_without_an_id(self):
        self.assertIsNone(self._executor(ConnectCloudServer("acme")).record_server_key_fallback())

    def test_different_accounts_get_different_keys(self):
        self.assertNotEqual(
            self._executor(ConnectCloudServer("acme")).record_server_key(),
            self._executor(ConnectCloudServer("emca")).record_server_key(),
        )

    def test_other_servers_keep_the_plain_url(self):
        executor = self._executor(api.RSConnectServer("https://connect.example.com", "key"))
        self.assertEqual(executor.record_server_key(), "https://connect.example.com")
        self.assertIsNone(executor.record_server_key_fallback())

    def test_a_name_keyed_record_is_still_found_when_an_id_arrives(self):
        # Records written before the account id was stored are keyed by name;
        # the read falls back to them, and the next write migrates the record.
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        app_path = os.path.join(tempdir.name, "app.py")

        server = ConnectCloudServer("acme", account_id="acct-1")
        store = AppStore(app_path)
        store.set(
            "https://api.connect.posit.cloud/v1#acme",
            app_path,
            "https://connect.posit.cloud/acme/content/c1",
            "c1",
            None,
            "T",
            AppModes.PYTHON_SHINY,
        )
        store.save()

        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.logger = None
        executor.remote_server = server
        executor.app_store = AppStore(app_path)
        executor.app_store_version = None
        executor.path = app_path
        executor.new = False
        executor.app_id = None
        executor.app_mode = None
        executor.validate_app_mode(app_mode=AppModes.PYTHON_SHINY)

        self.assertEqual(executor.app_id, "c1")


SHINYAPPS = "https://api.shinyapps.io"
MIGRATED_KEY = "%s#acct-1" % API


class TestConnectCloudMigrate(unittest.TestCase):
    """Migration rewrites the local deployment record; no content is copied."""

    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.app_dir = tempdir.name
        self.store_file = fake_module_file_from_directory(self.app_dir)

    def _store(self) -> AppStore:
        return AppStore(self.store_file)

    def _record(self, server_url: str, app_id: str = "42", app_mode: Any = AppModes.PYTHON_SHINY) -> None:
        store = self._store()
        store.set(server_url, self.app_dir, "https://acme.shinyapps.io/my-app", app_id, None, "My App", app_mode)

    def _executor(self, account_name: str = "acme", account_id: Optional[str] = "acct-1") -> RSConnectExecutor:
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.remote_server = ConnectCloudServer(account_name, access_token="at", account_id=account_id)
        executor.client = mock.MagicMock(spec=ConnectCloudClient)
        executor.client.get_content.return_value = {"id": "c1", "title": "My Cloud App", "account_id": "acct-1"}
        executor.client.get_accounts.return_value = [{"id": "acct-1", "name": "acme"}]
        executor.app_store = self._store()
        executor.path = self.app_dir
        executor.title = "app"
        executor.logger = None
        return executor

    def test_rewrites_the_record_and_removes_the_source(self):
        self._record(SHINYAPPS)

        record = self._executor().migrate_to_connect_cloud("c1")

        self.assertEqual(record["app_id"], "c1")
        self.assertEqual(record["title"], "My Cloud App")
        self.assertEqual(record["app_url"], "https://connect.posit.cloud/acme/content/c1")
        # The mode is not knowable from Connect Cloud, so the source record's is kept.
        self.assertEqual(record["app_mode"], "python-shiny")

        saved = self._store()
        self.assertIsNotNone(saved.get(MIGRATED_KEY))
        self.assertIsNone(saved.get(SHINYAPPS), "the migrated-from record should be gone")

    def test_the_next_deploy_finds_the_migrated_record(self):
        # The whole point: a deploy of the same path must pick the content id up,
        # or it would create a second content item in Connect Cloud.
        self._record(SHINYAPPS)
        self._executor().migrate_to_connect_cloud("c1")

        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.logger = None
        executor.remote_server = ConnectCloudServer("acme", account_id="acct-1")
        executor.app_store = self._store()
        executor.app_store_version = None
        executor.path = self.app_dir
        executor.new = False
        executor.app_id = None
        executor.app_mode = None
        executor.validate_app_mode(app_mode=AppModes.PYTHON_SHINY)

        self.assertEqual(executor.app_id, "c1")

    def test_content_owned_by_another_account_is_refused(self):
        # A record under this account would never be read for content the deploy
        # would refuse anyway, so the account that makes it usable is named.
        self._record(SHINYAPPS)
        executor = self._executor()
        executor.client.get_content.return_value = {"id": "c1", "title": "T", "account_id": "acct-2"}
        executor.client.get_accounts.return_value = [
            {"id": "acct-1", "name": "acme"},
            {"id": "acct-2", "name": "team"},
        ]

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn('"team"', str(context.exception))
        self.assertIn("-A team", str(context.exception))
        saved = self._store()
        self.assertIsNotNone(saved.get(SHINYAPPS), "the source record should be untouched")
        self.assertIsNone(saved.get("%s#acct-2" % API))

    def test_without_an_account_id_the_account_is_matched_by_name(self):
        # A server built from an account name alone keys its records by that name,
        # so the ownership check has to compare the same thing the key does.
        self._record(SHINYAPPS)
        executor = self._executor(account_id=None)

        record = executor.migrate_to_connect_cloud("c1")

        self.assertEqual(record["server_url"], "%s#acme" % API)

    def test_an_unresolvable_account_is_refused(self):
        self._record(SHINYAPPS)
        executor = self._executor()
        executor.client.get_content.return_value = {"id": "c1", "title": "T", "account_id": "acct-unknown"}

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("Unable to determine which Posit Connect Cloud account", str(context.exception))
        self.assertIsNotNone(self._store().get(SHINYAPPS))

    def test_an_account_without_publish_permission_is_refused(self):
        # An account id saved with a nickname skips the publish check in
        # validate_connect_cloud_server, so a viewer role would otherwise not be
        # caught until the deploy, with the source record already removed.
        self._record(SHINYAPPS)
        executor = self._executor()
        executor.client.get_accounts.return_value = [
            {"id": "acct-1", "name": "acme", "permissions": ["content:read"]},
        ]

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("do not have permission to publish", str(context.exception))
        saved = self._store()
        self.assertIsNotNone(saved.get(SHINYAPPS), "the source record must survive a refusal")
        self.assertIsNone(saved.get(MIGRATED_KEY))

    def test_an_account_named_after_its_id_keeps_the_written_record(self):
        # The id-keyed and name-keyed record locations collide when the account's
        # name equals its id; removing the name-keyed one then deletes the record
        # just written, and the source record is already gone.
        self._record(SHINYAPPS)
        executor = self._executor(account_name="acct-1", account_id="acct-1")
        executor.client.get_accounts.return_value = [{"id": "acct-1", "name": "acct-1"}]
        self.assertEqual(executor.record_server_key(), executor.record_server_key_fallback())

        record = executor.migrate_to_connect_cloud("c1")

        self.assertEqual(record["app_id"], "c1")
        saved = self._store()
        self.assertIsNotNone(saved.get(executor.record_server_key()), "the new record must survive")
        self.assertIsNone(saved.get(SHINYAPPS))

    def test_missing_content_leaves_the_records_alone(self):
        self._record(SHINYAPPS)
        executor = self._executor()
        executor.client.get_content.side_effect = RSConnectException("content c1 has been deleted", status=404)

        with self.assertRaises(RSConnectException):
            executor.migrate_to_connect_cloud("c1")

        saved = self._store()
        self.assertIsNotNone(saved.get(SHINYAPPS))
        self.assertIsNone(saved.get(MIGRATED_KEY))

    def test_an_existing_cloud_record_needs_overwrite(self):
        self._record(SHINYAPPS)
        self._record(MIGRATED_KEY, app_id="other")
        executor = self._executor()

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("--overwrite", str(context.exception))
        self.assertIn("other", str(context.exception))
        # The check precedes every request, so nothing was asked of the server.
        executor.client.get_content.assert_not_called()
        self.assertEqual(self._store().get(MIGRATED_KEY)["app_id"], "other")

    def test_a_name_keyed_cloud_record_also_needs_overwrite(self):
        # A record written before account ids were stored is keyed by name. A deploy
        # reads it when the id-keyed record is missing, so it is this account's
        # current target and must not be replaced silently.
        self._record("%s#acme" % API, app_id="old")
        executor = self._executor()

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("--overwrite", str(context.exception))
        self.assertIn("old", str(context.exception))
        executor.client.get_content.assert_not_called()

    def test_overwrite_replaces_a_name_keyed_cloud_record(self):
        # Both keys naming the same account must not be left behind as duplicates.
        self._record("%s#acme" % API, app_id="old")

        record = self._executor().migrate_to_connect_cloud("c1", overwrite=True)

        self.assertEqual(record["server_url"], MIGRATED_KEY)
        saved = self._store()
        self.assertEqual(saved.get(MIGRATED_KEY)["app_id"], "c1")
        self.assertIsNone(saved.get("%s#acme" % API))

    def test_overwrite_replaces_the_existing_cloud_record(self):
        self._record(MIGRATED_KEY, app_id="other")

        record = self._executor().migrate_to_connect_cloud("c1", overwrite=True)

        self.assertEqual(record["app_id"], "c1")
        self.assertEqual(self._store().get(MIGRATED_KEY)["app_id"], "c1")

    def test_a_cloud_record_is_never_treated_as_the_source(self):
        # Another account's record is not what this one is migrating away from;
        # deleting it would throw away a working deployment target.
        other_account = "%s#acct-9" % API
        self._record(other_account)

        self._executor().migrate_to_connect_cloud("c1")

        saved = self._store()
        self.assertIsNotNone(saved.get(other_account))
        self.assertIsNotNone(saved.get(MIGRATED_KEY))

    def test_no_source_record_reconstructs_from_the_content(self):
        record = self._executor().migrate_to_connect_cloud("c1")

        self.assertEqual(record["app_id"], "c1")
        self.assertEqual(record["title"], "My Cloud App")
        # Nothing local says what kind of content this is, and "unknown" does not
        # block a later deploy of any mode.
        self.assertEqual(record["app_mode"], "unknown")

    def test_several_records_require_from_server(self):
        self._record(SHINYAPPS)
        self._record("https://connect.example.com")
        executor = self._executor()

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("--from-server", str(context.exception))
        self.assertIn(SHINYAPPS, str(context.exception))
        self.assertIn("https://connect.example.com", str(context.exception))
        executor.client.get_content.assert_not_called()

    def test_from_server_selects_one_and_leaves_the_other(self):
        self._record(SHINYAPPS)
        self._record("https://connect.example.com")

        # The pseudo-server name resolves to the URL records are stored under.
        self._executor().migrate_to_connect_cloud("c1", from_server="shinyapps.io")

        saved = self._store()
        self.assertIsNone(saved.get(SHINYAPPS))
        self.assertIsNotNone(saved.get("https://connect.example.com"))
        self.assertIsNotNone(saved.get(MIGRATED_KEY))

    def test_a_lone_connect_record_is_inherited_but_kept(self):
        # Only shinyapps.io content is migrated away, so only that record is dead.
        # Connect content still exists and stays deployable from this directory.
        CONNECT = "https://connect.example.com"
        self._record(CONNECT, app_id="17")

        record = self._executor().migrate_to_connect_cloud("c1")

        saved = self._store()
        self.assertIsNotNone(saved.get(CONNECT), "the Connect record must survive")
        self.assertEqual(saved.get(CONNECT)["app_id"], "17")
        self.assertIsNotNone(saved.get(MIGRATED_KEY))
        # Still the source for the new record's app mode.
        self.assertEqual(record["app_mode"], "python-shiny")

    def test_a_named_connect_record_is_also_kept(self):
        # --from-server picks which record supplies the metadata; it does not make a
        # live Connect record removable.
        CONNECT = "https://connect.example.com"
        self._record(SHINYAPPS)
        self._record(CONNECT)

        self._executor().migrate_to_connect_cloud("c1", from_server=CONNECT)

        saved = self._store()
        self.assertIsNotNone(saved.get(CONNECT), "the Connect record must survive")
        self.assertIsNotNone(saved.get(SHINYAPPS), "an unselected record is untouched")
        self.assertIsNotNone(saved.get(MIGRATED_KEY))

    def test_from_server_matches_a_record_stored_with_a_trailing_slash(self):
        # Record keys are the server URL as it was typed at deploy time, so one can
        # carry a trailing slash the user does not repeat here.
        self._record(SHINYAPPS)
        self._record("https://connect.example.com/")

        self._executor().migrate_to_connect_cloud("c1", from_server="https://connect.example.com")

        saved = self._store()
        self.assertIsNotNone(saved.get("https://connect.example.com/"), "the Connect record must survive")
        self.assertIsNotNone(saved.get(MIGRATED_KEY))

    def test_from_server_with_a_trailing_slash_matches_a_record_without_one(self):
        self._record(SHINYAPPS)
        self._record("https://connect.example.com")

        self._executor().migrate_to_connect_cloud("c1", from_server="https://connect.example.com/")

        saved = self._store()
        self.assertIsNotNone(saved.get("https://connect.example.com"), "the Connect record must survive")
        self.assertIsNotNone(saved.get(MIGRATED_KEY))

    def test_the_shinyapps_short_name_matches_with_a_trailing_slash(self):
        self._record(SHINYAPPS)
        self._record("https://connect.example.com")

        self._executor().migrate_to_connect_cloud("c1", from_server="shinyapps.io/")

        saved = self._store()
        self.assertIsNone(saved.get(SHINYAPPS), "the migrated-from record should be gone")
        self.assertIsNotNone(saved.get("https://connect.example.com"))

    def test_from_server_picks_the_slash_variant_it_names(self):
        # Both spellings are separate record keys, and a deploy's lookup is keyed
        # exactly, so one directory can hold a record for each. Only the spelling
        # passed here tells them apart.
        CONNECT = "https://connect.example.com"
        self._record(CONNECT, app_id="11", app_mode=AppModes.PYTHON_API)
        self._record(CONNECT + "/", app_id="22", app_mode=AppModes.PYTHON_SHINY)

        self.assertEqual(self._executor().migration_source_record(from_server=CONNECT)["app_id"], "11")
        self.assertEqual(self._executor().migration_source_record(from_server=CONNECT + "/")["app_id"], "22")

    def test_several_records_matching_one_server_are_reported(self):
        # Nothing exactly matches what was typed, and normalizing reaches both, so
        # the choice belongs to the user rather than to record order.
        self._record("https://connect.example.com/")
        self._record("https://connect.example.com//")

        with self.assertRaises(RSConnectException) as context:
            self._executor().migration_source_record(from_server="https://connect.example.com")

        self.assertIn("Several deployment records match", str(context.exception))
        self.assertIn("Pass the record's URL exactly", str(context.exception))

    def test_from_server_that_matches_no_record_is_reported(self):
        self._record(SHINYAPPS)
        executor = self._executor()

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1", from_server="https://connect.example.com")

        self.assertIn("No deployment record", str(context.exception))
        self.assertIn(SHINYAPPS, str(context.exception))
        self.assertIsNotNone(self._store().get(SHINYAPPS))

    def test_a_non_cloud_target_is_rejected(self):
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.remote_server = api.RSConnectServer("https://connect.example.com", "key")
        executor.client = mock.MagicMock(spec=RSConnectClient)

        with self.assertRaises(RSConnectException) as context:
            executor.migrate_to_connect_cloud("c1")

        self.assertIn("Posit Connect Cloud account", str(context.exception))


class TestConnectCloudMigrateCli(CliTestCase):
    def setUp(self):
        super().setUp()
        # The executor opens its own store; point it at the same temporary one.
        api_store_patch = mock.patch("rsconnect.api.ServerStore", return_value=self.store)
        api_store_patch.start()
        self.addCleanup(api_store_patch.stop)

        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.app_dir = tempdir.name
        self.app_store = AppStore(fake_module_file_from_directory(self.app_dir))
        self.app_store.set(
            SHINYAPPS, self.app_dir, "https://acme.shinyapps.io/my-app", "42", None, "My App", AppModes.PYTHON_SHINY
        )

    def _migrate(self, *args: str):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(ConnectCloudClient, "get_current_user", return_value={"id": "u1"}))
            stack.enter_context(
                mock.patch.object(
                    ConnectCloudClient,
                    "get_content",
                    return_value={"id": "c1", "title": "My Cloud App", "account_id": "acct-1"},
                )
            )
            stack.enter_context(
                mock.patch.object(ConnectCloudClient, "get_accounts", return_value=[{"id": "acct-1", "name": "acme"}])
            )
            return self.runner.invoke(
                cli,
                ["content", "migrate-to-connect-cloud", self.app_dir, "--content-id", "c1", *args],
            )

    def test_migrates_with_a_saved_nickname(self):
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_account_id="acct-1",
            connect_cloud_access_token="at",
        )

        result = self._migrate("-n", "cloud")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("My Cloud App", result.output)
        self.assertIn("https://connect.posit.cloud/acme/content/c1", result.output)

        saved = AppStore(fake_module_file_from_directory(self.app_dir))
        self.assertEqual(saved.get(MIGRATED_KEY)["app_id"], "c1")
        self.assertIsNone(saved.get(SHINYAPPS))

    def test_a_connect_server_is_rejected(self):
        self.store.set("prod", "https://connect.example.com", api_key="key")

        with mock.patch.object(api.RSConnectExecutor, "validate_connect_server"):
            result = self._migrate("-n", "prod")

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("requires a Posit Connect Cloud account", result.output)
        self.assertIsNotNone(AppStore(fake_module_file_from_directory(self.app_dir)).get(SHINYAPPS))


class TestPresignedUrlErrorRedaction(unittest.TestCase):
    def test_upload_error_does_not_leak_the_signed_url(self):
        # handle_bad_response quotes the URI in its message; for a presigned
        # upload URL that would include the URL's own credentials.
        from rsconnect.api import S3Server
        from rsconnect.http_support import HTTPResponse

        url = "https://bucket.example/path?token=signed-credential&X-Amz-Signature=deadbeef&sig=sastoken"
        response = HTTPResponse(url, exception=ConnectionError("boom"))
        with self.assertRaises(RSConnectException) as context:
            S3Server(url).handle_bad_response(response, is_httpresponse=True)

        message = str(context.exception)
        self.assertNotIn("signed-credential", message)
        self.assertNotIn("deadbeef", message)
        self.assertNotIn("sastoken", message)
        self.assertIn("bucket.example", message)


class TestConnectCloudCliPolish(CliTestCase):
    def _manifest_path(self):
        path = os.path.join(tempfile.mkdtemp(), "manifest.json")
        with open(path, "w") as f:
            json.dump({"version": 1, "metadata": {"appmode": "python-shiny", "entrypoint": "app1"}, "files": {}}, f)
        return path

    def test_client_secret_is_masked_in_verbose_output(self):
        # The parameter dump goes to the logger, not to click's output stream.
        with mock.patch("rsconnect.connect_cloud.request_client_credentials_token") as request:
            request.return_value = {"access_token": "at"}
            with self.assertLogs("rsconnect", level=VERBOSE) as captured:
                result = self.runner.invoke(
                    cli,
                    [
                        "add",
                        "-v",
                        "--name",
                        "cloud",
                        "--server",
                        "connect.posit.cloud",
                        "--account",
                        "acme",
                        "--client-id",
                        "cid",
                        "--client-secret",
                        "sup3rs3cret",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        logged = "\n".join(captured.output)
        self.assertNotIn("sup3rs3cret", logged)
        self.assertIn("client_secret:    **********", logged)
        # The non-secret client id is still shown, so the log stays useful.
        self.assertIn("client_id:        cid", logged)

    def test_shinyapps_token_and_secret_are_masked_too(self):
        with mock.patch("rsconnect.main._test_rstudio_creds"):
            with self.assertLogs("rsconnect", level=VERBOSE) as captured:
                result = self.runner.invoke(
                    cli,
                    [
                        "add",
                        "-v",
                        "--name",
                        "sa",
                        "--server",
                        "shinyapps.io",
                        "--account",
                        "me",
                        "--token",
                        "tok3n",
                        "--secret",
                        "s3cret",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        logged = "\n".join(captured.output)
        self.assertNotIn("tok3n", logged)
        self.assertNotIn("s3cret", logged)

    def test_list_shows_connect_cloud_details(self):
        self.store.set(
            "cloud",
            "https://api.connect.posit.cloud/v1",
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_access_token="at",
        )
        result = self.runner.invoke(cli, ["list"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Posit Connect Cloud account: acme", result.output)
        self.assertIn("Service account client ID: cid", result.output)
        self.assertIn("Credentials are saved", result.output)
        self.assertNotIn("at", result.output.split("Credentials are saved")[0].split("client ID: cid")[1])

    def test_manifest_deploy_marks_a_defaulted_title(self):
        # deploy manifest computes a default title before building the executor;
        # it must still record that --title was not typed, or redeploys would
        # overwrite existing Connect Cloud content's title with the default.
        path = self._manifest_path()

        with mock.patch("rsconnect.main.RSConnectExecutor") as executor_cls:
            result = self.runner.invoke(cli, ["deploy", "manifest", path])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(executor_cls.call_args.kwargs["title"])
        self.assertTrue(executor_cls.call_args.kwargs["title_is_default"])

        with mock.patch("rsconnect.main.RSConnectExecutor") as executor_cls:
            result = self.runner.invoke(cli, ["deploy", "manifest", path, "-t", "Typed Title"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(executor_cls.call_args.kwargs["title"], "Typed Title")
        self.assertFalse(executor_cls.call_args.kwargs["title_is_default"])

    def test_env_var_values_are_hidden_in_verbose_output(self):
        # -E values are sent to Connect Cloud as secrets; -v must log names only.
        path = self._manifest_path()

        with mock.patch("rsconnect.main.RSConnectExecutor"):
            with self.assertLogs("rsconnect", level=VERBOSE) as captured:
                result = self.runner.invoke(cli, ["deploy", "manifest", path, "-v", "-E", "API_KEY=hunter2"])

        self.assertEqual(result.exit_code, 0, result.output)
        logged = "\n".join(captured.output)
        self.assertIn("API_KEY", logged)
        self.assertNotIn("hunter2", logged)
        self.assertIn("values hidden", logged)

    def test_manifest_pyproject_and_html_help_mention_connect_cloud(self):
        from rsconnect.main import deploy

        for command in ("manifest", "pyproject", "html"):
            self.assertIn("Posit Connect Cloud", str(deploy.commands[command].short_help), command)

    def test_pyproject_deploy_does_not_use_the_nickname_as_title(self):
        # The server nickname used to be a title fallback, so `deploy pyproject
        # -n cloud` renamed existing Connect Cloud content to "cloud".
        project_dir = tempfile.mkdtemp()
        with open(os.path.join(project_dir, "pyproject.toml"), "w") as f:
            f.write('[tool.rsconnect]\napp_mode = "python-shiny"\nentrypoint = "app:app"\n')
        with open(os.path.join(project_dir, "app.py"), "w") as f:
            f.write("app = None\n")
        with open(os.path.join(project_dir, "requirements.txt"), "w") as f:
            f.write("shiny\n")

        with mock.patch("rsconnect.main.RSConnectExecutor") as executor_cls:
            result = self.runner.invoke(cli, ["deploy", "pyproject", project_dir, "-n", "cloud"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(executor_cls.call_args.kwargs["title"])

        with mock.patch("rsconnect.main.RSConnectExecutor") as executor_cls:
            result = self.runner.invoke(cli, ["deploy", "pyproject", project_dir, "-n", "cloud", "-t", "Typed"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(executor_cls.call_args.kwargs["title"], "Typed")

    def test_notebook_and_quarto_take_connect_cloud_options(self):
        # jupyter and quarto are supported Connect Cloud content types, so their
        # commands need the target and credential options like the others.
        for command in ("notebook", "quarto"):
            result = self.runner.invoke(cli, ["deploy", command, "--help"])
            self.assertIn("--connect-cloud", result.output, command)
            self.assertIn("--client-id", result.output, command)
            self.assertIn("-A, --account", result.output, command)

    def test_connect_cloud_capable_commands_take_the_visibility_option(self):
        # -V sets the content's access level on Connect Cloud, so every command
        # that can publish there has to offer it.
        for command in ("notebook", "quarto", "html", "manifest", "pyproject", "shiny"):
            result = self.runner.invoke(cli, ["deploy", command, "--help"])
            self.assertIn("-V, --visibility", result.output, command)

    def test_the_visibility_option_reaches_the_executor(self):
        # notebook, quarto, and html only gained -V for Connect Cloud; the
        # commands that also target shinyapps.io have carried it all along.
        project_dir = tempfile.mkdtemp()
        notebook = os.path.join(project_dir, "notebook.ipynb")
        with open(notebook, "w") as f:
            f.write("{}")
        page = os.path.join(project_dir, "index.html")
        with open(page, "w") as f:
            f.write("<html></html>")

        for command, target in (("notebook", notebook), ("html", page)):
            with mock.patch("rsconnect.main.Environment.create_python_environment"):
                with mock.patch("rsconnect.main.RSConnectExecutor") as executor_cls:
                    result = self.runner.invoke(cli, ["deploy", command, target, "-V", "private", "--no-verify"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(executor_cls.call_args.kwargs["visibility"], "private", command)

    def test_help_mentions_connect_cloud_only_for_supported_types(self):
        # The generated commands share a template; unsupported types must not
        # advertise a target that rejects them at validation time. The
        # --connect-cloud *option* still appears everywhere (its rejection
        # message is the explanation), so only the descriptions are checked.
        from rsconnect.main import deploy

        for command in ("streamlit", "dash", "bokeh", "shiny"):
            self.assertIn("Posit Connect Cloud", str(deploy.commands[command].short_help), command)
            self.assertIn("Posit Connect Cloud", str(deploy.commands[command].help), command)
        for command in ("fastapi", "api", "flask", "gradio", "voila"):
            self.assertNotIn("Posit Connect Cloud", str(deploy.commands[command].short_help), command)
            self.assertNotIn("Posit Connect Cloud", str(deploy.commands[command].help), command)

    def test_deploy_group_help_mentions_connect_cloud(self):
        result = self.runner.invoke(cli, ["deploy", "--help"])
        self.assertIn("Posit Connect Cloud", result.output)


class TestConnectCloudFlagAlias(CliTestCase):
    """`--connect-cloud` is shorthand for `--server connect.posit.cloud`."""

    def _add(self, *args):
        self._mock_device_login()
        return self.runner.invoke(cli, ["add", "--name", "cloud", "--account", "acme", *args])

    def test_flag_produces_the_same_entry_as_the_pseudo_name(self):
        result = self._add("--connect-cloud")
        self.assertEqual(result.exit_code, 0, result.output)
        via_flag = self.store.get_by_name("cloud")

        self.store.remove_by_name("cloud")
        result = self._add("--server", "connect.posit.cloud")
        self.assertEqual(result.exit_code, 0, result.output)
        via_pseudo_name = self.store.get_by_name("cloud")

        self.assertEqual(via_flag, via_pseudo_name)
        assert via_flag is not None
        self.assertEqual(via_flag["url"], "https://api.connect.posit.cloud/v1")
        self.assertEqual(via_flag["connect_cloud_account_name"], "acme")

    def test_flag_is_redundant_but_allowed_with_the_pseudo_name(self):
        result = self._add("--connect-cloud", "--server", "connect.posit.cloud")
        self.assertEqual(result.exit_code, 0, result.output)

    def test_flag_conflicts_with_an_explicit_other_server(self):
        result = self._add("--connect-cloud", "--server", "https://connect.example.com")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("--connect-cloud cannot be combined with", result.output)

    def test_flag_conflicts_with_a_nickname_on_deploy(self):
        # On a deploy, -n references a saved server that may be a plain Connect
        # server; the flag must be rejected rather than silently dropped. `add`
        # is unaffected because there -n names the entry being created and add
        # does not pass it to validation.
        with self.assertRaises(RSConnectException) as context:
            _validate_options(name="myconnect")
        self.assertIn("cannot be specified in conjunction", str(context.exception))
        self.assertIn("--connect-cloud", str(context.exception))

    def test_flag_wins_over_connect_server_env_var(self):
        # A leftover CONNECT_SERVER from another target must not defeat the flag.
        with mock.patch.dict(os.environ, {"CONNECT_SERVER": "https://connect.example.com"}):
            result = self._add("--connect-cloud")

        self.assertEqual(result.exit_code, 0, result.output)
        entry = self.store.get_by_name("cloud")
        assert entry is not None
        self.assertEqual(entry["url"], "https://api.connect.posit.cloud/v1")

    def test_flag_alone_satisfies_the_target_requirement(self):
        # The flag names the target, so the "you must specify one of ..." check
        # must not fire and mask the real problem (a missing account).
        result = self.runner.invoke(cli, ["add", "--name", "cloud", "--connect-cloud"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("-A/--account is required for Posit Connect Cloud", result.output)
        self.assertNotIn("You must specify one of", result.output)

    def test_conflicting_options_are_reported_against_connect_cloud(self):
        # -A/--account is shared with shinyapps.io, so the generic connect-vs-shinyapps
        # rule would otherwise blame the wrong target.
        result = self.runner.invoke(
            cli, ["add", "--name", "cloud", "--connect-cloud", "--account", "acme", "--api-key", "key"]
        )
        self.assertEqual(result.exit_code, 1, result.output)
        message = result.output
        self.assertIn("may not be passed alongside Posit Connect Cloud", message)
        self.assertNotIn("shinyapps.io options", message)

    def test_env_sourced_connect_options_do_not_block_the_flag(self):
        # A CONNECT_API_KEY or CONNECT_INSECURE exported for another target is
        # just the environment, the same as for a saved cloud nickname.
        _validate_options(ctx=_ctx(api_key=ENV, insecure=ENV), api_key="env-key", insecure=True, account_name="acme")

    def test_env_sourced_shinyapps_token_does_not_block_the_flag(self):
        _validate_options(ctx=_ctx(token=ENV, secret=ENV), account_name="acme", token="env-token", secret="env-secret")

    def test_typed_shinyapps_token_still_conflicts_with_the_flag(self):
        with self.assertRaises(RSConnectException) as context:
            _validate_options(ctx=_ctx(token=TYPED), account_name="acme", token="typed-token")
        self.assertIn("shinyapps.io options", str(context.exception))

    def test_flag_appears_in_deploy_help(self):
        result = self.runner.invoke(cli, ["deploy", "shiny", "--help"])
        self.assertIn("--connect-cloud", result.output)

    def test_flag_selects_connect_cloud_in_the_executor(self):
        server = _cloud_server(account_name="acme", use_connect_cloud=True)
        self.assertEqual(server.url, "https://api.connect.posit.cloud/v1")
        self.assertEqual(server.account_name, "acme")


class TestConnectCloudSameAccountAmbiguity(unittest.TestCase):
    """Several credentials may share a default account (an interactive login and a
    service account, say), so the account cannot pick one of them."""

    def _store(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        for name in ("cloud-a", "cloud-b"):
            store.set(name, API, connect_cloud_account_name="acme", connect_cloud_access_token="at-" + name)
        return store

    def test_lookup_by_url_with_several_credentials_is_rejected(self):
        store = self._store()
        with self.assertRaises(RSConnectException) as context:
            store.get_by_url("connect.posit.cloud")
        message = str(context.exception)
        self.assertIn('"cloud-a"', message)
        self.assertIn('"cloud-b"', message)
        self.assertIn("-n/--name", message)

    def test_a_nickname_still_selects_one(self):
        store = self._store()
        entry = store.get_by_name("cloud-b")
        assert entry is not None
        self.assertEqual(entry["connect_cloud_access_token"], "at-cloud-b")

    def test_a_complete_supplied_pair_bypasses_the_ambiguity(self):
        # A one-shot/CI deploy brings its own identity, so saved entries must not
        # block it however many there are; it resolves to transient server data.
        server = _cloud_server(
            store=self._store(),
            account_name="acme",
            use_connect_cloud=True,
            client_id="ci-id",
            client_secret="ci-secret",
        )

        self.assertIsNone(server.access_token)
        self.assertIsNone(server.server_name)
        self.assertEqual(server.client_id, "ci-id")
        self.assertEqual(server.account_name, "acme")

    def test_without_credentials_the_ambiguity_still_stands(self):
        with self.assertRaises(RSConnectException) as context:
            _setup_remote_server(store=self._store(), account_name="acme", use_connect_cloud=True)
        self.assertIn("-n/--name", str(context.exception))

    def test_remove_by_url_is_rejected_when_ambiguous(self):
        store = self._store()
        with self.assertRaises(RSConnectException):
            store.remove_by_url("connect.posit.cloud")
        self.assertEqual(len(store.get_all_servers()), 2)


class TestConnectCloudUrlVariantLookup(unittest.TestCase):
    """Every URL variant is_connect_cloud_url accepts must also find the saved
    credential, or a trailing slash silently loses the login."""

    def test_lookup_by_variant_urls_finds_the_saved_entry(self):
        store = _store_with_cloud_entry()
        for variant in (
            "https://api.connect.posit.cloud/v1/",
            "HTTPS://API.CONNECT.POSIT.CLOUD/v1",
            "connect.posit.cloud/",
        ):
            entry = store.get_by_url(variant)
            assert entry is not None, variant
            self.assertEqual(entry["name"], "cloud", variant)

    def test_non_cloud_urls_are_not_rewritten(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key")
        entry = store.get_by_url("https://connect.example.com")
        assert entry is not None
        self.assertEqual(entry["name"], "prod")


class TestConnectCloudCredentialOptionsDeferred(unittest.TestCase):
    """Typed --client-id/--client-secret are judged against the resolved target:
    a nickname or default server may be Connect Cloud, which validation cannot
    see before the store lookup."""

    def _typed_credentials(self, store, **kwargs):
        return _setup_remote_server(
            ctx=_ctx(client_id=TYPED, client_secret=TYPED), store=store, client_id="cid", client_secret="sec", **kwargs
        )

    def test_typed_credentials_are_accepted_with_a_saved_cloud_nickname(self):
        server = self._typed_credentials(_store_with_cloud_entry(), name="cloud").remote_server
        assert isinstance(server, ConnectCloudServer)
        # Credentials that differ from the entry's are their own identity
        # (the finding-34 override), so the entry's token is not attached.
        self.assertEqual(server.client_id, "cid")
        self.assertIsNone(server.access_token)

    def test_typed_credentials_with_a_connect_nickname_fail_after_resolution(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key")
        with self.assertRaises(RSConnectException) as context:
            self._typed_credentials(store, name="prod")
        self.assertIn("require --connect-cloud", str(context.exception))

    def test_typed_credentials_with_a_non_cloud_default_fail_after_resolution(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key", set_as_default=True)
        with self.assertRaises(RSConnectException) as context:
            self._typed_credentials(store)
        self.assertIn("require --connect-cloud", str(context.exception))

    def test_typed_credentials_with_a_cloud_default_are_accepted(self):
        executor = self._typed_credentials(_store_with_cloud_entry(set_as_default=True))
        self.assertIsInstance(executor.remote_server, ConnectCloudServer)

    def test_remove_by_url_with_a_single_entry_removes_it(self):
        store = _store_with_cloud_entry()
        self.assertTrue(store.remove_by_url("connect.posit.cloud"))
        self.assertEqual(store.get_all_servers(), [])


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
            self.assertEqual(validation._typed_connect_only_deploy_options(ctx), [])


class TestConnectCloudFindsSavedCredentialsByUrl(unittest.TestCase):
    """`--connect-cloud` and `-s connect.posit.cloud` must find a saved server.

    `rsconnect add` stores the entry under the API URL, so a lookup by the short
    name only matches once it has been translated.
    """

    def setUp(self):
        env_patch = mock.patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.store = self._store("https://api.connect.posit.cloud/v1")
        self._use(self.store)

    def _store(self, url):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set(
            "cloud",
            url,
            connect_cloud_account_name="acme",
            connect_cloud_account_id="acct-1",
            connect_cloud_access_token="at",
            connect_cloud_refresh_token="rt",
        )
        return store

    def _use(self, store):
        store_patch = mock.patch("rsconnect.api.ServerStore", return_value=store)
        store_patch.start()
        self.addCleanup(store_patch.stop)
        main_patch = mock.patch("rsconnect.main.server_store", store)
        main_patch.start()
        self.addCleanup(main_patch.stop)

    def _server(self, **kwargs):
        return _cloud_server(**kwargs)

    def test_resolve_translates_the_short_name(self):
        data = self.store.resolve(None, connect_cloud.SERVER_NAME)
        self.assertTrue(data.from_store)
        self.assertEqual(data.name, "cloud")
        self.assertEqual(data.connect_cloud_access_token, "at")

    def test_flag_uses_the_saved_credentials(self):
        server = self._server(account_name="acme", use_connect_cloud=True)
        self.assertEqual(server.access_token, "at")
        self.assertEqual(server.refresh_token, "rt")
        # Without the nickname a refreshed token cannot be written back.
        self.assertEqual(server.server_name, "cloud")

    def test_short_name_uses_the_saved_credentials(self):
        server = self._server(url=connect_cloud.SERVER_NAME, account_name="acme")
        self.assertEqual(server.access_token, "at")
        self.assertEqual(server.server_name, "cloud")

    def test_an_explicit_account_wins_over_the_saved_one(self):
        server = self._server(account_name="team-b", use_connect_cloud=True)
        self.assertEqual(server.account_name, "team-b")
        self.assertEqual(server.access_token, "at")

    def test_the_saved_account_id_is_used_for_the_saved_account(self):
        server = self._server(account_name="acme", use_connect_cloud=True)
        self.assertEqual(server.account_id, "acct-1")

    def test_the_saved_account_id_is_dropped_for_a_different_account(self):
        # The id belongs to the saved account, so publishing elsewhere must resolve
        # the name rather than send the wrong id.
        server = self._server(account_name="team-b", use_connect_cloud=True)
        self.assertIsNone(server.account_id)

    def test_remove_accepts_the_short_name(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["remove", "-s", connect_cloud.SERVER_NAME])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(self.store.get_by_name("cloud"))

    def test_a_saved_staging_server_is_not_used_for_production(self):
        self._use(self._store("https://api.staging.connect.posit.cloud/v1"))
        server = self._server(account_name="acme", use_connect_cloud=True)
        self.assertEqual(server.url, "https://api.connect.posit.cloud/v1")
        self.assertIsNone(server.access_token)

    def test_a_saved_staging_server_is_used_when_staging_is_selected(self):
        self._use(self._store("https://api.staging.connect.posit.cloud/v1"))
        with mock.patch.dict(os.environ, {connect_cloud.ENVIRONMENT_ENV_VAR: "staging"}):
            server = self._server(account_name="acme", use_connect_cloud=True)
        self.assertEqual(server.url, "https://api.staging.connect.posit.cloud/v1")
        self.assertEqual(server.access_token, "at")


class TestConnectCloudAccountSelection(unittest.TestCase):
    """A saved entry is a credential, not an account binding: -A/--account says where
    to publish and only -n/--name picks the credential. A single saved credential is
    used whatever the account; several are ambiguous until a nickname names one."""

    def setUp(self):
        env_patch = mock.patch.dict(os.environ, {}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def _store(self, *entries):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        for nickname, account, token in entries:
            store.set(nickname, API, connect_cloud_account_name=account, connect_cloud_access_token=token)
        return store

    def _one(self):
        return self._store(("cloud", "sam", "sam-token"))

    def _two(self):
        return self._store(("personal", "sam", "sam-token"), ("ci", "acme-team", "ci-token"))

    def _server(self, store, **kwargs):
        return _cloud_server(store=store, **kwargs)

    def test_nothing_saved_resolves_to_no_credential(self):
        self.assertIsNone(self._store().get_by_url(connect_cloud.SERVER_NAME))

    def test_one_saved_credential_is_found_by_url(self):
        entry = self._one().get_by_url(connect_cloud.SERVER_NAME)
        assert entry is not None
        self.assertEqual(entry["name"], "cloud")

    def test_the_account_is_not_required_when_one_server_is_saved(self):
        server = self._server(self._one(), use_connect_cloud=True)
        self.assertEqual(server.account_name, "sam")
        self.assertEqual(server.access_token, "sam-token")

    def test_the_account_is_still_required_with_nothing_saved(self):
        with self.assertRaises(RSConnectException) as context:
            self._server(self._store(), use_connect_cloud=True)
        self.assertIn("-A/--account is required", str(context.exception))

    def test_add_still_requires_the_account_when_a_server_is_saved(self):
        # `add` registers a named account, so it must not fall back to a saved one.
        store = self._one()
        runner = CliRunner()
        with mock.patch("rsconnect.main.server_store", store):
            result = runner.invoke(cli, ["add", "--name", "second", "--connect-cloud"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("-A/--account is required", result.output)

    def test_the_account_does_not_select_among_several_credentials(self):
        # The account a credential was saved with is its default publish target, not
        # its scope, so naming an account cannot say which credential to use.
        for account in ("acme-team", "sam", "stranger"):
            with self.assertRaises(RSConnectException) as context:
                self._server(self._two(), use_connect_cloud=True, account_name=account)
            self.assertIn("-n/--name", str(context.exception))

    def test_several_saved_credentials_are_listed_with_their_accounts(self):
        with self.assertRaises(RSConnectException) as context:
            self._server(self._two(), use_connect_cloud=True)
        message = str(context.exception)
        self.assertIn("Several Posit Connect Cloud credentials are saved", message)
        self.assertIn('"ci" (account acme-team)', message)
        self.assertIn('"personal" (account sam)', message)

    def test_a_nickname_selects_a_server_without_the_account(self):
        server = self._server(self._two(), name="ci")
        self.assertEqual(server.account_name, "acme-team")
        self.assertEqual(server.access_token, "ci-token")

    def test_a_nickname_publishes_to_another_account_of_the_same_credential(self):
        store = self._two()
        store.set(
            "personal",
            API,
            connect_cloud_account_name="sam",
            connect_cloud_account_id="acct-sam",
            connect_cloud_access_token="sam-token",
        )
        server = self._server(store, name="personal", environ={"CONNECT_CLOUD_ACCOUNT": "acme-team"})

        self.assertEqual(server.access_token, "sam-token")
        self.assertEqual(server.account_name, "acme-team")
        self.assertIsNone(server.account_id)

    def test_one_saved_login_publishes_to_another_of_its_accounts(self):
        # A Connect Cloud token belongs to a user, who can publish to every account
        # they have access to, so an explicit account picks the target rather than
        # the credential.
        server = self._server(self._one(), use_connect_cloud=True, account_name="other-team")
        self.assertEqual(server.account_name, "other-team")
        self.assertEqual(server.access_token, "sam-token")

    def test_remove_reports_the_ambiguity_instead_of_deleting_one(self):
        store = self._two()
        runner = CliRunner()
        with mock.patch("rsconnect.main.server_store", store):
            result = runner.invoke(cli, ["remove", "-s", connect_cloud.SERVER_NAME])
        self.assertEqual(result.exit_code, 1, result.output)
        # `remove` reports through cli_feedback, so the message lands on stdout.
        self.assertIn("Several Posit Connect Cloud credentials are saved", result.output)
        self.assertIsNotNone(store.get_by_name("personal"))
        self.assertIsNotNone(store.get_by_name("ci"))

    def test_a_connect_server_url_is_unaffected(self):
        store = ServerStore(base_dir=tempfile.mkdtemp())
        store.set("prod", "https://connect.example.com", api_key="key")
        entry = store.get_by_url("https://connect.example.com")
        assert entry is not None
        self.assertEqual(entry["name"], "prod")


class TestConnectCloudKeyringStorage(CliTestCase):
    """Connect Cloud secrets go to the system keyring when there is one, keyed by URL
    and nickname because one URL covers every Connect Cloud credential. The
    servers.json fields stay as the fallback for machines without a usable keyring."""

    def setUp(self):
        super().setUp()
        self.keyring = _use_fake_keyring(self)
        self.base_dir = os.path.dirname(self.store.get_path())
        # Token write-back opens its own store, inside the function, from this module.
        store_patch = mock.patch("rsconnect.metadata.ServerStore", lambda: ServerStore(base_dir=self.base_dir))
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def _stored(self, field: str, nickname: str = "cloud") -> Optional[str]:
        return self.keyring.get_password("rsconnect-python", "%s#%s:%s" % (API, nickname, field))

    def _store_in_keyring(self, field: str, value: str, nickname: str = "cloud") -> None:
        self.keyring.set_password("rsconnect-python", "%s#%s:%s" % (API, nickname, field), value)

    def _saved_entry(self, nickname: str = "cloud") -> Any:
        entry = ServerStore(base_dir=self.base_dir).get_by_name(nickname)
        assert entry is not None
        return entry

    def _refresh(self, **kwargs: Any) -> bool:
        server = ConnectCloudServer("acme", access_token="stale", refresh_token="rt", server_name="cloud")
        client = ConnectCloudClient(server)
        with mock.patch("rsconnect.connect_cloud.refresh", **kwargs):
            return client._attempt_token_refresh()

    def test_add_stores_the_tokens_in_the_keyring_and_not_in_the_file(self):
        self._mock_device_login()
        result = self.runner.invoke(cli, ["add", "-n", "cloud", "--connect-cloud", "-A", "acme"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._stored("access_token"), "at")
        self.assertEqual(self._stored("refresh_token"), "rt")
        entry = self._saved_entry()
        self.assertNotIn("connect_cloud_access_token", entry)
        self.assertNotIn("connect_cloud_refresh_token", entry)
        self.assertEqual(entry["connect_cloud_account_name"], "acme")

    def test_add_stores_a_service_account_secret_in_the_keyring(self):
        with mock.patch(
            "rsconnect.connect_cloud.request_client_credentials_token", return_value={"access_token": "at"}
        ):
            result = self.runner.invoke(
                cli,
                ["add", "-n", "cloud", "--connect-cloud", "-A", "acme", "--client-id", "cid", "--client-secret", "sec"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self._stored("client_secret"), "sec")
        entry = self._saved_entry()
        self.assertNotIn("connect_cloud_client_secret", entry)
        # The client id is not a secret, and is what `list` shows to identify the credential.
        self.assertEqual(entry["connect_cloud_client_id"], "cid")

    def test_each_nickname_keys_its_own_entries(self):
        self._mock_device_login()
        for nickname in ("cloud", "other"):
            result = self.runner.invoke(cli, ["add", "-n", nickname, "--connect-cloud", "-A", "acme"])
            self.assertEqual(result.exit_code, 0, result.output)

        self.assertEqual(self._stored("access_token"), "at")
        self.assertEqual(self._stored("access_token", nickname="other"), "at")
        self.assertEqual(len(self.keyring.passwords), 4)

    def test_the_keyring_wins_over_the_fields_left_in_the_file(self):
        # An entry saved before keyring support keeps its plaintext fields until the
        # next add or refresh; whatever the keyring holds is used meanwhile.
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_access_token="file-at",
            connect_cloud_refresh_token="file-rt",
            connect_cloud_client_secret="file-secret",
        )
        self._store_in_keyring("access_token", "keyring-at")

        data = self.store.resolve("cloud", None)

        self.assertEqual(data.connect_cloud_access_token, "keyring-at")
        self.assertEqual(data.connect_cloud_refresh_token, "file-rt")
        self.assertEqual(data.connect_cloud_client_secret, "file-secret")

    def test_a_refresh_moves_the_tokens_out_of_the_file(self):
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_access_token="stale",
            connect_cloud_refresh_token="rt",
        )

        self.assertTrue(self._refresh(return_value={"access_token": "new-at", "refresh_token": "new-rt"}))

        self.assertEqual(self._stored("access_token"), "new-at")
        self.assertEqual(self._stored("refresh_token"), "new-rt")
        entry = self._saved_entry()
        self.assertNotIn("connect_cloud_access_token", entry)
        self.assertNotIn("connect_cloud_refresh_token", entry)

    def test_a_refresh_moves_a_client_secret_out_of_the_file_too(self):
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="file-secret",
            connect_cloud_refresh_token="rt",
        )

        self.assertTrue(self._refresh(return_value={"access_token": "new-at"}))

        self.assertEqual(self._stored("client_secret"), "file-secret")
        entry = self._saved_entry()
        self.assertNotIn("connect_cloud_client_secret", entry)
        self.assertEqual(entry["connect_cloud_client_id"], "cid")

    def test_a_refresh_keeps_a_client_secret_that_is_already_in_the_keyring(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme", connect_cloud_client_id="cid")
        self._store_in_keyring("client_secret", "keyring-secret")

        self.assertTrue(self._refresh(return_value={"access_token": "new-at"}))

        self.assertEqual(self._stored("client_secret"), "keyring-secret")

    def test_a_refresh_does_not_overwrite_the_keyring_secret_with_the_files(self):
        # A secret in both places means the file's copy predates the one in use; the
        # keyring is what reads prefer, so it stays and the stale copy goes.
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="file-secret",
        )
        self._store_in_keyring("client_secret", "keyring-secret")

        self.assertTrue(self._refresh(return_value={"access_token": "new-at"}))

        self.assertEqual(self._stored("client_secret"), "keyring-secret")
        self.assertNotIn("connect_cloud_client_secret", self._saved_entry())

    def test_a_keyring_read_failure_leaves_the_client_secret_where_it_is(self):
        # A read that failed says nothing about what the keyring holds, so the
        # file's copy is neither written over it nor dropped from the file.
        self.store.set(
            "cloud",
            API,
            connect_cloud_account_name="acme",
            connect_cloud_client_id="cid",
            connect_cloud_client_secret="file-secret",
            connect_cloud_refresh_token="rt",
        )
        secret_username = "%s#cloud:%s" % (API, "client_secret")
        stored = self.keyring.get_password

        def failing_read(service: str, username: str) -> Optional[str]:
            if username == secret_username:
                raise Exception("keychain locked")
            return stored(service, username)

        with mock.patch.object(self.keyring, "get_password", side_effect=failing_read):
            self.assertTrue(self._refresh(return_value={"access_token": "new-at"}))

        self.assertIsNone(self._stored("client_secret"))
        self.assertEqual(self._saved_entry()["connect_cloud_client_secret"], "file-secret")

    def test_replacing_a_credential_discards_its_keyring_values(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "at")

        self.store.set("cloud", "https://connect.example.com", api_key="key")

        self.assertEqual(self.keyring.passwords, {})

    def test_moving_a_credential_to_another_environment_discards_the_old_values(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "at")

        self.store.set("cloud", "https://api.staging.connect.posit.cloud/v1", connect_cloud_account_name="acme")

        self.assertEqual(self.keyring.passwords, {})

    def test_resaving_the_same_credential_keeps_its_keyring_values(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "at")

        self.store.set("cloud", API, connect_cloud_account_name="other-account")

        self.assertEqual(self._stored("access_token"), "at")

    def test_an_expired_refresh_token_clears_the_keyring_tokens(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "stale")
        self._store_in_keyring("refresh_token", "rt")
        self._store_in_keyring("client_secret", "sec")

        with self.assertRaises(RSConnectException):
            self._refresh(side_effect=InvalidGrantError())

        self.assertIsNone(self._stored("access_token"))
        self.assertIsNone(self._stored("refresh_token"))
        # Only the dead tokens go; the credential itself is what gets re-authenticated.
        self.assertEqual(self._stored("client_secret"), "sec")

    def test_remove_deletes_the_keyring_entries(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        for field in ("access_token", "refresh_token", "client_secret"):
            self._store_in_keyring(field, field + "-value")

        result = self.runner.invoke(cli, ["remove", "-n", "cloud"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.keyring.passwords, {})

    def test_remove_by_url_deletes_the_keyring_entries(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "at")

        result = self.runner.invoke(cli, ["remove", "-s", connect_cloud.SERVER_NAME])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.keyring.passwords, {})

    def test_list_reports_credentials_in_the_keyring(self):
        self.store.set("cloud", API, connect_cloud_account_name="acme")
        self._store_in_keyring("access_token", "at")

        result = self.runner.invoke(cli, ["list"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Credentials stored in system keyring", result.output)
        self.assertNotIn("Credentials are saved", result.output)


class TestConnectCloudServerValidation(unittest.TestCase):
    def _executor(self, visibility=None, server=None):
        executor = RSConnectExecutor.__new__(RSConnectExecutor)
        executor.remote_server = server or ConnectCloudServer("acme", access_token="at")
        executor.client = mock.Mock(spec=ConnectCloudClient)
        executor.client.__enter__ = mock.Mock(return_value=executor.client)
        executor.client.__exit__ = mock.Mock(return_value=False)
        executor.client.get_account_by_name.return_value = {"id": "acct-1", "name": "acme"}
        executor.visibility = visibility
        return executor

    def test_visibility_is_accepted(self):
        # Connect Cloud content has an access level, which -V sets.
        executor = self._executor("private")
        executor.validate_connect_cloud_server()
        executor.client.get_current_user.assert_called_once()

    def test_no_visibility_is_accepted(self):
        executor = self._executor()
        executor.validate_connect_cloud_server()
        executor.client.get_current_user.assert_called_once()

    def test_validation_resolves_the_account_id_when_none_is_saved(self):
        # Deployment records are keyed by account id; resolving it here, before
        # validate_app_mode reads the records, keeps redeployments finding their
        # content after an account rename.
        executor = self._executor()
        executor.validate_connect_cloud_server()
        executor.client.get_account_by_name.assert_called_once_with("acme")
        self.assertEqual(executor.remote_server.account_id, "acct-1")

    def test_validation_keeps_a_saved_account_id_without_a_lookup(self):
        executor = self._executor(server=ConnectCloudServer("acme", access_token="at", account_id="acct-saved"))
        executor.validate_connect_cloud_server()
        executor.client.get_account_by_name.assert_not_called()
        self.assertEqual(executor.remote_server.account_id, "acct-saved")

    def test_missing_credentials_are_reported(self):
        executor = self._executor(server=ConnectCloudServer("acme"))
        with self.assertRaises(RSConnectException) as context:
            executor.validate_connect_cloud_server()
        message = str(context.exception)
        self.assertIn("No Posit Connect Cloud credentials found", message)
        # The hint gets copied verbatim, and `add` without a nickname stores an entry
        # under a null name rather than failing.
        self.assertIn("rsconnect add -n <nickname> -s connect.posit.cloud -A <account>", message)


if __name__ == "__main__":
    unittest.main()
