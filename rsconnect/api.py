"""
Posit Connect API client and utility functions
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
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
from urllib.parse import urlparse
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
    from typing import NotRequired, TypedDict
else:
    from typing_extensions import NotRequired, TypedDict

from . import validation
from .bundle import _default_title, fake_module_file_from_directory
from .certificates import read_certificate_file
from .exception import DeploymentFailedException, RSConnectException
from .http_support import CookieJar, HTTPResponse, HTTPServer, JsonData, append_to_path
from .log import cls_logged, connect_logger, console_logger, logger
from .metadata import AppStore, ServerStore
from .models import (
    AppMode,
    AppModes,
    AppSearchResults,
    BootstrapOutputDTO,
    BuildOutputDTO,
    ConfigureResult,
    ContentItemV0,
    ContentItemV1,
    DeleteInputDTO,
    DeleteOutputDTO,
    ListEntryOutputDTO,
    PyInfo,
    ServerSettings,
    TaskStatusV0,
    TaskStatusV1,
    UserRecord,
)
from .timeouts import get_task_timeout, get_task_timeout_help_message

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
                    "Exception trying to connect to %s - %s" % (self.url, response.exception), cause=response.exception
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
                    raise RSConnectException(error)
                if response.status < 200 or response.status > 299:
                    raise RSConnectException(
                        "Received an unexpected response from %s (calling %s): %s %s"
                        % (
                            self.remote_name,
                            response.full_uri,
                            response.status,
                            response.reason,
                        )
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
    A class used to represent the server of the shinyapps.io and Posit Cloud APIs.
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


class CloudServer(PositServer):
    """
    A class to encapsulate the information needed to interact with an
    instance of the Posit Cloud server.
    """

    def __init__(self, url: str, account_name: str, token: str, secret: str):
        remote_name = "Posit Cloud"
        if url in {"posit.cloud", "rstudio.cloud", None}:
            url = "https://api.posit.cloud"
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
    ):
        super().__init__(url, "Posit Connect")
        self.api_key = api_key
        self.bootstrap_jwt = bootstrap_jwt
        self.insecure = insecure
        self.ca_data = ca_data
        # This is specifically not None.
        self.cookie_jar = CookieJar()


TargetableServer = typing.Union[ShinyappsServer, RSConnectServer, CloudServer]


class S3Server(AbstractRemoteServer):
    def __init__(self, url: str):
        super().__init__(url, "S3")


class RSConnectClientDeployResult(TypedDict):
    task_id: NotRequired[str]
    app_id: str
    app_guid: str
    app_url: str
    title: str | None


class RSConnectClient(HTTPServer):
    def __init__(self, server: RSConnectServer, cookies: Optional[CookieJar] = None):
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

    def _tweak_response(self, response: HTTPResponse) -> JsonData | HTTPResponse:
        return (
            response.json_data
            if response.status and response.status == 200 and response.json_data is not None
            else response
        )

    def me(self) -> UserRecord:
        response = cast(Union[UserRecord, HTTPResponse], self.get("me"))
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

    def app_search(self, filters: Optional[Mapping[str, JsonData]]) -> AppSearchResults:
        response = cast(Union[AppSearchResults, HTTPResponse], self.get("applications", query_params=filters))
        response = self._server.handle_bad_response(response)
        return response

    def app_create(self, name: str) -> ContentItemV0:
        response = cast(Union[ContentItemV0, HTTPResponse], self.post("applications", body={"name": name}))
        response = self._server.handle_bad_response(response)
        return response

    def app_get(self, app_id: str) -> ContentItemV0:
        response = cast(Union[ContentItemV0, HTTPResponse], self.get("applications/%s" % app_id))
        response = self._server.handle_bad_response(response)
        return response

    def app_upload(self, app_id: str, tarball: typing.IO[bytes]) -> ContentItemV0:
        response = cast(Union[ContentItemV0, HTTPResponse], self.post("applications/%s/upload" % app_id, body=tarball))
        response = self._server.handle_bad_response(response)
        return response

    def app_update(self, app_id: str, updates: Mapping[str, str | None]) -> ContentItemV0:
        response = cast(Union[ContentItemV0, HTTPResponse], self.post("applications/%s" % app_id, body=updates))
        response = self._server.handle_bad_response(response)
        return response

    def app_add_environment_vars(self, app_guid: str, env_vars: list[tuple[str, str]]):
        env_body = [dict(name=kv[0], value=kv[1]) for kv in env_vars]
        return self.patch("v1/content/%s/environment" % app_guid, body=env_body)

    def app_deploy(self, app_id: str, bundle_id: Optional[int] = None) -> TaskStatusV0:
        response = cast(
            Union[TaskStatusV0, HTTPResponse],
            self.post("applications/%s/deploy" % app_id, body={"bundle": bundle_id}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def app_config(self, app_id: str) -> ConfigureResult:
        response = cast(Union[ConfigureResult, HTTPResponse], self.get("applications/%s/config" % app_id))
        response = self._server.handle_bad_response(response)
        return response

    def is_app_failed_response(self, response: HTTPResponse | JsonData) -> bool:
        return isinstance(response, HTTPResponse) and response.status >= 500

    def app_access(self, app_guid: str) -> None:
        method = "GET"
        base = dirname(self._url.path)  # remove __api__
        path = f"{base}/content/{app_guid}/"
        response = self._do_request(method, path, None, None, 3, {}, False)

        if self.is_app_failed_response(response):
            raise RSConnectException(
                "Could not access the deployed content. "
                + "The app might not have started successfully. "
                + "Visit it in Connect to view the logs."
            )

    def bundle_download(self, content_guid: str, bundle_id: str) -> HTTPResponse:
        response = cast(
            HTTPResponse,
            self.get("v1/content/%s/bundles/%s/download" % (content_guid, bundle_id), decode_response=False),
        )
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def content_search(self) -> list[ContentItemV1]:
        response = cast(Union[List[ContentItemV1], HTTPResponse], self.get("v1/content"))
        response = self._server.handle_bad_response(response)
        return response

    def content_get(self, content_guid: str) -> ContentItemV1:
        response = cast(Union[ContentItemV1, HTTPResponse], self.get("v1/content/%s" % content_guid))
        response = self._server.handle_bad_response(response)
        return response

    def content_build(self, content_guid: str, bundle_id: Optional[str] = None) -> BuildOutputDTO:
        response = cast(
            Union[BuildOutputDTO, HTTPResponse],
            self.post("v1/content/%s/build" % content_guid, body={"bundle_id": bundle_id}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def system_caches_runtime_list(self) -> list[ListEntryOutputDTO]:
        response = cast(Union[List[ListEntryOutputDTO], HTTPResponse], self.get("v1/system/caches/runtime"))
        response = self._server.handle_bad_response(response)
        return response

    def system_caches_runtime_delete(self, target: DeleteInputDTO) -> DeleteOutputDTO:
        response = cast(Union[DeleteOutputDTO, HTTPResponse], self.delete("v1/system/caches/runtime", body=target))
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
        response = cast(Union[TaskStatusV1, HTTPResponse], self.get("v1/tasks/%s" % task_id, query_params=params))
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
    ) -> RSConnectClientDeployResult:
        if app_id is None:
            if app_name is None:
                raise RSConnectException("An app ID or name is required to deploy an app.")
            # create an app if id is not provided
            app = self.app_create(app_name)
            app_id = str(app["id"])

            # Force the title to update.
            title_is_default = False
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            try:
                app = self.app_get(app_id)
            except RSConnectException as e:
                raise RSConnectException(f"{e} Try setting the --new flag to overwrite the previous deployment.") from e

        app_guid = app["guid"]
        if env_vars:
            result = self.app_add_environment_vars(app_guid, list(env_vars.items()))
            result = self._server.handle_bad_response(result)

        if app["title"] != app_title and not title_is_default:
            result = self.app_update(app_id, {"title": app_title})
            result = self._server.handle_bad_response(result)
            app["title"] = app_title

        app_bundle = self.app_upload(app_id, tarball)

        task = self.app_deploy(app_id, app_bundle["id"])

        return {
            "task_id": task["id"],
            "app_id": app_id,
            "app_guid": app["guid"],
            "app_url": app["url"],
            "title": app["title"],
        }

    def download_bundle(self, content_guid: str, bundle_id: str) -> HTTPResponse:
        results = self.bundle_download(content_guid, bundle_id)
        return results

    def search_content(self) -> list[ContentItemV1]:
        results = self.content_search()
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


# for backwards compatibility with rsconnect-jupyter
RSConnect = RSConnectClient


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
        self.app_mode: AppMode | None = None
        self.app_store: AppStore = AppStore(fake_module_file_from_directory(self.path))
        self.app_store_version: int | None = None
        self.api_key_is_required: bool | None = None
        self.title_is_default: bool = not title
        self.deployment_name: str | None = None

        self.bundle: IO[bytes] | None = None
        self.deployed_info: RSConnectClientDeployResult | None = None

        self.logger: logging.Logger | None = logger
        self.ctx = ctx
        self.setup_remote_server(
            ctx=ctx,
            name=name,
            url=url or server,
            api_key=api_key,
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
        insecure: bool = False,
        cacert: Optional[str] = None,
        ca_data: Optional[str | bytes] = None,
        account_name: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        validation.validate_connection_options(
            ctx=ctx,
            url=url,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
            account_name=account_name,
            token=token,
            secret=secret,
            name=name,
        )
        # The validation.validate_connection_options() function ensures that certain
        # combinations of arguments are present; the cast() calls inside of the
        # if-statements below merely reflect these validations.
        header_output = False

        if cacert and not ca_data:
            ca_data = read_certificate_file(cacert)

        server_data = ServerStore().resolve(name, url)
        if server_data.from_store:
            url = server_data.url
            if self.logger:
                if server_data.api_key and api_key:
                    header_output = self.output_overlap_details("api-key", header_output)
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

            # TODO: Is this logic backward? Seems like the provided value should override the stored value.
            api_key = server_data.api_key or api_key
            insecure = server_data.insecure or insecure
            ca_data = server_data.ca_data or ca_data
            account_name = server_data.account_name or account_name
            token = server_data.token or token
            secret = server_data.secret or secret

        self.is_server_from_store = server_data.from_store

        if api_key:
            url = cast(str, url)
            self.remote_server = RSConnectServer(url, api_key, insecure, ca_data)
        elif token and secret:
            if url and ("rstudio.cloud" in url or "posit.cloud" in url):
                account_name = cast(str, account_name)
                self.remote_server = CloudServer(url, account_name, token, secret)
            else:
                url = cast(str, url)
                account_name = cast(str, account_name)
                self.remote_server = ShinyappsServer(url, account_name, token, secret)
        else:
            raise RSConnectException("Unable to infer Connect server type and setup server.")

    def setup_client(self, cookies: Optional[CookieJar] = None):
        if isinstance(self.remote_server, RSConnectServer):
            self.client = RSConnectClient(self.remote_server, cookies)
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
        if isinstance(self.remote_server, RSConnectServer):
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

    def validate_posit_server(self):
        if not isinstance(self.remote_server, PositServer):
            raise RSConnectException("remote_server is not a Posit server.")

        remote_server: PositServer = self.remote_server
        url = remote_server.url
        account_name = remote_server.account_name
        token = remote_server.token
        secret = remote_server.secret
        server = (
            CloudServer(url, account_name, token, secret)
            if "rstudio.cloud" in url or "posit.cloud" in url
            else ShinyappsServer(url, account_name, token, secret)
        )

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
        with S3Client("{}://{}".format(parsed_upload_url.scheme, parsed_upload_url.netloc)) as s3_client:
            upload_result = cast(
                HTTPResponse,
                s3_client.upload(
                    "{}?{}".format(parsed_upload_url.path, parsed_upload_url.query),
                    prepare_deploy_result.presigned_checksum,
                    bundle_size,
                    contents,
                ),
            )
            upload_result = S3Server(upload_url).handle_bad_response(upload_result, is_httpresponse=True)

    @cls_logged("Deploying bundle ...")
    def deploy_bundle(self):
        if self.deployment_name is None:
            raise RSConnectException("A deployment name must be created before deploying a bundle.")
        if self.bundle is None:
            raise RSConnectException("A bundle must be created before deploying it.")

        if isinstance(self.remote_server, RSConnectServer):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("client must be an RSConnectClient.")
            result = self.client.deploy(
                self.app_id,
                self.deployment_name,
                self.title,
                self.title_is_default,
                self.bundle,
                self.env_vars,
            )
            self.deployed_info = result
            return self
        else:
            contents = self.bundle.read()
            bundle_size = len(contents)
            bundle_hash = hashlib.md5(contents).hexdigest()

            if not isinstance(self.client, PositClient):
                raise RSConnectException("client must be a PositClient.")

            if isinstance(self.remote_server, ShinyappsServer):
                shinyapps_service = ShinyappsService(self.client, self.remote_server)
                prepare_deploy_result = shinyapps_service.prepare_deploy(
                    self.app_id,
                    self.deployment_name,
                    bundle_size,
                    bundle_hash,
                    self.visibility,
                )
                self.upload_posit_bundle(prepare_deploy_result, bundle_size, contents)
                shinyapps_service.do_deploy(prepare_deploy_result.bundle_id, prepare_deploy_result.app_id)
            else:
                cloud_service = CloudService(self.client, self.remote_server, os.getenv("LUCID_APPLICATION_ID"))
                app_store_version = self.app_store_version
                prepare_deploy_result = cloud_service.prepare_deploy(
                    self.app_id,
                    self.deployment_name,
                    bundle_size,
                    bundle_hash,
                    self.app_mode,
                    app_store_version,
                )
                self.upload_posit_bundle(prepare_deploy_result, bundle_size, contents)
                cloud_service.do_deploy(prepare_deploy_result.bundle_id, prepare_deploy_result.application_id)

            print("Application successfully deployed to {}".format(prepare_deploy_result.app_url))
            webbrowser.open_new(prepare_deploy_result.app_url)

            self.deployed_info = {
                "app_url": prepare_deploy_result.app_url,
                "app_id": prepare_deploy_result.app_id,
                "app_guid": None,
                "title": self.title,
            }
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
        if isinstance(self.remote_server, RSConnectServer):
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
            app_config = self.client.app_config(self.deployed_info["app_id"])
            app_config = self.remote_server.handle_bad_response(app_config)
            app_dashboard_url = app_config.get("config_url")
            log_callback.info("Deployment completed successfully.")
            log_callback.info("\t Dashboard content URL: %s", app_dashboard_url)
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

    @cls_logged("Verifying deployed content...")
    def verify_deployment(self):
        if isinstance(self.remote_server, RSConnectServer):
            if not isinstance(self.client, RSConnectClient):
                raise RSConnectException("To verify deployment, client must be a RSConnectClient.")
            deployed_info = self.deployed_info
            app_guid = deployed_info["app_guid"]
            self.client.app_access(app_guid)

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
                        app = get_app_info(self.remote_server, app_id)
                        # TODO: verify that this is correct. The previous code seemed
                        # incorrect. It passed an arg to app.get(), which would have
                        # been ignored.
                        existing_app_mode = AppModes.get_by_ordinal(app["app_mode"], True)
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
        If the API key verifies, we return the username of the associated user.
        """
        if not server:
            server = self.remote_server
        if isinstance(server, ShinyappsServer):
            raise RSConnectException("Shinnyapps server does not use an API key.")
        with RSConnectClient(server) as client:
            result = client.me()
            if isinstance(result, HTTPResponse):
                if (
                    result.json_data
                    and isinstance(result.json_data, dict)
                    and "code" in result.json_data
                    and result.json_data["code"] == 30
                ):
                    raise RSConnectException("The specified API key is not valid.")
                raise RSConnectException("Could not verify the API key: %s %s" % (result.status, result.reason))
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


