"""
Posit Connect API client and utility functions
"""
import binascii
import os
from os.path import abspath
import time
from typing import IO, Callable
import base64
import datetime
import hashlib
import hmac
import typing
import webbrowser
from _ssl import SSLError
from urllib import parse
from urllib.parse import urlparse

import re
from warnings import warn
from six import text_type
import gc

from . import validation
from .http_support import HTTPResponse, HTTPServer, append_to_path, CookieJar
from .log import logger, connect_logger, cls_logged, console_logger
from .models import AppModes
from .metadata import ServerStore, AppStore
from .exception import RSConnectException
from .bundle import _default_title, fake_module_file_from_directory


class AbstractRemoteServer:
    def __init__(self, url: str, remote_name: str):
        self.url = url
        self.remote_name = remote_name

    def handle_bad_response(self, response):
        if isinstance(response, HTTPResponse):
            if response.exception:
                raise RSConnectException(
                    "Exception trying to connect to %s - %s" % (self.url, response.exception), cause=response.exception
                )
            # Sometimes an ISP will respond to an unknown server name by returning a friendly
            # search page so trap that since we know we're expecting JSON from Connect.  This
            # also catches all error conditions which we will report as "not running Connect".
            else:
                if response.json_data and "error" in response.json_data and response.json_data["error"] is not None:
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


class RStudioServer(AbstractRemoteServer):
    """
    A class used to represent the server of the shinyapps.io and RStudio Cloud APIs.
    """

    def __init__(self, remote_name: str, url: str, account_name: str, token: str, secret: str):
        super().__init__(url, remote_name)
        self.account_name = account_name
        self.token = token
        self.secret = secret


class ShinyappsServer(RStudioServer):
    """
    A class to encapsulate the information needed to interact with an
    instance of the shinyapps.io server.
    """

    def __init__(self, url: str, account_name: str, token: str, secret: str):
        remote_name = "shinyapps.io"
        if url == "shinyapps.io" or url is None:
            url = "https://api.shinyapps.io"
        super().__init__(remote_name=remote_name, url=url, account_name=account_name, token=token, secret=secret)


class CloudServer(RStudioServer):
    """
    A class to encapsulate the information needed to interact with an
    instance of the RStudio Cloud server.
    """

    def __init__(self, url: str, account_name: str, token: str, secret: str):
        remote_name = "RStudio Cloud"
        if url == "rstudio.cloud" or url is None:
            url = "https://api.rstudio.cloud"
        super().__init__(remote_name=remote_name, url=url, account_name=account_name, token=token, secret=secret)


