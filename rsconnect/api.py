"""
RStudio Connect API client and utility functions
"""
import abc
import base64
import calendar
import datetime
import hashlib
import hmac
import time
import typing
import webbrowser
from _ssl import SSLError
from urllib import parse
from urllib.parse import urlparse

import click

from .http_support import HTTPResponse, HTTPServer, append_to_path, CookieJar
from .log import logger
from .models import AppModes


class RSConnectException(Exception):
    def __init__(self, message, cause=None):
        super(RSConnectException, self).__init__(message)
        self.message = message
        self.cause = cause


class AbstractRemoteServer:
    # @property
    # @abc.abstractmethod
    # def url(self) -> str:
    #     pass
    #
    # @property
    # @abc.abstractmethod
    # def remote_name(self) -> str:
    #     pass
    url: str
    remote_name: str

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
                    error = "%s reported an error: %s" % (self.remote_name, response.json_data["error"])
                    raise RSConnectException(error)
                if response.status < 200 or response.status > 299:
                    raise RSConnectException(
                        "Received an unexpected response from %s: %s %s"
                        % (self.remote_name, response.status, response.reason)
                    )


class ShinyappsServer(AbstractRemoteServer):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the shinyapps.io server.
    """

    remote_name = "shinyapps.io"

    def __init__(self, url: str, account_name: str, token: str, secret: str):
        self.url = url
        self.account_name = account_name
        self.token = token
        self.secret = secret


class RSConnectServer(AbstractRemoteServer):
    """
    A simple class to encapsulate the information needed to interact with an
    instance of the Connect server.
    """

    remote_name = "RStudio Connect"

    def __init__(self, url, api_key, insecure=False, ca_data=None):
        self.url = url
        self.api_key = api_key
        self.insecure = insecure
        self.ca_data = ca_data
        # This is specifically not None.
        self.cookie_jar = CookieJar()


class S3Server(AbstractRemoteServer):
    remote_name = 'S3'

    def __init__(self, url: str):
        self.url = url


RemoteServer = typing.Union[ShinyappsServer, RSConnectServer]


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


class S3Client(HTTPServer):
    def upload(self, path, presigned_checksum, bundle_size, contents):
        headers = {
            "content-type": "application/x-tar",
            "content-length": str(bundle_size),
            "content-md5": presigned_checksum,
        }
        return self.put(path, headers=headers, body=contents, decode_response=False)


class ShinyappsClient(HTTPServer):
    def __init__(self, shinyapps_server: ShinyappsServer, timeout: int = 30):
        self._token = shinyapps_server.token
        self._key = base64.b64decode(shinyapps_server.secret)
        self._server = shinyapps_server
        super().__init__(shinyapps_server.url, timeout=timeout)

    def _get_canonical_request(self, method, path, timestamp, content_hash):
        return "\n".join([method, path, timestamp, content_hash])

    def _get_canonical_request_signature(self, request):
        result = hmac.new(self._key, request.encode(), hashlib.sha256).hexdigest()
        return base64.b64encode(result.encode()).decode()

    def get_extra_headers(self, url, method, body):
        canonical_request_method = method.upper()
        canonical_request_path = parse.urlparse(url).path
        canonical_request_date = datetime.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')

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

    def create_application(self, account_id, application_name):
        application_data = {
            "account": account_id,
            "name": application_name,
            "template": "shiny",
        }
        return self.post("/v1/applications/", body=application_data)

    def get_accounts(self):
        return self.get("/v1/accounts/")

    def create_bundle(self, application_id: int, content_type: str, content_length: int, checksum: str):
        bundle_data = {
            "application": application_id,
            "content_type": content_type,
            "content_length": content_length,
            "checksum": checksum,
        }
        return self.post("/v1/bundles", body=bundle_data)

    def set_bundle_status(self, bundle_id, bundle_status):
        return self.post(f"/v1/bundles/{bundle_id}/status", body={"status": bundle_status})

    def deploy_application(self, bundle_id, app_id):
        return self.post(f"/v1/applications/{app_id}/deploy", body={"bundle": bundle_id, "rebuild": False})

    def get_task(self, task_id):
        return self.get(f"/v1/tasks/{task_id}", query_params={"legacy": "true"})

    def get_current_user(self):
        return self.get('/v1/users/me')

    def wait_until_task_is_successful(self, task_id, timeout=60):
        counter = 1
        status = None

        while counter < timeout and status not in ["success", "failed", "error"]:
            task = self.get_task(task_id)
            self._server.handle_bad_response(task)
            status = task.json_data["status"]
            description = task.json_data["description"]

            click.secho(f"Waiting: {status} - {description}")

            if status == "success":
                break

            time.sleep(2)
            counter += 1
        click.secho(f"Task done: {description}")

    def prepare_deploy(self, app_id, app_name, app_title, title_is_default, bundle_size, bundle_hash, env_vars=None):
        accounts = self.get_accounts()
        self._server.handle_bad_response(accounts)
        account = next(
            filter(lambda account: account["name"] == self._server.account_name, accounts.json_data["accounts"]), None
        )
        # TODO: also check this during `add` command
        if account is None:
            raise RSConnectException(
                "No account found by name : %s for given user credential" % self._server.account_name
            )

        application = self.create_application(account["id"], app_name)
        self._server.handle_bad_response(application)

        bundle = self.create_bundle(application.json_data["id"], "application/x-tar", bundle_size, bundle_hash)
        self._server.handle_bad_response(bundle)

        return {"app_id": application.json_data["id"], "app_url": application.json_data["url"], **bundle.json_data}

    def do_deploy(self, bundle_id, app_id):
        bundle_status_response = self.set_bundle_status(bundle_id, "ready")
        self._server.handle_bad_response(bundle_status_response)

        deploy_task = self.deploy_application(bundle_id, app_id)
        self._server.handle_bad_response(deploy_task)
        self.wait_until_task_is_successful(deploy_task.json_data["id"])


def verify_server(connect_server):
    """
    Verify that the given server information represents a Connect instance that is
    reachable, active and appears to be actually running RStudio Connect.  If the
    check is successful, the server settings for the Connect server is returned.

    :param connect_server: the Connect server information.
    :return: the server settings from the Connect server.
    """
    try:
        with RSConnectClient(connect_server) as client:
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


def do_bundle_deploy(remote_server: RemoteServer, app_id, name, title, title_is_default, bundle, env_vars):
    """
    Deploys the specified bundle.

    :param remote_server: the server information.
    :param app_id: the ID of the app to deploy, if this is a redeploy.
    :param name: the name for the deploy.
    :param title: the title for the deploy.
    :param title_is_default: a flag noting whether the title carries a defaulted value.
    :param bundle: the bundle to deploy.
    :param env_vars: list of NAME=VALUE pairs for the app environment
    :return: application information about the deploy.  This includes the ID of the
    task that may be queried for deployment progress.
    """
    if isinstance(remote_server, RSConnectServer):
        with RSConnectClient(remote_server, timeout=120) as client:
            result = client.deploy(app_id, name, title, title_is_default, bundle, env_vars)
            remote_server.handle_bad_response(result)
            return result
    else:
        contents = bundle.read()
        bundle_size = len(contents)
        bundle_hash = hashlib.md5(contents).hexdigest()

        with ShinyappsClient(remote_server, timeout=120) as client:
            prepare_deploy_result = client.prepare_deploy(
                app_id, name, title, title_is_default, bundle_size, bundle_hash, env_vars
            )

        upload_url = prepare_deploy_result["presigned_url"]
        parsed_upload_url = urlparse(upload_url)
        with S3Client(f"{parsed_upload_url.scheme}://{parsed_upload_url.netloc}", timeout=120) as client:
            upload_result = client.upload(
                upload_url,
                prepare_deploy_result["presigned_checksum"],
                bundle_size,
                contents,
            )
            S3Server(upload_url).handle_bad_response(upload_result)

        with ShinyappsClient(remote_server, timeout=120) as client:
            client.do_deploy(prepare_deploy_result["id"], prepare_deploy_result["app_id"])

        webbrowser.open_new(prepare_deploy_result["app_url"])

        return {"app_url": prepare_deploy_result["app_url"], "app_id": prepare_deploy_result["id"], "app_guid": None}


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