class PositClientCloudOutput(TypedDict):
    id: int
    space_id: str
    source_id: int
    url: str


class PositClientCloudOutputRevision(TypedDict):
    application_id: int


class PositClient(HTTPServer):
    """
    An HTTP client to call the Posit Cloud and shinyapps.io APIs.
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
            "X-Auth-Token": "{0}".format(self._token),
            "X-Auth-Signature": "{0}; version=1".format(signature),
            "Date": canonical_request_date,
            "X-Content-Checksum": canonical_request_checksum,
        }

    def get_application(self, application_id: str):
        response = cast(Union[PositClientApp, HTTPResponse], self.get("/v1/applications/{}".format(application_id)))
        response = self._server.handle_bad_response(response)
        return response

    def update_application_property(self, application_id: int, property: str, value: str) -> HTTPResponse:
        response = cast(
            HTTPResponse,
            self.put("/v1/applications/{}/properties/{}".format(application_id, property), body={"value": value}),
        )
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def get_content(self, content_id: str) -> PositClientCloudOutput:
        response = cast(Union[PositClientCloudOutput, HTTPResponse], self.get("/v1/content/{}".format(content_id)))
        response = self._server.handle_bad_response(response)
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

    def create_output(
        self,
        name: str,
        application_type: str,
        project_id: Optional[str] = None,
        space_id: Optional[str] = None,
        render_by: Optional[str] = None,
    ) -> PositClientCloudOutput:
        data = {"name": name, "space": space_id, "project": project_id, "application_type": application_type}
        if render_by:
            data["render_by"] = render_by
        response = cast(Union[PositClientCloudOutput, HTTPResponse], self.post("/v1/outputs/", body=data))
        response = self._server.handle_bad_response(response)
        return response

    def create_revision(self, content_id: str) -> PositClientCloudOutputRevision:
        response = cast(
            Union[PositClientCloudOutputRevision, HTTPResponse],
            self.post("/v1/outputs/{}/revisions".format(content_id), body={}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def update_output(self, output_id: int, output_data: Mapping[str, str]):
        return self.patch("/v1/outputs/{}".format(output_id), body=output_data)

    def get_accounts(self) -> PositClientAccountSearchResults:
        response = cast(Union[PositClientAccountSearchResults, HTTPResponse], self.get("/v1/accounts/"))
        response = self._server.handle_bad_response(response)
        return response

    def _get_applications_like_name_page(self, name: str, offset: int) -> PositClientAppSearchResults:
        response = cast(
            Union[PositClientAppSearchResults, HTTPResponse],
            self.get(
                "/v1/applications?filter=name:like:{}&offset={}&count=100&use_advanced_filters=true".format(
                    name, offset
                )
            ),
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
        response = self.post("/v1/bundles/{}/status".format(bundle_id), body={"status": bundle_status})
        response = self._server.handle_bad_response(response)
        return response

    def deploy_application(self, bundle_id: str, app_id: str) -> PositClientDeployTask:
        response = cast(
            Union[PositClientDeployTask, HTTPResponse],
            self.post("/v1/applications/{}/deploy".format(app_id), body={"bundle": bundle_id, "rebuild": False}),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_task(self, task_id: str) -> PositClientDeployTask:
        response = cast(
            Union[PositClientDeployTask, HTTPResponse],
            self.get("/v1/tasks/{}".format(task_id), query_params={"legacy": "true"}),
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
                        "parent_id:eq:{}".format(parent_task_id),
                        "action:eq:image-build",
                    ]
                },
            ),
        )
        response = self._server.handle_bad_response(response)
        return response

    def get_task_logs(self, task_id: str) -> HTTPResponse:
        response = cast(HTTPResponse, self.get("/v1/tasks/{}/logs".format(task_id)))
        response = self._server.handle_bad_response(response, is_httpresponse=True)
        return response

    def get_current_user(self):
        response = self.get("/v1/users/me")
        response = self._server.handle_bad_response(response)
        return response

    def wait_until_task_is_successful(self, task_id: str, timeout: int = get_task_timeout()) -> None:
        print()
        print("Waiting for task: {}".format(task_id))

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

            print("  {} - {}".format(status, description))
            time.sleep(2)

        if not finished:
            raise RSConnectException(get_task_timeout_help_message(timeout))

        if status != "success":
            raise DeploymentFailedException("Application deployment failed with error: {}".format(error))

        print("Task done: {}".format(description))

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
            logger.error("Build logs:\n{}".format(logs.response_body))
            raise e


class CloudService:
    """
    Encapsulates operations involving multiple API calls to Posit Cloud.
    """

    def __init__(
        self,
        cloud_client: PositClient,
        server: CloudServer,
        project_application_id: Optional[str],
    ):
        self._posit_client = cloud_client
        self._server = server
        self._project_application_id = project_application_id

    def _get_current_project_id(self) -> str | None:
        if self._project_application_id is not None:
            project_application = self._posit_client.get_application(self._project_application_id)
            return project_application["content_id"]
        return None

    def prepare_deploy(
        self,
        app_id: Optional[str | int],
        app_name: str,
        bundle_size: int,
        bundle_hash: str,
        app_mode: AppMode,
        app_store_version: Optional[int],
    ) -> PrepareDeployOutputResult:
        application_type = "static" if app_mode in [AppModes.STATIC, AppModes.STATIC_QUARTO] else "connect"
        logger.debug(f"application_type: {application_type}")

        render_by = "server" if app_mode == AppModes.STATIC_QUARTO else None
        logger.debug(f"render_by: {render_by}")

        project_id = self._get_current_project_id()

        if app_id is None:
            # this is a deployment of a new output
            if project_id is not None:
                project = self._posit_client.get_content(project_id)
                space_id = project["space_id"]
            else:
                project_id = None
                space_id = None

            # create the new output and associate it with the current Posit Cloud project and space
            output = self._posit_client.create_output(
                name=app_name,
                application_type=application_type,
                project_id=project_id,
                space_id=space_id,
                render_by=render_by,
            )
            app_id_int = output["source_id"]
        else:
            # this is a redeployment of an existing output
            if app_store_version is not None:
                # versioned app store files store content id in app_id
                output = self._posit_client.get_content(app_id)
                app_id_int = output["source_id"]
                content_id = output["id"]
            else:
                # unversioned appstore files (deployed using a prior release) store application id in app_id
                application = self._posit_client.get_application(app_id)
                # content_id will appear on static applications as output_id
                content_id = application.get("content_id") or application.get("output_id")
                app_id_int = application["id"]
                output = self._posit_client.get_content(content_id)

            if application_type == "static":
                revision = self._posit_client.create_revision(content_id)
                app_id_int = revision["application_id"]

            # associate the output with the current Posit Cloud project (if any)
            if project_id is not None:
                self._posit_client.update_output(output["id"], {"project": project_id})

        app_url = output["url"]
        output_id = output["id"]

        bundle = self._posit_client.create_bundle(app_id_int, "application/x-tar", bundle_size, bundle_hash)

        return PrepareDeployOutputResult(
            app_id=output_id,
            application_id=app_id_int,
            app_url=app_url,
            bundle_id=int(bundle["id"]),
            presigned_url=bundle["presigned_url"],
            presigned_checksum=bundle["presigned_checksum"],
        )

    def do_deploy(self, bundle_id: str, app_id: str):
        self._posit_client.set_bundle_status(bundle_id, "ready")
        deploy_task = self._posit_client.deploy_application(bundle_id, app_id)
        try:
            self._posit_client.wait_until_task_is_successful(deploy_task["id"])
        except DeploymentFailedException as e:
            logs_response = self._posit_client.get_task_logs(deploy_task["id"])
            if len(logs_response.response_body) > 0:
                logger.error("Build logs:\n{}".format(logs_response.response_body))
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


def verify_api_key(connect_server: RSConnectServer) -> str:
    """
    Verify that an API Key may be used to authenticate with the given Posit Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information, including the API key to test.
    :return: the username of the user to whom the API key belongs.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    with RSConnectClient(connect_server) as client:
        result = client.me()
        if isinstance(result, HTTPResponse):
            if (
                result.json_data
                and isinstance(result.json_data, dict)
                and "code" in result.json_data
                and result.json_data["code"] == 30
            ):
                raise RSConnectException("The specified API key is not valid.")
            raise RSConnectException("Could not verify the API key: %s %s" % (result.status, result.reason))
        return result["username"]


