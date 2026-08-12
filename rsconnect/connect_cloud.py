"""Posit Connect Cloud environment configuration and authentication.

Connect Cloud is a distinct deployment target from Posit Connect and
shinyapps.io. It authenticates with OAuth 2.0 against ``login.posit.cloud``,
using either the device code flow (interactive) or the client credentials
grant (non-interactive, for CI).
"""

from __future__ import annotations

import os
from typing import Any, NamedTuple, Optional
from urllib.parse import urlparse

from .exception import RSConnectException
from .oauth import login_with_device_code, refresh_access_token, request_client_credentials_token

# The OAuth scope Connect Cloud issues tokens for. "vivid" is the internal name
# of the Connect Cloud API.
SCOPE = "vivid"

# Environment selection. Connect Cloud has production, staging, and development
# deployments
ENVIRONMENT_ENV_VAR = "CONNECT_CLOUD_ENVIRONMENT"
# Overrides the OAuth client this CLI identifies itself as. Distinct from
# CONNECT_CLOUD_CLIENT_ID, which is a user's service account credential.
OAUTH_CLIENT_ID_ENV_VAR = "CONNECT_CLOUD_OAUTH_CLIENT_ID"
DEFAULT_ENVIRONMENT = "production"


class ConnectCloudUrls(NamedTuple):
    """The set of hosts that make up one Connect Cloud environment."""

    api: str
    ui: str
    auth: str
    logs: str

    @property
    def device_authorization_endpoint(self) -> str:
        return self.auth + "/oauth/device/authorize"

    @property
    def token_endpoint(self) -> str:
        return self.auth + "/oauth/token"

    def oauth_metadata(self) -> dict[str, Any]:
        """Shape these URLs like the OIDC discovery document ``oauth.py`` expects.

        Connect Cloud does not publish a discovery document, so we synthesize the
        two fields the device code flow needs.
        """
        return {
            "device_authorization_endpoint": self.device_authorization_endpoint,
            "token_endpoint": self.token_endpoint,
        }

    def content_url(self, account_name: str, content_id: str) -> str:
        """Build the browsable URL for a content item.

        The API never returns one: responses carry only ``account_id``, so the
        caller has to resolve the owning account name first.
        """
        return "%s/%s/content/%s" % (self.ui, account_name, content_id)


_ENVIRONMENTS: dict[str, ConnectCloudUrls] = {
    "production": ConnectCloudUrls(
        api="https://api.connect.posit.cloud/v1",
        ui="https://connect.posit.cloud",
        auth="https://login.posit.cloud",
        logs="https://logs.connect.posit.cloud",
    ),
    "staging": ConnectCloudUrls(
        api="https://api.staging.connect.posit.cloud/v1",
        ui="https://staging.connect.posit.cloud",
        auth="https://login.staging.posit.cloud",
        logs="https://logs.staging.connect.posit.cloud",
    ),
    "development": ConnectCloudUrls(
        api="https://api.dev.connect.posit.cloud/v1",
        ui="https://dev.connect.posit.cloud",
        # Development shares staging's auth service.
        auth="https://login.staging.posit.cloud",
        logs="https://logs.dev.connect.posit.cloud",
    ),
}

# The OAuth client registered for this CLI, per environment. These are public
# clients: the device code flow uses no client secret.
_CLIENT_IDS: dict[str, str] = {
    "production": "rsconnect-python",
    "staging": "rsconnect-python-staging",
    "development": "rsconnect-python-development",
}


def environment_name() -> str:
    """The selected Connect Cloud environment name."""
    name = os.environ.get(ENVIRONMENT_ENV_VAR) or DEFAULT_ENVIRONMENT
    if name not in _ENVIRONMENTS:
        raise RSConnectException(
            "Unknown Connect Cloud environment %r (from %s). Expected one of: %s."
            % (name, ENVIRONMENT_ENV_VAR, ", ".join(sorted(_ENVIRONMENTS)))
        )
    return name


def urls(environment: Optional[str] = None) -> ConnectCloudUrls:
    """The URLs for the given (or currently selected) Connect Cloud environment."""
    return _ENVIRONMENTS[environment or environment_name()]


