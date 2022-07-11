"""
RStudio Connect API client and utility functions
"""

from os.path import abspath, basename
import time
from typing import IO, Callable
from _ssl import SSLError
import re
from warnings import warn
from six import text_type
import gc
from .bundle import fake_module_file_from_directory
from .http_support import HTTPResponse, HTTPServer, append_to_path, CookieJar
from .log import logger, connect_logger, cls_logged, console_logger
from .models import AppModes
from .metadata import ServerStore, AppStore
from .exception import RSConnectException


class RSConnectServer(object):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the Connect server.
    """

    def __init__(self, url, api_key, insecure=False, ca_data=None):
        self.url = url
        self.api_key = api_key
        self.insecure = insecure
        self.ca_data = ca_data
        # This is specifically not None.
        self.cookie_jar = CookieJar()

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
                if response.json_data and "error" in response.json_data:
                    error = "The Connect server reported an error: %s" % response.json_data["error"]
                    raise RSConnectException(error)
                if response.status < 200 or response.status > 299:
                    raise RSConnectException(
                        "Received an unexpected response from RStudio Connect: %s %s"
                        % (response.status, response.reason)
                    )


class RSConnect(HTTPServer):
    def __init__(self, server, cookies=None, timeout=30):
        if cookies is None:
            cookies = server.cookie_jar
        super(RSConnect, self).__init__(
            append_to_path(server.url, "__api__"),
            server.insecure,
            server.ca_data,
            cookies,
            timeout,
        )
        self._server = server

        if server.api_key:
            self.key_authorization(server.api_key)

    def _tweak_response(self, response):
        return (
            response.json_data
            if response.status and response.status == 200 and response.json_data is not None
            else response
        )

    def me(self):
        return self.get("me")

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
        timeout: int = 30,
        logger=console_logger,
        **kwargs
    ) -> None:
        self.reset()
        self._d = kwargs
        self.setup_connect_server(name, url or kwargs.get("server"), api_key, insecure, cacert, ca_data)
        self.setup_client(cookies, timeout)
        self.logger = logger

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
        self.connect_server = None
        self.client = None
        self.logger = None
        gc.collect()
        return self

    def drop_context(self):
        self._d = None
        gc.collect()
        return self

    def setup_connect_server(
        self,
        name: str = None,
        url: str = None,
        api_key: str = None,
        insecure: bool = False,
        cacert: IO = None,
        ca_data: str = None,
    ):
        if name and url:
            raise RSConnectException("You must specify only one of -n/--name or -s/--server, not both.")
        if not name and not url:
            raise RSConnectException("You must specify one of -n/--name or -s/--server.")

        if cacert and not ca_data:
            ca_data = text_type(cacert.read())

        url, api_key, insecure, ca_data, _ = ServerStore().resolve(name, url, api_key, insecure, ca_data)
        self.connect_server = RSConnectServer(url, api_key, insecure, ca_data)

    def setup_client(self, cookies=None, timeout=30, **kwargs):
        self.client = RSConnect(self.connect_server, cookies, timeout)

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
        **kwargs
    ):
        """
        Validate that the user gave us enough information to talk to a Connect server.

        :param name: the nickname, if any, specified by the user.
        :param url: the URL, if any, specified by the user.
        :param api_key: the API key, if any, specified by the user.
        :param insecure: a flag noting whether TLS host/validation should be skipped.
        :param cacert: the file object of a CA certs file containing certificates to use.
        :param api_key_is_required: a flag that notes whether the API key is required or may
        be omitted.
        """
        url = url or self.connect_server.url
        api_key = api_key or self.connect_server.api_key
        insecure = insecure or self.connect_server.insecure
        api_key_is_required = api_key_is_required or self.get("api_key_is_required", **kwargs)
        server_store = ServerStore()

        if cacert:
            ca_data = text_type(cacert.read())
        else:
            ca_data = self.connect_server.ca_data

        if name and url:
            raise RSConnectException("You must specify only one of -n/--name or -s/--server, not both.")
        if not name and not url:
            raise RSConnectException("You must specify one of -n/--name or -s/--server.")

        real_server, api_key, insecure, ca_data, from_store = server_store.resolve(
            name, url, api_key, insecure, ca_data
        )

        # This can happen if the user specifies neither --name or --server and there's not
        # a single default to go with.
        if not real_server:
            raise RSConnectException("You must specify one of -n/--name or -s/--server.")

        connect_server = RSConnectServer(real_server, None, insecure, ca_data)

        # If our info came from the command line, make sure the URL really works.
        if not from_store:
            self.server_settings

        connect_server.api_key = api_key

        if not connect_server.api_key:
            if api_key_is_required:
                raise RSConnectException('An API key must be specified for "%s".' % connect_server.url)
            return self

        # If our info came from the command line, make sure the key really works.
        if not from_store:
            _ = self.verify_api_key()

        self.connect_server = connect_server
        self.client = RSConnect(self.connect_server)

        return self

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
        d["deployment_name"] = self.make_deployment_name(d["title"], app_id is None)

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
        result = self.client.deploy(
            app_id or self.get("app_id"),
            deployment_name or self.get("deployment_name"),
            title or self.get("title"),
            title_is_default or self.get("title_is_default"),
            bundle or self.get("bundle"),
            env_vars or self.get("env_vars"),
        )
        self.connect_server.handle_bad_response(result)
        self.state["deployed_info"] = result
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
        """
        app_id = app_id or self.state["deployed_info"]["app_id"]
        task_id = task_id or self.state["deployed_info"]["task_id"]
        log_lines, _ = self.client.wait_for_task(
            task_id, log_callback.info, abort_func, timeout, poll_wait, raise_on_error
        )
        self.connect_server.handle_bad_response(log_lines)
        app_config = self.client.app_config(app_id)
        self.connect_server.handle_bad_response(app_config)
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
            self.connect_server.url,
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
        connect_server = self.connect_server
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
                app_id, existing_app_mode = app_store.resolve(connect_server.url, app_id, app_mode)
                logger.debug("Using app mode from app %s: %s" % (app_id, app_mode))
            elif app_id is not None:
                # Don't read app metadata if app-id is specified. Instead, we need
                # to get this from Connect.
                app = get_app_info(connect_server, app_id)
                existing_app_mode = AppModes.get_by_ordinal(app.get("app_mode", 0), True)
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
            self.connect_server.handle_bad_response(result)
        except SSLError as ssl_error:
            raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)
        return result

    def verify_api_key(self):
        """
        Verify that an API Key may be used to authenticate with the given RStudio Connect server.
        If the API key verifies, we return the username of the associated user.
        """
        result = self.client.me()
        if isinstance(result, HTTPResponse):
            if result.json_data and "code" in result.json_data and result.json_data["code"] == 30:
                raise RSConnectException("The specified API key is not valid.")
            raise RSConnectException("Could not verify the API key: %s %s" % (result.status, result.reason))
        return self

    @property
    def api_username(self):
        result = self.client.me()
        self.connect_server.handle_bad_response(result)
        return result["username"]

    @property
    def python_info(self):
        """
        Return information about versions of Python that are installed on the indicated
        Connect server.

        :return: the Python installation information from Connect.
        """
        result = self.client.python_settings()
        self.connect_server.handle_bad_response(result)
        return result

    @property
    def server_details(self):
        """
        Builds a dictionary containing the version of RStudio Connect that is running
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

        :param connect_server: the information needed to interact with the Connect server.
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
            name = find_unique_name(self.connect_server, name)

        return name


def filter_out_server_info(**kwargs):
    server_fields = {"connect_server", "name", "server", "api_key", "insecure", "cacert"}
    new_kwargs = {k: v for k, v in kwargs.items() if k not in server_fields}
    return new_kwargs


def verify_server(connect_server):
    """
    Verify that the given server information represents a Connect instance that is
    reachable, active and appears to be actually running RStudio Connect.  If the
    check is successful, the server settings for the Connect server is returned.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)
    try:
        with RSConnect(connect_server) as client:
            result = client.server_settings()
            connect_server.handle_bad_response(result)
            return result
    except SSLError as ssl_error:
        raise RSConnectException("There is an SSL/TLS configuration problem: %s" % ssl_error)