def get_python_info(connect_server: RSConnectServer):
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


def get_app_info(connect_server: RSConnectServer, app_id: str):
    """
    Return information about an application that has been created in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get info for.
    :return: the Python installation information from Connect.
    """
    with RSConnectClient(connect_server) as client:
        return client.app_get(app_id)


def get_posit_app_info(server: PositServer, app_id: str):
    with PositClient(server) as client:
        if isinstance(server, ShinyappsServer):
            return client.get_application(app_id)
        else:
            response = client.get_content(app_id)
            return response["source"]


def get_app_config(connect_server: RSConnectServer, app_id: str):
    """
    Return the configuration information for an application that has been created
    in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get the info for.
    :return: the Python installation information from Connect.
    """
    with RSConnectClient(connect_server) as client:
        result = client.app_config(app_id)
        result = connect_server.handle_bad_response(result)
        return result


def emit_task_log(
    connect_server: RSConnectServer,
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
        app_config = client.app_config(app_id)
        connect_server.handle_bad_response(app_config)
        app_url = app_config.get("config_url")
        return (app_url, *result)


def retrieve_matching_apps(
    connect_server: RSConnectServer,
    filters: Optional[dict[str, str | int]] = None,
    limit: Optional[int] = None,
    mapping_function: Optional[Callable[[RSConnectClient, ContentItemV0], AbbreviatedAppItem | None]] = None,
) -> list[ContentItemV0 | AbbreviatedAppItem]:
    """
    Retrieves all the app names that start with the given default name.  The main
    point for this function is that it handles all the necessary paging logic.

    If a mapping function is provided, it must be a callable that accepts 2
    arguments.  The first will be an `RSConnect` client, in the event extra calls
    per app are required.  The second will be the current app.  If the function
    returns None, then the app will be discarded and not appear in the result.

    :param connect_server: the Connect server information.
    :param filters: the filters to use for isolating the set of desired apps.
    :param limit: the maximum number of apps to retrieve.  If this is None,
    then all matching apps are returned.
    :param mapping_function: an optional function that may transform or filter
    each app to return to something the caller wants.
    :return: the list of existing names that start with the proposed one.
    """
    page_size = 100
    result: list[ContentItemV0 | AbbreviatedAppItem] = []
    search_filters: dict[str, str | int] = filters.copy() if filters else {}
    search_filters["count"] = min(limit, page_size) if limit else page_size
    total_returned = 0
    maximum = limit
    finished = False

    with RSConnectClient(connect_server) as client:
        while not finished:
            response = client.app_search(search_filters)

            if not maximum:
                maximum = response["total"]
            else:
                maximum = min(maximum, response["total"])

            applications = response["applications"]
            returned = response["count"]
            delta = maximum - (total_returned + returned)
            # If more came back than we need, drop the rest.
            if delta < 0:
                applications = applications[: abs(delta)]
            total_returned = total_returned + len(applications)

            if mapping_function:
                applications = [mapping_function(client, app) for app in applications]
                # Now filter out the None values that represent the apps the
                # function told us to drop.
                applications = [app for app in applications if app is not None]

            result.extend(applications)

            if total_returned < maximum:
                search_filters = {
                    "start": total_returned,
                    "count": page_size,
                    "cont": response["continuation"],
                }
            else:
                finished = True

    return result


class AbbreviatedAppItem(TypedDict):
    id: int
    name: str
    title: str | None
    app_mode: AppModes.Modes
    url: str
    config_url: str


def override_title_search(connect_server: RSConnectServer, app_id: str, app_title: str):
    """
    Returns a list of abbreviated app data that contains apps with a title
    that matches the given one and/or the specific app noted by its ID.

    :param connect_server: the Connect server information.
    :param app_id: the ID of a specific app to look for, if any.
    :param app_title: the title to search for.
    :return: the list of matching apps, each trimmed to ID, name, title, mode
    URL and dashboard URL.
    """

    def map_app(app: ContentItemV0, config: ConfigureResult) -> AbbreviatedAppItem:
        """
        Creates the abbreviated data dictionary for the specified app and config
        information.

        :param app: the raw app data to start with.
        :param config: the configuration data to use.
        :return: the abbreviated app data dictionary.
        """
        return {
            "id": app["id"],
            "name": app["name"],
            "title": app["title"],
            "app_mode": AppModes.get_by_ordinal(app["app_mode"]).name(),
            "url": app["url"],
            "config_url": config["config_url"],
        }

    def mapping_filter(client: RSConnectClient, app: ContentItemV0) -> AbbreviatedAppItem | None:
        """
        Mapping/filter function for retrieving apps.  We only keep apps
        that have an app mode of static or Jupyter notebook.  The data
        for the apps we keep is an abbreviated subset.

        :param client: the client object to use for Posit Connect calls.
        :param app: the current app from Connect.
        :return: the abbreviated data for the app or None.
        """
        # Only keep apps that match our app modes.
        app_mode = AppModes.get_by_ordinal(app["app_mode"])
        if app_mode not in (AppModes.STATIC, AppModes.JUPYTER_NOTEBOOK):
            return None

        config = client.app_config(app["id"])
        config = connect_server.handle_bad_response(config)

        return map_app(app, config)

    apps = retrieve_matching_apps(
        connect_server,
        filters={"filter": "min_role:editor", "search": app_title},
        mapping_function=mapping_filter,
        limit=5,
    )

    if app_id:
        found = next((app for app in apps if app["id"] == app_id), None)

        if not found:
            try:
                app = get_app_info(connect_server, app_id)
                mode = AppModes.get_by_ordinal(app["app_mode"])
                if mode in (AppModes.STATIC, AppModes.JUPYTER_NOTEBOOK):
                    apps.append(map_app(app, get_app_config(connect_server, app_id)))
            except RSConnectException:
                logger.debug('Error getting info for previous app_id "%s", skipping.', app_id)

    return apps


def find_unique_name(remote_server: TargetableServer, name: str):
    """
    Poll through existing apps to see if anything with a similar name exists.
    If so, start appending numbers until a unique name is found.

    :param remote_server: the remote server information.
    :param name: the default name for an app.
    :return: the name, potentially with a suffixed number to guarantee uniqueness.
    """
    if isinstance(remote_server, RSConnectServer):
        existing_names = retrieve_matching_apps(
            remote_server,
            filters={"search": name},
            mapping_function=lambda client, app: app["name"],
        )
    elif isinstance(remote_server, ShinyappsServer):
        client = PositClient(remote_server)
        existing_names = client.get_applications_like_name(name)
    else:
        # non-unique names are permitted in cloud
        return name

    if name in existing_names:
        suffix = 1
        test = "%s%d" % (name, suffix)
        while test in existing_names:
            suffix = suffix + 1
            test = "%s%d" % (name, suffix)
        name = test

    return name