class RSConnectServer(AbstractRemoteServer):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the Connect server.
    """

    def __init__(self, url, api_key, insecure=False, ca_data=None, bootstrap_jwt=None):
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


class RSConnectClient(HTTPServer):
    def __init__(self, server: RSConnectServer, cookies=None, timeout=30):
        if cookies is None:
            cookies = server.cookie_jar
        super().__init__(
            append_to_path(server.url, "__api__"),
            server.insecure,
            server.ca_data,
            cookies,
            timeout,
        )
        self._server = server

        if server.api_key:
            self.key_authorization(server.api_key)

        if server.bootstrap_jwt:
            self.bootstrap_authorization(server.bootstrap_jwt)

    def _tweak_response(self, response):
        return (
            response.json_data
            if response.status and response.status == 200 and response.json_data is not None
            else response
        )

    def me(self):
        return self.get("me")

    def bootstrap(self):
        return self.post("v1/experimental/bootstrap")

    def server_settings(self):
        return self.get("server_settings")

    def python_settings(self):
        return self.get("v1/server_settings/python")

    def app_search(self, filters):
        return self.get("applications", query_params=filters)

    def app_create(self, name):
        return self.post("applications", body={"name": name})

    def app_get(self, app_id):
        return self.get("applications/%s" % app_id)

    def app_upload(self, app_id, tarball):
        return self.post("applications/%s/upload" % app_id, body=tarball)

    def app_update(self, app_id, updates):
        return self.post("applications/%s" % app_id, body=updates)

    def app_add_environment_vars(self, app_guid, env_vars):
        env_body = [dict(name=kv[0], value=kv[1]) for kv in env_vars]
        return self.patch("v1/content/%s/environment" % app_guid, body=env_body)

    def app_deploy(self, app_id, bundle_id=None):
        return self.post("applications/%s/deploy" % app_id, body={"bundle": bundle_id})

    def app_publish(self, app_id, access):
        return self.post(
            "applications/%s" % app_id,
            body={"access_type": access, "id": app_id, "needs_config": False},
        )

    def app_config(self, app_id):
        return self.get("applications/%s/config" % app_id)

    def bundle_download(self, content_guid, bundle_id):
        response = self.get("v1/content/%s/bundles/%s/download" % (content_guid, bundle_id), decode_response=False)
        self._server.handle_bad_response(response)
        return response

    def content_search(self):
        response = self.get("v1/content")
        self._server.handle_bad_response(response)
        return response

    def content_get(self, content_guid):
        response = self.get("v1/content/%s" % content_guid)
        self._server.handle_bad_response(response)
        return response

    def content_build(self, content_guid, bundle_id=None):
        response = self.post("v1/content/%s/build" % content_guid, body={"bundle_id": bundle_id})
        self._server.handle_bad_response(response)
        return response

    def task_get(self, task_id, first_status=None):
        params = None
        if first_status is not None:
            params = {"first_status": first_status}
        response = self.get("tasks/%s" % task_id, query_params=params)
        self._server.handle_bad_response(response)
        return response

    def deploy(self, app_id, app_name, app_title, title_is_default, tarball, env_vars=None):
        if app_id is None:
            # create an app if id is not provided
            app = self.app_create(app_name)
            self._server.handle_bad_response(app)
            app_id = app["id"]

            # Force the title to update.
            title_is_default = False
        else:
            # assume app exists. if it was deleted then Connect will
            # raise an error
            app = self.app_get(app_id)
            self._server.handle_bad_response(app)

        app_guid = app["guid"]
        if env_vars:
            result = self.app_add_environment_vars(app_guid, list(env_vars.items()))
            self._server.handle_bad_response(result)

        if app["title"] != app_title and not title_is_default:
            self._server.handle_bad_response(self.app_update(app_id, {"title": app_title}))
            app["title"] = app_title

        app_bundle = self.app_upload(app_id, tarball)

        self._server.handle_bad_response(app_bundle)

        task = self.app_deploy(app_id, app_bundle["id"])

        self._server.handle_bad_response(task)

        return {
            "task_id": task["id"],
            "app_id": app_id,
            "app_guid": app["guid"],
            "app_url": app["url"],
            "title": app["title"],
        }

    def download_bundle(self, content_guid, bundle_id):
        results = self.bundle_download(content_guid, bundle_id)
        self._server.handle_bad_response(results)
        return results

    def search_content(self):
        results = self.content_search()
        self._server.handle_bad_response(results)
        return results

    def get_content(self, content_guid):
        results = self.content_get(content_guid)
        self._server.handle_bad_response(results)
        return results

    def wait_for_task(
        self, task_id, log_callback, abort_func=lambda: False, timeout=None, poll_wait=0.5, raise_on_error=True
    ):

        last_status = None
        ending = time.time() + timeout if timeout else 999999999999

        if log_callback is None:
            log_lines = []
            log_callback = log_lines.append
        else:
            log_lines = None

        sleep_duration = 0.5
        time_slept = 0
        while True:
            if time.time() >= ending:
                raise RSConnectException("Task timed out after %d seconds" % timeout)
            elif abort_func():
                raise RSConnectException("Task aborted.")

            # we continue the loop so that we can re-check abort_func() in case there was an interrupt (^C),
            # otherwise the user would have to wait a full poll_wait cycle before the program would exit.
            if time_slept <= poll_wait:
                time_slept += sleep_duration
                time.sleep(sleep_duration)
                continue
            else:
                time_slept = 0
                task_status = self.task_get(task_id, last_status)
                self._server.handle_bad_response(task_status)
                last_status = self.output_task_log(task_status, last_status, log_callback)
                if task_status["finished"]:
                    result = task_status.get("result")
                    if isinstance(result, dict):
                        data = result.get("data", "")
                        type = result.get("type", "")
                        if data or type:
                            log_callback("%s (%s)" % (data, type))

                    err = task_status.get("error")
                    if err:
                        log_callback("Error from Connect server: " + err)

                    exit_code = task_status["code"]
                    if exit_code != 0:
                        exit_status = "Task exited with status %d." % exit_code
                        if raise_on_error:
                            raise RSConnectException(exit_status)
                        else:
                            log_callback("Task failed. %s" % exit_status)
                    return log_lines, task_status

    @staticmethod
    def output_task_log(task_status, last_status, log_callback):
        """Pipe any new output through the log_callback.

        Returns an updated last_status which should be passed into
        the next call to output_task_log.

        Raises RSConnectException on task failure.
        """
        new_last_status = last_status
        if task_status["last_status"] != last_status:
            for line in task_status["status"]:
                log_callback(line)
            new_last_status = task_status["last_status"]

        return new_last_status


# for backwards compatibility with rsconnect-jupyter
RSConnect = RSConnectClient


class RSConnectExecutor:
    def __init__(
        self,
        name: str = None,
        url: str = None,
        api_key: str = None,
        insecure: bool = False,
        cacert: IO = None,
        ca_data: str = None,
        cookies=None,
        account=None,
        token: str = None,
        secret: str = None,
        timeout: int = 30,
        logger=console_logger,
        **kwargs
    ) -> None:
        self.reset()
        self._d = kwargs
        self.logger = logger
        self.setup_remote_server(
            name=name,
            url=url or kwargs.get("server"),
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
            ca_data=ca_data,
            account_name=account,
            token=token,
            secret=secret,
        )
        self.setup_client(cookies, timeout)

    @classmethod
    def fromConnectServer(cls, connect_server, **kwargs):
        return cls(
            url=connect_server.url,
            api_key=connect_server.api_key,
            insecure=connect_server.insecure,
            ca_data=connect_server.ca_data,
            **kwargs,
        )

    def reset(self):
        self._d = None
        self.remote_server = None
        self.client = None
        self.logger = None
        gc.collect()
        return self

    def drop_context(self):
        self._d = None
        gc.collect()
        return self

    def setup_remote_server(
        self,
        name: str = None,
        url: str = None,
        api_key: str = None,
        insecure: bool = False,
        cacert: IO = None,
        ca_data: str = None,
        account_name: str = None,
        token: str = None,
        secret: str = None,
    ):
        validation.validate_connection_options(
            url=url,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
            account_name=account_name,
            token=token,
            secret=secret,
            name=name,
        )

        if cacert and not ca_data:
            ca_data = text_type(cacert.read())

        server_data = ServerStore().resolve(name, url)
        if server_data.from_store:
            url = server_data.url
            if (
                server_data.api_key
                and api_key
                or server_data.insecure
                and insecure
                or server_data.ca_data
                and ca_data
                or server_data.account_name
                and account_name
                or server_data.token
                and token
                or server_data.secret
                and secret
            ) and self.logger:
                self.logger.warning(
                    "Connect detected CLI commands and/or environment variables that overlap with stored credential.\n"
                )
                self.logger.warning(
                    "Check your environment variables (e.g. CONNECT_API_KEY) to make sure you want them to be used.\n"
                )
                self.logger.warning(
                    "Credential paremeters are taken with the following precedence: stored > CLI > environment.\n"
                )
                self.logger.warning(
                    "To ignore an environment variable, override it in the CLI with an empty string (e.g. -k '').\n"
                )
            api_key = server_data.api_key or api_key
            insecure = server_data.insecure or insecure
            ca_data = server_data.ca_data or ca_data
            account_name = server_data.account_name or account_name
            token = server_data.token or token
            secret = server_data.secret or secret
        self.is_server_from_store = server_data.from_store

        if api_key:
            self.remote_server = RSConnectServer(url, api_key, insecure, ca_data)
        elif token and secret:
            if url and "rstudio.cloud" in url:
                self.remote_server = CloudServer(url, account_name, token, secret)
            else:
                self.remote_server = ShinyappsServer(url, account_name, token, secret)
        else:
            raise RSConnectException("Unable to infer Connect server type and setup server.")

    def setup_client(self, cookies=None, timeout=30, **kwargs):
        if isinstance(self.remote_server, RSConnectServer):
            self.client = RSConnectClient(self.remote_server, cookies, timeout)
        elif isinstance(self.remote_server, RStudioServer):
            self.client = RStudioClient(self.remote_server, timeout)
        else:
            raise RSConnectException("Unable to infer Connect client.")

    @property
    def state(self):
        return self._d

    def get(self, key: str, *args, **kwargs):
        return kwargs.get(key) or self.state.get(key)

    def pipe(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    @cls_logged("Validating server...")
    def validate_server(
        self,
        name: str = None,
        url: str = None,
        api_key: str = None,
        insecure: bool = False,
        cacert: IO = None,
        api_key_is_required: bool = False,
        account_name: str = None,
        token: str = None,
        secret: str = None,
    ):
        if (url and api_key) or isinstance(self.remote_server, RSConnectServer):
            self.validate_connect_server(name, url, api_key, insecure, cacert, api_key_is_required)
        elif (url and token and secret) or isinstance(self.remote_server, RStudioServer):
            self.validate_rstudio_server(url, account_name, token, secret)
        else:
            raise RSConnectException("Unable to validate server from information provided.")

        return self

    def validate_connect_server(
        self,
        name: str = None,
        url: str = None,
        api_key: str = None,
        insecure: bool = False,
        cacert: IO = None,
        api_key_is_required: bool = False,
        **kwargs
    ):
        """
        Validate that the user gave us enough information to talk to shinyapps.io or a Connect server.
        :param name: the nickname, if any, specified by the user.
        :param url: the URL, if any, specified by the user.
        :param api_key: the API key, if any, specified by the user.
        :param insecure: a flag noting whether TLS host/validation should be skipped.
        :param cacert: the file object of a CA certs file containing certificates to use.
        :param api_key_is_required: a flag that notes whether the API key is required or may
        be omitted.
        :param token: The shinyapps.io authentication token.
        :param secret: The shinyapps.io authentication secret.
        """
        url = url or self.remote_server.url
        api_key = api_key or self.remote_server.api_key
        insecure = insecure or self.remote_server.insecure
        api_key_is_required = api_key_is_required or self.get("api_key_is_required", **kwargs)

        ca_data = None
        if cacert:
            ca_data = text_type(cacert.read())
        api_key = api_key or self.remote_server.api_key
        insecure = insecure or self.remote_server.insecure
        if not ca_data:
            ca_data = self.remote_server.ca_data

        api_key_is_required = api_key_is_required or self.get("api_key_is_required", **kwargs)

        if name and url:
            raise RSConnectException("You must specify only one of -n/--name or -s/--server, not both")
        if not name and not url:
            raise RSConnectException("You must specify one of -n/--name or -s/--server.")

        server_data = ServerStore().resolve(name, url)
        connect_server = RSConnectServer(url, None, insecure, ca_data)

        # If our info came from the command line, make sure the URL really works.
        if not server_data.from_store:
            self.server_settings

        connect_server.api_key = api_key

        if not connect_server.api_key:
            if api_key_is_required:
                raise RSConnectException('An API key must be specified for "%s".' % connect_server.url)
            return self

        # If our info came from the command line, make sure the key really works.
        if not server_data.from_store:
            _ = self.verify_api_key(connect_server)

        self.remote_server = connect_server
        self.client = RSConnectClient(self.remote_server)

        return self

    def validate_rstudio_server(
        self, url: str = None, account_name: str = None, token: str = None, secret: str = None, **kwargs
    ):
        url = url or self.remote_server.url
        account_name = account_name or self.remote_server.account_name
        token = token or self.remote_server.token
        secret = secret or self.remote_server.secret
        server = (
            CloudServer(url, account_name, token, secret)
            if "rstudio.cloud" in url
            else ShinyappsServer(url, account_name, token, secret)
        )

        with RStudioClient(server) as client:
            try:
                result = client.get_current_user()
                server.handle_bad_response(result)
            except RSConnectException as exc:
                raise RSConnectException("Failed to verify with {} ({}).".format(server.remote_name, exc))

    @cls_logged("Making bundle ...")
    def make_bundle(self, func: Callable, *args, **kwargs):
        path = (
            self.get("path", **kwargs)
            or self.get("file", **kwargs)
            or self.get("file_name", **kwargs)
            or self.get("directory", **kwargs)
            or self.get("file_or_directory", **kwargs)
        )
        app_id = self.get("app_id", **kwargs)
        title = self.get("title", **kwargs)
        app_store = self.get("app_store", *args, **kwargs)
        if not app_store:
            module_file = fake_module_file_from_directory(path)
            self.state["app_store"] = app_store = AppStore(module_file)

        d = self.state
        d["title_is_default"] = not bool(title)
        d["title"] = title or _default_title(path)
        force_unique_name = app_id is None
        d["deployment_name"] = self.make_deployment_name(d["title"], force_unique_name)

        try:
            bundle = func(*args, **kwargs)
        except IOError as error:
            msg = "Unable to include the file %s in the bundle: %s" % (
                error.filename,
                error.args[1],
            )
            raise RSConnectException(msg)

        d["bundle"] = bundle

        return self

    def check_server_capabilities(self, capability_functions):
        """
        Uses a sequence of functions that check for capabilities in a Connect server.  The
        server settings data is retrieved by the gather_server_details() function.

        Each function provided must accept one dictionary argument which will be the server
        settings data returned by the gather_server_details() function.  That function must
        return a boolean value.  It must also contain a docstring which itself must contain
        an ":error:" tag as the last thing in the docstring.  If the function returns False,
        an exception is raised with the function's ":error:" text as its message.

        :param capability_functions: a sequence of functions that will be called.
        :param details_source: the source for obtaining server details, gather_server_details(),
        by default.
        """
        if isinstance(self.remote_server, RStudioServer):
            return self

        details = self.server_details

        for function in capability_functions:
            if not function(details):
                index = function.__doc__.find(":error:") if function.__doc__ else -1
                if index >= 0:
                    message = function.__doc__[index + 7 :].strip()
                else:
                    message = "The server does not satisfy the %s capability check." % function.__name__
                raise RSConnectException(message)
        return self

    def upload_rstudio_bundle(self, prepare_deploy_result, bundle_size: int, contents):
        upload_url = prepare_deploy_result.presigned_url
        parsed_upload_url = urlparse(upload_url)
        with S3Client("{}://{}".format(parsed_upload_url.scheme, parsed_upload_url.netloc), timeout=120) as s3_client:
            upload_result = s3_client.upload(
                "{}?{}".format(parsed_upload_url.path, parsed_upload_url.query),
                prepare_deploy_result.presigned_checksum,
                bundle_size,
                contents,
            )
            S3Server(upload_url).handle_bad_response(upload_result)

    @cls_logged("Deploying bundle ...")
    def deploy_bundle(
        self,
        app_id: int = None,
        deployment_name: str = None,
        title: str = None,
        title_is_default: bool = False,
        bundle: IO = None,
        env_vars=None,
    ):
        app_id = app_id or self.get("app_id")
        deployment_name = deployment_name or self.get("deployment_name")
        title = title or self.get("title")
        title_is_default = title_is_default or self.get("title_is_default")
        bundle = bundle or self.get("bundle")
        env_vars = env_vars or self.get("env_vars")

        if isinstance(self.remote_server, RSConnectServer):
            result = self.client.deploy(
                app_id,
                deployment_name,
                title,
                title_is_default,
                bundle,
                env_vars,
            )
            self.remote_server.handle_bad_response(result)
            self.state["deployed_info"] = result
            return self
        else:
            contents = bundle.read()
            bundle_size = len(contents)
            bundle_hash = hashlib.md5(contents).hexdigest()

            if isinstance(self.remote_server, ShinyappsServer):
                shinyapps_service = ShinyappsService(self.client, self.remote_server)
                prepare_deploy_result = shinyapps_service.prepare_deploy(
                    app_id,
                    deployment_name,
                    bundle_size,
                    bundle_hash,
                )
                self.upload_rstudio_bundle(prepare_deploy_result, bundle_size, contents)
                shinyapps_service.do_deploy(prepare_deploy_result.bundle_id, prepare_deploy_result.app_id)
            else:
                cloud_service = CloudService(self.client, self.remote_server)
                prepare_deploy_result = cloud_service.prepare_deploy(
                    app_id,
                    deployment_name,
                    bundle_size,
                    bundle_hash,
                )
                self.upload_rstudio_bundle(prepare_deploy_result, bundle_size, contents)
                cloud_service.do_deploy(prepare_deploy_result.bundle_id, prepare_deploy_result.app_id)

            print("Application successfully deployed to {}".format(prepare_deploy_result.app_url))
            webbrowser.open_new(prepare_deploy_result.app_url)

            self.state["deployed_info"] = {
                "app_url": prepare_deploy_result.app_url,
                "app_id": prepare_deploy_result.app_id,
                "app_guid": None,
                "title": title,
            }
            return self

    def emit_task_log(
        self,
        app_id: int = None,
        task_id: int = None,
        log_callback=connect_logger,
        abort_func: Callable[[], bool] = lambda: False,
        timeout: int = None,
        poll_wait: float = 0.5,
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
            app_id = app_id or self.state["deployed_info"]["app_id"]
            task_id = task_id or self.state["deployed_info"]["task_id"]
            log_lines, _ = self.client.wait_for_task(
                task_id, log_callback.info, abort_func, timeout, poll_wait, raise_on_error
            )
            self.remote_server.handle_bad_response(log_lines)
            app_config = self.client.app_config(app_id)
            self.remote_server.handle_bad_response(app_config)
            app_dashboard_url = app_config.get("config_url")
            log_callback.info("Deployment completed successfully.")
            log_callback.info("\t Dashboard content URL: %s", app_dashboard_url)
            log_callback.info("\t Direct content URL: %s", self.state["deployed_info"]["app_url"])

        return self

    @cls_logged("Saving deployed information...")
    def save_deployed_info(self, *args, **kwargs):
        app_store = self.get("app_store", *args, **kwargs)
        path = (
            self.get("path", **kwargs)
            or self.get("file", **kwargs)
            or self.get("file_name", **kwargs)
            or self.get("directory", **kwargs)
            or self.get("file_or_directory", **kwargs)
        )
        deployed_info = self.get("deployed_info", *args, **kwargs)

        app_store.set(
            self.remote_server.url,
            abspath(path),
            deployed_info["app_url"],
            deployed_info["app_id"],
            deployed_info["app_guid"],
            deployed_info["title"],
            self.state["app_mode"],
        )

        return self

    @cls_logged("Validating app mode...")
    def validate_app_mode(self, *args, **kwargs):
        path = (
            self.get("path", **kwargs)
            or self.get("file", **kwargs)
            or self.get("file_name", **kwargs)
            or self.get("directory", **kwargs)
            or self.get("file_or_directory", **kwargs)
        )
        app_store = self.get("app_store", *args, **kwargs)
        if not app_store:
            module_file = fake_module_file_from_directory(path)
            self.state["app_store"] = app_store = AppStore(module_file)
        new = self.get("new", **kwargs)
        app_id = self.get("app_id", **kwargs)
        app_mode = self.get("app_mode", **kwargs)

        if new and app_id:
            raise RSConnectException("Specify either a new deploy or an app ID but not both.")

        existing_app_mode = None
        if not new:
            if app_id is None:
                # Possible redeployment - check for saved metadata.
                # Use the saved app information unless overridden by the user.
                app_id, existing_app_mode = app_store.resolve(self.remote_server.url, app_id, app_mode)
                logger.debug("Using app mode from app %s: %s" % (app_id, app_mode))
            elif app_id is not None:
                # Don't read app metadata if app-id is specified. Instead, we need
                # to get this from the remote.
                if isinstance(self.remote_server, RSConnectServer):
                    app = get_app_info(self.remote_server, app_id)
                    existing_app_mode = AppModes.get_by_ordinal(app.get("app_mode", 0), True)
                elif isinstance(self.remote_server, RStudioServer):
                    app = get_rstudio_app_info(self.remote_server, app_id)
                    existing_app_mode = AppModes.get_by_cloud_name(app.json_data["mode"])
                else:
                    raise RSConnectException("Unable to infer Connect client.")
            if existing_app_mode and app_mode != existing_app_mode:
                msg = (
                    "Deploying with mode '%s',\n"
                    + "but the existing deployment has mode '%s'.\n"
                    + "Use the --new option to create a new deployment of the desired type."
                ) % (app_mode.desc(), existing_app_mode.desc())
                raise RSConnectException(msg)

        self.state["app_id"] = app_id
        self.state["app_mode"] = app_mode
        return self

    @property
    def server_settings(self):
        try:
            result = self.client.server_settings()
            self.remote_server.handle_bad_response(result)
        except SSLError as ssl_error:
            raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)
        return result

    def verify_api_key(self, server=None):
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
                if result.json_data and "code" in result.json_data and result.json_data["code"] == 30:
                    raise RSConnectException("The specified API key is not valid.")
                raise RSConnectException("Could not verify the API key: %s %s" % (result.status, result.reason))
        return self

    @property
    def api_username(self):
        result = self.client.me()
        self.remote_server.handle_bad_response(result)
        return result["username"]

    @property
    def python_info(self):
        """
        Return information about versions of Python that are installed on the indicated
        Connect server.

        :return: the Python installation information from Connect.
        """
        result = self.client.python_settings()
        self.remote_server.handle_bad_response(result)
        return result

    @property
    def server_details(self):
        """
        Builds a dictionary containing the version of Posit Connect that is running
        and the versions of Python installed there.

        :return: a three-entry dictionary.  The key 'connect' will refer to the version
        of Connect that was found.  The key `python` will refer to a sequence of version
        strings for all the versions of Python that are installed.  The key `conda` will
        refer to data about whether Connect is configured to support Conda environments.
        """

        def _to_sort_key(text):
            parts = [part.zfill(5) for part in text.split(".")]
            return "".join(parts)

        server_settings = self.server_settings
        python_settings = self.python_info
        python_versions = sorted([item["version"] for item in python_settings["installations"]], key=_to_sort_key)
        conda_settings = {
            "supported": python_settings["conda_enabled"] if "conda_enabled" in python_settings else False
        }
        return {
            "connect": server_settings["version"],
            "python": {
                "api_enabled": python_settings["api_enabled"] if "api_enabled" in python_settings else False,
                "versions": python_versions,
            },
            "conda": conda_settings,
        }

    def make_deployment_name(self, title, force_unique):
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


def filter_out_server_info(**kwargs):
    server_fields = {"connect_server", "name", "server", "api_key", "insecure", "cacert"}
    new_kwargs = {k: v for k, v in kwargs.items() if k not in server_fields}
    return new_kwargs


class S3Client(HTTPServer):
    def upload(self, path, presigned_checksum, bundle_size, contents):
        headers = {
            "content-type": "application/x-tar",
            "content-length": str(bundle_size),
            "content-md5": presigned_checksum,
        }
        return self.put(path, headers=headers, body=contents, decode_response=False)


class PrepareDeployResult:
    def __init__(self, app_id: int, app_url: str, bundle_id: int, presigned_url: str, presigned_checksum: str):
        self.app_id = app_id
        self.app_url = app_url
        self.bundle_id = bundle_id
        self.presigned_url = presigned_url
        self.presigned_checksum = presigned_checksum


class PrepareDeployOutputResult(PrepareDeployResult):
    def __init__(
        self, app_id: int, app_url: str, bundle_id: int, presigned_url: str, presigned_checksum: str, output_id: int
    ):
        super().__init__(
            app_id=app_id,
            app_url=app_url,
            bundle_id=bundle_id,
            presigned_url=presigned_url,
            presigned_checksum=presigned_checksum,
        )
        self.output_id = output_id


class RStudioClient(HTTPServer):
    """
    An HTTP client to call the RStudio Cloud and shinyapps.io APIs.
    """

    _TERMINAL_STATUSES = {"success", "failed", "error"}

    def __init__(self, rstudio_server: RStudioServer, timeout: int = 30):
        self._token = rstudio_server.token
        try:
            self._key = base64.b64decode(rstudio_server.secret)
        except binascii.Error as e:
            raise RSConnectException("Invalid secret.") from e
        self._server = rstudio_server
        super().__init__(rstudio_server.url, timeout=timeout)

    def _get_canonical_request(self, method, path, timestamp, content_hash):
        return "\n".join([method, path, timestamp, content_hash])

    def _get_canonical_request_signature(self, request):
        result = hmac.new(self._key, request.encode(), hashlib.sha256).hexdigest()
        return base64.b64encode(result.encode()).decode()

    def get_extra_headers(self, url, method, body):
        canonical_request_method = method.upper()
        canonical_request_path = parse.urlparse(url).path
        canonical_request_date = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

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

    def get_application(self, application_id):
        return self.get("/v1/applications/{}".format(application_id))

    def get_content(self, content_id):
        return self.get("/v1/content/{}".format(content_id))

    def create_application(self, account_id, application_name):
        application_data = {
            "account": account_id,
            "name": application_name,
            "template": "shiny",
        }
        return self.post("/v1/applications/", body=application_data)

    def create_output(self, name, project_id=None, space_id=None):
        data = {
            "name": name,
            "space": space_id,
            "project": project_id,
        }
        return self.post("/v1/outputs/", body=data)

    def get_accounts(self):
        return self.get("/v1/accounts/")

    def _get_applications_like_name_page(self, name: str, offset: int):
        return self.get(
            "/v1/applications?filter=name:like:{}&offset={}&count=100&use_advanced_filters=true".format(name, offset)
        )

    def create_bundle(self, application_id: int, content_type: str, content_length: int, checksum: str):
        bundle_data = {
            "application": application_id,
            "content_type": content_type,
            "content_length": content_length,
            "checksum": checksum,
        }
        result = self.post("/v1/bundles", body=bundle_data)
        return result

    def set_bundle_status(self, bundle_id, bundle_status):
        return self.post("/v1/bundles/{}/status".format(bundle_id), body={"status": bundle_status})

    def deploy_application(self, bundle_id, app_id):
        return self.post("/v1/applications/{}/deploy".format(app_id), body={"bundle": bundle_id, "rebuild": False})

    def get_task(self, task_id):
        return self.get("/v1/tasks/{}".format(task_id), query_params={"legacy": "true"})

    def get_current_user(self):
        return self.get("/v1/users/me")

    def wait_until_task_is_successful(self, task_id, timeout=180):
        print()
        print("Waiting for task: {}".format(task_id))
        start_time = time.time()
        while time.time() - start_time < timeout:
            task = self.get_task(task_id)
            self._server.handle_bad_response(task)
            finished = task.json_data["finished"]
            status = task.json_data["status"]
            description = task.json_data["description"]
            error = task.json_data["error"]

            if finished:
                break

            print("  {} - {}".format(status, description))
            time.sleep(2)

        if not finished:
            raise RSConnectException("Application deployment timed out.")

        if status != "success":
            raise RSConnectException("Application deployment failed with error: {}".format(error))

        print("Task done: {}".format(description))

    def get_applications_like_name(self, name):
        applications = []

        results = self._get_applications_like_name_page(name, 0)
        self._server.handle_bad_response(results)
        offset = 0

        while len(applications) < int(results.json_data["total"]):
            results = self._get_applications_like_name_page(name, offset)
            self._server.handle_bad_response(results)
            applications = results.json_data["applications"]
            applications.extend(applications)
            offset += int(results.json_data["count"])

        return [app["name"] for app in applications]


class ShinyappsService:
    """
    Encapsulates operations involving multiple API calls to shinyapps.io.
    """

    def __init__(self, rstudio_client: RStudioClient, server: ShinyappsServer):
        self._rstudio_client = rstudio_client
        self._server = server

    def prepare_deploy(self, app_id: typing.Optional[int], app_name: str, bundle_size: int, bundle_hash: str):
        accounts = self._rstudio_client.get_accounts()
        self._server.handle_bad_response(accounts)
        account = next(
            filter(lambda acct: acct["name"] == self._server.account_name, accounts.json_data["accounts"]), None
        )
        # TODO: also check this during `add` command
        if account is None:
            raise RSConnectException(
                "No account found by name : %s for given user credential" % self._server.account_name
            )

        if app_id is None:
            application = self._rstudio_client.create_application(account["id"], app_name)
        else:
            application = self._rstudio_client.get_application(app_id)
        self._server.handle_bad_response(application)
        app_id_int = application.json_data["id"]
        app_url = application.json_data["url"]

        bundle = self._rstudio_client.create_bundle(app_id_int, "application/x-tar", bundle_size, bundle_hash)
        self._server.handle_bad_response(bundle)

        return PrepareDeployResult(
            app_id_int,
            app_url,
            int(bundle.json_data["id"]),
            bundle.json_data["presigned_url"],
            bundle.json_data["presigned_checksum"],
        )

    def do_deploy(self, bundle_id, app_id):
        bundle_status_response = self._rstudio_client.set_bundle_status(bundle_id, "ready")
        self._server.handle_bad_response(bundle_status_response)

        deploy_task = self._rstudio_client.deploy_application(bundle_id, app_id)
        self._server.handle_bad_response(deploy_task)
        self._rstudio_client.wait_until_task_is_successful(deploy_task.json_data["id"])


class CloudService:
    """
    Encapsulates operations involving multiple API calls to RStudio Cloud.
    """

    def __init__(self, rstudio_client: RStudioClient, server: CloudServer):
        self._rstudio_client = rstudio_client
        self._server = server

    def prepare_deploy(
        self,
        app_id: typing.Optional[int],
        app_name: str,
        bundle_size: int,
        bundle_hash: str,
    ):
        if app_id is None:
            project_application_id = os.getenv("LUCID_APPLICATION_ID")
            if project_application_id is not None:
                project_application = self._rstudio_client.get_application(project_application_id)
                self._server.handle_bad_response(project_application)
                project_id = project_application.json_data["content_id"]
                project = self._rstudio_client.get_content(project_id)
                self._server.handle_bad_response(project)
                space_id = project.json_data["space_id"]
            else:
                project_id = None
                space_id = None

            output = self._rstudio_client.create_output(name=app_name, project_id=project_id, space_id=space_id)
            self._server.handle_bad_response(output)
            app_id = output.json_data["source_id"]
            application = self._rstudio_client.get_application(app_id)
            self._server.handle_bad_response(application)
        else:
            application = self._rstudio_client.get_application(app_id)
            self._server.handle_bad_response(application)
            output = self._rstudio_client.get_content(application.json_data["content_id"])
            self._server.handle_bad_response(output)

        app_id_int = application.json_data["id"]
        app_url = output.json_data["url"]
        output_id = output.json_data["id"]

        bundle = self._rstudio_client.create_bundle(app_id_int, "application/x-tar", bundle_size, bundle_hash)
        self._server.handle_bad_response(bundle)

        return PrepareDeployOutputResult(
            app_id=app_id_int,
            app_url=app_url,
            bundle_id=int(bundle.json_data["id"]),
            presigned_url=bundle.json_data["presigned_url"],
            presigned_checksum=bundle.json_data["presigned_checksum"],
            output_id=output_id,
        )

    def do_deploy(self, bundle_id, app_id):
        bundle_status_response = self._rstudio_client.set_bundle_status(bundle_id, "ready")
        self._server.handle_bad_response(bundle_status_response)

        deploy_task = self._rstudio_client.deploy_application(bundle_id, app_id)
        self._server.handle_bad_response(deploy_task)
        self._rstudio_client.wait_until_task_is_successful(deploy_task.json_data["id"])


def verify_server(connect_server):
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
            connect_server.handle_bad_response(result)
            return result
    except SSLError as ssl_error:
        raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)


def verify_api_key(connect_server):
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
            if result.json_data and "code" in result.json_data and result.json_data["code"] == 30:
                raise RSConnectException("The specified API key is not valid.")
            raise RSConnectException("Could not verify the API key: %s %s" % (result.status, result.reason))
        return result["username"]


def get_python_info(connect_server):
    """
    Return information about versions of Python that are installed on the indicated
    Connect server.

    :param connect_server: the Connect server information.
    :return: the Python installation information from Connect.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    with RSConnectClient(connect_server) as client:
        result = client.python_settings()
        connect_server.handle_bad_response(result)
        return result


