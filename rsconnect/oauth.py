"""OAuth 2.1 authentication support for Posit Connect.

Implements RFC 8414 (discovery), RFC 7591 (DCR), Authorization Code + PKCE,
Device Code flow, token refresh, and keyring integration.
"""

from __future__ import annotations

import base64
import hashlib
import queue
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer as _HTTPServer
from typing import Any, Dict, Optional, Tuple, cast
from urllib.parse import parse_qs, urlencode, urlparse

import click

from .exception import RSConnectException
from .http_support import HTTPResponse, HTTPServer
from .log import logger

# pyright: reportMissingTypeStubs=false

_KEYRING_SERVICE = "rsconnect-python"
_CLIENT_NAME = "rsconnect-python"
_CALLBACK_TIMEOUT_SECONDS = 600


class InvalidClientError(RSConnectException):
    """Raised when the OAuth server returns an invalid_client error."""

    def __init__(self) -> None:
        super().__init__("OAuth client_id is invalid or has been deleted on the server.")


def _check_oauth_error_response(response: HTTPResponse) -> None:
    """Check an HTTPResponse for OAuth error codes and raise appropriately."""
    if response.json_data and isinstance(response.json_data, dict):
        error = response.json_data.get("error", "")
        if error == "invalid_client":
            raise InvalidClientError()
        description = response.json_data.get("error_description", error)
        if description:
            raise RSConnectException(f"OAuth error: {description}")


def _unwrap_json_response(response: Any) -> dict[str, Any]:
    """Extract JSON dict from an HTTPResponse (raw HTTPServer doesn't auto-unwrap).

    Returns the dict if successful, raises RSConnectException on error responses.
    """
    if isinstance(response, HTTPResponse):
        if response.status and 200 <= response.status < 300 and isinstance(response.json_data, dict):
            return cast(Dict[str, Any], response.json_data)
        _check_oauth_error_response(response)
        raise RSConnectException(f"OAuth request failed: HTTP {response.status}.")
    if isinstance(response, dict):
        return cast(Dict[str, Any], response)
    raise RSConnectException("Unexpected OAuth response format.")


