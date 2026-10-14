"""Resumable OAuth device login for Posit Connect and Connect Cloud."""

from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import math
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, Mapping, Optional, cast
from urllib.parse import urlsplit, urlunsplit

from . import api, connect_cloud
from .exception import ConnectCloudAccountNotFoundError, RSConnectException
from .metadata import ServerDataDict, ServerStore, config_dirname
from .oauth import (
    InvalidClientError,
    InvalidGrantError,
    _oauth_response_data,
    _post_oauth_form_request,
    _unwrap_json_response,
    discover_oauth_metadata,
    keyring_store_token,
    register_client,
)
from .validation import require_posix

_START_TIMEOUT = 120
_STATE_LOCK_TIMEOUT = 10
_POLL_INTERVAL_STEP = 5
_LOCK_POLL_INTERVAL = 0.05


class _Denied(RSConnectException):
    def __init__(self) -> None:
        super().__init__("Device authorization was denied.")


class _Expired(RSConnectException):
    def __init__(self) -> None:
        super().__init__("Device authorization expired. Start a new login.")


class _Pending(Exception):
    pass


class _SlowDown(Exception):
    pass


class _FinishDeadline(Exception):
    pass


class _LockBusy(RSConnectException):
    pass


_DEVICE_ERRORS: dict[str, type[Exception]] = {
    "authorization_pending": _Pending,
    "slow_down": _SlowDown,
    "access_denied": _Denied,
    "expired_token": _Expired,
    "invalid_client": InvalidClientError,
    "invalid_grant": InvalidGrantError,
}
_STATE_REQUIRED = (
    "version",
    "kind",
    "name",
    "server",
    "client_id",
    "device_endpoint",
    "token_endpoint",
    "device_code",
    "user_code",
    "verification_uri",
    "expires_at",
    "interval",
    "last_poll_at",
    "scope",
    "set_default",
    "insecure",
    "ca_data",
    "ca_data_b64",
    "account",
    "tokens",
)


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RSConnectException("%s must be a non-empty string." % label)
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RSConnectException("%s must not contain control characters." % label)
    return value


def _parse_http_url(
    value: str,
    label: str,
    allow_query: bool = False,
    allow_fragment: bool = False,
) -> tuple[Any, str]:
    _validate_url_text(value, label)
    try:
        parts = urlsplit(value)
        authority = _url_authority(parts, label, allow_query, allow_fragment)
    except ValueError as exc:
        raise RSConnectException("%s must be a valid HTTP or HTTPS URL." % label) from exc
    return parts, urlunsplit((parts.scheme.lower(), authority, parts.path, parts.query, parts.fragment))


def _validate_url_text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise RSConnectException("%s must be a valid HTTP or HTTPS URL." % label)
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise RSConnectException("%s must not contain whitespace or control characters." % label)


def _url_authority(parts: Any, label: str, allow_query: bool, allow_fragment: bool) -> str:
    scheme = parts.scheme.lower()
    if scheme != "http" and scheme != "https":
        raise RSConnectException("%s must use HTTP or HTTPS." % label)
    _validate_url_policy(parts, label, allow_query, allow_fragment)
    host = parts.hostname
    if not host:
        raise RSConnectException("%s must include a host." % label)
    port = parts.port
    if port == 0:
        raise RSConnectException("%s contains an invalid port." % label)
    return _format_authority(host, port, scheme)


def _validate_url_policy(parts: Any, label: str, allow_query: bool, allow_fragment: bool) -> None:
    if parts.username is not None or parts.password is not None:
        raise RSConnectException("%s must not contain user information." % label)
    if parts.query and not allow_query:
        raise RSConnectException("%s must not contain a query or fragment." % label)
    if parts.fragment and not allow_fragment:
        raise RSConnectException("%s must not contain a query or fragment." % label)


def _format_authority(host: str, port: Optional[int], scheme: str) -> str:
    host = host.lower()
    authority = "[%s]" % host if ":" in host else host
    if port is not None and port != (443 if scheme == "https" else 80):
        authority += ":%d" % port
    return authority


def _normalize_server_url(url: str) -> str:
    parts, normalized = _parse_http_url(url, "Server URL", allow_query=True, allow_fragment=True)
    authority = urlsplit(normalized).netloc
    path = parts.path.rstrip("/")
    if path.endswith("/__api__"):
        path = path[: -len("/__api__")]
    return urlunsplit((parts.scheme.lower(), authority, path, "", ""))


def _cloud_server_url(url: Optional[str]) -> str:
    if url is not None and not connect_cloud.is_connect_cloud_url(_identifier(url, "Connect Cloud URL")):
        raise RSConnectException("Connect Cloud URL must identify a supported environment.")
    return _normalize_server_url(connect_cloud.resolve_url(url))


