"""
Posit Connect API client and utility functions
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import json
import os
import re
import sys
import time
import typing
import webbrowser
from os.path import abspath, dirname
from ssl import SSLError
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Literal,
    Mapping,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)
from urllib import parse
from urllib.parse import urlencode, urlparse
from warnings import warn

import click

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

# Even though TypedDict is available in Python 3.8, because it's used with NotRequired,
# they should both come from the same typing module.
# https://peps.python.org/pep-0655/#usage-in-python-3-11
if sys.version_info >= (3, 11):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

from . import validation
from .bundle import _default_title
from .certificates import read_certificate_file
from .environment import fake_module_file_from_directory
from .exception import DeploymentFailedException, RSConnectException
from .http_support import (
    CookieJar,
    HTTPResponse,
    HTTPServer,
    JsonData,
    append_to_path,
    create_multipart_form_data,
)
from .log import cls_logged, connect_logger, console_logger, logger
from .metadata import AppStore, ServerData, ServerStore
from .models import (
    AppMode,
    AppModes,
    BootstrapOutputDTO,
    BuildOutputDTO,
    BundleMetadata,
    ContentItemV0,
    ContentItemV1,
    DeleteInputDTO,
    DeleteOutputDTO,
    EnvironmentCreateInput,
    EnvironmentPermissionInput,
    EnvironmentPermissionV1,
    EnvironmentUpdateInput,
    EnvironmentV1,
    ListEntryOutputDTO,
    OAuthIntegration,
    OAuthIntegrationInput,
    OAuthIntegrationUpdate,
    OAuthTemplate,
    PyInfo,
    RepositoryBundleOutput,
    RepositoryInfo,
    ServerSettings,
    TaskStatusV1,
    UserRecord,
)
from .snowflake import generate_jwt, get_parameters
from .timeouts import get_task_timeout, get_task_timeout_help_message
from .utils_package import compare_semvers

if TYPE_CHECKING:
    import logging


T = TypeVar("T")
P = ParamSpec("P")


class AbstractRemoteServer:
    def __init__(self, url: str, remote_name: str):
        self.url = url
        self.remote_name = remote_name

    @overload
    def handle_bad_response(self, response: HTTPResponse, is_httpresponse: Literal[True]) -> HTTPResponse: ...

    @overload
    def handle_bad_response(self, response: HTTPResponse | T, is_httpresponse: Literal[False] = False) -> T: ...

    def handle_bad_response(self, response: HTTPResponse | T, is_httpresponse: bool = False) -> T | HTTPResponse:
        """
        Handle a bad response from the server.

        For most requests, we expect the response to already have been converted to
        JSON. This is when `is_httpresponse` has the default value False. In these
        cases:

        * By the time a response object reaches this function, it should have been
          converted to the JSON data contained in the original HTTPResponse object.
          If the response is still an HTTPResponse object at this point, that means
          that something went wrong, and it raises an exception, even if the status
          was 2xx.

        However, in some cases, we expect that the input object is an HTTPResponse
        that did not contain JSON. This is when `is_httpresponse` is set to True. In
        these cases:

        * The response object should still be an HTTPResponse object. If it has a
          2xx status, then it will be returned. If it has any other status, then
          an exceptio nwill be raised.

        :param response: The response object to check.
        :param is_httpresponse: If False (the default), expect that the input object is
            a JsonData object. If True, expect that the input object is a HTTPResponse
            object.
        :return: The response object, if it is not an HTTPResponse object. If it was
                an HTTPResponse object, this function will raise an exception and
                not return.
        """

        if isinstance(response, HTTPResponse):
            if response.exception:
                raise RSConnectException(
                    "Could not connect to %s - %s" % (self.url, response.exception), cause=response.exception
                )
            # Sometimes an ISP will respond to an unknown server name by returning a friendly
            # search page so trap that since we know we're expecting JSON from Connect.  This
            # also catches all error conditions which we will report as "not running Connect".
            else:
                if (
                    response.json_data
                    and isinstance(response.json_data, dict)
                    and "error" in response.json_data
                    and response.json_data["error"] is not None
                ):
                    error = "%s reported an error (calling %s): %s" % (
                        self.remote_name,
                        response.full_uri,
                        response.json_data["error"],
                    )
                    raise RSConnectException(error, status=response.status)
                if response.status < 200 or response.status > 299:
                    raise RSConnectException(
                        "Received an unexpected response from %s (calling %s): %s %s"
                        % (
                            self.remote_name,
                            response.full_uri,
                            response.status,
                            response.reason,
                        ),
                        status=response.status,
                    )
                if not is_httpresponse:
                    # If we got here, it was a 2xx response that contained JSON and did not
                    # have an error field, but for some reason the object returned from the
                    # prior function call was not converted from a HTTPResponse to JSON. This
                    # should never happen, so raise an exception.
                    raise RSConnectException(
                        "Received an unexpected response from %s (calling %s): %s %s"
                        % (
                            self.remote_name,
                            response.full_uri,
                            response.status,
                            response.reason,
                        )
                    )
        return response


class PositServer(AbstractRemoteServer):
    """
    A class used to represent the server of the shinyapps.io API.
    """

    def __init__(self, remote_name: str, url: str, account_name: str, token: str, secret: str):
        super().__init__(url, remote_name)
        self.account_name = account_name
        self.token = token
        self.secret = secret


class ShinyappsServer(PositServer):
    """
    A class to encapsulate the information needed to interact with an
    instance of the shinyapps.io server.
    """

    def __init__(self, url: str, account_name: str, token: str, secret: str):
        remote_name = "shinyapps.io"
        if url == "shinyapps.io" or url is None:
            url = "https://api.shinyapps.io"
        super().__init__(remote_name=remote_name, url=url, account_name=account_name, token=token, secret=secret)


class RSConnectServer(AbstractRemoteServer):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the Connect server.
    """

    def __init__(
        self,
        url: str,
        api_key: Optional[str],
        insecure: bool = False,
        ca_data: Optional[str | bytes] = None,
        bootstrap_jwt: Optional[str] = None,
        oauth_access_token: Optional[str] = None,
        oauth_client_id: Optional[str] = None,
        server_name: Optional[str] = None,
    ):
        super().__init__(url, "Posit Connect")
        self.api_key = api_key
        self.bootstrap_jwt = bootstrap_jwt
        self.insecure = insecure
        self.ca_data = ca_data
        self.oauth_access_token = oauth_access_token
        self.oauth_client_id = oauth_client_id
        self.server_name = server_name
        # This is specifically not None.
        self.cookie_jar = CookieJar()
        # for compatibility with RSconnectClient
        self.snowflake_connection_name = None


class SPCSConnectServer(AbstractRemoteServer):
    """
    A class to encapsulate the information needed to interact with an instance
    of Posit Connect deployed in Snowflake SPCS (Snowpark Container Services).

    SPCS deployments use Snowflake OIDC authentication combined with Connect API keys.
    """

    def __init__(
        self,
        url: str,
        api_key: Optional[str],
        snowflake_connection_name: Optional[str],
        insecure: bool = False,
        ca_data: Optional[str | bytes] = None,
    ):
        super().__init__(url, "Posit Connect (SPCS)")
        self.snowflake_connection_name = snowflake_connection_name
        self.insecure = insecure
        self.ca_data = ca_data
        # for compatibility with RSConnectClient
        self.cookie_jar = CookieJar()
        self.api_key = api_key
        self.bootstrap_jwt = None

    def token_endpoint(self) -> str:
        params = get_parameters(self.snowflake_connection_name)

        if params is None:
            raise RSConnectException("No Snowflake connection found.")

        return f"https://{params['account']}.snowflakecomputing.com/"

    def fmt_payload(self):
        params = get_parameters(self.snowflake_connection_name)

        if params is None:
            raise RSConnectException("No Snowflake connection found.")

        authenticator = params.get("authenticator")
        if not authenticator:
            raise NotImplementedError("Snowflake connection does not declare an authenticator.")

        authenticator = authenticator.lower()
        if authenticator == "snowflake_jwt":
            spcs_url = urlparse(self.url)
            scope = f"session:role:{params['role']} {spcs_url.netloc}" if params.get("role") else spcs_url.netloc
            jwt = generate_jwt(self.snowflake_connection_name)
            grant_type = "urn:ietf:params:oauth:grant-type:jwt-bearer"

            payload = {"scope": scope, "assertion": jwt, "grant_type": grant_type}
            payload = urlencode(payload)
            return {
                "body": payload,
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "path": "/oauth/token",
            }
        elif authenticator == "oauth":
            payload = {
                "data": {
                    "AUTHENTICATOR": "OAUTH",
                    "TOKEN": params["token"],
                }
            }
            return {
                "body": payload,
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {params['token']}",
                    "X-Snowflake-Authorization-Token-Type": "OAUTH",
                },
                "path": "/session/v1/login-request",
            }
        else:
            raise NotImplementedError(f"Unsupported authenticator for SPCS Connect: {authenticator}")

    def exchange_token(self) -> str:
        try:
            server = HTTPServer(url=self.token_endpoint())
            payload = self.fmt_payload()

            response = server.request(
                method="POST",
                **payload,  # type: ignore[arg-type]  # fmt_payload returns a dict with body and headers
            )
            response = cast(HTTPResponse, response)

            # borrowed from AbstractRemoteServer.handle_bad_response
            # since we don't want to pick up its json decoding assumptions
            if response.status < 200 or response.status > 299:
                raise RSConnectException(
                    "Received an unexpected response from %s (calling %s): %s %s"
                    % (
                        self.url,
                        response.full_uri,
                        response.status,
                        response.reason,
                    )
                )

            # Validate response body exists
            if not response.response_body:
                raise RSConnectException("Token exchange returned empty response")

            # Ensure response body is decoded to string on the object
            if isinstance(response.response_body, bytes):
                response.response_body = response.response_body.decode("utf-8")

                # Try to parse as JSON first
            try:
                import json

                json_data = json.loads(response.response_body)
                # If it's JSON, extract the token from data.token
                if isinstance(json_data, dict) and "data" in json_data and "token" in json_data["data"]:
                    return json_data["data"]["token"]
                else:
                    # JSON format doesn't match expected structure, return raw response
                    return response.response_body
            except (json.JSONDecodeError, ValueError):
                # Not JSON, return the raw response body
                return response.response_body

        except RSConnectException as e:
            raise RSConnectException(f"Failed to exchange Snowflake token: {str(e)}") from e


