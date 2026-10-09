from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from rsconnect import connect_cloud, device_login, oauth
from rsconnect.environment import fake_module_file_from_directory
from rsconnect.exception import ConnectCloudAccountNotFoundError, RSConnectException
from rsconnect.http_support import HTTPResponse
from rsconnect.metadata import AppStore, ServerStore
from rsconnect.models import AppModes


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Agent login and preflight require POSIX.")

SERVER = "https://connect.example.com"
METADATA = {
    "token_endpoint": SERVER + "/oauth/token",
    "device_authorization_endpoint": SERVER + "/oauth/device",
    "registration_endpoint": SERVER + "/oauth/register",
}
DEVICE_RESPONSE = {
    "device_code": "device-code-secret",
    "user_code": "ABCD-EFGH",
    "verification_uri": SERVER + "/activate",
    "expires_in": 600,
    "interval": 5,
}


def _response(status: int, data: dict[str, Any]) -> HTTPResponse:
    response = HTTPResponse("", body=b"")
    response.status = status
    response.json_data = data
    return response


class _Clock:
    def __init__(self) -> None:
        self.wall = 1_700_000_000.0
        self.elapsed = 0.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.elapsed

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.elapsed += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


@pytest.fixture
def login_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    clock = _Clock()
    monkeypatch.setattr(device_login, "config_dirname", lambda: str(tmp_path))
    monkeypatch.setattr(device_login, "time", clock)

    class HTTPBoundary:
        responses: list[Any] = []
        instances: list[Any] = []

        def __init__(
            self,
            url: str,
            disable_tls_check: bool = False,
            ca_data: Any = None,
            request_timeout: float | None = None,
            request_deadline: float | None = None,
            **kwargs: Any,
        ) -> None:
            self.url = url
            self.disable_tls_check = disable_tls_check
            self.ca_data = ca_data
            self.request_timeout = request_timeout
            self.request_deadline = request_deadline
            self.entered_timeout = None
            self.entered_deadline = None

        def __enter__(self) -> Any:
            self.entered_timeout = self.request_timeout
            self.entered_deadline = self.request_deadline
            self.instances.append(self)
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def request(self, method: str, path: str, **kwargs: Any) -> Any:
            self.calls = getattr(self, "calls", [])
            self.calls.append((method, path, kwargs))
            result = self.responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result

        def get(self, path: str, **kwargs: Any) -> Any:
            return self.request("GET", path, **kwargs)

        def post(self, path: str, **kwargs: Any) -> Any:
            return self.request("POST", path, **kwargs)

    monkeypatch.setattr(oauth, "HTTPServer", HTTPBoundary)
    return SimpleNamespace(path=tmp_path, clock=clock, http=HTTPBoundary)


