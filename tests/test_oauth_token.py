"""Tests for the shared OAuth token refresh and the `rsconnect token` command."""

from __future__ import annotations

import inspect
import json
import threading
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from rsconnect.exception import RSConnectException
from rsconnect.metadata import ServerStore
from rsconnect.oauth import (
    InvalidClientError,
    InvalidGrantError,
    NotLoggedInError,
    _refresh_lock,
    refresh_stored_tokens,
    stored_tokens,
)

FAKE_URL = "https://connect.example.com"
FAKE_METADATA: dict[str, Any] = {"token_endpoint": f"{FAKE_URL}/oauth/v1/token"}


@pytest.fixture
def store(tmp_path: Any) -> Iterator[ServerStore]:
    """A server store in a temporary directory, used by both the command and the refresh."""
    server_store = ServerStore(str(tmp_path))
    with patch("rsconnect.main.server_store", server_store):
        with patch("rsconnect.metadata.ServerStore", return_value=server_store):
            yield server_store


@pytest.fixture
def keyring() -> Iterator[dict[str, tuple[Any, Any]]]:
    """An in-memory stand-in for the keyring, keyed by server URL."""
    tokens: dict[str, tuple[Any, Any]] = {}

    def store_token(key: str, access_token: Any, refresh_token: Any) -> bool:
        tokens[key] = (access_token, refresh_token)
        return True

    with patch("rsconnect.oauth.keyring_get_tokens", side_effect=lambda key: tokens.get(key, (None, None))):
        with patch("rsconnect.oauth.keyring_store_token", side_effect=store_token):
            with patch("rsconnect.oauth.keyring_delete_tokens", side_effect=lambda key: tokens.pop(key, None)):
                yield tokens


@pytest.fixture
def token_endpoint() -> Iterator[MagicMock]:
    """Patch OAuth discovery, and return the mock for the refresh token request."""
    with patch("rsconnect.oauth.discover_oauth_metadata", return_value=FAKE_METADATA):
        with patch("rsconnect.oauth.refresh_access_token") as refresh:
            refresh.return_value = {"access_token": "new-at", "refresh_token": "new-rt", "expires_in": 3600}
            yield refresh


def _runner() -> CliRunner:
    options = {"mix_stderr": False} if "mix_stderr" in inspect.signature(CliRunner).parameters else {}
    return CliRunner(**options)


def _invoke(args: list[str]) -> Any:
    from rsconnect.main import cli

    return _runner().invoke(cli, ["token", *args], env={"CONNECT_SERVER": None}, prog_name="rsconnect")


class TestStoredTokens:
    def test_reads_the_keyring(self, store: ServerStore, keyring: dict[str, Any]):
        keyring[FAKE_URL] = ("at", "rt")
        assert stored_tokens(FAKE_URL) == ("at", "rt")

    def test_falls_back_to_the_saved_entry(self, store: ServerStore, keyring: dict[str, Any]):
        store.set("myserver", FAKE_URL, oauth_client_id="c", oauth_access_token="at", oauth_refresh_token="rt")
        assert stored_tokens(FAKE_URL, "myserver") == ("at", "rt")