TargetableServer = typing.Union[ShinyappsServer, RSConnectServer, SPCSConnectServer]


class S3Server(AbstractRemoteServer):
    def __init__(self, url: str):
        super().__init__(url, "S3")


class RSConnectClientDeployResult(TypedDict):
    task_id: str | None
    app_id: str
    app_guid: str | None
    app_url: str
    dashboard_url: str
    draft_url: str | None
    bundle_id: str | None
    title: str | None


def server_supports_git_metadata(server_version: Optional[str]) -> bool:
    """
    Check if the server version supports git metadata in bundle uploads.

    Git metadata support was added in Connect 2025.12.0.

    :param server_version: The Connect server version string
    :return: True if the server supports git metadata, False otherwise
    """
    if not server_version:
        return False

    try:
        return compare_semvers(server_version, "2025.11.0") > 0
    except Exception:
        # If we can't parse the version, assume it doesn't support it
        logger.debug(f"Unable to parse server version: {server_version}")
        return False


def server_supports_draft_deploy(server_version: Optional[str]) -> bool:
    """
    Check if the server supports deploying a bundle as a draft and activating it
    separately, i.e. the ``activate`` field on the content deploy/build endpoints.

    Older servers reject the unknown field, so we must not send it to them.

    Draft deploys were added in Connect 2025.06.0.

    :param server_version: The Connect server version string
    :return: True if the server supports draft deploys, False otherwise
    """
    if not server_version:
        return False

    try:
        return compare_semvers(server_version, "2025.06.0") >= 0
    except Exception:
        # If we can't parse the version, assume it doesn't support it
        logger.debug(f"Unable to parse server version: {server_version}")
        return False


