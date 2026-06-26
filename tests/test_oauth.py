from __future__ import annotations

import base64
import hashlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rsconnect.exception import RSConnectException
from rsconnect.http_support import HTTPResponse
from rsconnect.metadata import ServerData
from rsconnect.oauth import (
    InvalidClientError,
    _exchange_code_for_token,
    _poll_for_device_token,
    discover_oauth_metadata,
    exchange_token_for_api_key,
    generate_pkce_pair,
    keyring_delete_tokens,
    keyring_get_tokens,
    keyring_store_token,
    login_with_browser,
    login_with_device_code,
    refresh_access_token,
    register_client,
)


FAKE_URL = "https://connect.example.com"
FAKE_METADATA: dict[str, Any] = {
    "issuer": FAKE_URL,
    "authorization_endpoint": f"{FAKE_URL}/oauth/v1/authorize",
    "token_endpoint": f"{FAKE_URL}/oauth/v1/token",
    "registration_endpoint": f"{FAKE_URL}/oauth/v1/register",
    "device_authorization_endpoint": f"{FAKE_URL}/oauth/v1/device",
}


def _make_response(status: int = 200, json_data: Any = None) -> HTTPResponse:
    response = HTTPResponse("", body=b"")
    response.status = status
    response.json_data = json_data
    return response


@pytest.fixture
def mock_http_server():
    with patch("rsconnect.oauth.HTTPServer") as mock_cls:
        mock_server = MagicMock()
        mock_cls.return_value = mock_server
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)
        yield mock_server


class TestPKCE:
    def test_generates_valid_pair(self):
        verifier, challenge = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert challenge == expected_challenge


class TestDiscoverOAuthMetadata:
    def test_success(self, mock_http_server: MagicMock):
        mock_http_server.get.return_value = _make_response(200, FAKE_METADATA)
        result = discover_oauth_metadata(FAKE_URL)
        assert result == FAKE_METADATA

    def test_server_not_supporting_oauth(self, mock_http_server: MagicMock):
        mock_http_server.get.return_value = _make_response(404, None)
        with pytest.raises(RSConnectException, match="does not support OAuth"):
            discover_oauth_metadata(FAKE_URL)

    def test_missing_token_endpoint(self, mock_http_server: MagicMock):
        mock_http_server.get.return_value = {"issuer": FAKE_URL}
        with pytest.raises(RSConnectException, match="invalid OAuth metadata"):
            discover_oauth_metadata(FAKE_URL)


class TestRegisterClient:
    def test_success(self, mock_http_server: MagicMock):
        mock_http_server.post.return_value = _make_response(200, {"client_id": "test-client-123"})
        result = register_client(FAKE_METADATA, FAKE_URL)
        assert result == "test-client-123"

    def test_failure(self, mock_http_server: MagicMock):
        mock_http_server.post.return_value = _make_response(
            400, {"error": "invalid_request", "error_description": "bad request"}
        )
        with pytest.raises(RSConnectException, match="OAuth error"):
            register_client(FAKE_METADATA, FAKE_URL)

    def test_missing_registration_endpoint(self):
        metadata = {k: v for k, v in FAKE_METADATA.items() if k != "registration_endpoint"}
        with pytest.raises(RSConnectException, match="registration_endpoint"):
            register_client(metadata, FAKE_URL)