def _stub_connect_discovery(monkeypatch: pytest.MonkeyPatch, metadata: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr(device_login, "discover_oauth_metadata", lambda *args, **kwargs: metadata or METADATA)
    monkeypatch.setattr(device_login, "register_client", lambda *args, **kwargs: "registered-client")


def _queue_device(login_env: Any, response: dict[str, Any] | HTTPResponse | None = None) -> None:
    login_env.http.responses.append(response or _response(200, DEVICE_RESPONSE))


def _state_path(kind: str, name: str) -> Path:
    return Path(device_login._state_path(kind, name))


def test_connect_start_uses_oauth_helpers_with_one_bounded_deadline(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    login_env.http.responses.extend(
        [
            _response(200, METADATA),
            _response(200, {"client_id": "registered-client"}),
            _response(200, DEVICE_RESPONSE),
        ]
    )
    discover = oauth.discover_oauth_metadata
    register = oauth.register_client

    def discover_then_advance(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = discover(*args, **kwargs)
        login_env.clock.advance(12)
        return result

    def register_then_advance(*args: Any, **kwargs: Any) -> str:
        result = register(*args, **kwargs)
        login_env.clock.advance(7)
        return result

    monkeypatch.setattr(oauth, "HTTPServer", login_env.http)
    monkeypatch.setattr(device_login, "discover_oauth_metadata", discover_then_advance)
    monkeypatch.setattr(device_login, "register_client", register_then_advance)

    result = device_login.start_connect_login(SERVER + "/proxy/__api__?tab=login#top", "work")

    assert result == {
        "status": "pending",
        "name": "work",
        "server": SERVER + "/proxy",
        "verification_uri": SERVER + "/activate",
        "user_code": "ABCD-EFGH",
        "expires_in": 600,
    }
    assert [client.entered_timeout for client in login_env.http.instances] == [120, 108, 101]
    assert [client.entered_deadline for client in login_env.http.instances] == [120, 120, 120]
    assert [client.calls[0][1] for client in login_env.http.instances] == [
        "/.well-known/oauth-authorization-server",
        "/oauth/register",
        "/oauth/device",
    ]
    state_file = _state_path("connect", "work")
    assert state_file.exists()
    assert stat.S_IMODE(state_file.stat().st_mode) == 0o600


def test_start_and_finish_share_form_transport_and_keep_endpoint_queries(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    metadata = {
        **METADATA,
        "device_authorization_endpoint": SERVER + "/oauth/device?tenant=acme",
        "token_endpoint": SERVER + "/oauth/token?tenant=acme",
    }
    _stub_connect_discovery(monkeypatch, metadata)
    monkeypatch.setattr(device_login, "keyring_store_token", lambda *args: False)
    _queue_device(login_env)

    device_login.start_connect_login(SERVER, "work", client_id="client")
    login_env.clock.advance(5)
    login_env.http.responses.extend(
        [
            _response(400, {"error": "authorization_pending"}),
            _response(200, {"access_token": "approved-access", "refresh_token": "approved-refresh"}),
        ]
    )

    result = device_login.finish_login("connect", "work", timeout=30)

    assert result == {"status": "done", "name": "work", "server": SERVER}
    assert [client.calls[0][1] for client in login_env.http.instances] == [
        "/oauth/device?tenant=acme",
        "/oauth/token?tenant=acme",
        "/oauth/token?tenant=acme",
    ]
    assert login_env.http.instances[0].entered_deadline == 120
    assert login_env.http.instances[1].entered_deadline == 35
    assert login_env.http.instances[2].entered_deadline == 35


@pytest.mark.parametrize("kind", ["connect", "cloud"])
@pytest.mark.parametrize("elapsed", [119.99, 120, 120.01])
def test_start_rechecks_deadline_after_complete_authorization(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, kind: str, elapsed: float
):
    _stub_connect_discovery(monkeypatch)
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)
    original_request = device_login._start_device_request

    def completed_request(*args: Any, **kwargs: Any):
        result = original_request(*args, **kwargs)
        login_env.clock.advance(elapsed)
        return result

    monkeypatch.setattr(device_login, "_start_device_request", completed_request)

    def start():
        if kind == "connect":
            return device_login.start_connect_login(SERVER, "work")
        return device_login.start_cloud_login("team", "work")

    if elapsed >= 120:
        with pytest.raises(RSConnectException, match="start exceeded its 120-second limit"):
            start()
        assert device_login._read_state(kind, "work") is None
    else:
        assert start()["status"] == "pending"
        assert device_login._read_state(kind, "work")["device_code"] == "device-code-secret"


def test_same_target_reuses_code_and_other_target_is_rejected(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    first = device_login.start_connect_login(SERVER + "/proxy/__api__", "work")
    resumed = device_login.start_connect_login(SERVER.upper().replace("HTTPS", "https") + "/proxy#again", "work")

    assert resumed["user_code"] == first["user_code"]
    assert len(login_env.http.instances) == 1
    with pytest.raises(RSConnectException, match="different target"):
        device_login.start_connect_login("https://elsewhere.example.com", "work")


def test_connect_path_named_connect_is_preserved(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    discovered: list[str] = []
    monkeypatch.setattr(
        device_login,
        "discover_oauth_metadata",
        lambda server, *args, **kwargs: discovered.append(server) or METADATA,
    )
    monkeypatch.setattr(device_login, "register_client", lambda *args, **kwargs: "registered-client")
    _queue_device(login_env)

    result = device_login.start_connect_login(SERVER + "/connect", "work")

    assert discovered == [SERVER + "/connect"]
    assert result["server"] == SERVER + "/connect"


def test_live_state_is_scoped_by_kind_and_name(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    connect = device_login.start_connect_login(SERVER, "same")

    login_env.http.responses.append(_response(200, DEVICE_RESPONSE))
    cloud = device_login.start_cloud_login("team", "same")

    assert connect["server"] == SERVER
    assert cloud["server"] == connect_cloud.urls("production").api
    assert _state_path("connect", "same") != _state_path("cloud", "same")
    assert device_login._read_state("connect", "same")["kind"] == "connect"
    assert device_login._read_state("cloud", "same")["kind"] == "cloud"


@pytest.mark.parametrize("kind", ["connect", "cloud"])
def test_start_reuses_expired_checkpoint_and_preserves_target(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, kind: str
):
    _stub_connect_discovery(monkeypatch)
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)

    def start():
        if kind == "connect":
            return device_login.start_connect_login(SERVER, "work")
        return device_login.start_cloud_login("team", "work")

    start()
    state = device_login._read_state(kind, "work")
    state["tokens"] = {
        "access_token": "checkpointed-access",
        "refresh_token": "checkpointed-refresh",
        "expires_at": login_env.clock.time() + 3600,
    }
    device_login._write_state(state)
    login_env.clock.advance(601)
    _queue_device(login_env, _response(200, {**DEVICE_RESPONSE, "user_code": "NEW-CODE"}))

    result = start()

    assert result["user_code"] == "ABCD-EFGH"
    assert result["expires_in"] == 0
    assert device_login._read_state(kind, "work")["tokens"] == state["tokens"]
    assert len(login_env.http.instances) == 1
    with pytest.raises(RSConnectException, match="different target"):
        if kind == "connect":
            device_login.start_connect_login("https://elsewhere.example.com", "work")
        else:
            device_login.start_cloud_login("other-team", "work")
    assert device_login._read_state(kind, "work")["tokens"] == state["tokens"]


@pytest.mark.parametrize("kind", ["connect", "cloud"])
def test_start_replaces_expired_code_without_checkpointed_tokens(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, kind: str
):
    _stub_connect_discovery(monkeypatch)
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)

    def start():
        if kind == "connect":
            return device_login.start_connect_login(SERVER, "work")
        return device_login.start_cloud_login("team", "work")

    start()
    login_env.clock.advance(601)
    _queue_device(login_env, _response(200, {**DEVICE_RESPONSE, "user_code": "NEW-CODE"}))

    result = start()

    assert result["user_code"] == "NEW-CODE"
    assert result["expires_in"] == 600
    assert device_login._read_state(kind, "work")["tokens"] is None
    assert len(login_env.http.instances) == 2


def test_saved_nickname_cannot_be_retargeted(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    device_login._store().set("work", SERVER, oauth_client_id="saved-client")

    with pytest.raises(RSConnectException, match="already saved for a different target"):
        device_login.start_connect_login("https://other.example.com", "work")
    assert not login_env.http.instances


def test_saved_non_connect_credential_is_not_reused_for_connect(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    device_login._store().set("work", SERVER, account_name="analyst", token="t", secret="s")

    with pytest.raises(RSConnectException, match="different target"):
        device_login.start_connect_login(SERVER, "work")
    assert not login_env.http.instances


def test_saved_tls_and_client_id_are_reused(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    device_login._store().set("work", SERVER, oauth_client_id="saved-client", insecure=True)
    _queue_device(login_env)

    device_login.start_connect_login(SERVER, "work")

    assert login_env.http.instances[-1].disable_tls_check is True
    assert device_login._read_state("connect", "work")["client_id"] == "saved-client"


@pytest.mark.parametrize("name", ["work", "alias"])
@pytest.mark.parametrize(
    "saved_url",
    [
        SERVER + "/",
        "https://CONNECT.example.com:443",
        SERVER + "?tab=login",
        SERVER + "/__api__",
        SERVER + "?refresh_token=url-query-secret#access_token=url-fragment-secret",
    ],
)
def test_connect_finish_preserves_saved_url_key_and_deployment_history(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, name: str, saved_url: str
):
    _stub_connect_discovery(monkeypatch)
    keyring_save = Mock(return_value=False)
    monkeypatch.setattr(device_login, "keyring_store_token", keyring_save)
    store = device_login._store()
    store.set("work", saved_url, oauth_client_id="saved-client")
    project = login_env.path / "project"
    project.mkdir()
    app_file = fake_module_file_from_directory(str(project))
    history = AppStore(app_file)
    history.set(saved_url, app_file, SERVER + "/content/existing", "existing-id", None, "Existing", "python-api")
    original_history = Path(history.get_path()).read_bytes()
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, name)
    login_env.clock.advance(5)
    login_env.http.responses.append({"access_token": "approved-access", "refresh_token": "approved-refresh"})

    result = device_login.finish_login("connect", name)

    saved = device_login._store().get_by_name(name)
    assert result == {"status": "done", "name": name, "server": SERVER}
    assert saved["url"] == saved_url
    assert saved["oauth_access_token"] == "approved-access"
    keyring_save.assert_called_once_with(saved_url, "approved-access", "approved-refresh")
    assert history.resolve(saved["url"], None, AppModes.get_by_name("python-api"))[0] == "existing-id"
    assert Path(history.get_path()).read_bytes() == original_history
    assert not _state_path("connect", name).exists()


@pytest.mark.parametrize(
    ("saved_tls", "explicit_tls", "expected_insecure", "expected_ca"),
    [
        ({"insecure": True}, {"ca_data": b"CERT"}, False, b"CERT"),
        ({"insecure": False, "ca_data": "saved-ca"}, {"insecure": True}, True, None),
    ],
)
def test_explicit_tls_replaces_saved_tls(
    login_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    saved_tls: dict[str, Any],
    explicit_tls: dict[str, Any],
    expected_insecure: bool,
    expected_ca: str | bytes | None,
):
    _stub_connect_discovery(monkeypatch)
    device_login._store().set(
        "work",
        SERVER,
        oauth_client_id="saved-client",
        insecure=saved_tls.get("insecure"),
        ca_data=saved_tls.get("ca_data"),
    )
    _queue_device(login_env)

    device_login.start_connect_login(SERVER, "work", **explicit_tls)

    discovery = login_env.http.instances[0]
    device_request = login_env.http.instances[-1]
    assert discovery.disable_tls_check is expected_insecure
    assert discovery.ca_data == expected_ca
    assert device_request.disable_tls_check is expected_insecure
    assert device_request.ca_data == expected_ca
    state = device_login._read_state("connect", "work")
    assert state["client_id"] == "saved-client"


@pytest.mark.parametrize(
    ("metadata_change", "device_change"),
    [
        ({"device_authorization_endpoint": "http://connect.example.com/device"}, {}),
        ({}, {"verification_uri": "http://attacker.example/approve"}),
    ],
)
def test_https_target_rejects_http_oauth_or_verification_uri(
    login_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    metadata_change: dict[str, Any],
    device_change: dict[str, Any],
):
    _stub_connect_discovery(monkeypatch, {**METADATA, **metadata_change})
    _queue_device(login_env, _response(200, {**DEVICE_RESPONSE, **device_change}))

    with pytest.raises(RSConnectException, match="HTTPS"):
        device_login.start_connect_login(SERVER, "work")
    assert not _state_path("connect", "work").exists()


@pytest.mark.parametrize("url", ["https://user@connect.example.com", "https://connect.example.com/\npath"])
def test_server_url_rejects_userinfo_and_control_characters(login_env: Any, monkeypatch: pytest.MonkeyPatch, url: str):
    _stub_connect_discovery(monkeypatch)

    with pytest.raises(RSConnectException):
        device_login.start_connect_login(url, "work")
    assert not login_env.http.instances


def test_invalid_client_retries_registration_once(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    registered: list[dict[str, Any]] = []
    monkeypatch.setattr(
        device_login,
        "register_client",
        lambda *args, **kwargs: registered.append(kwargs) or "replacement-client",
    )
    login_env.http.responses.extend(
        [
            _response(401, {"error": "invalid_client", "error_description": "do not reveal this"}),
            _response(200, DEVICE_RESPONSE),
        ]
    )

    result = device_login.start_connect_login(SERVER, "work", client_id="old-client")

    assert result["status"] == "pending"
    assert len(registered) == 1
    assert len(login_env.http.instances) == 2
    assert device_login._read_state("connect", "work")["client_id"] == "replacement-client"


@pytest.mark.parametrize("source", ["explicit", "saved", "registered"])
def test_invalid_client_id_never_persists_pending_state(login_env: Any, monkeypatch: pytest.MonkeyPatch, source: str):
    _stub_connect_discovery(monkeypatch)
    options: dict[str, Any] = {}
    if source == "explicit":
        options["client_id"] = "invalid\nclient"
    elif source == "saved":
        device_login._store().set("work", SERVER, oauth_client_id="invalid\nclient")
    else:
        monkeypatch.setattr(device_login, "register_client", lambda *args, **kwargs: "invalid\nclient")

    with pytest.raises(RSConnectException, match="OAuth client ID"):
        device_login.start_connect_login(SERVER, "work", **options)

    assert not _state_path("connect", "work").exists()
    assert not login_env.http.instances


@pytest.mark.parametrize("field", ["interval", "expires_in"])
def test_non_finite_device_timing_is_rejected_before_saving(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, field: str
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env, _response(200, {**DEVICE_RESPONSE, field: 10**1000}))

    with pytest.raises(RSConnectException, match="invalid expiry or interval"):
        device_login.start_connect_login(SERVER, "work", client_id="client")

    assert not _state_path("connect", "work").exists()


def test_read_state_rejects_unrepresentable_poll_interval(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work", client_id="client")
    state = device_login._read_state("connect", "work")
    state["interval"] = 10**1000
    device_login._write_state(state)

    with pytest.raises(RSConnectException, match="Pending device login state is invalid"):
        device_login._read_state("connect", "work")


def test_start_error_does_not_echo_server_description(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    login_env.http.responses.append(
        _response(400, {"error": "invalid_request", "error_description": "device-code-secret"})
    )

    with pytest.raises(RSConnectException) as raised:
        device_login.start_connect_login(SERVER, "work", client_id="client")

    assert "device-code-secret" not in str(raised.value)
    assert not _state_path("connect", "work").exists()


def test_finish_pending_hides_secrets_and_slow_down_survives_calls(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    login_env.http.responses.append(_response(400, {"error": "slow_down"}))

    first = device_login.finish_login("connect", "work", timeout=1)
    second = device_login.finish_login("connect", "work", timeout=4)
    state = device_login._read_state("connect", "work")

    assert first == {"status": "pending", "name": "work", "server": SERVER}
    assert second == first
    assert state["interval"] == 10
    assert len(login_env.http.instances) == 2  # one authorization request and one token poll
    assert login_env.http.instances[-1].entered_timeout == 1
    assert not {"device_code", "access_token", "refresh_token"} & first.keys()


def test_authorization_pending_persists_poll_time_before_immediate_retry(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    poll_time = login_env.clock.time()
    login_env.http.responses.extend(
        [
            _response(400, {"error": "authorization_pending"}),
            {"access_token": "approved-access", "expires_in": 3600},
        ]
    )

    first = device_login.finish_login("connect", "work", timeout=1)
    checkpoint = device_login._read_state("connect", "work")

    assert first == {"status": "pending", "name": "work", "server": SERVER}
    assert checkpoint["last_poll_at"] == poll_time
    assert checkpoint["interval"] == 5
    assert len(login_env.http.instances) == 2

    second = device_login.finish_login("connect", "work", timeout=4)
    checkpoint = device_login._read_state("connect", "work")

    assert second == first
    assert checkpoint["last_poll_at"] == poll_time
    assert len(login_env.http.instances) == 2


def test_poll_failure_after_finish_deadline_returns_pending_without_retrying_early(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    attempts = 0

    def fail_after_deadline(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        request_timeout = args[-1]
        login_env.clock.advance(request_timeout + 0.25)
        raise RSConnectException("temporary network failure")

    monkeypatch.setattr(device_login, "_post_form", fail_after_deadline)

    result = device_login.finish_login("connect", "work", timeout=1)
    checkpoint = device_login._read_state("connect", "work")

    assert result == {"status": "pending", "name": "work", "server": SERVER}
    assert checkpoint["last_poll_at"] == login_env.clock.time()
    assert attempts == 1

    result = device_login.finish_login("connect", "work", timeout=1)
    assert result == {"status": "pending", "name": "work", "server": SERVER}
    assert attempts == 1


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("access_denied", "denied"),
        ("expired_token", "expired"),
        ("invalid_client", "invalid"),
        ("invalid_grant", "invalid"),
    ],
)
def test_terminal_poll_errors_remove_state(login_env: Any, monkeypatch: pytest.MonkeyPatch, error: str, message: str):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.http.responses.append(_response(400, {"error": error, "error_description": "access-token-secret"}))

    with pytest.raises(RSConnectException, match=message) as raised:
        device_login.finish_login("connect", "work")

    assert "access-token-secret" not in str(raised.value)
    assert not _state_path("connect", "work").exists()


def test_expired_pending_state_is_removed(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(601)

    with pytest.raises(RSConnectException, match="expired"):
        device_login.finish_login("connect", "work")
    assert not _state_path("connect", "work").exists()


@pytest.mark.skipif(os.name != "posix", reason="owner-only mode bits are POSIX-specific")
def test_pending_state_with_permissive_mode_is_rejected_before_poll(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    os.chmod(_state_path("connect", "work"), 0o644)

    with pytest.raises(RSConnectException, match="owner-only"):
        device_login.finish_login("connect", "work")
    assert len(login_env.http.instances) == 1


def test_symlink_pending_state_is_rejected_before_poll(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    state_file = _state_path("connect", "work")
    target = login_env.path / "linked-state.json"
    target.write_bytes(state_file.read_bytes())
    state_file.unlink()
    try:
        state_file.symlink_to(target)
    except OSError as exc:
        pytest.skip("symlink creation is unavailable: %s" % exc)

    with pytest.raises(RSConnectException, match="safely read"):
        device_login.finish_login("connect", "work")
    assert len(login_env.http.instances) == 1


@pytest.mark.skipif(os.name != "posix", reason="owner IDs are POSIX-specific")
def test_pending_state_owned_by_another_user_is_rejected(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    original_fstat = os.fstat

    def other_owner(descriptor: int) -> Any:
        info = original_fstat(descriptor)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_uid=info.st_uid + 1,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
        )

    monkeypatch.setattr(device_login.os, "fstat", other_owner)
    with pytest.raises(RSConnectException, match="owner-only"):
        device_login._read_state("connect", "work")


@pytest.mark.skipif(os.name != "posix", reason="directory permission bits are POSIX-specific")
def test_new_state_directory_is_private_and_existing_config_permissions_are_preserved(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    new_config = login_env.path / "new-config"
    monkeypatch.setattr(device_login, "config_dirname", lambda: str(new_config))
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "private")
    assert stat.S_IMODE(new_config.stat().st_mode) == 0o700

    existing_config = login_env.path / "existing-config"
    existing_config.mkdir(mode=0o755)
    os.chmod(existing_config, 0o755)
    monkeypatch.setattr(device_login, "config_dirname", lambda: str(existing_config))
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "existing")
    assert stat.S_IMODE(existing_config.stat().st_mode) == 0o755
    assert stat.S_IMODE(_state_path("connect", "existing").stat().st_mode) == 0o600


def test_start_removes_only_orphaned_temps_for_the_same_login(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    orphan = login_env.path / (device_login._temporary_state_prefix("connect", "work") + "interrupted")
    other_login = login_env.path / (device_login._temporary_state_prefix("connect", "other") + "active")
    orphan.write_text("secret device state", encoding="utf-8")
    other_login.write_text("other active secret", encoding="utf-8")
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)

    device_login.start_connect_login(SERVER, "work")

    assert not orphan.exists()
    assert other_login.read_text(encoding="utf-8") == "other active secret"


def test_interrupted_state_write_removes_its_secret_temp(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(device_login.json, "dump", interrupt)
    with pytest.raises(KeyboardInterrupt):
        device_login._write_state({"kind": "connect", "name": "work", "device_code": "secret"})

    assert not list(login_env.path.glob(device_login._temporary_state_prefix("connect", "work") + "*"))


def test_replace_error_is_wrapped_and_preserves_previous_state(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    state_file = _state_path("connect", "work")
    original = state_file.read_bytes()
    state = device_login._read_state("connect", "work")
    state["set_default"] = not state["set_default"]

    def fail_replace(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("destination is temporarily locked")

    monkeypatch.setattr(device_login.os, "replace", fail_replace)
    with pytest.raises(RSConnectException, match="safely write"):
        device_login._write_state(state)

    assert state_file.read_bytes() == original
    assert not list(login_env.path.glob(device_login._temporary_state_prefix("connect", "work") + "*"))


def test_state_reader_does_not_close_a_reused_descriptor(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    original_fdopen = os.fdopen
    replacement_file = login_env.path / "replacement"
    replacement_file.write_bytes(b"ok")
    opened = []

    @contextmanager
    def fdopen_with_concurrent_open(*args, **kwargs):
        with original_fdopen(*args, **kwargs) as stream:
            yield stream
        opened.append(os.open(str(replacement_file), os.O_RDONLY))

    monkeypatch.setattr(device_login.os, "fdopen", fdopen_with_concurrent_open)
    try:
        assert device_login._read_state("connect", "work")["name"] == "work"
        assert os.read(opened[0], 2) == b"ok"
    finally:
        for descriptor in opened:
            os.close(descriptor)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform does not support FIFOs")
def test_pending_fifo_is_rejected_without_waiting_for_a_writer(login_env: Any):
    fifo = _state_path("connect", "work")
    os.mkfifo(str(fifo), mode=0o600)
    script = """
import sys
from rsconnect import device_login
from rsconnect.exception import RSConnectException
device_login.config_dirname = lambda: sys.argv[1]
try:
    device_login.finish_login("connect", "work")
except RSConnectException as error:
    print(str(error))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(login_env.path)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, result.stderr
    assert "not a regular file" in result.stdout


def test_start_and_finish_share_a_bounded_cross_process_lock(tmp_path: Path):
    marker = tmp_path / "lock-held"
    holder_script = """
import sys
import time
from pathlib import Path
from rsconnect import device_login
device_login.config_dirname = lambda: sys.argv[1]
with device_login._state_lock("connect", "work", time.monotonic() + 10):
    Path(sys.argv[2]).write_text("locked")
    time.sleep(10)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script, str(tmp_path), str(marker)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready_by = time.monotonic() + 5
        while not marker.exists() and holder.poll() is None and time.monotonic() < ready_by:
            time.sleep(0.01)
        assert marker.exists(), "lock holder did not acquire the state lock"

        finish_script = """
import json, sys
from rsconnect import device_login
device_login.config_dirname = lambda: sys.argv[1]
print(json.dumps(device_login.finish_login("connect", "work", timeout=1)))
"""
        result = subprocess.run(
            [sys.executable, "-c", finish_script, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"status": "pending", "name": "work", "server": None}

        start_script = """
import sys
from rsconnect import device_login
from rsconnect.exception import RSConnectException
device_login.config_dirname = lambda: sys.argv[1]
device_login._STATE_LOCK_TIMEOUT = 1
def unexpected_discovery(*args, **kwargs):
    raise AssertionError("start performed OAuth I/O while the state lock was busy")
device_login.discover_oauth_metadata = unexpected_discovery
try:
    device_login.start_connect_login("https://connect.example.com", "work")
except RSConnectException as error:
    print(str(error))
"""
        result = subprocess.run(
            [sys.executable, "-c", start_script, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        assert result.returncode == 0, result.stderr
        assert "operation is in progress" in result.stdout
    finally:
        holder.terminate()
        holder.wait(timeout=5)


@pytest.mark.parametrize(
    ("key", "value"),
    [("version", "2"), ("last_poll_at", "not-a-time"), ("expires_at", 10**400)],
)
def test_corrupt_state_schema_is_rejected_before_poll(
    login_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: Any,
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    state_file = _state_path("connect", "work")
    state = json.loads(state_file.read_text())
    state[key] = value
    state_file.write_text(json.dumps(state))

    with pytest.raises(RSConnectException, match="state"):
        device_login.finish_login("connect", "work")
    assert len(login_env.http.instances) == 1


@pytest.mark.parametrize("failure", ["transport", "server"])
def test_failed_poll_still_enforces_the_interval_on_an_immediate_retry(
    login_env: Any, monkeypatch: pytest.MonkeyPatch, failure: str
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    response = (
        HTTPResponse("", exception=TimeoutError("temporary connection failure"))
        if failure == "transport"
        else _response(503, {"error": "server_error"})
    )
    login_env.http.responses.append(response)

    with pytest.raises(RSConnectException):
        device_login.finish_login("connect", "work")
    assert device_login._read_state("connect", "work")["last_poll_at"] == login_env.clock.time()

    result = device_login.finish_login("connect", "work", timeout=1)
    assert result["status"] == "pending"
    assert len(login_env.http.instances) == 2

    login_env.clock.advance(4)
    login_env.http.responses.append({"access_token": "approved-access", "expires_in": 3600})
    result = device_login.finish_login("connect", "work", timeout=1)
    assert result["status"] == "done"
    assert len(login_env.http.instances) == 3


def test_transient_network_failure_keeps_state_and_token_error_does_not_leak(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.http.responses.extend(
        [
            HTTPResponse("", exception=TimeoutError("access-token-secret")),
            _response(400, {"error": "server_error", "error_description": "access-token-secret"}),
        ]
    )

    with pytest.raises(RSConnectException) as raised:
        device_login.finish_login("connect", "work")
    assert "access-token-secret" not in str(raised.value)
    assert _state_path("connect", "work").exists()

    with pytest.raises(RSConnectException) as raised:
        device_login.finish_login("connect", "work")
    assert "access-token-secret" not in str(raised.value)
    assert _state_path("connect", "work").exists()


def test_connect_token_checkpoint_resumes_store_failure(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "access-secret", "refresh_token": "refresh-secret", "expires_in": 3600}
    )
    monkeypatch.setattr(device_login, "keyring_store_token", lambda *args: False)
    original_set = ServerStore.set
    attempts = 0

    def fail_once(store: ServerStore, *args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary store failure")
        return original_set(store, *args, **kwargs)

    monkeypatch.setattr(ServerStore, "set", fail_once)
    with pytest.raises(OSError, match="temporary store failure"):
        device_login.finish_login("connect", "work")
    checkpoint = device_login._read_state("connect", "work")
    assert checkpoint["tokens"]["access_token"] == "access-secret"
    assert stat.S_IMODE(_state_path("connect", "work").stat().st_mode) == 0o600

    login_env.clock.advance(601)
    resumed = device_login.start_connect_login(SERVER, "work")
    assert resumed["user_code"] == "ABCD-EFGH"
    assert device_login._read_state("connect", "work")["tokens"]["access_token"] == "access-secret"
    result = device_login.finish_login("connect", "work")
    saved = device_login._store().get_by_name("work")
    assert result["status"] == "done"
    assert saved["oauth_access_token"] == "access-secret"
    assert saved["oauth_refresh_token"] == "refresh-secret"
    assert device_login._store().get_default()["name"] == "work"
    assert len(login_env.http.instances) == 2
    assert not _state_path("connect", "work").exists()


@pytest.mark.parametrize(
    "expires_in",
    [float("inf"), float("-inf"), float("nan"), True, False, "invalid", 10**400],
)
def test_unusable_token_expiry_keeps_approved_tokens(login_env: Any, monkeypatch: pytest.MonkeyPatch, expires_in: Any):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "approved-access", "refresh_token": "approved-refresh", "expires_in": expires_in}
    )
    monkeypatch.setattr(device_login, "keyring_store_token", lambda *args: False)

    result = device_login.finish_login("connect", "work")

    saved = device_login._store().get_by_name("work")
    assert result["status"] == "done"
    assert saved["oauth_access_token"] == "approved-access"
    assert saved["oauth_refresh_token"] == "approved-refresh"
    assert saved.get("oauth_token_expiry") is None


def test_bytes_ca_is_persisted_and_reused_during_finish(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    _stub_connect_discovery(monkeypatch)
    _queue_device(login_env)
    device_login.start_connect_login(SERVER, "work", ca_data=b"CERTIFICATE")
    state = device_login._read_state("connect", "work")
    assert state["ca_data"] is None
    assert state["ca_data_b64"] == "Q0VSVElGSUNBVEU="

    login_env.clock.advance(5)
    login_env.http.responses.append({"access_token": "access", "expires_in": 60})
    monkeypatch.setattr(device_login, "keyring_store_token", lambda *args: False)
    device_login.finish_login("connect", "work")

    assert login_env.http.instances[-1].ca_data == b"CERTIFICATE"
    assert device_login._store().get_by_name("work")["ca_cert"] == "CERTIFICATE"


@pytest.mark.parametrize(
    ("lookup_results", "save_failures", "expected_error", "expected_message"),
    [
        (
            [RSConnectException("temporary account lookup failure"), {"id": "team-id"}],
            [],
            RSConnectException,
            "account lookup failed",
        ),
        (
            [
                RSConnectException(
                    "Rejected cloud-access-secret", status=200, cause=OSError("original transport error")
                ),
                {"id": "team-id"},
            ],
            [],
            RSConnectException,
            r"account lookup failed \(HTTP 200\)",
        ),
        (
            [
                RSConnectException(
                    "Rejected cloud-access-secret", status=503, cause=OSError("original transport error")
                ),
                {"id": "team-id"},
            ],
            [],
            RSConnectException,
            r"account lookup failed \(HTTP 503\)",
        ),
        (
            [{"id": "team-id"}, {"id": "team-id"}],
            [OSError("temporary store failure")],
            OSError,
            "temporary store failure",
        ),
    ],
)
def test_cloud_checkpoint_retries_permission_lookup_or_save(
    login_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    lookup_results: list[Any],
    save_failures: list[Any],
    expected_error: type[Exception],
    expected_message: str,
):
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    login_env.http.responses.append(_response(200, DEVICE_RESPONSE))
    result = device_login.start_cloud_login("team", "cloud-login")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "cloud-access-secret", "refresh_token": "cloud-refresh-secret", "expires_in": 3600}
    )
    clients: list[Any] = []
    account_results = iter(lookup_results)

    class CloudServer:
        def __init__(self, **kwargs: Any) -> None:
            self.access_token = kwargs["access_token"]
            self.refresh_token = kwargs["refresh_token"]

    class CloudClient:
        def __init__(self, server: Any) -> None:
            self.server = server
            self.request_timeout = None
            self.request_deadline = None
            self.get_account_by_name = Mock(side_effect=account_results)
            clients.append(self)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    monkeypatch.setattr(device_login.api, "ConnectCloudServer", CloudServer)
    monkeypatch.setattr(device_login, "_DeviceLoginCloudClient", CloudClient)
    monkeypatch.setattr(connect_cloud, "store_credentials_in_keyring", lambda *args: False)
    original_set = ServerStore.set
    failures = iter(save_failures)

    def maybe_fail_save(store: ServerStore, *args: Any, **kwargs: Any) -> Any:
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return original_set(store, *args, **kwargs)

    monkeypatch.setattr(ServerStore, "set", maybe_fail_save)
    finish_deadline = login_env.clock.monotonic() + 120
    with pytest.raises(expected_error, match=expected_message) as raised:
        device_login.finish_login("cloud", "cloud-login")

    assert "cloud-access-secret" not in str(raised.value)
    if isinstance(lookup_results[0], RSConnectException):
        assert raised.value.status == lookup_results[0].status
        assert raised.value.cause is lookup_results[0].cause
    checkpoint = device_login._read_state("cloud", "cloud-login")
    assert checkpoint["tokens"]["access_token"] == "cloud-access-secret"
    assert len(login_env.http.instances) == 2

    login_env.clock.advance(601)
    resumed = device_login.start_cloud_login("team", "cloud-login")
    assert resumed["user_code"] == "ABCD-EFGH"
    assert device_login._read_state("cloud", "cloud-login")["tokens"]["access_token"] == "cloud-access-secret"

    completed = device_login.finish_login("cloud", "cloud-login")
    saved = device_login._store().get_by_name("cloud-login")
    assert completed == {
        "status": "done",
        "name": "cloud-login",
        "server": result["server"],
        "account": "team",
    }
    assert saved["connect_cloud_account_id"] == "team-id"
    assert saved["connect_cloud_access_token"] == "cloud-access-secret"
    assert device_login._store().get_default() is None
    assert clients[0].request_timeout <= 120
    assert clients[0].request_deadline == finish_deadline
    assert clients[0]._suppress_oauth_response_logging is True
    assert not _state_path("cloud", "cloud-login").exists()


def test_cloud_refresh_invalid_grant_removes_the_consumed_device_checkpoint(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)
    device_login.start_cloud_login("team", "cloud-login")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "cloud-access", "refresh_token": "revoked-refresh", "expires_in": 3600}
    )

    class CloudServer:
        def __init__(self, **kwargs: Any) -> None:
            self.access_token = kwargs["access_token"]
            self.refresh_token = kwargs["refresh_token"]

    class CloudClient:
        request_timeout = None
        request_deadline = None

        def __init__(self, server: Any) -> None:
            self.server = server

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def get_account_by_name(self, account_name: str) -> dict[str, str]:
            try:
                raise oauth.InvalidGrantError("refresh token revoked")
            except oauth.InvalidGrantError as error:
                raise RSConnectException("Cloud session expired") from error

    monkeypatch.setattr(device_login.api, "ConnectCloudServer", CloudServer)
    monkeypatch.setattr(device_login, "_DeviceLoginCloudClient", CloudClient)

    with pytest.raises(oauth.InvalidGrantError, match="OAuth grant is invalid"):
        device_login.finish_login("cloud", "cloud-login")

    assert not _state_path("cloud", "cloud-login").exists()
    with pytest.raises(RSConnectException, match="No pending"):
        device_login.finish_login("cloud", "cloud-login")


def test_cloud_finish_refresh_uses_client_id_saved_at_start(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    monkeypatch.setenv(connect_cloud.OAUTH_CLIENT_ID_ENV_VAR, "started-client")
    _queue_device(login_env)
    device_login.start_cloud_login("team", "cloud-login")
    state = device_login._read_state("cloud", "cloud-login")
    state["tokens"] = {
        "access_token": "cloud-access",
        "refresh_token": "cloud-refresh",
        "expires_at": login_env.clock.time() + 3600,
    }
    monkeypatch.setenv(connect_cloud.OAUTH_CLIENT_ID_ENV_VAR, "current-client")
    monkeypatch.setattr(device_login.api.time, "monotonic", lambda: 10.0)
    refresh = Mock(return_value={"access_token": "refreshed-access"})
    monkeypatch.setattr(connect_cloud, "refresh", refresh)

    cloud_server, client, _ = device_login._cloud_login_client(state, 20.0)
    client._refresh_user_token()

    assert cloud_server.oauth_client_id == "started-client"
    refresh.assert_called_once_with(
        "cloud-refresh",
        "production",
        request_timeout=10.0,
        request_deadline=20.0,
        client_id_override="started-client",
        suppress_response_logging=True,
    )


def test_registration_error_is_private_and_can_be_retried(login_env: Any):
    login_env.http.responses.extend(
        [
            _response(200, METADATA),
            _response(503, {"error": "server_error", "error_description": "device-code-secret"}),
        ]
    )

    with pytest.raises(RSConnectException, match="client registration failed") as failed:
        device_login.start_connect_login(SERVER, "work")

    assert "device-code-secret" not in str(failed.value)
    assert not _state_path("connect", "work").exists()
    assert login_env.http.instances[-1]._suppress_oauth_response_logging is True
    login_env.http.responses.extend(
        [
            _response(200, METADATA),
            _response(201, {"client_id": "registered-client"}),
            _response(200, DEVICE_RESPONSE),
        ]
    )
    assert device_login.start_connect_login(SERVER, "work")["status"] == "pending"


def test_missing_cloud_account_removes_checkpoint_for_corrected_start(login_env: Any, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)
    device_login.start_cloud_login("typo", "cloud-login")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "cloud-access", "refresh_token": "cloud-refresh", "expires_in": 3600}
    )

    monkeypatch.setattr(
        device_login.api.ConnectCloudClient,
        "get_accounts",
        lambda self: [{"id": "team-id", "name": "correct-team"}],
    )

    with pytest.raises(ConnectCloudAccountNotFoundError):
        device_login.finish_login("cloud", "cloud-login")

    assert not _state_path("cloud", "cloud-login").exists()
    _queue_device(login_env)
    corrected = device_login.start_cloud_login("correct-team", "cloud-login")
    assert corrected["status"] == "pending"
    assert device_login._read_state("cloud", "cloud-login")["account"] == "correct-team"


def test_cloud_account_deadline_returns_pending_and_checkpoints_rotated_tokens(
    login_env: Any, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(connect_cloud.ENVIRONMENT_ENV_VAR, "production")
    _queue_device(login_env)
    device_login.start_cloud_login("team", "cloud-login")
    login_env.clock.advance(5)
    login_env.http.responses.append(
        {"access_token": "initial-access", "refresh_token": "initial-refresh", "expires_in": 3600}
    )
    lookups = 0
    clients: list[Any] = []

    class CloudServer:
        def __init__(self, **kwargs: Any) -> None:
            self.access_token = kwargs["access_token"]
            self.refresh_token = kwargs["refresh_token"]

    class CloudClient:
        def __init__(self, server: Any) -> None:
            self.server = server
            self.request_timeout = None
            self.request_deadline = None
            clients.append(self)

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def get_account_by_name(self, account_name: str) -> dict[str, str]:
            nonlocal lookups
            lookups += 1
            if lookups == 1:
                self.server.access_token = "rotated-access"
                self.server.refresh_token = "rotated-refresh"
                login_env.clock.advance(5)
            return {"id": "team-id"}

    monkeypatch.setattr(device_login.api, "ConnectCloudServer", CloudServer)
    monkeypatch.setattr(device_login, "_DeviceLoginCloudClient", CloudClient)
    monkeypatch.setattr(connect_cloud, "store_credentials_in_keyring", lambda *args: False)

    result = device_login.finish_login("cloud", "cloud-login", timeout=5)
    checkpoint = device_login._read_state("cloud", "cloud-login")

    assert result == {"status": "pending", "name": "cloud-login", "server": connect_cloud.urls().api}
    assert checkpoint["tokens"]["access_token"] == "rotated-access"
    assert checkpoint["tokens"]["refresh_token"] == "rotated-refresh"
    assert clients[0].request_deadline == 10.0

    completed = device_login.finish_login("cloud", "cloud-login", timeout=5)
    saved = device_login._store().get_by_name("cloud-login")
    assert completed["status"] == "done"
    assert saved["connect_cloud_access_token"] == "rotated-access"
    assert saved["connect_cloud_refresh_token"] == "rotated-refresh"