def _normalize_endpoint(url: str, label: str, target_https: bool, allow_query: bool = True) -> str:
    parts, normalized = _parse_http_url(url, label, allow_query=allow_query)
    if target_https and parts.scheme.lower() != "https":
        raise RSConnectException("%s must use HTTPS when the server URL uses HTTPS." % label)
    return normalized


def _verification_uri(value: str, target_https: bool) -> str:
    parts, normalized = _parse_http_url(value, "Verification URI", True, True)
    if target_https and parts.scheme.lower() != "https":
        raise RSConnectException("Verification URI must use HTTPS when the server URL uses HTTPS.")
    return normalized


def _endpoint_location(endpoint: str) -> tuple[str, str]:
    _, normalized = _parse_http_url(endpoint, "OAuth endpoint", allow_query=True)
    parsed = urlsplit(normalized)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return "%s://%s" % (parsed.scheme, parsed.netloc), path


def _metadata(metadata: dict[str, Any], server: str) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise RSConnectException("OAuth discovery returned invalid metadata.")
    checked = dict(metadata)
    target_https = urlsplit(server).scheme == "https"
    for key in ("device_authorization_endpoint", "token_endpoint"):
        endpoint = metadata.get(key)
        if not isinstance(endpoint, str) or not endpoint:
            raise RSConnectException("OAuth metadata is missing %s." % key.replace("_", " "))
        checked[key] = _normalize_endpoint(endpoint, key, target_https)
    registration = metadata.get("registration_endpoint")
    if registration:
        if not isinstance(registration, str):
            raise RSConnectException("OAuth registration endpoint is invalid.")
        checked["registration_endpoint"] = _normalize_endpoint(
            registration, "registration_endpoint", target_https, allow_query=False
        )
    return checked


def _store() -> ServerStore:
    return ServerStore(base_dir=config_dirname())


def _state_path(kind: str, name: str) -> str:
    digest = _state_digest(kind, name)
    return os.path.join(config_dirname(), "device-login-%s-%s.json" % (kind, digest))


def _state_digest(kind: str, name: str) -> str:
    return hashlib.sha256((kind + "\0" + name).encode("utf-8")).hexdigest()


def _temporary_state_prefix(kind: str, name: str) -> str:
    return ".device-login-%s-" % _state_digest(kind, name)


def _remove_temporary_state_files(kind: str, name: str) -> None:
    directory = os.path.dirname(_state_path(kind, name))
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RSConnectException("Could not clean up pending device login state.") from exc

    prefix = _temporary_state_prefix(kind, name)
    for filename in names:
        if filename.startswith(prefix):
            try:
                os.unlink(os.path.join(directory, filename))
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RSConnectException("Could not clean up pending device login state.") from exc


def _same_open_file(path: str, descriptor: int) -> bool:
    try:
        path_info = os.stat(path, follow_symlinks=False)
        open_info = os.fstat(descriptor)
    except OSError:
        return False
    return (
        stat.S_ISREG(path_info.st_mode)
        and path_info.st_dev == open_info.st_dev
        and path_info.st_ino == open_info.st_ino
    )


def _validate_open_state_file(path: str, descriptor: int, purpose: str) -> None:
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or not _same_open_file(path, descriptor):
        raise RSConnectException("Pending device login %s is not a regular file." % purpose)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RSConnectException("Pending device login %s is not owner-only." % purpose)


def _open_state_file(path: str, flags: int, mode: int, purpose: str) -> int:
    if os.path.islink(path):
        raise RSConnectException("Could not safely %s pending device login state." % purpose)
    descriptor = os.open(path, flags, mode)
    try:
        _validate_open_state_file(path, descriptor, purpose)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_state_lock(kind: str, name: str) -> int:
    path = _state_path(kind, name) + ".lock"
    directory = os.path.dirname(path)
    descriptor: Optional[int] = None
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = _open_state_file(path, flags, 0o600, "lock")
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise RSConnectException("Could not safely lock pending device login state.") from exc


def _try_state_lock(descriptor: int) -> None:
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _acquire_state_lock(descriptor: int, name: str, deadline: float) -> None:
    busy_errors = (errno.EACCES, errno.EAGAIN, getattr(errno, "EDEADLK", errno.EAGAIN))
    while True:
        try:
            _try_state_lock(descriptor)
            return
        except OSError as exc:
            if exc.errno not in busy_errors:
                raise RSConnectException("Could not lock pending device login state.") from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _LockBusy('Another device login operation is in progress for nickname "%s".' % name)
            time.sleep(min(_LOCK_POLL_INTERVAL, remaining))


@contextmanager
def _state_lock(kind: str, name: str, deadline: float) -> Generator[None, None, None]:
    descriptor = _open_state_lock(kind, name)
    try:
        _acquire_state_lock(descriptor, name, deadline)
        yield
    finally:
        os.close(descriptor)