class TestTokenExchange:
    def test_success(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(
            200, {"access_token": "at-123", "refresh_token": "rt-456", "expires_in": 3600}
        )
        result = _exchange_code_for_token(
            FAKE_METADATA, "client-1", "auth-code", "verifier", "http://127.0.0.1:8080/callback"
        )
        assert result["access_token"] == "at-123"

    def test_invalid_client(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(401, {"error": "invalid_client"})
        with pytest.raises(InvalidClientError):
            _exchange_code_for_token(
                FAKE_METADATA, "bad-client", "auth-code", "verifier", "http://127.0.0.1:8080/callback"
            )


class TestExchangeTokenForApiKey:
    def test_success(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(200, {"access_token": "minted-key"})
        result = exchange_token_for_api_key(FAKE_URL, "oidc-token")
        assert result == "minted-key"
        # RFC 8693 token-exchange request shape.
        body = mock_http_server.request.call_args.kwargs["body"]
        assert b"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange" in body
        assert b"subject_token=oidc-token" in body

    def test_success_no_access_token(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(200, {"something_else": "x"})
        with pytest.raises(RSConnectException, match="no API key"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_server_too_old_404(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(404, None)
        with pytest.raises(RSConnectException, match="too old to support trusted publishing"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_unsupported_grant_type(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(400, {"error": "unsupported_grant_type"})
        with pytest.raises(RSConnectException, match="does not support token exchange"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_no_trusted_publisher(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(
            400, {"error": "invalid_grant", "error_description": "no service principal found"}
        )
        with pytest.raises(RSConnectException, match="did not recognize this token as a trusted publisher"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_ambiguous_trusted_publisher(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(
            400, {"error": "invalid_grant", "error_description": "ambiguous match"}
        )
        with pytest.raises(RSConnectException, match="more than one trusted publisher"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_verification_failure(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(
            400, {"error": "invalid_grant", "error_description": "could not verify token signature"}
        )
        with pytest.raises(RSConnectException, match="could not verify the OIDC token"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")

    def test_generic_failure(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(500, {"error": "boom", "error_description": "kaboom"})
        with pytest.raises(RSConnectException, match="HTTP 500"):
            exchange_token_for_api_key(FAKE_URL, "oidc-token")


class TestDeviceCodeFlow:
    def test_device_code_not_supported(self):
        metadata = {k: v for k, v in FAKE_METADATA.items() if k != "device_authorization_endpoint"}
        with pytest.raises(RSConnectException, match="does not support the device code flow"):
            login_with_device_code(FAKE_URL, "client-1", metadata)

    @patch("rsconnect.oauth.time.sleep")
    def test_poll_success(self, _, mock_http_server: MagicMock):
        mock_http_server.request.side_effect = [
            _make_response(400, {"error": "authorization_pending"}),
            _make_response(200, {"access_token": "at-final", "refresh_token": "rt-final"}),
        ]
        result = _poll_for_device_token(FAKE_METADATA, "client-1", "device-code-1", 5, 600)
        assert result["access_token"] == "at-final"

    @patch("rsconnect.oauth.time.sleep")
    def test_poll_expired(self, _, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(400, {"error": "expired_token"})
        with pytest.raises(RSConnectException, match="expired"):
            _poll_for_device_token(FAKE_METADATA, "client-1", "device-code-1", 5, 600)

    @patch("rsconnect.oauth.time.sleep")
    def test_poll_invalid_client(self, _, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(401, {"error": "invalid_client"})
        with pytest.raises(InvalidClientError):
            _poll_for_device_token(FAKE_METADATA, "bad-client", "device-code-1", 5, 600)

    @patch("rsconnect.oauth.time.sleep")
    def test_poll_malformed_response(self, _, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(200, {})
        with pytest.raises(RSConnectException, match="unexpected response"):
            _poll_for_device_token(FAKE_METADATA, "client-1", "device-code-1", 5, 600)


class TestRefreshAccessToken:
    def test_success(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(
            200, {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 7200}
        )
        result = refresh_access_token(FAKE_METADATA, "client-1", "old-rt")
        assert result["access_token"] == "new-at"

    def test_invalid_client(self, mock_http_server: MagicMock):
        mock_http_server.request.return_value = _make_response(401, {"error": "invalid_client"})
        with pytest.raises(InvalidClientError):
            refresh_access_token(FAKE_METADATA, "bad-client", "old-rt")


class TestKeyringIntegration:
    def test_store_success(self):
        mock_keyring = MagicMock()
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            result = keyring_store_token("https://example.com", "at-1", "rt-1")
        assert result is True
        assert mock_keyring.set_password.call_count == 2

    def test_store_no_keyring(self):
        with patch.dict("sys.modules", {"keyring": None}):
            result = keyring_store_token("https://example.com", "at-1", "rt-1")
        assert result is False

    def test_get_success(self):
        mock_keyring = MagicMock()
        mock_keyring.get_password.side_effect = lambda svc, key: "token-value"
        with patch.dict("sys.modules", {"keyring": mock_keyring}):
            access, refresh = keyring_get_tokens("https://example.com")
        assert access == "token-value"
        assert refresh == "token-value"

    def test_get_no_keyring(self):
        with patch.dict("sys.modules", {"keyring": None}):
            access, refresh = keyring_get_tokens("https://example.com")
        assert access is None
        assert refresh is None

    def test_delete_success(self):
        mock_keyring = MagicMock()
        mock_keyring_errors = MagicMock()
        mock_keyring_errors.PasswordDeleteError = Exception
        with patch.dict("sys.modules", {"keyring": mock_keyring, "keyring.errors": mock_keyring_errors}):
            keyring_delete_tokens("https://example.com")
        assert mock_keyring.delete_password.call_count == 2


class TestLoginWithBrowser:
    @patch("rsconnect.oauth.webbrowser.open", return_value=True)
    @patch("rsconnect.oauth._exchange_code_for_token")
    @patch("rsconnect.oauth._HTTPServer")
    @patch("rsconnect.oauth.secrets.token_urlsafe", return_value="fixed-state")
    def test_success(
        self,
        mock_token_urlsafe: MagicMock,
        mock_httpserver_cls: MagicMock,
        mock_exchange: MagicMock,
        mock_browser: MagicMock,
    ):
        mock_exchange.return_value = {"access_token": "at-browser", "refresh_token": "rt-browser"}

        mock_server_instance = MagicMock()
        mock_server_instance.server_address = ("127.0.0.1", 9999)
        mock_httpserver_cls.return_value = mock_server_instance

        # When handle_request is called in the thread, simulate putting
        # the auth code onto the result_queue that the function created
        def fake_handle_request():
            # The function sets result_queue on RequestHandlerClass before starting the thread
            rq = mock_server_instance.RequestHandlerClass.result_queue
            rq.put(("success", "auth-code-123", "fixed-state"))

        mock_server_instance.handle_request.side_effect = fake_handle_request

        result = login_with_browser(FAKE_URL, "client-1", FAKE_METADATA)

        assert result == {"access_token": "at-browser", "refresh_token": "rt-browser"}
        mock_browser.assert_called_once()


class TestExecutorOAuthSetup:
    @pytest.mark.parametrize(
        "keyring_token,expected_token",
        [
            ("keyring-access-token", "keyring-access-token"),
            (None, "stored-fallback-token"),
        ],
        ids=["keyring-available", "keyring-fallback"],
    )
    def test_setup_remote_server_with_oauth_entry(self, keyring_token, expected_token):
        from rsconnect.api import RSConnectExecutor, RSConnectServer

        with patch("rsconnect.oauth.keyring_get_tokens", return_value=(keyring_token, None)):
            with patch("rsconnect.metadata.ServerStore.resolve") as mock_resolve:
                mock_resolve.return_value = ServerData(
                    name="myserver",
                    url=FAKE_URL,
                    from_store=True,
                    oauth_client_id="client-123",
                    oauth_access_token="stored-fallback-token",
                )

                executor = RSConnectExecutor.__new__(RSConnectExecutor)
                executor.logger = None
                executor.ctx = None
                executor.setup_remote_server(ctx=None, name="myserver")

        assert isinstance(executor.remote_server, RSConnectServer)
        assert executor.remote_server.oauth_access_token == expected_token
        assert executor.remote_server.oauth_client_id == "client-123"


class TestRefreshTokenFallback:
    @pytest.mark.parametrize(
        "server_name,get_by_name_rv,get_by_url_rv",
        [
            ("testserver", {"oauth_refresh_token": "stored-rt"}, None),
            (FAKE_URL, None, {"oauth_refresh_token": "url-rt", "name": "myserver"}),
            (None, None, {"oauth_refresh_token": "url-rt", "name": "resolved-name"}),
        ],
        ids=["name-lookup", "url-fallback", "no-server-name"],
    )
    @patch("rsconnect.oauth.HTTPServer")
    @patch("rsconnect.oauth.keyring_get_tokens", return_value=(None, None))
    @patch("rsconnect.oauth.keyring_store_token", return_value=False)
    def test_refresh_falls_back_to_store(
        self,
        mock_keyring_store: MagicMock,
        mock_keyring_get: MagicMock,
        mock_http_server_cls: MagicMock,
        server_name: "str | None",
        get_by_name_rv: Any,
        get_by_url_rv: Any,
    ):
        from rsconnect.api import RSConnectClient, RSConnectServer
        from rsconnect.metadata import ServerStore

        mock_http_server = MagicMock()
        mock_http_server_cls.return_value = mock_http_server
        mock_http_server.__enter__ = MagicMock(return_value=mock_http_server)
        mock_http_server.__exit__ = MagicMock(return_value=False)

        mock_http_server.get.return_value = _make_response(200, FAKE_METADATA)
        mock_http_server.request.return_value = _make_response(
            200, {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 3600}
        )

        server = RSConnectServer(
            FAKE_URL,
            None,
            False,
            None,
            oauth_access_token="old-at",
            oauth_client_id="client-1",
            server_name=server_name,
        )

        with patch.object(ServerStore, "get_by_name", return_value=get_by_name_rv):
            with patch.object(ServerStore, "get_by_url", return_value=get_by_url_rv):
                with patch.object(ServerStore, "update_oauth_tokens"):
                    client = RSConnectClient(server)
                    result = client._attempt_token_refresh()

        assert result is True


class TestStreamBodyRetry:
    def test_seekable_stream_rewinds_for_retry(self):
        import io

        from rsconnect.api import RSConnectClient, RSConnectServer
        from rsconnect.http_support import HTTPServer as _HTTPServer

        server = RSConnectServer(
            FAKE_URL,
            None,
            False,
            None,
            oauth_access_token="old-at",
            oauth_client_id="client-1",
            server_name="testserver",
        )

        client = RSConnectClient(server)
        stream_body = io.BytesIO(b"bundle-payload-data")
        call_bodies: list[object] = []

        def fake_super_request(
            self_arg, method, path, query_params, body, maximum_redirects=5, decode_response=True, headers=None
        ):
            call_bodies.append(body.read() if hasattr(body, "read") else body)
            return _make_response(401, None) if len(call_bodies) == 1 else _make_response(200, {"result": "ok"})

        with patch.object(_HTTPServer, "request", fake_super_request):
            with patch.object(client, "_attempt_token_refresh", return_value=True):
                client.request("POST", "/v1/content/upload", body=stream_body)

        assert len(call_bodies) == 2
        assert call_bodies[0] == b"bundle-payload-data"
        assert call_bodies[1] == b"bundle-payload-data"

    def test_non_seekable_stream_buffered_for_retry(self):
        import io

        from rsconnect.api import RSConnectClient, RSConnectServer
        from rsconnect.http_support import HTTPServer as _HTTPServer

        class NonSeekableStream(io.RawIOBase):
            def __init__(self, data: bytes):
                self._data = data
                self._pos = 0

            def read(self, size=-1):
                if size == -1:
                    result = self._data[self._pos :]
                else:
                    result = self._data[self._pos : self._pos + size]
                self._pos += len(result)
                return result

            def readable(self):
                return True

            def seekable(self):
                return False

        server = RSConnectServer(
            FAKE_URL,
            None,
            False,
            None,
            oauth_access_token="old-at",
            oauth_client_id="client-1",
            server_name="testserver",
        )

        client = RSConnectClient(server)
        stream_body = NonSeekableStream(b"bundle-payload-data")
        call_bodies: list[object] = []

        def fake_super_request(
            self_arg, method, path, query_params, body, maximum_redirects=5, decode_response=True, headers=None
        ):
            call_bodies.append(body)
            return _make_response(401, None) if len(call_bodies) == 1 else _make_response(200, {"result": "ok"})

        with patch.object(_HTTPServer, "request", fake_super_request):
            with patch.object(client, "_attempt_token_refresh", return_value=True):
                client.request("POST", "/v1/content/upload", body=stream_body)

        assert len(call_bodies) == 2
        assert call_bodies[0] == b"bundle-payload-data"
        assert call_bodies[1] == b"bundle-payload-data"


class TestLoginCommand:
    @patch("rsconnect.oauth.keyring_store_token", return_value=True)
    @patch("rsconnect.oauth.login_with_browser")
    @patch("rsconnect.oauth.register_client", return_value="new-client-id")
    @patch("rsconnect.oauth.discover_oauth_metadata")
    def test_login_success(
        self,
        mock_discover: MagicMock,
        mock_register: MagicMock,
        mock_login: MagicMock,
        mock_keyring: MagicMock,
    ):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_discover.return_value = FAKE_METADATA
        mock_login.return_value = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}

        runner = CliRunner()
        result = runner.invoke(cli, ["login", "--server", FAKE_URL, "--name", "test-server"])

        assert result.exit_code == 0, result.output
        assert "Logged in" in result.output

    @patch("rsconnect.oauth.keyring_store_token", return_value=True)
    @patch("rsconnect.oauth.login_with_browser")
    @patch("rsconnect.oauth.register_client", return_value="new-client-id")
    @patch("rsconnect.oauth.discover_oauth_metadata")
    def test_login_positional_server(
        self,
        mock_discover: MagicMock,
        mock_register: MagicMock,
        mock_login: MagicMock,
        mock_keyring: MagicMock,
    ):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_discover.return_value = FAKE_METADATA
        mock_login.return_value = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}

        runner = CliRunner()
        result = runner.invoke(cli, ["login", FAKE_URL, "--name", "test-server"])

        assert result.exit_code == 0, result.output
        assert "Logged in" in result.output

    @patch("rsconnect.oauth.keyring_store_token", return_value=True)
    @patch("rsconnect.oauth.login_with_browser")
    @patch("rsconnect.oauth.register_client", return_value="new-client-id")
    @patch("rsconnect.oauth.discover_oauth_metadata")
    def test_login_positional_server_overrides_connect_server_env(
        self,
        mock_discover: MagicMock,
        mock_register: MagicMock,
        mock_login: MagicMock,
        mock_keyring: MagicMock,
    ):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_discover.return_value = FAKE_METADATA
        mock_login.return_value = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["login", FAKE_URL, "--name", "test-server"],
            env={"CONNECT_SERVER": "https://env-server.example.com"},
        )

        assert result.exit_code == 0, result.output
        assert "Logged in" in result.output
        # The positional argument should win over the CONNECT_SERVER envvar.
        assert mock_discover.call_args.args[0] == FAKE_URL

    @patch("rsconnect.main.server_store")
    @patch("rsconnect.main.test_api_key")
    @patch("rsconnect.main.test_server")
    @patch("rsconnect.oauth.exchange_token_for_api_key", return_value="minted-key")
    def test_login_with_token_exchange(
        self,
        mock_exchange: MagicMock,
        mock_test_server: MagicMock,
        mock_test_api_key: MagicMock,
        mock_store: MagicMock,
    ):
        from click.testing import CliRunner

        from rsconnect.api import RSConnectServer
        from rsconnect.main import cli

        real_server = RSConnectServer(FAKE_URL, "minted-key")
        mock_test_server.return_value = (real_server, None)

        runner = CliRunner()
        result = runner.invoke(cli, ["login", FAKE_URL, "--name", "ci-server", "--token", "oidc-token"])

        assert result.exit_code == 0, result.output
        assert "via OIDC token exchange" in result.output
        mock_exchange.assert_called_once()
        assert mock_exchange.call_args.args[1] == "oidc-token"
        # The minted key is stored as the server's API key.
        assert mock_store.set.call_args.kwargs["api_key"] == "minted-key"

    @patch("rsconnect.main.server_store")
    @patch("rsconnect.main.test_api_key")
    @patch("rsconnect.main.test_server")
    @patch("rsconnect.oauth.exchange_token_for_api_key", return_value="minted-key")
    def test_login_with_token_from_stdin(
        self,
        mock_exchange: MagicMock,
        mock_test_server: MagicMock,
        mock_test_api_key: MagicMock,
        mock_store: MagicMock,
    ):
        from click.testing import CliRunner

        from rsconnect.api import RSConnectServer
        from rsconnect.main import cli

        real_server = RSConnectServer(FAKE_URL, "minted-key")
        mock_test_server.return_value = (real_server, None)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["login", FAKE_URL, "--name", "ci-server", "--token", "-"],
            input="oidc-from-stdin\n",
        )

        assert result.exit_code == 0, result.output
        assert mock_exchange.call_args.args[1] == "oidc-from-stdin"

    def test_login_with_empty_token(self):
        from click.testing import CliRunner

        from rsconnect.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["login", FAKE_URL, "--token", "   "])

        assert result.exit_code != 0
        assert "No OIDC token" in result.output

    def test_login_positional_and_option_server_conflict(self):
        from click.testing import CliRunner

        from rsconnect.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["login", FAKE_URL, "--server", FAKE_URL])

        assert result.exit_code != 0
        assert "only one of SERVER" in result.output

    def test_login_missing_server(self):
        from click.testing import CliRunner

        from rsconnect.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["login"])

        assert "Usage:" in result.output

    @patch("rsconnect.oauth.keyring_delete_tokens")
    @patch("rsconnect.main.server_store")
    def test_logout_non_oauth_entry(self, mock_store: MagicMock, mock_keyring_del: MagicMock):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_store.get_by_name.return_value = {"name": "myserver", "url": FAKE_URL, "api_key": "key-123"}

        runner = CliRunner()
        result = runner.invoke(cli, ["logout", "--name", "myserver"])

        assert result.exit_code != 0
        assert "not an OAuth" in result.output or "rsconnect remove" in result.output

    @patch("rsconnect.oauth.keyring_delete_tokens")
    @patch("rsconnect.main.server_store")
    def test_logout_success(self, mock_store: MagicMock, mock_keyring_del: MagicMock):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_store.get_by_name.return_value = {
            "name": "myserver",
            "url": FAKE_URL,
            "oauth_client_id": "client-123",
        }
        mock_store.update_oauth_tokens = MagicMock()

        runner = CliRunner()
        result = runner.invoke(cli, ["logout", "--name", "myserver"])

        assert result.exit_code == 0, result.output
        mock_keyring_del.assert_called_once()

    @patch("rsconnect.oauth.keyring_delete_tokens")
    @patch("rsconnect.main.server_store")
    def test_logout_positional_server(self, mock_store: MagicMock, mock_keyring_del: MagicMock):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_store.get_by_url.return_value = {
            "name": "myserver",
            "url": FAKE_URL,
            "oauth_client_id": "client-123",
        }
        mock_store.update_oauth_tokens = MagicMock()

        runner = CliRunner()
        result = runner.invoke(cli, ["logout", FAKE_URL])

        assert result.exit_code == 0, result.output
        mock_keyring_del.assert_called_once()


class TestListCommand:
    @patch("rsconnect.oauth.keyring_get_tokens", return_value=("at-from-keyring", None))
    @patch("rsconnect.main.server_store")
    def test_list_oauth_entry_with_keyring(self, mock_store: MagicMock, mock_keyring: MagicMock):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_store.get_all_servers.return_value = [
            {"name": "myserver", "url": FAKE_URL, "oauth_client_id": "client-abc"},
        ]
        mock_store.get_path.return_value = "/tmp/servers.json"

        runner = CliRunner()
        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0, result.output
        assert "OAuth Client ID: client-abc" in result.output
        assert "Credentials stored in system keyring" in result.output

    @patch("rsconnect.oauth.keyring_get_tokens", return_value=(None, None))
    @patch("rsconnect.main.server_store")
    def test_list_oauth_entry_without_keyring(self, mock_store: MagicMock, mock_keyring: MagicMock):
        from click.testing import CliRunner

        from rsconnect.main import cli

        mock_store.get_all_servers.return_value = [
            {"name": "myserver", "url": FAKE_URL, "oauth_client_id": "client-abc"},
        ]
        mock_store.get_path.return_value = "/tmp/servers.json"

        runner = CliRunner()
        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0, result.output
        assert "OAuth Client ID: client-abc" in result.output
        assert "Credentials stored in system keyring" not in result.output
