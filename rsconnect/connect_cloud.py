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

from packaging.specifiers import InvalidSpecifier, Specifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .exception import RSConnectException
from .log import logger
from .oauth import (
    ACCESS_TOKEN_FIELD,
    CLIENT_SECRET_FIELD,
    REFRESH_TOKEN_FIELD,
    keyring_delete_values,
    keyring_get_value,
    keyring_read_value,
    keyring_store_values,
    login_with_device_code,
    refresh_access_token,
    request_client_credentials_token,
)

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
        logs="https://logs.connect.posit.cloud/v1",
    ),
    "staging": ConnectCloudUrls(
        api="https://api.staging.connect.posit.cloud/v1",
        ui="https://staging.connect.posit.cloud",
        auth="https://login.staging.posit.cloud",
        logs="https://logs.staging.connect.posit.cloud/v1",
    ),
    "development": ConnectCloudUrls(
        api="https://api.dev.connect.posit.cloud/v1",
        ui="https://dev.connect.posit.cloud",
        # Development shares staging's auth service.
        auth="https://login.staging.posit.cloud",
        logs="https://logs.dev.connect.posit.cloud/v1",
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


_CREDENTIAL_FIELDS = (ACCESS_TOKEN_FIELD, REFRESH_TOKEN_FIELD, CLIENT_SECRET_FIELD)


def keyring_key(url: str, nickname: str) -> str:
    """The system keyring key for a saved Connect Cloud credential.

    Every Connect Cloud entry records the same API URL, so the nickname is what
    makes the key unique. Posit Connect keys its entries by URL alone and must
    keep doing so, or existing logins stop finding their tokens.
    """
    return "%s#%s" % (url, nickname)


def store_credentials_in_keyring(
    url: str,
    nickname: str,
    access_token: Optional[str],
    refresh_token: Optional[str],
    client_secret: Optional[str],
) -> bool:
    """Store a saved credential's secrets in the system keyring, replacing all of them.

    Returns False when no keyring is available, which means the caller has to keep
    the secrets in servers.json instead.
    """
    return keyring_store_values(
        keyring_key(url, nickname),
        {
            ACCESS_TOKEN_FIELD: access_token,
            REFRESH_TOKEN_FIELD: refresh_token,
            CLIENT_SECRET_FIELD: client_secret,
        },
    )


def store_tokens_in_keyring(url: str, nickname: str, access_token: Optional[str], refresh_token: Optional[str]) -> bool:
    """Store (or, for empty values, delete) a saved credential's tokens.

    Leaves any stored client secret alone: a token refresh rotates the tokens
    only, and `rsconnect add` is what changes the credential itself.
    """
    return keyring_store_values(
        keyring_key(url, nickname),
        {ACCESS_TOKEN_FIELD: access_token, REFRESH_TOKEN_FIELD: refresh_token},
    )


def client_secret_from_keyring(url: str, nickname: str) -> tuple[bool, Optional[str]]:
    """The stored service account client secret, and whether the keyring could be read.

    A read failure is not the same as no secret: overwriting one that may be there
    with an older copy from servers.json would break the credential.
    """
    return keyring_read_value(keyring_key(url, nickname), CLIENT_SECRET_FIELD)


def credentials_from_keyring(url: str, nickname: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """A saved credential's secrets from the system keyring, as
    (access token, refresh token, client secret). Each is None when absent."""
    key = keyring_key(url, nickname)
    return (
        keyring_get_value(key, ACCESS_TOKEN_FIELD),
        keyring_get_value(key, REFRESH_TOKEN_FIELD),
        keyring_get_value(key, CLIENT_SECRET_FIELD),
    )


def delete_credentials_from_keyring(url: str, nickname: str) -> None:
    """Delete a saved credential's secrets from the system keyring."""
    keyring_delete_values(keyring_key(url, nickname), _CREDENTIAL_FIELDS)


# The MAJOR.MINOR values Connect Cloud accepts for a revision's python_version,
# matching the RequestPythonVersion enum in its OpenAPI schema
# (https://api.connect.posit.cloud/openapi.json). Ordered lowest first.
PYTHON_VERSIONS = ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")


def _clause_version(clause: Specifier) -> Optional[Version]:
    """The version a single specifier clause names, or None if it cannot be parsed.

    Strips the wildcard from "==3.11.*", which is not a version on its own.
    """
    try:
        return Version(clause.version.rstrip("*").rstrip("."))
    except InvalidVersion:
        return None


def _line_satisfies(minor: str, specifier: SpecifierSet) -> bool:
    """Whether any patch release of a MAJOR.MINOR line satisfies the constraint.

    Connect Cloud names only the minor line, never the patch it runs, so
    ">=3.11.3" has to be judged against the whole 3.11 line rather than against
    3.11.0 alone -- otherwise a constraint Connect Cloud can actually meet is
    reported as unsupported.

    A SpecifierSet exposes no interval to test a range against, so this tests the
    patches the constraint itself names, one above each of them, and the bottom of
    the line. Every edge of the region a PEP 440 constraint admits falls on one of
    those, so a region with anything in it contains one of them.
    """
    line = Version(minor).release[:2]
    patches = {0}
    for clause in specifier:
        version = _clause_version(clause)
        if version is None or version.release[:2] != line:
            continue
        patch = version.release[2] if len(version.release) > 2 else 0
        patches.update((patch, patch + 1))
    return any(Version("%s.%d" % (minor, patch)) in specifier for patch in sorted(patches))


def _minor_version(version: str) -> Optional[str]:
    """The MAJOR.MINOR prefix of a version string, or None if it has no minor part."""
    parts = version.strip().split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return "%s.%s" % (parts[0], parts[1])


def resolve_python_version(requires: Optional[str], local_version: Optional[str]) -> Optional[str]:
    """Pick the Connect Cloud Python version for a deploy.

    `requires` is the PEP 440 constraint from the manifest's
    ``environment.python.requires``; `local_version` is the interpreter the
    bundle was built against, from ``python.version``. Returns None when neither
    is usable, which leaves the field off the request so Connect Cloud keeps
    whatever the content already has.

    The interpreter the content was built against wins when Connect Cloud offers
    its MAJOR.MINOR and the constraint allows it, so a deploy reproduces the
    development environment. Otherwise the lowest offered line satisfying the
    constraint is used, which keeps ">=3.10" on the same version as Connect Cloud
    adds newer ones.

    Connect Cloud picks the patch itself, so a constraint that names one ("==3.11.14")
    can only be honored as far as its minor line.
    """
    specifier = None
    if requires:
        try:
            specifier = SpecifierSet(requires)
        except InvalidSpecifier:
            logger.warning(
                "Ignoring the manifest's Python version requirement, which is not a valid "
                "PEP 440 constraint: %s" % requires
            )

    if local_version:
        local_minor = _minor_version(local_version)
        try:
            allowed = specifier is None or Version(local_version) in specifier
        except InvalidVersion:
            allowed = False
            local_minor = None
        if local_minor in PYTHON_VERSIONS and allowed:
            return local_minor

    if specifier is None:
        return None

    for candidate in PYTHON_VERSIONS:
        if _line_satisfies(candidate, specifier):
            return candidate

    raise RSConnectException(
        "This content requires Python %s, which Posit Connect Cloud does not offer. "
        "Supported versions are %s. Change the requirement in .python-version, "
        "pyproject.toml, or setup.cfg." % (requires, ", ".join(PYTHON_VERSIONS))
    )