def discover_oauth_metadata(
    url: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Fetch OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Returns the parsed JSON metadata dict, or raises RSConnectException if
    the server does not support OAuth.
    """
    server = HTTPServer(url, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.get("/.well-known/oauth-authorization-server")

    if isinstance(response, HTTPResponse):
        if response.status != 200:
            raise RSConnectException(
                f"Server at {url} does not support OAuth 2.1 "
                f"(discovery endpoint returned HTTP {response.status}). "
                f"The server may need to be upgraded, or OAuth may be intentionally disabled by an administrator."
            )
        if isinstance(response.json_data, dict) and "token_endpoint" in response.json_data:
            return response.json_data
        raise RSConnectException(f"Server at {url} returned a non-JSON response from the OAuth discovery endpoint.")

    if not isinstance(response, dict) or "token_endpoint" not in response:
        raise RSConnectException(f"Server at {url} returned invalid OAuth metadata (missing token_endpoint).")

    return response


def register_client(
    metadata: dict[str, Any],
    url: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> str:
    """Register an OAuth client via Dynamic Client Registration (RFC 7591).

    Returns the client_id.
    """
    registration_endpoint = str(metadata.get("registration_endpoint", ""))
    if not registration_endpoint:
        raise RSConnectException("OAuth metadata does not include a registration_endpoint.")

    parsed = urlparse(registration_endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    grant_types = ["authorization_code", "refresh_token"]
    if metadata.get("device_authorization_endpoint"):
        grant_types.append("urn:ietf:params:oauth:grant-type:device_code")

    server = HTTPServer(base, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.post(
            path,
            body={
                "client_name": _CLIENT_NAME,
                "redirect_uris": ["http://127.0.0.1/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": grant_types,
                "response_types": ["code"],
            },
        )

    data = _unwrap_json_response(response)
    if "client_id" not in data:
        raise RSConnectException("OAuth client registration returned an unexpected response (no client_id).")

    return str(data["client_id"])


def generate_pkce_pair() -> Tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(96)[:96]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def _exchange_code_for_token(
    metadata: dict[str, Any],
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""
    token_endpoint = str(metadata["token_endpoint"])
    parsed = urlparse(token_endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    body = urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode("utf-8")

    server = HTTPServer(base, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    data = _unwrap_json_response(response)
    if "access_token" not in data:
        raise RSConnectException("Token exchange returned an unexpected response.")

    return data


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the OAuth redirect callback."""

    result_queue: queue.Queue[Tuple[str, Optional[str], Optional[str]]]

    def do_GET(self) -> None:  # noqa: N802
        qs = parse_qs(urlparse(self.path).query)
        code = qs.get("code", [None])[0]
        state = qs.get("state", [None])[0]
        error = qs.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()

        if error:
            self.wfile.write(b"<html><body><h1>Authentication failed.</h1><p>You may close this tab.</p></body></html>")
            self.result_queue.put(("error", error, qs.get("error_description", [""])[0]))
        elif code:
            self.wfile.write(
                b"<html><body><h1>Authentication successful!</h1><p>You may close this tab.</p></body></html>"
            )
            self.result_queue.put(("success", code, state))
        else:
            self.wfile.write(b"<html><body><h1>Unexpected response.</h1></body></html>")
            self.result_queue.put(("error", "no_code", "No authorization code in callback"))

    def log_message(self, format: str, *args: object) -> None:
        logger.debug(f"OAuth callback server: {format % args}")


def login_with_browser(
    url: str,
    client_id: str,
    metadata: dict[str, Any],
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Perform OAuth Authorization Code + PKCE flow via browser.

    Opens the user's browser to the authorization URL and starts a local
    HTTP server to receive the callback. Returns the token response dict.
    """
    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    result_queue: queue.Queue[Tuple[str, Optional[str], Optional[str]]] = queue.Queue()

    callback_server = _HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = callback_server.server_address[1]
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    # Attach queue to the handler class for this server instance
    callback_server.RequestHandlerClass.result_queue = result_queue  # type: ignore[attr-defined]

    auth_endpoint = str(metadata["authorization_endpoint"])
    auth_params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    auth_url = f"{auth_endpoint}?{auth_params}"

    server_thread = threading.Thread(target=callback_server.handle_request, daemon=True)
    server_thread.start()

    if not webbrowser.open(auth_url):
        click.echo(
            f"Could not open browser automatically. This can happen if no display is available\n"
            f"or localhost is blocked by network rules. Please open this URL manually:\n\n"
            f"  {auth_url}\n\n"
            f"Waiting for authentication callback..."
        )
    else:
        click.echo("Opened browser for authentication. Waiting for callback...")

    server_thread.join(timeout=_CALLBACK_TIMEOUT_SECONDS)
    callback_server.server_close()

    if result_queue.empty():
        raise RSConnectException(f"OAuth browser callback timed out after {_CALLBACK_TIMEOUT_SECONDS} seconds.")

    result = result_queue.get_nowait()
    if result[0] == "error":
        raise RSConnectException(f"OAuth authentication failed: {result[1]} — {result[2]}")

    _, code, returned_state = result
    if returned_state != state:
        raise RSConnectException("OAuth state mismatch — possible CSRF attack.")
    if not code:
        raise RSConnectException("OAuth callback did not contain an authorization code.")

    return _exchange_code_for_token(metadata, client_id, code, code_verifier, redirect_uri, insecure, ca_data)


def login_with_device_code(
    url: str,
    client_id: str,
    metadata: dict[str, Any],
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Perform OAuth Device Code flow.

    Displays a URL and user code for the user to enter in a browser,
    then polls for token completion.
    """
    device_endpoint = str(metadata.get("device_authorization_endpoint", ""))
    if not device_endpoint:
        raise RSConnectException(
            "Server does not support the device code flow. "
            "The server may need to be upgraded, or the device code flow may be "
            "intentionally disabled by an administrator. Try again without --use-device-code."
        )

    parsed = urlparse(device_endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    body = urlencode({"client_id": client_id}).encode("utf-8")

    server = HTTPServer(base, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    resp = _unwrap_json_response(response)
    device_code = str(resp.get("device_code", ""))
    user_code = str(resp.get("user_code", ""))
    verification_uri = str(resp.get("verification_uri", ""))
    interval = int(resp.get("interval", 5))
    expires_in = int(resp.get("expires_in", 600))

    verification_uri_complete = str(resp.get("verification_uri_complete", "")) or verification_uri

    click.echo(f"\nOpen this URL in your browser:\n\n  {verification_uri_complete}\n")
    click.echo(f"Enter the code: {user_code}\n")
    click.echo("Waiting for authorization...")

    return _poll_for_device_token(metadata, client_id, device_code, interval, expires_in, insecure, ca_data)


def _poll_for_device_token(
    metadata: dict[str, Any],
    client_id: str,
    device_code: str,
    interval: int,
    expires_in: int,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Poll the token endpoint for device code completion."""
    token_endpoint = str(metadata["token_endpoint"])
    parsed = urlparse(token_endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    deadline = time.time() + expires_in
    poll_interval = interval

    while time.time() < deadline:
        time.sleep(poll_interval)

        body = urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            }
        ).encode("utf-8")

        server = HTTPServer(base, disable_tls_check=insecure, ca_data=ca_data)
        with server:
            response = server.request(
                "POST",
                path,
                body=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        # Extract JSON from the response (raw HTTPServer always returns HTTPResponse)
        json_data: Optional[dict[str, Any]] = None
        if isinstance(response, HTTPResponse):
            if isinstance(response.json_data, dict):
                json_data = response.json_data
            else:
                raise RSConnectException(f"Device code token request failed: HTTP {response.status}.")
        elif isinstance(response, dict):
            json_data = response

        if json_data is None:
            raise RSConnectException("Device code token request returned an unexpected response.")

        if "access_token" in json_data:
            return json_data

        error = str(json_data.get("error", ""))
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            poll_interval += 5
            continue
        elif error == "invalid_client":
            raise InvalidClientError()
        elif error == "expired_token":
            raise RSConnectException("Device code expired. Please try again.")
        elif error == "access_denied":
            raise RSConnectException("Authorization was denied by the user.")
        elif error:
            description = str(json_data.get("error_description", error))
            raise RSConnectException(f"Device code flow failed: {description}")
        else:
            raise RSConnectException("Device code token request returned an unexpected response.")

    raise RSConnectException("Device code authorization timed out. Please try again.")


def refresh_access_token(
    metadata: dict[str, Any],
    client_id: str,
    refresh_token: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> dict[str, Any]:
    """Refresh an OAuth access token using a refresh token.

    Returns the new token response dict. Raises InvalidClientError if the
    client_id has been deleted server-side.
    """
    token_endpoint = str(metadata["token_endpoint"])
    parsed = urlparse(token_endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path

    body = urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")

    server = HTTPServer(base, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    data = _unwrap_json_response(response)
    if "access_token" not in data:
        raise RSConnectException("Token refresh returned an unexpected response.")

    return data


_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
_ID_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
_ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


def exchange_token_for_api_key(
    url: str,
    subject_token: str,
    insecure: bool = False,
    ca_data: Optional[str | bytes] = None,
) -> str:
    """Exchange an OIDC token for a short-lived Connect API key (RFC 8693).

    This performs the trusted-publishing token exchange against Connect's OAuth
    token endpoint (``POST /oauth/v1/token``). Connect verifies the OIDC
    ``subject_token`` and, if it matches a service principal that a content owner
    has bound as a "trusted publisher", mints an ephemeral API key scoped to that
    content.

    Returns the API key. Raises RSConnectException with an actionable message
    when the exchange fails.
    """
    body = urlencode(
        {
            "grant_type": _TOKEN_EXCHANGE_GRANT,
            "subject_token_type": _ID_TOKEN_TYPE,
            "requested_token_type": _ACCESS_TOKEN_TYPE,
            "subject_token": subject_token,
        }
    ).encode("utf-8")

    # Pass the full server URL (not just scheme://netloc) so HTTPServer appends
    # the token-exchange path relative to any configured path prefix.
    server = HTTPServer(url, disable_tls_check=insecure, ca_data=ca_data)
    with server:
        response = server.request(
            "POST",
            "/oauth/v1/token",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if not isinstance(response, HTTPResponse):
        raise RSConnectException("Unexpected response from the OIDC token exchange.")

    status = response.status
    data = response.json_data if isinstance(response.json_data, dict) else {}

    if status and 200 <= status < 300:
        api_key = data.get("access_token")
        if not api_key:
            raise RSConnectException("Connect returned a successful token exchange but no API key (access_token).")
        return str(api_key)

    raise _token_exchange_error(status, data)


def _token_exchange_error(status: Optional[int], data: dict[str, Any]) -> RSConnectException:
    """Translate a failed token-exchange response into an actionable exception."""
    error = str(data.get("error", "")) if data else ""
    description = str(data.get("error_description", "")) if data else ""

    if status == 404:
        return RSConnectException(
            "This Connect server has no OIDC token-exchange endpoint (/oauth/v1/token). "
            "It is likely too old to support trusted publishing; upgrade Connect, or "
            "authenticate with an API key instead."
        )

    if status == 400 and error == "unsupported_grant_type":
        return RSConnectException(
            "This Connect server's OAuth service does not support token exchange, so it is "
            "likely too old to support trusted publishing. Upgrade Connect, or authenticate "
            "with an API key instead."
        )

    if status == 400 and error == "invalid_grant":
        lowered = description.lower()
        if "ambiguous" in lowered:
            return RSConnectException(
                f"The OIDC token matched more than one trusted publisher on Connect ({description}). "
                "Resolve the duplicate trusted publishers on the server, or authenticate with an API key."
            )
        if "verif" in lowered:
            return RSConnectException(
                f"Connect could not verify the OIDC token ({description}). "
                "Check the server clock and the OIDC issuer configuration, or authenticate with an API key."
            )
        return RSConnectException(
            f"Connect did not recognize this token as a trusted publisher ({description or 'no match'}). "
            "Confirm a trusted publisher has been configured for the target content and that the token's "
            "audience matches it, or authenticate with an API key."
        )

    detail = error
    if description:
        detail = f"{error}: {description}" if error else description
    suffix = f" ({detail})" if detail else ""
    return RSConnectException(f"OIDC token exchange failed (HTTP {status}){suffix}.")


# ---------------------------------------------------------------------------
# Keyring integration
# ---------------------------------------------------------------------------


def keyring_store_token(server_url: str, access_token: str, refresh_token: Optional[str]) -> bool:
    """Store OAuth tokens in the system keyring.

    Returns True on success, False if keyring is not available.
    """
    try:
        import keyring  # type: ignore[import-untyped]

        keyring.set_password(_KEYRING_SERVICE, f"{server_url}:access_token", access_token)
        if refresh_token:
            keyring.set_password(_KEYRING_SERVICE, f"{server_url}:refresh_token", refresh_token)
        else:
            try:
                keyring.delete_password(_KEYRING_SERVICE, f"{server_url}:refresh_token")
            except keyring.errors.PasswordDeleteError:
                pass
        return True
    except ImportError:
        return False
    except Exception as e:
        logger.warning(f"keyring storage failed: {e}")
        return False


def keyring_get_tokens(server_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Retrieve OAuth tokens from the system keyring.

    Returns (access_token, refresh_token), or (None, None) if unavailable.
    """
    try:
        import keyring  # type: ignore[import-untyped]

        access = keyring.get_password(_KEYRING_SERVICE, f"{server_url}:access_token")
        refresh = keyring.get_password(_KEYRING_SERVICE, f"{server_url}:refresh_token")
        return access, refresh
    except ImportError:
        return None, None
    except Exception as e:
        logger.warning(f"keyring retrieval failed: {e}")
        return None, None


def keyring_delete_tokens(server_url: str) -> None:
    """Delete OAuth tokens from the system keyring."""
    try:
        import keyring  # type: ignore[import-untyped]
        import keyring.errors  # type: ignore[import-untyped]

        for suffix in (":access_token", ":refresh_token"):
            try:
                keyring.delete_password(_KEYRING_SERVICE, f"{server_url}{suffix}")
            except keyring.errors.PasswordDeleteError:
                pass
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"keyring deletion failed: {e}")