def client_id(environment: Optional[str] = None) -> str:
    """The OAuth client ID to authenticate this CLI with."""
    override = os.environ.get(OAUTH_CLIENT_ID_ENV_VAR)
    if override:
        return override
    return _CLIENT_IDS[environment or environment_name()]


# What a user types for --server to mean Connect Cloud, mirroring how
# "shinyapps.io" is accepted in place of https://api.shinyapps.io.
SERVER_NAME = "connect.posit.cloud"


def _canonical_api_url(url: str) -> Optional[str]:
    """The environment API base URL that `url` refers to, or None.

    Tolerates only scheme/host case and a trailing slash; the path, port, and
    query must match exactly, keeping the no-substring rule from
    is_connect_cloud_url.
    """
    parsed = urlparse(url)
    key = (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, parsed.fragment)
    for env in _ENVIRONMENTS.values():
        api = urlparse(env.api)
        if key == (api.scheme, api.netloc, api.path, api.query, api.fragment):
            return env.api
    return None


def is_connect_cloud_url(url: Optional[str]) -> bool:
    """Whether a --server value or stored URL refers to Connect Cloud.

    Matches the pseudo-server name and the API base URL of every environment,
    tolerating host case and a trailing slash but nothing looser. This is
    deliberately not a substring test: the removed Posit Cloud support matched
    "posit.cloud" anywhere in the URL, in four separate places, which would
    also match an unrelated host such as connect.posit.cloud.example.com.
    """
    if not url:
        return False
    if url.rstrip("/").lower() == SERVER_NAME:
        return True
    return _canonical_api_url(url) is not None


def resolve_url(url: Optional[str]) -> str:
    """Turn a --server value into the API base URL for the selected environment.

    Recognized API URLs are canonicalized (case, trailing slash), so the stored
    URL always matches environment_for_url and joins cleanly with request paths.
    """
    if not url or url.rstrip("/").lower() == SERVER_NAME:
        return urls().api
    return _canonical_api_url(url) or url


def environment_for_url(url: Optional[str]) -> str:
    """Which environment an API base URL belongs to.

    A saved server records only its API URL, so this is how everything else about
    that environment — the auth, UI, and logs hosts — is recovered. Without it, a
    server saved against staging would have its tokens refreshed against
    production and its content URLs built from the production UI host.

    Falls back to the selected environment for a URL we do not recognize.
    """
    canonical = _canonical_api_url(url) if url else None
    for name, env in _ENVIRONMENTS.items():
        if canonical == env.api:
            return name
    return environment_name()


def login_interactive(environment: Optional[str] = None) -> dict[str, Any]:
    """Authenticate with the OAuth device code flow.

    Prints a verification URL and user code, then polls until the user
    authorizes. Returns the token response, which includes ``access_token`` and
    ``refresh_token``.
    """
    env = environment or environment_name()
    env_urls = urls(env)
    return login_with_device_code(
        url=env_urls.auth,
        client_id=client_id(env),
        metadata=env_urls.oauth_metadata(),
        scope=SCOPE,
    )


def login_client_credentials(
    client_id_value: str,
    client_secret: str,
    environment: Optional[str] = None,
) -> dict[str, Any]:
    """Authenticate with the OAuth client credentials grant, for CI.

    Credentials are minted at https://login.posit.cloud/identity/credentials.
    The response carries no refresh token, so the credentials themselves are
    stored and used to mint a new access token when the current one expires.
    """
    env_urls = urls(environment)
    return request_client_credentials_token(
        token_endpoint=env_urls.token_endpoint,
        client_id=client_id_value,
        client_secret=client_secret,
        scope=SCOPE,
    )


def refresh(refresh_token: str, environment: Optional[str] = None) -> dict[str, Any]:
    """Mint a new access token from a refresh token."""
    env = environment or environment_name()
    return refresh_access_token(
        metadata=urls(env).oauth_metadata(),
        client_id=client_id(env),
        refresh_token=refresh_token,
        scope=SCOPE,
    )