def verify_api_key(connect_server):
    """
    Verify that an API Key may be used to authenticate with the given RStudio Connect server.
    If the API key verifies, we return the username of the associated user.

    :param connect_server: the Connect server information, including the API key to test.
    :return: the username of the user to whom the API key belongs.
    """
    warn("This method has been moved and will be deprecated.", DeprecationWarning, stacklevel=2)

    with RSConnect(connect_server) as client:
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

    with RSConnect(connect_server) as client:
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
    with RSConnect(connect_server) as client:
        result = client.app_get(app_id)
        connect_server.handle_bad_response(result)
        return result


def get_app_config(connect_server, app_id):
    """
    Return the configuration information for an application that has been created
    in Connect.

    :param connect_server: the Connect server information.
    :param app_id: the ID (numeric or GUID) of the application to get the info for.
    :return: the Python installation information from Connect.
    """
    with RSConnect(connect_server) as client:
        result = client.app_config(app_id)
        connect_server.handle_bad_response(result)
        return result


def do_bundle_deploy(connect_server, app_id, name, title, title_is_default, bundle, env_vars):
    """
    Deploys the specified bundle.

    :param connect_server: the Connect server information.
    :param app_id: the ID of the app to deploy, if this is a redeploy.
    :param name: the name for the deploy.
    :param title: the title for the deploy.
    :param title_is_default: a flag noting whether the title carries a defaulted value.
    :param bundle: the bundle to deploy.
    :param env_vars: list of NAME=VALUE pairs for the app environment
    :return: application information about the deploy.  This includes the ID of the
    task that may be queried for deployment progress.
    """
    with RSConnect(connect_server, timeout=120) as client:
        result = client.deploy(app_id, name, title, title_is_default, bundle, env_vars)
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
    with RSConnect(connect_server) as client:
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

    with RSConnect(connect_server) as client:
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

        :param client: the client object to use for RStudio Connect calls.
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


def find_unique_name(connect_server, name):
    """
    Poll through existing apps to see if anything with a similar name exists.
    If so, start appending numbers until a unique name is found.

    :param connect_server: the Connect server information.
    :param name: the default name for an app.
    :return: the name, potentially with a suffixed number to guarantee uniqueness.
    """
    existing_names = retrieve_matching_apps(
        connect_server,
        filters={"search": name},
        mapping_function=lambda client, app: app["name"],
    )

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


def _default_title(file_name):
    """
    Produce a default content title from the given file path.  The result is
    guaranteed to be between 3 and 1024 characters long, as required by RStudio
    Connect.

    :param file_name: the name from which the title will be derived.
    :return: the derived title.
    """
    # Make sure we have enough of a path to derive text from.
    file_name = abspath(file_name)
    # noinspection PyTypeChecker
    return basename(file_name).rsplit(".", 1)[0][:1024].rjust(3, "0")