class TestRefreshStoredTokens:
    def test_refreshes_and_stores_rotated_tokens(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("old-at", "old-rt")

        result = refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token="old-at")

        assert result == "new-at"
        assert keyring[FAKE_URL] == ("new-at", "new-rt")
        assert token_endpoint.call_args.args[1:3] == ("client-1", "old-rt")

    def test_keeps_the_refresh_token_when_the_server_does_not_rotate_it(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("old-at", "old-rt")
        token_endpoint.return_value = {"access_token": "new-at"}

        refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token="old-at")

        assert keyring[FAKE_URL] == ("new-at", "old-rt")

    def test_returns_a_token_another_process_already_refreshed(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("newer-at", "newer-rt")

        result = refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token="old-at")

        assert result == "newer-at"
        token_endpoint.assert_not_called()

    def test_stores_in_the_saved_entry_without_a_keyring(self, store: ServerStore, token_endpoint: MagicMock):
        store.set("myserver", FAKE_URL, oauth_client_id="c", oauth_access_token="old-at", oauth_refresh_token="old-rt")
        with patch("rsconnect.oauth.keyring_get_tokens", return_value=(None, None)):
            with patch("rsconnect.oauth.keyring_store_token", return_value=False):
                refresh_stored_tokens(FAKE_URL, "c", "myserver", rejected_access_token="old-at")

        entry = store.get_by_name("myserver")
        assert entry is not None
        assert entry.get("oauth_access_token") == "new-at"
        assert entry.get("oauth_refresh_token") == "new-rt"
        assert isinstance(entry.get("oauth_token_expiry"), float)

    def test_not_logged_in_without_a_refresh_token(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        with pytest.raises(NotLoggedInError):
            refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token=None)
        token_endpoint.assert_not_called()

    def test_rejected_refresh_token_keeps_the_stored_tokens(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("old-at", "old-rt")
        token_endpoint.side_effect = InvalidGrantError()

        with pytest.raises(InvalidGrantError):
            refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token="old-at")
        assert keyring[FAKE_URL] == ("old-at", "old-rt")

    def test_deleted_client_clears_tokens_and_registers_a_new_client(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        store.set("myserver", FAKE_URL, oauth_client_id="client-1")
        keyring[FAKE_URL] = ("old-at", "old-rt")
        token_endpoint.side_effect = InvalidClientError()

        with patch("rsconnect.oauth.register_client", return_value="client-2"):
            with pytest.raises(InvalidClientError):
                refresh_stored_tokens(FAKE_URL, "client-1", "myserver", rejected_access_token="old-at")

        assert FAKE_URL not in keyring
        entry = store.get_by_name("myserver")
        assert entry is not None
        assert entry.get("oauth_client_id") == "client-2"


class TestRefreshLock:
    def test_a_second_holder_waits_for_the_first(self):
        with _refresh_lock():
            with pytest.raises(RSConnectException, match="Timed out"):
                with _refresh_lock(timeout=0.1):
                    pass
        # Released on exit, so it can be taken again.
        with _refresh_lock(timeout=0.1):
            pass

    def test_concurrent_refreshes_exchange_the_refresh_token_once(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("old-at", "old-rt")
        results: list[str] = []

        def refresh() -> None:
            results.append(refresh_stored_tokens(FAKE_URL, "client-1", rejected_access_token="old-at"))

        threads = [threading.Thread(target=refresh) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == ["new-at"] * 4
        assert token_endpoint.call_count == 1

    def test_refreshes_unlocked_when_the_lock_file_cannot_be_created(self, tmp_path: Any):
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("")
        with patch("rsconnect.oauth._refresh_lock_path", return_value=str(blocker / "oauth-refresh.lock")):
            with _refresh_lock():
                pass


class TestClientRefresh:
    """The refresh a client attempts when a request gets a 401."""

    def _client(self, access_token: str) -> Any:
        from rsconnect.api import RSConnectClient, RSConnectServer

        server = RSConnectServer(FAKE_URL, None, oauth_access_token=access_token, oauth_client_id="client-1")
        return RSConnectClient(server)

    def test_refreshes_and_applies_the_new_token(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("old-at", "old-rt")
        client = self._client("old-at")

        assert client._attempt_token_refresh() is True
        assert client._headers["Authorization"] == "Bearer new-at"
        assert keyring[FAKE_URL] == ("new-at", "new-rt")

    def test_uses_a_token_another_process_already_refreshed(
        self, store: ServerStore, keyring: dict[str, Any], token_endpoint: MagicMock
    ):
        keyring[FAKE_URL] = ("newer-at", "newer-rt")
        client = self._client("old-at")

        assert client._attempt_token_refresh() is True
        assert client._headers["Authorization"] == "Bearer newer-at"
        token_endpoint.assert_not_called()


class TestTokenCommand:
    @pytest.fixture(autouse=True)
    def logged_in(self, store: ServerStore, keyring: dict[str, Any]) -> None:
        store.set("myserver", FAKE_URL, oauth_client_id="client-1")
        keyring[FAKE_URL] = ("stored-at", "stored-rt")

    def test_prints_the_stored_token_without_contacting_the_server(self, token_endpoint: MagicMock):
        result = _invoke(["-n", "myserver"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "stored-at\n"
        token_endpoint.assert_not_called()

    def test_resolves_the_server_by_url(self):
        result = _invoke(["-s", FAKE_URL])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "stored-at\n"

    def test_uses_the_only_saved_server_by_default(self):
        result = _invoke([])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "stored-at\n"

    def test_json(self):
        result = _invoke(["-n", "myserver", "--format", "json"])

        assert result.exit_code == 0, result.stderr
        assert json.loads(result.stdout) == {"access_token": "stored-at", "token_type": "Bearer", "server": FAKE_URL}

    def test_refresh(self, keyring: dict[str, Any], token_endpoint: MagicMock):
        result = _invoke(["-n", "myserver", "--refresh"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "new-at\n"
        assert token_endpoint.call_args.args[2] == "stored-rt"
        assert keyring[FAKE_URL] == ("new-at", "new-rt")

    def test_refreshes_when_only_a_refresh_token_is_stored(self, keyring: dict[str, Any], token_endpoint: MagicMock):
        keyring[FAKE_URL] = (None, "stored-rt")

        result = _invoke(["-n", "myserver"])

        assert result.exit_code == 0, result.stderr
        assert result.stdout == "new-at\n"

    def test_logged_out(self, keyring: dict[str, Any]):
        keyring.clear()

        result = _invoke(["-n", "myserver"])

        assert result.exit_code == 4
        assert result.stdout == ""
        assert "Run 'rsconnect login' to log in." in result.stderr

    def test_revoked(self, token_endpoint: MagicMock):
        token_endpoint.side_effect = InvalidGrantError()

        result = _invoke(["-n", "myserver", "--refresh"])

        assert result.exit_code == 4
        assert result.stdout == ""
        assert "rejected the stored OAuth credentials" in result.stderr

    def test_other_refresh_failures_do_not_ask_for_login(self, token_endpoint: MagicMock):
        token_endpoint.side_effect = RSConnectException("OAuth request failed: HTTP 503.")

        result = _invoke(["-n", "myserver", "--refresh"])

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "HTTP 503" in result.stderr

    def test_never_prints_an_api_key(self, store: ServerStore):
        store.set("keyserver", "https://other.example.com", api_key="secret-api-key")

        result = _invoke(["-n", "keyserver"])

        assert result.exit_code == 4
        assert "secret-api-key" not in result.stdout + result.stderr
        assert "not added with OAuth login" in result.stderr

    def test_unknown_url(self):
        result = _invoke(["-s", "https://unknown.example.com"])

        assert result.exit_code == 4
        assert "No saved credentials" in result.stderr

    def test_unknown_nickname(self):
        result = _invoke(["-n", "nope"])

        assert result.exit_code == 1
        assert "does not exist" in result.stderr

    def test_no_server(self, store: ServerStore):
        store.set("second", "https://other.example.com", oauth_client_id="c")

        result = _invoke([])

        assert result.exit_code == 1
        assert "Specify a server" in result.stderr

    def test_login_hint_names_the_mounting_cli(self, keyring: dict[str, Any]):
        from rsconnect.main import cli

        keyring.clear()

        @click.group()
        def posit() -> None:
            pass

        @posit.group()
        def connect() -> None:
            pass

        connect.add_command(cli.commands["token"])

        result = _runner().invoke(posit, ["connect", "token", "-n", "myserver"], env={"CONNECT_SERVER": None})

        assert result.exit_code == 4
        assert "Run 'posit connect login' to log in." in result.stderr