def _write_state(state: dict[str, Any]) -> None:
    target = _state_path(state["kind"], state["name"])
    directory = os.path.dirname(target)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=_temporary_state_prefix(state["kind"], state["name"]), dir=directory
        )
    except OSError as exc:
        raise RSConnectException("Could not safely write pending device login state.") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            _validate_open_state_file(temporary, stream.fileno(), "write")
            json.dump(state, stream, separators=(",", ":"), sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        if isinstance(exc, OSError):
            raise RSConnectException("Could not safely write pending device login state.") from exc
        raise


def _valid_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _positive_finite_duration(value: Any) -> bool:
    return type(value) is int and value >= 1 and _valid_number(value)


def _validate_tokens(tokens: Any) -> None:
    if tokens is None:
        return
    if not isinstance(tokens, dict):
        raise RSConnectException("Pending device login state is invalid.")
    token_data = cast(Mapping[str, Any], tokens)
    if not isinstance(token_data.get("access_token"), str) or not token_data["access_token"]:
        raise RSConnectException("Pending device login state is invalid.")
    if token_data.get("refresh_token") is not None and not isinstance(token_data["refresh_token"], str):
        raise RSConnectException("Pending device login state is invalid.")
    expiry = token_data.get("expires_at")
    if expiry is not None and not _valid_number(expiry):
        raise RSConnectException("Pending device login state is invalid.")


def _validate_state_target(state: dict[str, Any], kind: str) -> None:
    server = _normalize_server_url(state["server"])
    if server != state["server"]:
        raise RSConnectException("Pending device login state is invalid.")
    if kind == "cloud":
        _validate_cloud_target(state, server)
    elif state["account"] is not None or state["scope"] is not None:
        raise RSConnectException("Pending device login state is invalid.")


def _validate_cloud_target(state: dict[str, Any], server: str) -> None:
    if not isinstance(state["account"], str) or not state["account"]:
        raise RSConnectException("Pending device login state is invalid.")
    cloud_target = server == _cloud_server_url(server) and state["scope"] == connect_cloud.SCOPE
    no_custom_tls = not state["insecure"] and state["ca_data"] is None and state["ca_data_b64"] is None
    if not cloud_target or not no_custom_tls:
        raise RSConnectException("Pending device login state is invalid.")


def _validate_state_identity(kind: str, name: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RSConnectException("Pending device login state is invalid.")
    for key in _STATE_REQUIRED:
        if key not in raw:
            raise RSConnectException("Pending device login state is invalid.")
    state = cast(Dict[str, Any], raw)
    if type(state["version"]) is not int or state["version"] != 1 or state["kind"] != kind or state["name"] != name:
        raise RSConnectException("Pending device login state does not match the requested login.")
    _identifier(state["name"], "Nickname")
    _identifier(state["client_id"], "OAuth client ID")
    if not isinstance(state["set_default"], bool) or not isinstance(state["insecure"], bool):
        raise RSConnectException("Pending device login state is invalid.")
    return state


def _validate_state_tls(raw: dict[str, Any]) -> None:
    if raw["ca_data"] is not None and not isinstance(raw["ca_data"], str):
        raise RSConnectException("Pending device login state is invalid.")
    if raw["ca_data_b64"] is not None:
        if not isinstance(raw["ca_data_b64"], str) or raw["ca_data"] is not None:
            raise RSConnectException("Pending device login state is invalid.")
        try:
            base64.b64decode(raw["ca_data_b64"].encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise RSConnectException("Pending device login state is invalid.") from exc


def _validate_state_protocol(raw: dict[str, Any]) -> None:
    server = cast(str, raw["server"])
    target_https = urlsplit(server).scheme == "https"
    _validate_state_endpoints(raw, target_https)
    _validate_state_codes(raw)


def _validate_state_endpoints(raw: dict[str, Any], target_https: bool) -> None:
    for key in ("device_endpoint", "token_endpoint"):
        endpoint = raw[key]
        if not isinstance(endpoint, str) or _normalize_endpoint(endpoint, key, target_https) != endpoint:
            raise RSConnectException("Pending device login state is invalid.")
    verification = _verification_uri(raw["verification_uri"], target_https)
    if verification != raw["verification_uri"]:
        raise RSConnectException("Pending device login state is invalid.")


def _validate_state_codes(raw: dict[str, Any]) -> None:
    if not isinstance(raw["device_code"], str) or not raw["device_code"]:
        raise RSConnectException("Pending device login state is invalid.")
    if not isinstance(raw["user_code"], str) or not raw["user_code"]:
        raise RSConnectException("Pending device login state is invalid.")


def _validate_state_polling(raw: dict[str, Any]) -> None:
    if not _valid_number(raw["expires_at"]) or not _valid_number(raw["last_poll_at"]):
        raise RSConnectException("Pending device login state is invalid.")
    if not _positive_finite_duration(raw["interval"]):
        raise RSConnectException("Pending device login state is invalid.")
    _validate_tokens(raw["tokens"])


def _validate_state(kind: str, name: str, raw: Any) -> dict[str, Any]:
    state = _validate_state_identity(kind, name, raw)
    _validate_state_tls(state)
    _validate_state_target(state, kind)
    _validate_state_protocol(state)
    _validate_state_polling(state)
    return state


def _read_state(kind: str, name: str) -> Optional[dict[str, Any]]:
    path = _state_path(kind, name)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = _open_state_file(path, flags, 0, "read")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RSConnectException("Could not safely read pending device login state.") from exc
    try:
        raw = _read_state_json(descriptor)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return _validate_state(kind, name, raw)


def _read_state_json(descriptor: int) -> Any:
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            return json.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RSConnectException("Pending device login state is invalid.") from exc


def _remove_state(kind: str, name: str) -> None:
    try:
        os.unlink(_state_path(kind, name))
    except FileNotFoundError:
        pass


def _ca_values(ca_data: Optional[str | bytes]) -> tuple[Optional[str], Optional[str]]:
    if ca_data is None:
        return None, None
    if isinstance(ca_data, str):
        return ca_data, None
    if isinstance(ca_data, bytes):
        return None, base64.b64encode(ca_data).decode("ascii")
    raise RSConnectException("CA data must be text or bytes.")


def _state_ca(state: dict[str, Any]) -> Optional[str | bytes]:
    if state["ca_data_b64"] is not None:
        return base64.b64decode(state["ca_data_b64"].encode("ascii"), validate=True)
    return state["ca_data"]


def _same_server(value: Any, server: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return _normalize_server_url(value) == server
    except RSConnectException:
        return False


def _assert_nickname_target(
    store: ServerStore, kind: str, name: str, server: str, account: Optional[str] = None
) -> None:
    entry = store.get_by_name(name)
    if entry is None:
        return
    matches = _same_server(entry.get("url"), server) and _saved_server_kind(entry) == kind
    if kind == "cloud":
        matches = matches and entry.get("connect_cloud_account_name") == account
    if not matches:
        raise RSConnectException('The nickname, "%s", is already saved for a different target.' % name)


def _saved_server_kind(entry: Mapping[str, Any]) -> str:
    if entry.get("connect_cloud_account_name"):
        return "cloud"
    if any(entry.get(key) for key in ("account_name", "token", "secret", "snowflake_connection_name")):
        return "other"
    return "connect"


def _saved_connect_entry(store: ServerStore, name: str, server: str) -> Optional[ServerDataDict]:
    named = store.get_by_name(name)
    if named is not None:
        return named
    for entry in store.get_all_servers():
        if _saved_server_kind(entry) == "connect" and _same_server(entry.get("url"), server):
            return entry
    return None


def _resolve_tls(
    saved: Optional[ServerDataDict], insecure: bool, ca_data: Optional[str | bytes], client_id: Optional[str]
) -> tuple[bool, Optional[str | bytes], Optional[str]]:
    tls_insecure, tls_ca = _tls_settings(saved, insecure, ca_data)
    saved_id = saved.get("oauth_client_id") if saved else None
    resolved_client_id = client_id if client_id is not None else (str(saved_id) if saved_id else None)
    if resolved_client_id is not None:
        resolved_client_id = _identifier(resolved_client_id, "OAuth client ID")
    return tls_insecure, tls_ca, resolved_client_id


def _tls_settings(
    saved: Optional[ServerDataDict], insecure: bool, ca_data: Optional[str | bytes]
) -> tuple[bool, Optional[str | bytes]]:
    if insecure and ca_data is not None:
        raise RSConnectException("Cannot combine insecure TLS with a custom CA certificate.")
    if insecure or ca_data is not None:
        tls_insecure, tls_ca = insecure, ca_data
    elif saved:
        tls_insecure, tls_ca = bool(saved.get("insecure")), saved.get("ca_cert")
    else:
        return False, None
    if tls_insecure and tls_ca is not None:
        raise RSConnectException("Cannot combine insecure TLS with a custom CA certificate.")
    return tls_insecure, tls_ca


def _check_pending_target(
    state: dict[str, Any],
    kind: str,
    server: str,
    account: Optional[str],
    client_id: Optional[str],
    insecure: bool,
    ca_data: Optional[str | bytes],
) -> None:
    matches = state["server"] == server
    if kind == "cloud":
        matches = matches and state["account"] == account
    if client_id:
        matches = matches and state["client_id"] == client_id
    if insecure or ca_data is not None:
        matches = matches and state["insecure"] == insecure and _state_ca(state) == ca_data
    if not matches:
        raise RSConnectException('A pending "%s" login for "%s" has a different target.' % (kind, state["name"]))


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RSConnectException("Device login start exceeded its 120-second limit.")
    return remaining


def _post_form(
    endpoint: str,
    fields: dict[str, str],
    insecure: bool,
    ca_data: Optional[str | bytes],
    request_timeout: float,
    request_deadline: Optional[float] = None,
) -> Any:
    base, path = _endpoint_location(endpoint)
    return _post_oauth_form_request(
        base,
        path,
        fields,
        insecure,
        ca_data,
        request_timeout,
        request_deadline,
        suppress_response_logging=True,
    )


def _device_authorization_response(response: Any) -> dict[str, Any]:
    try:
        return _unwrap_json_response(response)
    except InvalidClientError:
        raise
    except RSConnectException:
        raise RSConnectException("OAuth device authorization request failed.") from None


def _register_device_client(
    metadata: dict[str, Any],
    server: str,
    insecure: bool,
    ca_data: Optional[str | bytes],
    deadline: float,
) -> str:
    try:
        client_id = register_client(
            metadata,
            server,
            insecure,
            ca_data,
            request_timeout=_remaining(deadline),
            request_deadline=deadline,
            suppress_response_logging=True,
        )
    except InvalidClientError:
        raise
    except RSConnectException:
        raise RSConnectException("OAuth client registration failed.") from None
    return _identifier(client_id, "OAuth client ID")


def _start_device_request(
    metadata: dict[str, Any],
    server: str,
    client_id: str,
    scope: Optional[str],
    insecure: bool,
    ca_data: Optional[str | bytes],
    deadline: float,
) -> tuple[str, dict[str, Any]]:
    client_id = _identifier(client_id, "OAuth client ID")
    fields = {"client_id": client_id}
    if scope:
        fields["scope"] = scope
    try:
        response = _post_form(
            metadata["device_authorization_endpoint"],
            fields,
            insecure,
            ca_data,
            _remaining(deadline),
            request_deadline=deadline,
        )
        return client_id, _device_authorization_response(response)
    except InvalidClientError:
        if not metadata.get("registration_endpoint"):
            raise
        client_id = _register_device_client(metadata, server, insecure, ca_data, deadline)
        fields["client_id"] = client_id
        response = _post_form(
            metadata["device_authorization_endpoint"],
            fields,
            insecure,
            ca_data,
            _remaining(deadline),
            request_deadline=deadline,
        )
        return client_id, _device_authorization_response(response)


def _make_state(
    kind: str,
    name: str,
    server: str,
    metadata: dict[str, Any],
    response: dict[str, Any],
    client_id: str,
    scope: Optional[str],
    set_default: bool,
    insecure: bool,
    ca_data: Optional[str | bytes],
    account: Optional[str],
) -> dict[str, Any]:
    client_id = _identifier(client_id, "OAuth client ID")
    device_code = response.get("device_code")
    user_code = response.get("user_code")
    verification = response.get("verification_uri_complete") or response.get("verification_uri")
    if not all(isinstance(value, str) and value for value in (device_code, user_code, verification)):
        raise RSConnectException("Device authorization returned an incomplete response.")
    verification_uri = cast(str, verification)
    expires_in = response.get("expires_in", 600)
    interval = response.get("interval", 5)
    if not _positive_finite_duration(expires_in) or not _positive_finite_duration(interval):
        raise RSConnectException("Device authorization returned an invalid expiry or interval.")
    ca_text, ca_b64 = _ca_values(ca_data)
    now = time.time()
    state = {
        "version": 1,
        "kind": kind,
        "name": name,
        "server": server,
        "client_id": client_id,
        "device_endpoint": metadata["device_authorization_endpoint"],
        "token_endpoint": metadata["token_endpoint"],
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": _verification_uri(verification_uri, urlsplit(server).scheme == "https"),
        "expires_at": now + expires_in,
        "interval": interval,
        "last_poll_at": now,
        "scope": scope,
        "set_default": set_default,
        "insecure": insecure,
        "ca_data": ca_text,
        "ca_data_b64": ca_b64,
        "account": account,
        "tokens": None,
    }
    return _validate_state(kind, name, state)


def _start_result(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "pending",
        "name": state["name"],
        "server": state["server"],
        "verification_uri": state["verification_uri"],
        "user_code": state["user_code"],
        "expires_in": max(0, int(math.ceil(cast(float, state["expires_at"]) - time.time()))),
    }


def _device_code_expired(state: dict[str, Any]) -> bool:
    return state["tokens"] is None and state["expires_at"] <= time.time()


def start_connect_login(
    url: str,
    name: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
    set_default: bool = True,
    client_id: Optional[str] = None,
) -> dict[str, Any]:
    require_posix("Resumable device login")
    name = _identifier(name, "Nickname")
    if client_id is not None:
        client_id = _identifier(client_id, "OAuth client ID")
    with _state_lock("connect", name, time.monotonic() + _STATE_LOCK_TIMEOUT):
        _remove_temporary_state_files("connect", name)
        return _start_connect_login(url, name, insecure, ca_data, set_default, client_id)


def _start_connect_login(
    url: str,
    name: str,
    insecure: bool,
    ca_data: Optional[str | bytes],
    set_default: bool,
    client_id: Optional[str],
) -> dict[str, Any]:
    server = _normalize_server_url(url)
    store = _store()
    _assert_nickname_target(store, "connect", name, server)
    state = _read_state("connect", name)
    if state and _device_code_expired(state):
        _remove_state("connect", name)
        state = None
    if state:
        _check_pending_target(state, "connect", server, None, client_id, insecure, ca_data)
        state["set_default"] = set_default
        _write_state(state)
        return _start_result(state)

    insecure, ca_data, client_id = _resolve_tls(_saved_connect_entry(store, name, server), insecure, ca_data, client_id)
    deadline = time.monotonic() + _START_TIMEOUT
    metadata = _metadata(
        discover_oauth_metadata(
            server,
            insecure,
            ca_data,
            request_timeout=_remaining(deadline),
            request_deadline=deadline,
            suppress_response_logging=True,
        ),
        server,
    )
    if not client_id:
        client_id = _register_device_client(metadata, server, insecure, ca_data, deadline)
    client_id, response = _start_device_request(metadata, server, client_id, None, insecure, ca_data, deadline)
    _remaining(deadline)
    state = _make_state(
        "connect", name, server, metadata, response, client_id, None, set_default, insecure, ca_data, None
    )
    _write_state(state)
    return _start_result(state)


def start_cloud_login(
    account: str,
    name: str,
    url: Optional[str] = None,
    set_default: bool = False,
) -> dict[str, Any]:
    require_posix("Resumable device login")
    name = _identifier(name, "Nickname")
    with _state_lock("cloud", name, time.monotonic() + _STATE_LOCK_TIMEOUT):
        _remove_temporary_state_files("cloud", name)
        return _start_cloud_login(account, name, url, set_default)


def _start_cloud_login(
    account: str,
    name: str,
    url: Optional[str],
    set_default: bool,
) -> dict[str, Any]:
    account = _identifier(account, "Connect Cloud account")
    server = _cloud_server_url(url)
    store = _store()
    _assert_nickname_target(store, "cloud", name, server, account)
    state = _read_state("cloud", name)
    if state and _device_code_expired(state):
        _remove_state("cloud", name)
        state = None
    if state:
        _check_pending_target(state, "cloud", server, account, None, False, None)
        state["set_default"] = set_default
        _write_state(state)
        return _start_result(state)

    environment = connect_cloud.environment_for_url(server)
    metadata = _metadata(connect_cloud.urls(environment).oauth_metadata(), server)
    client_id = _identifier(connect_cloud.client_id(environment), "OAuth client ID")
    deadline = time.monotonic() + _START_TIMEOUT
    client_id, response = _start_device_request(metadata, server, client_id, connect_cloud.SCOPE, False, None, deadline)
    _remaining(deadline)
    state = _make_state(
        "cloud",
        name,
        server,
        metadata,
        response,
        client_id,
        connect_cloud.SCOPE,
        set_default,
        False,
        None,
        account,
    )
    _write_state(state)
    return _start_result(state)


def _raise_device_error(code: Any) -> None:
    error_type = _DEVICE_ERRORS.get(code) if isinstance(code, str) else None
    if error_type is None:
        raise RSConnectException("OAuth device token request failed.")
    raise error_type()


def _response_data(response: Any) -> tuple[dict[str, Any], Optional[int]]:
    data, status = _oauth_response_data(response)
    if data is None:
        raise RSConnectException("Device token request returned an unexpected response.")
    return data, status


def _device_token_response(response: Any) -> dict[str, Any]:
    data, status = _response_data(response)
    if data.get("error"):
        _raise_device_error(data["error"])
    _validate_token_success(data, status)
    return data


def _validate_token_success(data: dict[str, Any], status: Optional[int]) -> None:
    if status is None or status < 200 or status >= 300:
        if status is None:
            raise RSConnectException("OAuth device token request failed.")
        raise RSConnectException("OAuth device token request failed (HTTP %s)." % status)
    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RSConnectException("Device token request returned no access token.")


def _poll_timeout(state: dict[str, Any], deadline: float) -> Optional[float]:
    remaining = deadline - time.monotonic()
    device_remaining = state["expires_at"] - time.time()
    if device_remaining <= 0:
        raise _Expired()
    if remaining <= 0:
        return None
    wait = state["interval"] - (time.time() - state["last_poll_at"])
    if wait > 0:
        time.sleep(min(wait, remaining, device_remaining))
    remaining = deadline - time.monotonic()
    device_remaining = state["expires_at"] - time.time()
    if device_remaining <= 0:
        raise _Expired()
    if remaining <= 0:
        return None
    return min(remaining, device_remaining)


def _record_poll_error(state: dict[str, Any], error: Exception) -> None:
    if isinstance(error, _SlowDown):
        state["interval"] += _POLL_INTERVAL_STEP
    state["last_poll_at"] = time.time()
    _write_state(state)


def _poll_for_token(state: dict[str, Any], deadline: float) -> Optional[dict[str, Any]]:
    while True:
        request_timeout = _poll_timeout(state, deadline)
        if request_timeout is None:
            return None
        fields = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": state["client_id"],
            "device_code": state["device_code"],
        }
        if state["scope"]:
            fields["scope"] = state["scope"]
        try:
            request_deadline = min(deadline, time.monotonic() + request_timeout)
            response = _post_form(
                state["token_endpoint"],
                fields,
                state["insecure"],
                _state_ca(state),
                request_timeout,
                request_deadline=request_deadline,
            )
            tokens = _device_token_response(response)
        except (_Pending, _SlowDown) as error:
            _record_poll_error(state, error)
            continue
        except (_Denied, _Expired, InvalidClientError, InvalidGrantError):
            raise
        except Exception:
            state["last_poll_at"] = time.time()
            _write_state(state)
            if deadline <= time.monotonic():
                raise _FinishDeadline()
            raise
        state["last_poll_at"] = time.time()
        return tokens


def _checkpoint(tokens: dict[str, Any]) -> dict[str, Any]:
    refresh = tokens.get("refresh_token")
    if refresh is not None and not isinstance(refresh, str):
        raise RSConnectException("OAuth device token response was invalid.")
    expiry = tokens.get("expires_in")
    try:
        seconds = int(expiry) if expiry is not None else 0
    except (OverflowError, TypeError, ValueError):
        seconds = 0
    expires_at = None
    if seconds > 0 and not isinstance(expiry, bool):
        try:
            candidate = time.time() + seconds
            if _valid_number(candidate):
                expires_at = candidate
        except OverflowError:
            pass
    return {
        "access_token": tokens["access_token"],
        "refresh_token": refresh,
        "expires_at": expires_at,
    }


def _pending(state: dict[str, Any]) -> dict[str, Any]:
    return {"status": "pending", "name": state["name"], "server": state["server"]}


def _finalize_connect(state: dict[str, Any]) -> dict[str, Any]:
    name, server, tokens = state["name"], state["server"], state["tokens"]
    store = _store()
    _assert_nickname_target(store, "connect", name, server)
    saved = _saved_connect_entry(store, name, server)
    if saved is not None:
        # Deployment history and keyring entries use the exact saved URL.
        server = saved["url"]
    in_keyring = keyring_store_token(server, tokens["access_token"], tokens["refresh_token"])
    ca_data = _state_ca(state)
    ca_text = ca_data.decode("utf-8") if isinstance(ca_data, bytes) else ca_data
    store.set(
        name,
        server,
        oauth_client_id=state["client_id"],
        insecure=state["insecure"],
        ca_data=ca_text,
        oauth_access_token=None if in_keyring else tokens["access_token"],
        oauth_refresh_token=None if in_keyring else tokens["refresh_token"],
        oauth_token_expiry=tokens["expires_at"],
        set_as_default=state["set_default"],
    )
    return {"status": "done", "name": name, "server": state["server"]}


class _DeviceLoginCloudClient(api.ConnectCloudClient):
    def _no_such_account(self, accounts: list[api.ConnectCloudAccount], not_found_message: str) -> RSConnectException:
        error = super()._no_such_account(accounts, not_found_message)
        return ConnectCloudAccountNotFoundError(error.message)


def _cloud_login_client(
    state: dict[str, Any], deadline: float
) -> tuple[api.ConnectCloudServer, api.ConnectCloudClient, dict[str, Any]]:
    tokens = state["tokens"]
    cloud_server = api.ConnectCloudServer(
        account_name=state["account"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        url=state["server"],
        oauth_client_id=state["client_id"],
    )
    client = _DeviceLoginCloudClient(cloud_server)
    client._suppress_oauth_response_logging = True
    client.request_timeout = deadline - time.monotonic()
    client.request_deadline = deadline
    if client.request_timeout <= 0:
        raise _FinishDeadline()
    return cloud_server, client, tokens


def _lookup_cloud_account(
    client: api.ConnectCloudClient, account_name: str, deadline: float
) -> api.ConnectCloudAccount:
    try:
        with client:
            account = client.get_account_by_name(account_name)
            if deadline <= time.monotonic():
                raise _FinishDeadline()
    except Exception as exc:
        if isinstance(exc, ConnectCloudAccountNotFoundError):
            raise
        if _invalid_grant_error(exc):
            raise InvalidGrantError() from exc
        if deadline <= time.monotonic():
            raise _FinishDeadline() from exc
        if isinstance(exc, RSConnectException):
            status_detail = " (HTTP %s)" % exc.status if exc.status is not None else ""
            safe_error = RSConnectException(
                "Posit Connect Cloud account lookup failed%s." % status_detail,
                cause=exc.cause,
                status=exc.status,
            )
            raise safe_error from None
        raise
    return account


def _checkpoint_rotated_cloud_tokens(
    state: dict[str, Any], cloud_server: api.ConnectCloudServer, tokens: dict[str, Any]
) -> None:
    if cloud_server.access_token == tokens["access_token"] and cloud_server.refresh_token == tokens["refresh_token"]:
        return
    state["tokens"] = {
        "access_token": cloud_server.access_token,
        "refresh_token": cloud_server.refresh_token,
        "expires_at": tokens["expires_at"],
    }
    _write_state(state)


def _save_cloud_account(
    state: dict[str, Any], cloud_server: api.ConnectCloudServer, account: api.ConnectCloudAccount
) -> dict[str, Any]:
    name, server_url, account_name = state["name"], state["server"], state["account"]
    store = _store()
    _assert_nickname_target(store, "cloud", name, server_url, account_name)
    in_keyring = connect_cloud.store_credentials_in_keyring(
        server_url, name, cloud_server.access_token, cloud_server.refresh_token, None
    )
    store.set(
        name,
        server_url,
        connect_cloud_account_name=account_name,
        connect_cloud_account_id=account["id"],
        connect_cloud_access_token=None if in_keyring else cloud_server.access_token,
        connect_cloud_refresh_token=None if in_keyring else cloud_server.refresh_token,
        set_as_default=state["set_default"],
    )
    return {"status": "done", "name": name, "server": server_url, "account": account_name}


def _finalize_cloud(state: dict[str, Any], deadline: float) -> dict[str, Any]:
    cloud_server, client, tokens = _cloud_login_client(state, deadline)
    try:
        account = _lookup_cloud_account(client, state["account"], deadline)
    finally:
        _checkpoint_rotated_cloud_tokens(state, cloud_server, tokens)
    return _save_cloud_account(state, cloud_server, account)


def _invalid_grant_error(error: BaseException) -> bool:
    current: Optional[BaseException] = error
    while current is not None:
        if isinstance(current, InvalidGrantError):
            return True
        cause = getattr(current, "cause", None) or current.__cause__
        current = cause if isinstance(cause, BaseException) and cause is not current else None
    return False


def _finish_state(state: dict[str, Any], deadline: float) -> dict[str, Any]:
    if state["tokens"] is None:
        tokens = _poll_for_token(state, deadline)
        if tokens is None:
            return _pending(state)
        state["tokens"] = _checkpoint(tokens)
        _write_state(state)
    if deadline <= time.monotonic():
        return _pending(state)
    if state["kind"] == "cloud":
        return _finalize_cloud(state, deadline)
    return _finalize_connect(state)


def _load_pending(kind: str, name: str) -> dict[str, Any]:
    state = _read_state(kind, name)
    if state is None:
        raise RSConnectException('No pending "%s" login exists for nickname "%s".' % (kind, name))
    if _device_code_expired(state):
        _remove_state(kind, name)
        raise _Expired()
    _assert_nickname_target(_store(), kind, name, state["server"], state["account"])
    return state


def _validate_finish_args(kind: str, name: str, timeout: int) -> str:
    if kind not in ("connect", "cloud"):
        raise RSConnectException('Login kind must be "connect" or "cloud".')
    name = _identifier(name, "Nickname")
    if type(timeout) is not int or timeout < 1:
        raise RSConnectException("Login timeout must be a positive integer.")
    return name


def finish_login(kind: str, name: str, timeout: int = 120) -> dict[str, Any]:
    require_posix("Resumable device login")
    name = _validate_finish_args(kind, name, timeout)
    deadline = time.monotonic() + timeout
    try:
        with _state_lock(kind, name, deadline):
            _remove_temporary_state_files(kind, name)
            state = _load_pending(kind, name)
            return _finish_and_cleanup(kind, name, state, deadline)
    except _LockBusy:
        return {"status": "pending", "name": name, "server": None}


def _finish_and_cleanup(kind: str, name: str, state: dict[str, Any], deadline: float) -> dict[str, Any]:
    try:
        result = _finish_state(state, deadline)
    except _FinishDeadline:
        return _pending(state)
    except (_Denied, _Expired, InvalidClientError, InvalidGrantError, ConnectCloudAccountNotFoundError):
        _remove_state(kind, name)
        raise
    if result["status"] == "done":
        _remove_state(kind, name)
    return result