class RSConnectClient(HTTPServer):
    def __init__(self, server: Union[RSConnectServer, SPCSConnectServer], cookies: Optional[CookieJar] = None):
        if cookies is None:
            cookies = server.cookie_jar
        super().__init__(
            append_to_path(server.url, "__api__"),
            server.insecure,
            server.ca_data,
            cookies,
        )
        self._server = server

        if server.api_key:
            self.key_authorization(server.api_key)

        if server.bootstrap_jwt:
            self.bootstrap_authorization(server.bootstrap_jwt)

        if server.snowflake_connection_name and isinstance(server, SPCSConnectServer):
            token = server.exchange_token()
            self.snowflake_authorization(token)
            if server.api_key:
                self._headers["X-RSC-Authorization"] = server.api_key

        if (
            isinstance(server, RSConnectServer)
            and server.oauth_access_token
            and not server.api_key
            and not server.bootstrap_jwt
        ):
            self.authorization(f"Bearer {server.oauth_access_token}")

    def request(
        self,
        method: str,
        path: str,
        query_params: Optional[Mapping[str, "JsonData"]] = None,
        body: "str | bytes | IO[bytes] | Mapping[str, Any] | list[Any] | None" = None,
        maximum_redirects: int = 5,
        decode_response: bool = True,
        headers: Optional[Mapping[str, str]] = None,
    ) -> "JsonData | HTTPResponse":
        can_retry = isinstance(self._server, RSConnectServer) and bool(self._server.oauth_client_id)
        start_pos: "int | None" = None
        if can_retry and hasattr(body, "read"):
            if getattr(body, "seekable", lambda: False)():
                start_pos = body.tell()  # type: ignore[union-attr]
            else:
                body = body.read()  # type: ignore[union-attr]
        response = super().request(method, path, query_params, body, maximum_redirects, decode_response, headers)  # pyright: ignore[reportUnknownArgumentType]
        if can_retry and isinstance(response, HTTPResponse) and response.status == 401:
            if self._attempt_token_refresh():
                if start_pos is not None:
                    body.seek(start_pos)  # type: ignore[union-attr]
                return super().request(method, path, query_params, body, maximum_redirects, decode_response, headers)  # pyright: ignore[reportUnknownArgumentType]
        return response

    def _attempt_token_refresh(self) -> bool:
        from .oauth import (
            InvalidClientError,
            discover_oauth_metadata,
            keyring_delete_tokens,
            keyring_get_tokens,
            keyring_store_token,
            refresh_access_token,
            register_client,
        )
        from .metadata import ServerStore

        server = cast(RSConnectServer, self._server)

        _, refresh_token = keyring_get_tokens(server.url)
        if not refresh_token:
            store = ServerStore()
            entry = None
            if server.server_name:
                entry = store.get_by_name(server.server_name)
            if not entry:
                entry = store.get_by_url(server.url)
            if entry:
                refresh_token = entry.get("oauth_refresh_token")  # type: ignore[assignment]
        if not refresh_token:
            return False

        try:
            metadata = discover_oauth_metadata(server.url, server.insecure, server.ca_data)
            token_response = refresh_access_token(
                metadata, server.oauth_client_id or "", refresh_token, server.insecure, server.ca_data
            )
        except InvalidClientError:
            # Client was deleted server-side; clear stale tokens and re-register
            keyring_delete_tokens(server.url)
            store = ServerStore()
            entry = None
            if server.server_name:
                entry = store.get_by_name(server.server_name)
            if not entry:
                entry = store.get_by_url(server.url)
            if entry:
                entry_name = str(entry.get("name", server.server_name or server.url))
                store.update_oauth_tokens(entry_name, None, None, None)
            try:
                metadata = discover_oauth_metadata(server.url, server.insecure, server.ca_data)
                new_client_id = register_client(metadata, server.url, server.insecure, server.ca_data)
                server.oauth_client_id = new_client_id
                if entry:
                    entry["oauth_client_id"] = new_client_id  # type: ignore[typeddict-unknown-key]
                    store._set(entry_name, entry)  # type: ignore[possibly-undefined]
                logger.warning("OAuth client was re-registered; please run `rsconnect login` again.")
            except Exception as exc:
                logger.warning(f"OAuth client re-registration failed: {exc}. Please run `rsconnect login` again.")
            return False
        except Exception as exc:
            logger.warning(f"OAuth token refresh failed: {exc}")
            return False

        new_access = token_response["access_token"]
        new_refresh = token_response.get("refresh_token", refresh_token)
        expires_in = token_response.get("expires_in")
        import time

        new_expiry = time.time() + expires_in if expires_in else None

        self.authorization(f"Bearer {new_access}")
        server.oauth_access_token = new_access

        stored = keyring_store_token(server.url, new_access, new_refresh)
        if not stored:
            store = ServerStore()
            entry = None
            if server.server_name:
                entry = store.get_by_name(server.server_name)
            if not entry:
                entry = store.get_by_url(server.url)
            if entry:
                entry_name = str(entry.get("name", server.server_name or server.url))
                store.update_oauth_tokens(entry_name, new_access, new_refresh, new_expiry)

        return True

    def _tweak_response(self, response: HTTPResponse) -> JsonData | HTTPResponse:
        return (
            response.json_data
            if response.status and response.status >= 200 and response.status <= 299 and response.json_data is not None
            else response
        )

    def me(self) -> UserRecord:
        response = cast(Union[UserRecord, HTTPResponse], self.get("v1/user"))
        response = self._server.handle_bad_response(response)
        return response

    def bootstrap(self) -> BootstrapOutputDTO | HTTPResponse:
        response = cast(Union[BootstrapOutputDTO, HTTPResponse], self.post("v1/experimental/bootstrap"))
        # TODO: The place where bootstrap() is called expects a JSON object if the response is successfule, and a
        # HTTPResponse if it is not; then it handles the error. This is different from the other methods, and probably
        # should be changed in the future. For this to work, we will _not_ call .handle_bad_response() here at present.
        # response = self._server.handle_bad_response(response)
        return response

    def server_settings(self) -> ServerSettings:
        response = cast(Union[ServerSettings, HTTPResponse], self.get("server_settings"))
        response = self._server.handle_bad_response(response)
        return response

    def python_settings(self) -> PyInfo:
        response = cast(Union[PyInfo, HTTPResponse], self.get("v1/server_settings/python"))
        response = self._server.handle_bad_response(response)
        return response

    def app_get(self, app_id: str) -> ContentItemV0:
        response = cast(Union[ContentItemV0, HTTPResponse], self.get(f"applications/{app_id}"))
        response = self._server.handle_bad_response(response)
        return response

    def add_environment_vars(self, content_guid: str, env_vars: list[tuple[str, str]]):
        env_body = [dict(name=kv[0], value=kv[1]) for kv in env_vars]
        return self.patch(f"v1/content/{content_guid}/environment", body=env_body)

    def is_failed_response(self, response: HTTPResponse | JsonData) -> bool:
        return isinstance(response, HTTPResponse) and response.status >= 500

    def access_content(self, content_guid: str, bundle_id: Optional[str] = None) -> None:
        method = "GET"
        base = dirname(self._url.path).rstrip("/")  # strip "__api__" and any trailing slash
        # Access a specific (e.g. draft, not-yet-activated) bundle's preview URL when a
        # bundle id is given. Connect spins the process up cold to serve this, so a
        # successful response confirms the bundle actually runs without touching the
        # active bundle.
        suffix = f"_bundle{bundle_id}/" if bundle_id is not None else ""
        path = f"{base}/content/{content_guid}/{suffix}"
        response = self._do_request(method, path, None, None, 3, {}, False)

        if self.is_failed_response(response):
            # Get content metadata to construct logs URL
            content = self.content_get(content_guid)
            logs_url = content["dashboard_url"] + "/logs"
            raise RSConnectException(
                "Could not access the deployed content. "
                + "The app might not have started successfully."
                + f"\n\t For more information: {logs_url}"
            )

    def bundle_download(self, content_guid: str, bundle_id: str) -> HTTPResponse:
        response = cast(
            HTTPResponse,
            self.get(f"v1/content/{content_guid}/bundles/{bundle_id}/download", decode_response=False),
        )
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def content_lockfile(self, content_guid: str) -> HTTPResponse:
        response = cast(
            HTTPResponse,
            self.get(f"v1/content/{content_guid}/lockfile", decode_response=False),
        )
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def content_list(self, filters: Optional[Mapping[str, JsonData]] = None) -> list[ContentItemV1]:
        response = cast(Union[List[ContentItemV1], HTTPResponse], self.get("v1/content", query_params=filters))
        response = self._server.handle_bad_response(response)
        return response

    def content_get(self, content_guid: str) -> ContentItemV1:
        response = cast(Union[ContentItemV1, HTTPResponse], self.get(f"v1/content/{content_guid}"))
        response = self._server.handle_bad_response(response)
        return response

    def get_content_by_id(self, id: str) -> ContentItemV1:
        """
        Get content by ID, which can be either a numeric ID (legacy) or GUID.

        :param app_id: Either a numeric ID (e.g., "1234") or GUID (e.g., "abc-def-123")
        :return: ContentItemV1 data
        """
        # Check if it looks like a GUID (contains hyphens)
        if "-" in str(id):
            return self.content_get(id)
        else:
            # Legacy numeric ID - get v0 content first to get GUID
            app_v0 = self.app_get(id)
            # TODO: deprecation warning here
            return self.content_get(app_v0["guid"])

    def content_create(self, name: str) -> ContentItemV1:
        response = cast(Union[ContentItemV1, HTTPResponse], self.post("v1/content", body={"name": name}))
        response = self._server.handle_bad_response(response)
        return response

    def upload_bundle(
        self, content_guid: str, tarball: typing.IO[bytes], metadata: Optional[dict[str, str]] = None
    ) -> BundleMetadata:
        """
        Upload a bundle to the server.

        :param app_id: Application ID
        :param tarball: Bundle tarball file object
        :param metadata: Optional metadata dictionary (e.g., git metadata)
        :return: ContentItemV0 with bundle information
        """
        if metadata:
            # Use multipart form upload when metadata is provided
            tarball_content = tarball.read()
            fields = {
                "archive": ("bundle.tar.gz", tarball_content, "application/x-tar"),
                "metadata": json.dumps(metadata),
            }
            body, content_type = create_multipart_form_data(fields)
            response = cast(
                Union[BundleMetadata, HTTPResponse],
                self.post(f"v1/content/{content_guid}/bundles", body=body, headers={"Content-Type": content_type}),
            )
        else:
            response = cast(
                Union[BundleMetadata, HTTPResponse], self.post(f"v1/content/{content_guid}/bundles", body=tarball)
            )
            response = self._server.handle_bad_response(response)
        return response

    def content_update(self, content_guid: str, updates: Mapping[str, str | None]) -> ContentItemV1:
        response = cast(Union[ContentItemV1, HTTPResponse], self.patch(f"v1/content/{content_guid}", body=updates))
        response = self._server.handle_bad_response(response)
        return response

    def content_build(
        self, content_guid: str, bundle_id: Optional[str] = None, activate: bool = True
    ) -> BuildOutputDTO:
        body: dict[str, str | bool | None] = {"bundle_id": bundle_id}
        if not activate:
            # The default behavior is to activate the app after building.
            # So we only pass the parameter if we want to deactivate it.
            # That way we can keep the API backwards compatible.
            body["activate"] = False
        response = cast(
            Union[BuildOutputDTO, HTTPResponse],
            self.post(f"v1/content/{content_guid}/build", body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def content_deploy(
        self, content_guid: str, bundle_id: Optional[str] = None, activate: bool = True
    ) -> BuildOutputDTO:
        body: dict[str, str | bool | None] = {"bundle_id": bundle_id}
        if not activate:
            # The default behavior is to activate the app after deploying.
            # So we only pass the parameter if we want to deactivate it.
            # That way we can keep the API backwards compatible.
            body["activate"] = False
        response = cast(
            Union[BuildOutputDTO, HTTPResponse],
            self.post(f"v1/content/{content_guid}/deploy", body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_repository(self, content_guid: str) -> Optional[RepositoryInfo]:
        """Get git repository configuration for a content item.

        :param content_guid: The GUID of the content item
        :return: Repository configuration if git-managed, None otherwise
        """
        response = self.get("v1/content/%s/repository" % content_guid)
        if isinstance(response, HTTPResponse):
            # 404 means not git-managed, which is not an error
            if response.status == 404:
                return None
            self._server.handle_bad_response(response)
        return cast(RepositoryInfo, response)

    def set_repository(
        self,
        content_guid: str,
        repository: str,
        branch: str = "main",
        directory: str = ".",
        polling: bool = True,
    ) -> RepositoryInfo:
        """Create or overwrite git repository configuration for a content item.

        :param content_guid: The GUID of the content item
        :param repository: URL of the git repository (https:// only)
        :param branch: Branch to deploy from (default: main)
        :param directory: Directory containing manifest.json (default: .)
        :param polling: Whether the git repository should be regularly polled (default: True)
        :return: The repository configuration
        """
        body = {
            "repository": repository,
            "branch": branch,
            "directory": directory,
            "polling": polling,
        }
        response = cast(
            Union[RepositoryInfo, HTTPResponse],
            self.put("v1/content/%s/repository" % content_guid, body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def update_repository(
        self,
        content_guid: str,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        directory: Optional[str] = None,
        polling: Optional[bool] = None,
    ) -> RepositoryInfo:
        """Partially update git repository configuration for a content item.

        Only fields that are provided will be updated.

        :param content_guid: The GUID of the content item
        :param repository: URL of the git repository (https:// only)
        :param branch: Branch to deploy from
        :param directory: Directory containing manifest.json
        :param polling: Whether the git repository should be regularly polled
        :return: The updated repository configuration
        """
        body: dict[str, str | bool] = {}
        if repository is not None:
            body["repository"] = repository
        if branch is not None:
            body["branch"] = branch
        if directory is not None:
            body["directory"] = directory
        if polling is not None:
            body["polling"] = polling

        response = cast(
            Union[RepositoryInfo, HTTPResponse],
            self.patch("v1/content/%s/repository" % content_guid, body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def delete_repository(self, content_guid: str) -> None:
        """Remove git repository configuration from a content item.

        :param content_guid: The GUID of the content item
        """
        response = self.delete("v1/content/%s/repository" % content_guid)
        if isinstance(response, HTTPResponse):
            self._server.handle_bad_response(response, is_httpresponse=True)

    def create_bundle_from_repository(
        self,
        content_guid: str,
        repository: Optional[str] = None,
        ref: Optional[str] = None,
        directory: Optional[str] = None,
    ) -> RepositoryBundleOutput:
        """Create a bundle from a git repository location.

        This triggers Connect to clone the repository and create a bundle.
        If the content item has existing git configuration, those values are used
        as defaults; provided parameters will override them.

        :param content_guid: The GUID of the content item
        :param repository: URL of the git repository (uses existing config if not provided)
        :param ref: Git ref to bundle from (branch, tag, or commit; uses existing branch if not provided)
        :param directory: Directory containing manifest.json (uses existing config if not provided)
        :return: Bundle creation result with bundle_id and task_id
        """
        body: dict[str, str] = {}
        if repository is not None:
            body["repository"] = repository
        if ref is not None:
            body["ref"] = ref
        if directory is not None:
            body["directory"] = directory

        response = cast(
            Union[RepositoryBundleOutput, HTTPResponse],
            self.post("v1/content/%s/repository/bundle" % content_guid, body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def deploy_git(
        self,
        app_id: Optional[str],
        name: str,
        repository: str,
        branch: str,
        subdirectory: str,
        title: Optional[str],
        env_vars: Optional[dict[str, str]],
        polling: bool = True,
        activate: bool = True,
    ) -> RSConnectClientDeployResult:
        """Deploy content from a git repository.

        Creates or updates a git-backed content item in Posit Connect. Connect will clone
        the repository and regularly poll it for updates.

        :param app_id: Existing content ID/GUID to update, or None to create new content
        :param name: Name for the content item (used if creating new)
        :param repository: URL of the git repository (https:// only)
        :param branch: Branch to deploy from
        :param subdirectory: Subdirectory containing manifest.json
        :param title: Title for the content
        :param env_vars: Environment variables to set
        :param polling: Whether the git repository should be regularly polled (default: True)
        :param activate: Whether to activate the deployment (False = draft mode)
        :return: Deployment result with task_id, app info, etc.
        """
        # Create or get existing content
        if app_id is None:
            app = self.content_create(name)
        else:
            try:
                app = self.get_content_by_id(app_id)
            except RSConnectException as e:
                raise RSConnectException(
                    f"{e} Try setting the --new flag or omit --app-id to create new content."
                ) from e

        app_guid = app["guid"]

        # Map subdirectory to directory (API uses "directory" field)
        directory = subdirectory if subdirectory else "."

        # Check if content already has git configuration
        existing_repo = self.get_repository(app_guid)

        try:
            if existing_repo:
                # Update existing git configuration using PATCH
                self.update_repository(
                    app_guid,
                    repository=repository,
                    branch=branch,
                    directory=directory,
                    polling=polling,
                )
            else:
                # Create new git configuration using PUT
                self.set_repository(
                    app_guid,
                    repository=repository,
                    branch=branch,
                    directory=directory,
                    polling=polling,
                )
        except RSConnectException as e:
            # A 404 from the repository endpoint means git-backed deployment is
            # not available on this Connect server.
            if e.status == 404:
                raise RSConnectException(
                    "Git-backed deployment is not enabled on this Connect server. "
                    "Contact your administrator to enable Git support."
                ) from e
            raise

        # Update title if provided (and different from current)
        if title and app.get("title") != title:
            self.patch("v1/content/%s" % app_guid, body={"title": title})

        # Set environment variables
        if env_vars:
            result = self.add_environment_vars(app_guid, list(env_vars.items()))
            self._server.handle_bad_response(result)

        # Trigger deployment (bundle_id=None uses the latest bundle from git clone)
        task = self.content_deploy(app_guid, bundle_id=None, activate=activate)

        return RSConnectClientDeployResult(
            app_id=str(app["id"]),
            app_guid=app_guid,
            app_url=app["content_url"],
            task_id=task["task_id"],
            title=title or app.get("title"),
            dashboard_url=app["dashboard_url"],
            draft_url=None,
        )

    def system_caches_runtime_list(self) -> list[ListEntryOutputDTO]:
        response = cast(Union[List[ListEntryOutputDTO], HTTPResponse], self.get("v1/system/caches/runtime"))
        response = self._server.handle_bad_response(response)
        return response

    def system_caches_runtime_delete(self, target: DeleteInputDTO) -> DeleteOutputDTO:
        response = cast(Union[DeleteOutputDTO, HTTPResponse], self.delete("v1/system/caches/runtime", body=target))
        response = self._server.handle_bad_response(response)
        return response

    def environment_list(self) -> list[EnvironmentV1]:
        response = cast(Union[List[EnvironmentV1], HTTPResponse], self.get("v1/environments"))
        response = self._server.handle_bad_response(response)
        return response

    def environment_get(self, guid: str) -> EnvironmentV1:
        response = cast(Union[EnvironmentV1, HTTPResponse], self.get(f"v1/environments/{guid}"))
        response = self._server.handle_bad_response(response)
        return response

    def environment_create(self, body: EnvironmentCreateInput) -> EnvironmentV1:
        response = cast(Union[EnvironmentV1, HTTPResponse], self.post("v1/environments", body=body))
        response = self._server.handle_bad_response(response)
        return response

    def environment_update(self, guid: str, body: EnvironmentUpdateInput) -> EnvironmentV1:
        response = cast(Union[EnvironmentV1, HTTPResponse], self.put(f"v1/environments/{guid}", body=body))
        response = self._server.handle_bad_response(response)
        return response

    def environment_delete(self, guid: str) -> None:
        response = cast(HTTPResponse, self.delete(f"v1/environments/{guid}", decode_response=False))
        self._server.handle_bad_response(response, is_httpresponse=True)

    def environment_permission_list(self, env_guid: str) -> list[EnvironmentPermissionV1]:
        response = cast(
            Union[List[EnvironmentPermissionV1], HTTPResponse],
            self.get(f"v1/environments/{env_guid}/permissions"),
        )
        response = self._server.handle_bad_response(response)
        return response

    def environment_permission_add(self, env_guid: str, body: EnvironmentPermissionInput) -> EnvironmentPermissionV1:
        response = cast(
            Union[EnvironmentPermissionV1, HTTPResponse],
            self.post(f"v1/environments/{env_guid}/permissions", body=body),
        )
        response = self._server.handle_bad_response(response)
        return response

    def environment_permission_delete(self, env_guid: str, permission_guid: str) -> None:
        response = cast(
            HTTPResponse,
            self.delete(f"v1/environments/{env_guid}/permissions/{permission_guid}", decode_response=False),
        )
        self._server.handle_bad_response(response, is_httpresponse=True)

    def oauth_integration_list(self) -> list[OAuthIntegration]:
        response = cast(Union[List[OAuthIntegration], HTTPResponse], self.get("v1/oauth/integrations"))
        response = self._server.handle_bad_response(response)
        return response

    def oauth_integration_get(self, guid: str) -> OAuthIntegration:
        response = cast(Union[OAuthIntegration, HTTPResponse], self.get(f"v1/oauth/integrations/{guid}"))
        response = self._server.handle_bad_response(response)
        return response

    def oauth_integration_create(self, body: OAuthIntegrationInput) -> OAuthIntegration:
        response = cast(Union[OAuthIntegration, HTTPResponse], self.post("v1/oauth/integrations", body=body))
        response = self._server.handle_bad_response(response)
        return response

    def oauth_integration_update(self, guid: str, body: OAuthIntegrationUpdate) -> OAuthIntegration:
        response = cast(Union[OAuthIntegration, HTTPResponse], self.patch(f"v1/oauth/integrations/{guid}", body=body))
        response = self._server.handle_bad_response(response)
        return response

    def oauth_integration_delete(self, guid: str) -> None:
        response = cast(HTTPResponse, self.delete(f"v1/oauth/integrations/{guid}", decode_response=False))
        self._server.handle_bad_response(response, is_httpresponse=True)

    def oauth_template_list(self) -> list[OAuthTemplate]:
        response = cast(Union[List[OAuthTemplate], HTTPResponse], self.get("v1/oauth/templates"))
        response = self._server.handle_bad_response(response)
        return response

    def oauth_template_get(self, key: str) -> OAuthTemplate:
        response = cast(Union[OAuthTemplate, HTTPResponse], self.get(f"v1/oauth/templates/{key}"))
        response = self._server.handle_bad_response(response)
        return response

    def task_get(
        self,
        task_id: str,
        first: Optional[int] = None,
        wait: Optional[int] = None,
    ) -> TaskStatusV1:
        params = None
        if first is not None or wait is not None:
            params = {}
            if first is not None:
                params["first"] = first
            if wait is not None:
                params["wait"] = wait
        response = cast(Union[TaskStatusV1, HTTPResponse], self.get(f"v1/tasks/{task_id}", query_params=params))
        response = self._server.handle_bad_response(response)

        # compatibility with rsconnect-jupyter
        response["status"] = response["output"]
        response["last_status"] = response["last"]

        return response

    def deploy(
        self,
        app_id: Optional[str],
        app_name: Optional[str],
        app_title: Optional[str],
        title_is_default: bool,
        tarball: IO[bytes],
        env_vars: Optional[dict[str, str]] = None,
        activate: bool = True,
        metadata: Optional[dict[str, str]] = None,
    ) -> RSConnectClientDeployResult:
        if app_id is None:
            if app_name is None:
                raise RSConnectException("An app ID or name is required to deploy an app.")
            # create content if id is not provided
            app = self.content_create(app_name)

            # Force the title to update.
            title_is_default = False
        else:
            # assume content exists. if it was deleted then Connect will raise an error
            try:
                # app_id could be a numeric ID (legacy) or GUID
                app = self.get_content_by_id(app_id)
            except RSConnectException as e:
                raise RSConnectException(f"{e} Try setting the --new flag to overwrite the previous deployment.") from e

        app_guid = app["guid"]
        if env_vars:
            result = self.add_environment_vars(app_guid, list(env_vars.items()))
            result = self._server.handle_bad_response(result)

        if app["title"] != app_title and not title_is_default:
            result = self.content_update(app_guid, {"title": app_title})
            result = self._server.handle_bad_response(result)
            app["title"] = app_title

        app_bundle = self.upload_bundle(app_guid, tarball, metadata=metadata)

        task = self.content_deploy(app_guid, app_bundle["id"], activate=activate)

        draft_url = app["dashboard_url"] + f"/draft/{app_bundle['id']}"

        return {
            "task_id": task["task_id"],
            "app_id": app["id"],
            "app_guid": app["guid"],
            "app_url": app["content_url"],
            "dashboard_url": app["dashboard_url"],
            "draft_url": draft_url if not activate else None,
            "bundle_id": app_bundle["id"],
            "title": app["title"],
        }

    def download_bundle(self, content_guid: str, bundle_id: str) -> HTTPResponse:
        results = self.bundle_download(content_guid, bundle_id)
        return results

    def search_content(self) -> list[ContentItemV1]:
        results = self.content_list()
        return results

    def get_content(self, content_guid: str) -> ContentItemV1:
        results = self.content_get(content_guid)
        return results

    def wait_for_task(
        self,
        task_id: str,
        log_callback: Optional[Callable[[str], None]],
        abort_func: Callable[[], bool] = lambda: False,
        timeout: int = get_task_timeout(),
        poll_wait: int = 1,
        raise_on_error: bool = True,
    ) -> tuple[list[str] | None, TaskStatusV1]:
        if log_callback is None:
            log_lines: list[str] | None = []
            log_callback = log_lines.append
        else:
            log_lines = None

        first: int | None = None
        start_time = time.time()
        while True:
            if (time.time() - start_time) > timeout:
                raise RSConnectException(get_task_timeout_help_message(timeout))
            elif abort_func():
                raise RSConnectException("Task aborted.")

            task = self.task_get(task_id, first=first, wait=poll_wait)
            self.output_task_log(task, log_callback)
            first = task["last"]
            if task["finished"]:
                result = task.get("result")
                if isinstance(result, dict):
                    data = result.get("data", "")
                    type = result.get("type", "")
                    if data or type:
                        log_callback("%s (%s)" % (data, type))

                err = task.get("error")
                if err:
                    log_callback("Error from Connect server: " + err)

                exit_code = task["code"]
                if exit_code != 0:
                    exit_status = "Task exited with status %d." % exit_code
                    if raise_on_error:
                        raise RSConnectException(exit_status)
                    else:
                        log_callback("Task failed. %s" % exit_status)
                return log_lines, task

    @staticmethod
    def output_task_log(
        task: TaskStatusV1,
        log_callback: Callable[[str], None],
    ):
        """Pipe any new output through the log_callback."""
        for line in task["output"]:
            log_callback(line)


class ServerDetailsPython(TypedDict):
    api_enabled: bool
    versions: list[str]


class ServerDetails(TypedDict):
    connect: str
    python: ServerDetailsPython


class RSConnectExecutor:
    def __init__(
        self,
        ctx: Optional[click.Context] = None,
        name: Optional[str] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        snowflake_connection_name: Optional[str] = None,
        insecure: bool = False,
        cacert: Optional[str] = None,
        ca_data: Optional[str | bytes] = None,
        cookies: Optional[CookieJar] = None,
        account: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: int = 30,
        logger: Optional[logging.Logger] = console_logger,
        *,
        path: Optional[str] = None,
        server: Optional[str] = None,
        exclude: Optional[tuple[str, ...]] = None,
        new: Optional[bool] = None,
        app_id: Optional[str] = None,
        title: Optional[str] = None,
        visibility: Optional[str] = None,
        disable_env_management: Optional[bool] = None,
        env_vars: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        subdirectory: Optional[str] = None,
        polling: bool = True,
    ) -> None:
        self.remote_server: TargetableServer
        self.client: RSConnectClient | PositClient

        self.path = path or os.getcwd()
        self.server = server
        self.exclude = exclude
        self.new = new
        self.app_id = app_id
        self.title = title or _default_title(self.path)
        self.visibility = visibility
        self.disable_env_management = disable_env_management
        self.env_vars = env_vars
        self.metadata = metadata
        self.app_mode: AppMode | None = None
        self.app_store: AppStore = AppStore(fake_module_file_from_directory(self.path))
        self.app_store_version: int | None = None
        self.api_key_is_required: bool | None = None
        self.title_is_default: bool = not title
        self.deployment_name: str | None = None

        # Git deployment parameters
        self.repository: str | None = repository
        self.branch: str | None = branch
        self.subdirectory: str | None = subdirectory
        self.polling: bool = polling

        self.bundle: IO[bytes] | None = None
        self.deployed_info: RSConnectClientDeployResult | None = None
        self._draft_deploy_supported: bool | None = None

        self.logger: logging.Logger | None = logger
        self.ctx = ctx
        self.setup_remote_server(
            ctx=ctx,
            name=name,
            url=url or server,
            api_key=api_key,
            snowflake_connection_name=snowflake_connection_name,
            insecure=insecure,
            cacert=cacert,
            ca_data=ca_data,
            account_name=account,
            token=token,
            secret=secret,
        )
        self.setup_client(cookies)

    @classmethod
    def fromConnectServer(
        cls,
        connect_server: RSConnectServer,
        ctx: Optional[click.Context] = None,
        cookies: Optional[CookieJar] = None,
        account: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: int = 30,
        logger: Optional[logging.Logger] = console_logger,
        *,
        path: Optional[str] = None,
        server: Optional[str] = None,
        exclude: Optional[tuple[str, ...]] = None,
        new: Optional[bool] = None,
        app_id: Optional[str] = None,
        title: Optional[str] = None,
        visibility: Optional[str] = None,
        disable_env_management: Optional[bool] = None,
        env_vars: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, str]] = None,
        repository: Optional[str] = None,
        branch: Optional[str] = None,
        subdirectory: Optional[str] = None,
        polling: bool = True,
    ):
        return cls(
            ctx=ctx,
            url=connect_server.url,
            api_key=connect_server.api_key,
            insecure=connect_server.insecure,
            ca_data=connect_server.ca_data,
            cookies=cookies,
            account=account,
            token=token,
            secret=secret,
            timeout=timeout,
            logger=logger,
            path=path,
            server=server,
            exclude=exclude,
            new=new,
            app_id=app_id,
            title=title,
            visibility=visibility,
            disable_env_management=disable_env_management,
            env_vars=env_vars,
            metadata=metadata,
            repository=repository,
            branch=branch,
            subdirectory=subdirectory,
            polling=polling,
        )

    def output_overlap_header(self, previous: bool) -> bool:
        if self.logger and not previous:
            self.logger.warning(
                "\nConnect detected CLI commands and/or environment variables that overlap with stored credential.\n"
            )
            self.logger.warning(
                "Check your environment variables (e.g. CONNECT_API_KEY) to make sure you want them to be used.\n"
            )
            self.logger.warning(
                "Credential parameters are taken with the following precedence: stored > CLI > environment.\n"
            )
            self.logger.warning(
                "To ignore an environment variable, override it in the CLI with an empty string (e.g. -k '').\n\n"
            )
            return True
        else:
            return False

    def output_overlap_details(self, cli_param: str, previous: bool):
        new_previous = self.output_overlap_header(previous)
        sourceName = validation.get_parameter_source_name_from_ctx(cli_param, self.ctx)
        if self.logger is not None:
            self.logger.warning(f">> stored {cli_param} value overrides the {cli_param} value from {sourceName}\n")
        return new_previous

    def setup_remote_server(
        self,
        ctx: Optional[click.Context],
        name: Optional[str] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        snowflake_connection_name: Optional[str] = None,
        insecure: bool = False,
        cacert: Optional[str] = None,
        ca_data: Optional[str | bytes] = None,
        account_name: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        store = ServerStore()
        validation.validate_connection_options(
            ctx=ctx,
            url=url,
            api_key=api_key,
            snowflake_connection_name=snowflake_connection_name,
            insecure=insecure,
            cacert=cacert,
            account_name=account_name,
            token=token,
            secret=secret,
            name=name,
            has_default_server=store.get_default() is not None,
        )
        # The validation.validate_connection_options() function ensures that certain
        # combinations of arguments are present; the cast() calls inside of the
        # if-statements below merely reflect these validations.
        header_output = False

        if cacert and not ca_data:
            ca_data = read_certificate_file(cacert)

        # Skip default-server resolution when shinyapps credentials are explicitly
        # provided — the user is targeting shinyapps.io, not a stored Connect server.
        if token and secret and account_name and not name and not url:
            server_data = ServerData(None, None, False)
        else:
            server_data = store.resolve(name, url)
        if server_data.from_store:
            url = server_data.url
            if self.logger:
                if server_data.api_key and api_key:
                    header_output = self.output_overlap_details("api-key", header_output)
                if server_data.snowflake_connection_name and snowflake_connection_name:
                    header_output = self.output_overlap_details("snowflake_connection_name", header_output)
                if server_data.insecure and insecure:
                    header_output = self.output_overlap_details("insecure", header_output)
                if server_data.ca_data and ca_data:
                    header_output = self.output_overlap_details("cacert", header_output)
                if server_data.account_name and account_name:
                    header_output = self.output_overlap_details("account", header_output)
                if server_data.token and token:
                    header_output = self.output_overlap_details("token", header_output)
                if server_data.secret and secret:
                    header_output = self.output_overlap_details("secret", header_output)
                if header_output:
                    self.logger.warning("\n")

            api_key = api_key or server_data.api_key
            snowflake_connection_name = snowflake_connection_name or server_data.snowflake_connection_name
            insecure = insecure or server_data.insecure
            ca_data = ca_data or server_data.ca_data
            account_name = account_name or server_data.account_name
            token = token or server_data.token
            secret = secret or server_data.secret

        self.is_server_from_store = server_data.from_store

        if snowflake_connection_name:
            url = cast(str, url)
            self.remote_server = SPCSConnectServer(url, api_key, snowflake_connection_name, insecure, ca_data)
        elif api_key:
            url = cast(str, url)
            self.remote_server = RSConnectServer(url, api_key, insecure, ca_data)
        elif token and secret:
            url = cast(str, url)
            account_name = cast(str, account_name)
            self.remote_server = ShinyappsServer(url, account_name, token, secret)
        elif server_data.from_store and server_data.oauth_client_id:
            url = cast(str, url)
            from .oauth import keyring_get_tokens

            access_token, _ = keyring_get_tokens(url)
            oauth_access_token = access_token or server_data.oauth_access_token
            self.remote_server = RSConnectServer(
                url,
                None,
                insecure,
                ca_data,
                oauth_access_token=oauth_access_token,
                oauth_client_id=server_data.oauth_client_id,
                server_name=name or server_data.name,
            )
        else:
            raise RSConnectException("Unable to infer Connect server type and setup server.")

    def setup_client(self, cookies: Optional[CookieJar] = None):
        if isinstance(self.remote_server, RSConnectServer):
            self.client = RSConnectClient(self.remote_server, cookies)
        elif isinstance(self.remote_server, SPCSConnectServer):
            self.client = RSConnectClient(self.remote_server)
        elif isinstance(self.remote_server, PositServer):
            self.client = PositClient(self.remote_server)
        else:
            raise RSConnectException("Unable to infer Connect client.")

    def pipe(self, func: Callable[P, T], *args: P.args, **kwargs: P.kwargs):
        return func(*args, **kwargs)

    @cls_logged("Validating server...")
    def validate_server(self):
        """
        Validate that there is enough information to talk to shinyapps.io or a Connect server.
        """
        if isinstance(self.remote_server, SPCSConnectServer):
            self.validate_spcs_server()
        elif isinstance(self.remote_server, RSConnectServer):
            self.validate_connect_server()

        elif isinstance(self.remote_server, PositServer):
            self.validate_posit_server()
        else:
            raise RSConnectException("Unable to validate server from information provided.")

        return self

    def validate_connect_server(self):
        if not isinstance(self.remote_server, RSConnectServer):
            raise RSConnectException("remote_server must be a Connect server.")
        url = self.remote_server.url
        api_key = self.remote_server.api_key
        insecure = self.remote_server.insecure
        api_key_is_required = self.api_key_is_required
        ca_data = self.remote_server.ca_data

        server_data = ServerStore().resolve(None, url)
        connect_server = RSConnectServer(url, None, insecure, ca_data)

        # If our info came from the command line, make sure the URL really works.
        if not server_data.from_store:
            self.server_settings()

        connect_server.api_key = api_key

        if not connect_server.api_key:
            if api_key_is_required:
                raise RSConnectException('An API key must be specified for "%s".' % connect_server.url)
            return self

        # If our info came from the command line, make sure the key really works.
        if not server_data.from_store:
            self.verify_api_key(connect_server)

        self.remote_server = connect_server
        self.client = RSConnectClient(self.remote_server)

        return self

    def validate_spcs_server(self):
        if not isinstance(self.remote_server, SPCSConnectServer):
            raise RSConnectException("remote_server must be a Connect server in SPCS")

        url = self.remote_server.url
        api_key = self.remote_server.api_key
        snowflake_connection_name = self.remote_server.snowflake_connection_name
        server = SPCSConnectServer(url, api_key, snowflake_connection_name)

        with RSConnectClient(server) as client:
            try:
                result = client.me()
                result = server.handle_bad_response(result)
            except RSConnectException as exc:
                raise RSConnectException(f"Failed to verify with {server.remote_name} ({exc})")

        return self

    def validate_posit_server(self):
        if not isinstance(self.remote_server, PositServer):
            raise RSConnectException("remote_server is not a Posit server.")

        remote_server: PositServer = self.remote_server
        url = remote_server.url
        account_name = remote_server.account_name
        token = remote_server.token
        secret = remote_server.secret
        server = ShinyappsServer(url, account_name, token, secret)

        with PositClient(server) as client:
            try:
                result = client.get_current_user()
                result = server.handle_bad_response(result)
            except RSConnectException as exc:
                raise RSConnectException("Failed to verify with {} ({}).".format(server.remote_name, exc))

    @cls_logged("Making bundle ...")
    def make_bundle(
        self,
        func: Callable[P, IO[bytes]],
        *args: P.args,
        **kwargs: P.kwargs,
        # These are the actual kwargs that appear to be present in practice
        # image: Optional[str] = None,
        # env_management_py: Optional[bool] = None,
        # env_management_r: Optional[bool] = None,
        # multi_notebook: Optional[bool] = None,
    ):
        force_unique_name = self.app_id is None
        self.deployment_name = self.make_deployment_name(self.title, force_unique_name)

        try:
            self.bundle = func(*args, **kwargs)
        except IOError as error:
            msg = "Unable to include the file %s in the bundle: %s" % (
                error.filename,
                error.args[1],
            )
            raise RSConnectException(msg)

        return self

    def upload_posit_bundle(self, prepare_deploy_result: PrepareDeployResult, bundle_size: int, contents: bytes):
        upload_url = prepare_deploy_result.presigned_url
        parsed_upload_url = urlparse(upload_url)
        with S3Client(f"{parsed_upload_url.scheme}://{parsed_upload_url.netloc}") as s3_client:
            upload_result = cast(
                HTTPResponse,
                s3_client.upload(
                    f"{parsed_upload_url.path}?{parsed_upload_url.query}",
                    prepare_deploy_result.presigned_checksum,
                    bundle_size,
                    contents,
                ),
            )
            upload_result = S3Server(upload_url).handle_bad_response(upload_result, is_httpresponse=True)

    @cls_logged("Deploying bundle ...")
    def deploy_bundle(self, activate: bool = True):
        if self.deployment_name is None:
            raise RSConnectException("A deployment name must be created before deploying a bundle.")
        if self.bundle is None:
            raise RSConnectException("A bundle must be created before deploying it.")

        if isinstance(self.remote_server, (RSConnectServer, SPCSConnectServer)):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("client must be an RSConnectClient.")
            result = self.client.deploy(
                self.app_id,
                self.deployment_name,
                self.title,
                self.title_is_default,
                self.bundle,
                self.env_vars,
                activate=activate,
                metadata=self.metadata,
            )
            self.deployed_info = result
            return self
        else:
            contents = self.bundle.read()
            bundle_size = len(contents)
            bundle_hash = hashlib.md5(contents).hexdigest()

            if not isinstance(self.client, PositClient):
                raise RSConnectException("client must be a PositClient.")

            shinyapps_service = ShinyappsService(self.client, self.remote_server)
            prepare_deploy_result = shinyapps_service.prepare_deploy(
                self.app_id,
                self.deployment_name,
                bundle_size,
                bundle_hash,
                self.visibility,
            )
            self.upload_posit_bundle(prepare_deploy_result, bundle_size, contents)
            # type: ignore[arg-type] - PrepareDeployResult uses int, but format() accepts it
            shinyapps_service.do_deploy(prepare_deploy_result.bundle_id, prepare_deploy_result.app_id)

            print(f"Application successfully deployed to {prepare_deploy_result.app_url}")
            webbrowser.open_new(prepare_deploy_result.app_url)

            self.deployed_info = RSConnectClientDeployResult(
                app_url=prepare_deploy_result.app_url,
                app_id=str(prepare_deploy_result.app_id),
                app_guid=None,
                task_id=None,
                draft_url=None,
                bundle_id=None,
                title=self.title,
            )
            return self

    @cls_logged("Creating git-backed deployment ...")
    def deploy_git(self, activate: bool = True):
        """Deploy content from a remote git repository.

        Creates a git-backed content item in Posit Connect. Connect will clone
        the repository and regularly poll it for updates.
        """
        if not isinstance(self.client, RSConnectClient):
            raise RSConnectException(
                "Git deployment is only supported for Posit Connect servers, not shinyapps.io or Posit Cloud."
            )

        if not self.repository:
            raise RSConnectException("Repository URL is required for git deployment.")

        # Generate a valid deployment name from the title
        # This sanitizes characters like "/" that aren't allowed in names
        force_unique_name = self.app_id is None
        deployment_name = self.make_deployment_name(self.title, force_unique_name)

        result = self.client.deploy_git(
            app_id=self.app_id,
            name=deployment_name,
            repository=self.repository,
            branch=self.branch or "main",
            subdirectory=self.subdirectory or "",
            title=self.title,
            env_vars=self.env_vars,
            polling=self.polling,
            activate=activate,
        )

        self.deployed_info = result
        return self

    def emit_task_log(
        self,
        log_callback: logging.Logger = connect_logger,
        abort_func: Callable[[], bool] = lambda: False,
        timeout: int = get_task_timeout(),
        poll_wait: int = 1,
        raise_on_error: bool = True,
    ):
        """
        Helper for spooling the deployment log for an app.

        :param app_id: the ID of the app that was deployed.
        :param task_id: the ID of the task that is tracking the deployment of the app..
        :param log_callback: the callback to use to write the log to.  If this is None
        (the default) the lines from the deployment log will be returned as a sequence.
        If a log callback is provided, then None will be returned for the log lines part
        of the return tuple.
        :param timeout: an optional timeout for the wait operation.
        :param poll_wait: how long to wait between polls of the task api for status/logs
        :param raise_on_error: whether to raise an exception when a task is failed, otherwise we
        return the task_result so we can record the exit code.
        """
        if isinstance(self.remote_server, (RSConnectServer, SPCSConnectServer)):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("To emit task log, client must be a RSConnectClient.")

            log_lines, _ = self.client.wait_for_task(
                self.deployed_info["task_id"],
                log_callback.info,
                abort_func,
                timeout,
                poll_wait,
                raise_on_error,
            )
            log_lines = self.remote_server.handle_bad_response(log_lines)

            log_callback.info("Deployment completed successfully.")
            if self.deployed_info.get("draft_url"):
                log_callback.info("\t Draft content URL: %s", self.deployed_info["draft_url"])
            else:
                log_callback.info("\t Dashboard content URL: %s", self.deployed_info["dashboard_url"])
                log_callback.info("\t Direct content URL: %s", self.deployed_info["app_url"])

        return self

    @cls_logged("Saving deployed information...")
    def save_deployed_info(self):
        app_store = self.app_store
        path = self.path
        deployed_info = self.deployed_info

        app_store.set(
            self.remote_server.url,
            abspath(path),
            deployed_info["app_url"],
            deployed_info["app_id"],
            deployed_info["app_guid"],
            deployed_info["title"],
            self.app_mode,
        )

        return self

    @property
    def supports_verify_before_activate(self) -> bool:
        """Whether the target server supports deploying a bundle as a draft and
        activating it separately. shinyapps.io / Posit Cloud and pre-2025.06.0 Connect
        do not, so for those we deploy and activate in one step and verify the active
        content instead."""
        if not isinstance(self.client, RSConnectClient):
            return False
        if self._draft_deploy_supported is None:
            try:
                server_version = self.client.server_settings().get("version", "")
            except Exception:
                server_version = None
            self._draft_deploy_supported = server_supports_draft_deploy(server_version)
        return self._draft_deploy_supported

    def should_deploy_as_draft(self, draft: bool, no_verify: bool) -> bool:
        """Whether the bundle should be deployed without activating it.

        An explicit ``--draft`` always deploys a draft. Otherwise we deploy a draft only
        when we are going to verify it before activating, which requires server support.
        With ``--no-verify`` we activate immediately.
        """
        if draft:
            if not self.supports_verify_before_activate:
                # We can't honor --draft without the activate field: silently activating
                # would be the opposite of what the user asked for, so fail loudly.
                raise RSConnectException("Deploying as a draft requires Posit Connect 2025.06.0 or later.")
            return True
        if no_verify:
            return False
        return self.supports_verify_before_activate

    @cls_logged("Verifying deployed content...")
    def verify_deployment(self):
        if isinstance(self.remote_server, (RSConnectServer, SPCSConnectServer)):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("To verify deployment, client must be a RSConnectClient.")
            deployed_info = self.deployed_info
            app_guid = deployed_info["app_guid"]
            # If the bundle was deployed as a draft (not activated), verify the draft
            # bundle's preview URL rather than the currently-active content. Otherwise a
            # broken draft would be masked by a previously-working active bundle.
            bundle_id = deployed_info.get("bundle_id") if deployed_info.get("draft_url") else None
            self.client.access_content(app_guid, bundle_id=bundle_id)
        return self

    @cls_logged("Activating deployed content...")
    def activate_deployment(self):
        """Activate the bundle deployed as a draft, e.g. after verifying it runs.

        This re-issues the deploy request for the same bundle with ``activate=True``,
        which is what the "Activate Draft" button in the Connect UI does.
        """
        if isinstance(self.remote_server, (RSConnectServer, SPCSConnectServer)):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("To activate deployment, client must be a RSConnectClient.")
            deployed_info = self.deployed_info
            app_guid = deployed_info["app_guid"]
            bundle_id = deployed_info["bundle_id"]
            if app_guid is None or bundle_id is None:
                raise RSConnectException("An app GUID and bundle ID are required to activate a deployment.")
            task = self.client.content_deploy(app_guid, bundle_id, activate=True)
            # Update deployed_info so a subsequent emit_task_log() waits on the activation
            # task and reports the live content URLs instead of the draft URL.
            deployed_info["task_id"] = task["task_id"]
            deployed_info["draft_url"] = None
        return self

    @cls_logged("Validating app mode...")
    def validate_app_mode(self, app_mode: AppMode):
        path = self.path
        app_store = self.app_store
        if not app_store:
            module_file = fake_module_file_from_directory(path)
            self.app_store = app_store = AppStore(module_file)
        new = self.new
        app_id = self.app_id
        app_mode = app_mode or self.app_mode

        if new and app_id:
            raise RSConnectException("Specify either a new deploy or an app ID but not both.")

        existing_app_mode = None
        app_store_version = 0
        if not new:
            if app_id is None:
                # Possible redeployment - check for saved metadata.
                # Use the saved app information unless overridden by the user.
                app_id, existing_app_mode, app_store_version = app_store.resolve(
                    self.remote_server.url, app_id, app_mode
                )
                self.app_store_version = app_store_version

                logger.debug("Using app mode from app %s: %s" % (app_id, app_mode))
            elif app_id is not None:
                # Don't read app metadata if app-id is specified. Instead, we need
                # to get this from the remote.
                if isinstance(self.remote_server, RSConnectServer):
                    try:
                        with RSConnectClient(self.remote_server) as client:
                            content = client.get_content_by_id(app_id)
                            existing_app_mode = AppModes.get_by_ordinal(content["app_mode"], True)
                    except RSConnectException as e:
                        raise RSConnectException(
                            f"{e} Try setting the --new flag to overwrite the previous deployment."
                        ) from e
                elif isinstance(self.remote_server, PositServer):
                    try:
                        app = get_posit_app_info(self.remote_server, app_id)
                        existing_app_mode = AppModes.get_by_cloud_name(app["mode"])
                    except RSConnectException as e:
                        raise RSConnectException(
                            f"{e} Try setting the --new flag to overwrite the previous deployment."
                        ) from e
                else:
                    raise RSConnectException("Unable to infer Connect client.")
            if existing_app_mode and existing_app_mode not in (None, AppModes.UNKNOWN, app_mode):
                msg = (
                    "Deploying with mode '%s',\n"
                    + "but the existing deployment has mode '%s'.\n"
                    + "Use the --new option to create a new deployment of the desired type."
                ) % (app_mode.desc(), existing_app_mode.desc())
                raise RSConnectException(msg)

        self.app_id = app_id
        self.app_mode = app_mode
        self.app_store_version = app_store_version
        return self

    def server_settings(self):
        try:
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("To get server settings, client must be a RSConnectClient.")
            result = self.client.server_settings()
        except SSLError as ssl_error:
            raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)
        return result

    def verify_api_key(self, server: Optional[RSConnectServer] = None):
        """
        Verify that an API Key may be used to authenticate with the given Posit Connect server.
        """
        if not server:
            server = self.remote_server
        if isinstance(server, ShinyappsServer):
            raise RSConnectException("Shinnyapps server does not use an API key.")
        with RSConnectClient(server) as client:
            verify_api_key_response(client)
        return self

    @property
    def api_username(self) -> str:
        if not isinstance(self.client, RSConnectClient):
            raise RSConnectException("To get server settings, client must be a RSConnectClient.")
        result = self.client.me()
        return result["username"]

    @property
    def python_info(self):
        """
        Return information about versions of Python that are installed on the indicated
        Connect server.

        :return: the Python installation information from Connect.
        """
        if not isinstance(self.client, RSConnectClient):
            raise RSConnectException("To get Python info, client must be a RSConnectClient.")
        result = self.client.python_settings()
        return result

    def server_details(self) -> ServerDetails:
        """
        Builds a dictionary containing the version of Posit Connect that is running
        and the versions of Python installed there.

        :return: a two-entry dictionary.  The key 'connect' will refer to the version
        of Connect that was found.  The key `python` will refer to a sequence of version
        strings for all the versions of Python that are installed.
        """

        def _to_sort_key(text: str):
            parts = [part.zfill(5) for part in text.split(".")]
            return "".join(parts)

        server_settings = self.server_settings()
        python_settings = self.python_info
        python_versions = sorted([item["version"] for item in python_settings["installations"]], key=_to_sort_key)
        return {
            "connect": server_settings["version"],
            "python": {
                "api_enabled": python_settings["api_enabled"] if "api_enabled" in python_settings else False,
                "versions": python_versions,
            },
        }

    def make_deployment_name(self, title: str, force_unique: bool) -> str:
        """
        Produce a name for a deployment based on its title.  It is assumed that the
        title is already defaulted and validated as appropriate (meaning the title
        isn't None or empty).

        We follow the same rules for doing this as the R rsconnect package does.  See
        the title.R code in https://github.com/rstudio/rsconnect/R with the exception
        that we collapse repeating underscores and, if the name is too short, it is
        padded to the left with underscores.

        :param title: the title to start with.
        :param force_unique: a flag noting whether the generated name must be forced to be
        unique.
        :return: a name for a deployment based on its title.
        """
        _name_sub_pattern = re.compile(r"[^A-Za-z0-9_ -]+")
        _repeating_sub_pattern = re.compile(r"_+")

        # First, Generate a default name from the given title.
        name = _name_sub_pattern.sub("", title.lower()).replace(" ", "_")
        name = _repeating_sub_pattern.sub("_", name)[:64].rjust(3, "_")

        # Now, make sure it's unique, if needed.
        if force_unique:
            name = find_unique_name(self.remote_server, name)

        return name

    @property
    def runtime_caches(self) -> list[ListEntryOutputDTO]:
        if not isinstance(self.client, RSConnectClient):
            raise RSConnectException("To delete a runtime cache, client must be a RSConnectClient.")
        return self.client.system_caches_runtime_list()

    def delete_runtime_cache(self, language: str, version: str, image_name: str, dry_run: bool):
        if not isinstance(self.client, RSConnectClient):
            raise RSConnectException("To delete a runtime cache, client must be a RSConnectClient.")
        target: DeleteInputDTO = {
            "language": language,
            "version": version,
            "image_name": image_name,
            "dry_run": dry_run,
        }
        result = self.client.system_caches_runtime_delete(target)
        self.result = result
        if result["task_id"] is None:
            print("Dry run finished")
            return result, None
        else:
            (_, task) = self.client.wait_for_task(result["task_id"], connect_logger.info, raise_on_error=False)
            return result, task


class S3Client(HTTPServer):
    def upload(self, path: str, presigned_checksum: str, bundle_size: int, contents: bytes):
        headers = {
            "content-type": "application/x-tar",
            "content-length": str(bundle_size),
            "content-md5": presigned_checksum,
        }
        return self.put(path, headers=headers, body=contents, decode_response=False)


class PrepareDeployResult:
    def __init__(
        self,
        app_id: int,
        app_url: str,
        bundle_id: int,
        presigned_url: str,
        presigned_checksum: str,
    ):
        self.app_id = app_id
        self.app_url = app_url
        self.bundle_id = bundle_id
        self.presigned_url = presigned_url
        self.presigned_checksum = presigned_checksum


class PrepareDeployOutputResult(PrepareDeployResult):
    def __init__(
        self,
        app_id: int,
        app_url: str,
        bundle_id: int,
        presigned_url: str,
        presigned_checksum: str,
        application_id: int,
    ):
        super().__init__(
            app_id=app_id,
            app_url=app_url,
            bundle_id=bundle_id,
            presigned_url=presigned_url,
            presigned_checksum=presigned_checksum,
        )
        self.application_id = application_id


# Placeholder types
# NOTE: These were inferred from the existing code, but they should be updated with
# the actual types from the Posit API.
class PositClientDeployTask(TypedDict):
    id: str
    finished: bool
    status: str
    description: str
    error: str


class PositClientApp(TypedDict):
    id: int
    name: str
    url: str
    deployment: dict[str, Any]
    content_id: str


class PositClientAppSearchResults(TypedDict):
    applications: list[PositClientApp]
    count: int
    total: str


class PositClientAccountSearchResults(TypedDict):
    accounts: list[PositClientAccount]


class PositClientAccount(TypedDict):
    id: int
    name: str


class PositClientBundle(TypedDict):
    id: str
    presigned_url: str
    presigned_checksum: str


class PositClientShinyappsBuildTask(TypedDict):
    id: str


class PositClientShinyappsBuildTaskSearchResults(TypedDict):
    tasks: list[PositClientShinyappsBuildTask]


class PositClient(HTTPServer):
    """
    An HTTP client to call the shinyapps.io API.
    """

    _TERMINAL_STATUSES = {"success", "failed", "error"}

    def __init__(self, posit_server: PositServer):
        self._token = posit_server.token
        try:
            self._key = base64.b64decode(posit_server.secret)
        except binascii.Error as e:
            raise RSConnectException("Invalid secret.") from e
        self._server = posit_server
        super().__init__(posit_server.url)

    def _get_canonical_request(self, method: str, path: str, timestamp: str, content_hash: str):
        return "\n".join([method, path, timestamp, content_hash])

    def _get_canonical_request_signature(self, request: str):
        result = hmac.new(self._key, request.encode(), hashlib.sha256).hexdigest()
        return base64.b64encode(result.encode()).decode()

    def _tweak_response(self, response: HTTPResponse) -> JsonData | HTTPResponse:
        return (
            response.json_data
            if (
                response.status and response.status >= 200 and response.status <= 299 and response.json_data is not None
            )
            else response
        )

    def get_extra_headers(self, url: str, method: str, body: str | bytes):
        canonical_request_method = method.upper()
        canonical_request_path = parse.urlparse(url).path
        canonical_request_date = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

        # get request checksum
        md5 = hashlib.md5()
        body = body or b""
        body_bytes = body if isinstance(body, bytes) else body.encode()
        md5.update(body_bytes)
        canonical_request_checksum = md5.hexdigest()

        canonical_request = self._get_canonical_request(
            canonical_request_method, canonical_request_path, canonical_request_date, canonical_request_checksum
        )

        signature = self._get_canonical_request_signature(canonical_request)

        return {
            "X-Auth-Token": self._token,
            "X-Auth-Signature": f"{signature}; version=1",
            "Date": canonical_request_date,
            "X-Content-Checksum": canonical_request_checksum,
        }

    def get_application(self, application_id: str):
        response = cast(Union[PositClientApp, HTTPResponse], self.get(f"/v1/applications/{application_id}"))
        response = self._server.handle_bad_response(response)
        return response

    def update_application_property(self, application_id: int, property: str, value: str) -> HTTPResponse:
        response = cast(
            HTTPResponse,
            self.put(f"/v1/applications/{application_id}/properties/{property}", body={"value": value}),
        )
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def create_application(self, account_id: int, application_name: str) -> PositClientApp:
        application_data = {
            "account": account_id,
            "name": application_name,
            "template": "shiny",
        }
        response = cast(Union[PositClientApp, HTTPResponse], self.post("/v1/applications/", body=application_data))
        response = self._server.handle_bad_response(response)
        return response

    def get_accounts(self) -> PositClientAccountSearchResults:
        response = cast(Union[PositClientAccountSearchResults, HTTPResponse], self.get("/v1/accounts/"))
        response = self._server.handle_bad_response(response)
        return response

    def _get_applications_like_name_page(self, name: str, offset: int) -> PositClientAppSearchResults:
        response = cast(
            Union[PositClientAppSearchResults, HTTPResponse],
            self.get(f"/v1/applications?filter=name:like:{name}&offset={offset}&count=100&use_advanced_filters=true"),
        )
        response = self._server.handle_bad_response(response)
        return response

    def create_bundle(
        self, application_id: int, content_type: str, content_length: int, checksum: str
    ) -> PositClientBundle:
        bundle_data = {
            "application": application_id,
            "content_type": content_type,
            "content_length": content_length,
            "checksum": checksum,
        }
        response = cast(Union[PositClientBundle, HTTPResponse], self.post("/v1/bundles", body=bundle_data))
        response = self._server.handle_bad_response(response)
        return response

    def set_bundle_status(self, bundle_id: str, bundle_status: str):
        response = self.post(f"/v1/bundles/{bundle_id}/status", body={"status": bundle_status})
        response = self._server.handle_bad_response(response)
        return response

    def deploy_application(self, bundle_id: str, app_id: str) -> PositClientDeployTask:
        response = cast(
            Union[PositClientDeployTask, HTTPResponse],
            self.post(f"/v1/applications/{app_id}/deploy", body={"bundle": bundle_id, "rebuild": False}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_task(self, task_id: str) -> PositClientDeployTask:
        response = cast(
            Union[PositClientDeployTask, HTTPResponse],
            self.get(f"/v1/tasks/{task_id}", query_params={"legacy": "true"}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_shinyapps_build_task(self, parent_task_id: str) -> PositClientShinyappsBuildTaskSearchResults:
        response = cast(
            Union[PositClientShinyappsBuildTaskSearchResults, HTTPResponse],
            self.get(
                "/v1/tasks",
                query_params={
                    "filter": [
                        f"parent_id:eq:{parent_task_id}",
                        "action:eq:image-build",
                    ]
                },
            ),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_task_logs(self, task_id: str) -> HTTPResponse:
        response = cast(HTTPResponse, self.get(f"/v1/tasks/{task_id}/logs"))
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def get_current_user(self):
        response = self.get("/v1/users/me")
        response = self._server.handle_bad_response(response)
        return response

    def wait_until_task_is_successful(self, task_id: str, timeout: int = get_task_timeout()) -> None:
        print()
        print(f"Waiting for task: {task_id}")

        start_time = time.time()
        finished: bool | None = None
        status: str | None = None
        error: str | None = None
        description: str | None = None

        while time.time() - start_time < timeout:
            task = self.get_task(task_id)
            finished = task["finished"]
            status = task["status"]
            description = task["description"]
            error = task["error"]

            if finished:
                break

            print(f"  {status} - {description}")
            time.sleep(2)

        if not finished:
            raise RSConnectException(get_task_timeout_help_message(timeout))

        if status != "success":
            raise DeploymentFailedException(f"Application deployment failed with error: {error}")

        print(f"Task done: {description}")

    def get_applications_like_name(self, name: str) -> list[str]:
        applications: list[PositClientApp] = []

        results = self._get_applications_like_name_page(name, 0)
        results = self._server.handle_bad_response(results)
        offset = 0

        while len(applications) < int(results["total"]):
            results = self._get_applications_like_name_page(name, offset)
            applications = results["applications"]
            applications.extend(applications)
            offset += int(results["count"])

        return [app["name"] for app in applications]


class ShinyappsService:
    """
    Encapsulates operations involving multiple API calls to shinyapps.io.
    """

    def __init__(self, posit_client: PositClient, server: ShinyappsServer):
        self._posit_client = posit_client
        self._server = server

    def prepare_deploy(
        self,
        app_id: Optional[str],
        app_name: str,
        bundle_size: int,
        bundle_hash: str,
        visibility: Optional[str],
    ):
        accounts = self._posit_client.get_accounts()
        accounts = self._server.handle_bad_response(accounts)
        account: PositClientAccount = next(
            filter(lambda acct: acct["name"] == self._server.account_name, accounts["accounts"]), None
        )
        # TODO: also check this during `add` command
        if account is None:
            raise RSConnectException(
                "No account found by name : %s for given user credential" % self._server.account_name
            )

        if app_id is None:
            application = self._posit_client.create_application(account["id"], app_name)
            if visibility is not None:
                self._posit_client.update_application_property(application["id"], "application.visibility", visibility)

        else:
            application = self._posit_client.get_application(app_id)

            if visibility is not None:
                if visibility != application["deployment"]["properties"]["application.visibility"]:
                    self._posit_client.update_application_property(
                        application["id"], "application.visibility", visibility
                    )

        app_id_int = application["id"]
        app_url = application["url"]

        bundle = self._posit_client.create_bundle(app_id_int, "application/x-tar", bundle_size, bundle_hash)

        return PrepareDeployResult(
            app_id_int,
            app_url,
            int(bundle["id"]),
            bundle["presigned_url"],
            bundle["presigned_checksum"],
        )

    def do_deploy(self, bundle_id: str, app_id: str):
        self._posit_client.set_bundle_status(bundle_id, "ready")
        deploy_task = self._posit_client.deploy_application(bundle_id, app_id)
        try:
            self._posit_client.wait_until_task_is_successful(deploy_task["id"])
        except DeploymentFailedException as e:
            build_task_result = self._posit_client.get_shinyapps_build_task(deploy_task["id"])
            build_task = build_task_result["tasks"][0]
            logs = self._posit_client.get_task_logs(build_task["id"])
            logger.error(f"Build logs:\n{logs.response_body}")
            raise e


def verify_server(connect_server: RSConnectServer):
    """
    Verify that the given server information represents a Connect instance that is
    reachable, active and appears to be actually running Posit Connect.  If the
    check is successful, the server settings for the Connect server is returned.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    try:
        with RSConnectClient(connect_server) as client:
            result = client.server_settings()
            result = connect_server.handle_bad_response(result)
            return result
    except SSLError as ssl_error:
        raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)


def verify_api_key_response(client: RSConnectClient) -> Optional[UserRecord]:
    """
    Issue GET v1/user and interpret the response for the purpose of API key verification.

    :param client: a client configured with the credential to verify.
    :return: the user record on success, or None for a valid credential that has no
        associated user (a service principal or machine identity, for example one used
        for trusted publishing).
    :raises RSConnectException: if the credential is invalid or the request otherwise fails.
    """
    # Use the raw response rather than client.me(), which would raise a generic error
    # and discard the error code we need to distinguish the verification-specific cases
    # below. Everything else (success, connection errors, other HTTP errors) is left to
    # the standard handle_bad_response handler.
    result = client.get("v1/user")
    if isinstance(result, HTTPResponse) and not result.exception:
        json_data = result.json_data if isinstance(result.json_data, dict) else {}
        code = json_data.get("code")
        # A service principal or machine identity authenticates successfully but has no
        # associated user, so the v1/user endpoint rejects it with a 403 and error code
        # 22. That code is unambiguous on this endpoint -- a genuinely invalid credential
        # is rejected at the auth layer with code 30 instead -- so the credential is valid
        # and we treat it as verified. This distinction only holds for v1/user, which is
        # why it lives here rather than in handle_bad_response.
        if result.status == 403 and code == 22:
            return None
        if code == 30:
            raise RSConnectException("The specified API key is not valid.")
    return cast(UserRecord, client._server.handle_bad_response(result))


def verify_api_key(connect_server: RSConnectServer) -> str:
    """
    Verify that an API Key may be used to authenticate with the given Posit Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information, including the API key to test.
    :return: the username of the user to whom the API key belongs, or an empty string for a
        valid credential with no associated user (a service principal or machine identity).
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    with RSConnectClient(connect_server) as client:
        user = verify_api_key_response(client)
    return user["username"] if user else ""


def get_python_info(connect_server: Union[RSConnectServer, SPCSConnectServer]):
    """
    Return information about versions of Python that are installed on the indicated
    Connect server.

    :param connect_server: the Connect server information.
    :return: the Python installation information from Connect.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    with RSConnectClient(connect_server) as client:
        result = client.python_settings()
        return result


def get_posit_app_info(server: PositServer, app_id: str):
    with PositClient(server) as client:
        return client.get_application(app_id)


def emit_task_log(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    app_id: str,
    task_id: str,
    log_callback: Optional[Callable[[str], None]],
    abort_func: Callable[[], bool] = lambda: False,
    timeout: int = get_task_timeout(),
    poll_wait: int = 1,
    raise_on_error: bool = True,
):
    """
    Helper for spooling the deployment log for an app.

    :param connect_server: the Connect server information.
    :param app_id: the ID of the app that was deployed.
    :param task_id: the ID of the task that is tracking the deployment of the app..
    :param log_callback: the callback to use to write the log to.  If this is None
    (the default) the lines from the deployment log will be returned as a sequence.
    If a log callback is provided, then None will be returned for the log lines part
    of the return tuple.
    :param timeout: an optional timeout for the wait operation.
    :param poll_wait: how long to wait between polls of the task api for status/logs
    :param raise_on_error: whether to raise an exception when a task is failed, otherwise we
    return the task_result so we can record the exit code.
    :return: the ultimate URL where the deployed app may be accessed and the sequence
    of log lines.  The log lines value will be None if a log callback was provided.
    """
    with RSConnectClient(connect_server) as client:
        result = client.wait_for_task(task_id, log_callback, abort_func, timeout, poll_wait, raise_on_error)
        result = connect_server.handle_bad_response(result)
        # Get content (handles both numeric IDs and GUIDs)
        content = client.get_content_by_id(app_id)
        app_url = content["dashboard_url"]
        return (app_url, *result)


class AbbreviatedAppItem(TypedDict):
    id: int
    name: str
    title: str | None
    app_mode: AppModes.Modes
    url: str
    config_url: str


def find_unique_name(remote_server: TargetableServer, name: str):
    """
    Poll through existing apps to see if anything with a similar name exists.
    If so, start appending numbers until a unique name is found.

    :param remote_server: the remote server information.
    :param name: the default name for an app.
    :return: the name, potentially with a suffixed number to guarantee uniqueness.
    """
    if isinstance(remote_server, (RSConnectServer, SPCSConnectServer)):
        # Use v1/content API with name query parameter
        with RSConnectClient(remote_server) as client:
            results = client.content_list(filters={"name": name})

            # If name exists, append suffix and try again
            if len(results) > 0:
                suffix = 1
                test_name = "%s%d" % (name, suffix)
                while True:
                    results = client.content_list(filters={"name": test_name})
                    if len(results) == 0:
                        return test_name
                    suffix = suffix + 1
                    test_name = "%s%d" % (name, suffix)

            return name

    elif isinstance(remote_server, ShinyappsServer):
        client = PositClient(remote_server)
        existing_names = client.get_applications_like_name(name)

        if name in existing_names:
            suffix = 1
            test = "%s%d" % (name, suffix)
            while test in existing_names:
                suffix = suffix + 1
                test = "%s%d" % (name, suffix)
            name = test

        return name
    else:
        # non-unique names are permitted in cloud
        return name