def get_app_info(connect_server, app_id):
    """
    Return information about an application that has been created in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get info for.
    :return: the Python installation information from Connect.
    """
    with RSConnectClient(connect_server) as client:
        result = client.app_get(app_id)
        connect_server.handle_bad_response(result)
        return result


def get_rstudio_app_info(server, app_id):
    with RStudioClient(server) as client:
        result = client.get_application(app_id)
        server.handle_bad_response(result)
        return result


def get_app_config(connect_server, app_id):
    """
    Return the configuration information for an application that has been created
    in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get the info for.
    :return: the Python installation information from Connect.
    """
    with RSConnectClient(connect_server) as client:
        result = client.app_config(app_id)
        connect_server.handle_bad_response(result)
        return result


def emit_task_log(
    connect_server,
    app_id,
    task_id,
    log_callback,
    abort_func=lambda: False,
    timeout=None,
    poll_wait=0.5,
    raise_on_error=True,
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
        connect_server.handle_bad_response(result)
        app_config = client.app_config(app_id)
        connect_server.handle_bad_response(app_config)
        app_url = app_config.get("config_url")
        return (app_url, *result)


def retrieve_matching_apps(connect_server, filters=None, limit=None, mapping_function=None):
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
    result = []
    search_filters = filters.copy() if filters else {}
    search_filters["count"] = min(limit, page_size) if limit else page_size
    total_returned = 0
    maximum = limit
    finished = False

    with RSConnectClient(connect_server) as client:
        while not finished:
            response = client.app_search(search_filters)
            connect_server.handle_bad_response(response)

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


def override_title_search(connect_server, app_id, app_title):
    """
    Returns a list of abbreviated app data that contains apps with a title
    that matches the given one and/or the specific app noted by its ID.

    :param connect_server: the Connect server information.
    :param app_id: the ID of a specific app to look for, if any.
    :param app_title: the title to search for.
    :return: the list of matching apps, each trimmed to ID, name, title, mode
    URL and dashboard URL.
    """

    def map_app(app, config):
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

    def mapping_filter(client, app):
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
        connect_server.handle_bad_response(config)

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
        client = RStudioClient(remote_server)
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


def _to_server_check_list(url):
    """
    Build a list of servers to check from the given one.  If the specified server
    appears not to have a scheme, then we'll provide https and http variants to test.

    :param url: the server URL text to start with.
    :return: a list of server strings to test.
    """
    # urlparse will end up with an empty netloc in this case.
    if "//" not in url:
        items = ["https://%s", "http://%s"]
    # urlparse would parse this correctly and end up with an empty scheme.
    elif url.startswith("//"):
        items = ["https:%s", "http:%s"]
    else:
        items = ["%s"]

    return [item % url for item in items]
