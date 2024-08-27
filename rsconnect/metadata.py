"""
Metadata management objects and utility functions
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from io import BufferedWriter
from os.path import abspath, basename, dirname, exists, join
from threading import Lock
from typing import TYPE_CHECKING, Callable, Dict, Generic, Mapping, Optional, TypeVar
from urllib.parse import urlparse

# Even though TypedDict is available in Python 3.8, because it's used with NotRequired,
# they should both come from the same typing module.
# https://peps.python.org/pep-0655/#usage-in-python-3-11
if sys.version_info >= (3, 11):
    from typing import NotRequired, TypedDict
else:
    from typing_extensions import NotRequired, TypedDict


if TYPE_CHECKING:
    from .api import RSConnectServer

from .exception import RSConnectException
from .log import logger
from .models import AppMode, AppModes, ContentItemV1, TaskStatusResult, TaskStatusV1

T = TypeVar("T", bound=Mapping[str, object])


def config_dirname(platform: str = sys.platform, env: Mapping[str, str] = os.environ):
    """Get the user's configuration directory path for this platform."""
    home = env.get("HOME", "~")
    base_dir = home

    if platform.startswith("linux"):
        base_dir = env.get("XDG_CONFIG_HOME", home)
    elif platform == "darwin":
        base_dir = join(home, "Library", "Application Support")
    elif platform == "win32":
        # noinspection SpellCheckingInspection
        base_dir = env.get("APPDATA", home)

    if base_dir == home:
        return join(base_dir, ".rsconnect-python")
    else:
        return join(base_dir, "rsconnect-python")


# noinspection SpellCheckingInspection
def makedirs(filepath: str):
    """Create the parent directories of filepath.

    `filepath` itself is not created.
    It is not an error if the directories already exist.
    """
    try:
        os.makedirs(dirname(filepath))
    except OSError:
        pass


def _normalize_server_url(server_url: str):
    url = urlparse(server_url)
    return url.netloc.replace(".", "_").replace(":", "_")


class DataStore(Generic[T]):
    """
    Defines a base class for a persistent store.  The store supports a primary location and
    an optional secondary one.
    """

    def __init__(self, primary_path: str, secondary_path: Optional[str] = None, chmod: bool = False):
        self._primary_path = primary_path
        self._secondary_path = secondary_path
        self._chmod = chmod
        self._data: dict[str, T] = {}
        self._real_path: str | None = None
        self._lock = Lock()

        self.load()

    def count(self):
        """
        Return the number of items in the data store.

        :return: the number of items currently in the data store.
        """
        return len(self._data)

    def _load_from(self, path: str):
        """
        Load the data for this store from the specified path, if it exists.

        Returns True if the data was successfully loaded.
        """
        if exists(path):
            with open(path, "rb") as f:
                self._data = json.loads(f.read().decode("utf-8"))
                self._real_path = path
                return True
        return False

    def load(self):
        """
        Load the data from a file.  If the primary file doesn't exist, load it
        from the secondary one (if there is one.
        """
        if not self._load_from(self._primary_path) and self._secondary_path:
            self._load_from(self._secondary_path)

    def _get_by_key(self, key: str, default: T | None = None) -> T | None:
        """
        Return a stored value by its key.

        :param key: the key for the value to return.
        :return: the associated value or None if there isn't one.
        """
        return self._data.get(key, default)

    def _get_by_value_attr(self, attr: str, value: T) -> T | None:
        """
        Return a stored value by an attribute of its value.

        :param attr: the value attribute to search for.
        :param value: the value of the attribute to search for.
        :return: the value that carries the named attribute's value  or None if
        there isn't one.
        """
        for item in self._data.values():
            if item[attr] == value:
                return item
        return None

    def _get_first_value(self) -> T:
        """
        A convenience function that returns the (arbitrary) first value in the
        store.  This is most useful when the store contains one, and only one,
        value

        :return: the first value in the store.
        """
        return list(self._data.values())[0]

    def _get_sorted_values(self, sort_by: Callable[[T], str]):
        """
        Return all the values in the store sorted by the given lambda expression.

        :param sort_by: a lambda expression to use to sort the values.
        :return: the sorted values.
        """
        return sorted(self._data.values(), key=sort_by)

    def _set(self, key: str, value: T):
        """
        Store a new (or updated) value in the store.  This will automatically rewrite
        the backing file.

        :param key: the key to store the data under.
        :param value: the data to store.
        """
        self._data[key] = value
        self.save()

    def _remove_by_key(self, key: str):
        """
        Remove the given key from our data store.

        :param key: the key of the value to remove.
        :return: True if the associated value was removed.
        """
        if self._get_by_key(key):
            del self._data[key]
            self.save()
            return True
        return False

    def _remove_by_value_attr(self, key_attr: str, attr: str, value: T) -> bool:
        """
        Remove a stored value by an attribute of its value.

        :param key_attr: the name of the attribute which is on the value and kee
        to the store.
        :param attr: the value attribute to search for.
        :param value: the value of the attribute to search for.
        :return: True if the associated value was removed.
        """
        val = self._get_by_value_attr(attr, value)
        if val:
            del self._data[val[key_attr]]
            self.save()
            return True
        return False

    def get_path(self):
        return self._real_path or self._primary_path

    # noinspection PyShadowingBuiltins
    def save_to(self, path: str, data: bytes, open: Callable[..., BufferedWriter] = open):
        """
        Save our data to the specified file.
        """
        with open(path, "wb") as f:
            f.write(data)
        self._real_path = path

    # noinspection PyShadowingBuiltins
    def save(self, open: Callable[..., BufferedWriter] = open):
        """
        Save our data to a file.

        The app directory is tried first. If that fails,
        then we write to the global config location.
        """
        data = json.dumps(self._data, indent=4).encode("utf-8")
        try:
            makedirs(self._primary_path)
            self.save_to(self._primary_path, data, open)
        except OSError:
            if not self._secondary_path:
                raise
            makedirs(self._secondary_path)
            self.save_to(self._secondary_path, data, open)

        if self._chmod and self._real_path is not None:
            os.chmod(self._real_path, 0o600)


class ServerDataDict(TypedDict):
    """
    Server data representation used internally in the ServerStore class.
    """

    name: str
    url: str
    api_key: NotRequired[str]
    insecure: NotRequired[bool]
    ca_cert: NotRequired[str]
    account_name: NotRequired[str]
    token: NotRequired[str]
    secret: NotRequired[str]


class ServerData:
    """
    Server data representation which the ServerStore class provides to external
    consumers.
    """

    def __init__(
        self,
        name: str,
        url: str,
        from_store: bool,
        api_key: Optional[str] = None,
        insecure: Optional[bool] = None,
        ca_data: Optional[str] = None,
        account_name: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        self.name = name
        self.url = url
        self.from_store = from_store
        self.api_key = api_key
        self.insecure = insecure
        self.ca_data = ca_data
        self.account_name = account_name
        self.token = token
        self.secret = secret


class ServerStore(DataStore[ServerDataDict]):
    """Defines a metadata store for server information.

    Servers consist of a user-supplied name, URL, and API key.
    Data is stored in the customary platform-specific location
    (typically a subdirectory of the user's home directory).
    """

    def __init__(self, base_dir: str = config_dirname()):
        super(ServerStore, self).__init__(join(base_dir, "servers.json"), chmod=True)

    def get_by_name(self, name: str):
        """
        Get the server information for the given nickname..

        :param name: the nickname of the server to get information for.
        """
        return self._get_by_key(name)

    def get_by_url(self, url: str):
        """
        Get the server information for the given URL..

        :param url: the Connect URL of the server to get information for.
        """
        return self._get_by_value_attr("url", url)

    def get_all_servers(self):
        """
        Returns a list of all known servers sorted by nickname.

        :return: the sorted list of known servers.
        """
        return self._get_sorted_values(lambda s: s["name"])

    def set(
        self,
        name: str,
        url: str,
        api_key: Optional[str] = None,
        insecure: Optional[bool] = False,
        ca_data: Optional[str] = None,
        account_name: Optional[str] = None,
        token: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        """
        Add (or update) information about a Connect server

        :param name: the nickname for the Connect server.
        :param url: the full URL for the Connect server.
        :param api_key: the API key to use to authenticate with the Connect server.
        :param insecure: a flag to disable TLS verification.
        :param ca_data: client side certificate data to use for TLS.
        :param account_name: shinyapps.io account name.
        :param token: shinyapps.io token.
        :param secret: shinyapps.io secret.
        """
        common_data: ServerDataDict = {
            "name": name,
            "url": url,
        }
        if api_key:
            target_data = dict(api_key=api_key, insecure=insecure, ca_cert=ca_data)
        elif account_name:
            target_data = dict(account_name=account_name, token=token, secret=secret)
        else:
            target_data = dict(token=token, secret=secret)

        self._set(name, {**common_data, **target_data})  # type: ignore

    def remove_by_name(self, name: str):
        """
        Remove the server information for the given nickname.

        :param name: the nickname of the server to remove.
        """
        return self._remove_by_key(name)

    def remove_by_url(self, url: str):
        """
        Remove the server information for the given URL..

        :param url: the Connect URL of the server to remove.
        """
        return self._remove_by_value_attr("name", "url", url)

    def resolve(self, name: Optional[str], url: Optional[str]) -> ServerData:
        """
        This function will resolve the given inputs into a set of server information.
        It assumes that either `name` or `url` is provided.

        If `name` is provided, the server information is looked up by its nickname
        and an error is produced if the nickname is not known.

        If `url` is provided, the server information is looked up by its URL.  If
        that is found, the stored information is returned.  Otherwise the corresponding
        arguments are returned as-is.

        If neither 'name' nor 'url' is provided and there is only one stored server,
        that information is returned.  In this case, the last value in the tuple returned
        notes this situation.  It is `False` in all other cases.

        :param name: the nickname to look for.
        :param url: the Connect server URL to look for.
        :return: the information needed to interact with the resolved server and whether
        it came from the store or the arguments.
        """
        if name:
            entry = self.get_by_name(name)
            if not entry:
                raise RSConnectException('The nickname, "%s", does not exist.' % name)
        elif url:
            entry = self.get_by_url(url)
        else:
            # if there is a single server, default to it
            if self.count() == 1:
                entry = self._get_first_value()
            else:
                entry = None

        if entry:
            return ServerData(
                name,
                entry["url"],
                True,
                insecure=entry.get("insecure"),
                ca_data=entry.get("ca_cert"),
                api_key=entry.get("api_key"),
                account_name=entry.get("account_name"),
                token=entry.get("token"),
                secret=entry.get("secret"),
            )
        else:
            return ServerData(
                name,
                url,
                False,
            )


def sha1(s: str):
    m = hashlib.sha1()
    b = s.encode("utf-8")
    m.update(b)
    return base64.urlsafe_b64encode(m.digest()).decode("utf-8").rstrip("=")


class AppMetadata(TypedDict):
    server_url: str
    filename: str
    app_url: str
    app_id: str
    app_guid: str
    title: str
    app_mode: str
    app_store_version: int


class AppStore(DataStore[AppMetadata]):
    """
    Defines a metadata store for information about where the app has been
    deployed.  Each instance of this store represents one application as
    represented by its entry point file.

    Metadata for an app consists of one entry for each server where it was
    deployed, containing:

    * Server URL
    * Entry point file name
    * App URL
    * App ID
    * App GUID
    * Title
    * App mode
    * App store file version

    The metadata file for an app is written in the same directory as the app's
    entry point file, if that directory is writable.  Otherwise, it is stored
    in the user's config directory under `applications/{hash}.json` where the
    hash is derived from the entry point file name. The file contains a version
    field, which is incremented when backwards-incompatible file format changes
    are made.
    """

    def __init__(self, app_file: str, version: int = 1):
        base_name = str(basename(app_file).rsplit(".", 1)[0]) + ".json"
        super(AppStore, self).__init__(
            join(dirname(app_file), "rsconnect-python", base_name),
            join(config_dirname(), "applications", sha1(abspath(app_file)) + ".json"),
        )
        self.version = version

    def get(self, server_url: str):
        """
        Get the metadata for the last app deployed to the given server.

        :param server_url: the Connect URL to get the metadata for.
        """
        return self._get_by_key(server_url)

    def get_all(self):
        """
        Get all metadata for this app.
        """
        return self._get_sorted_values(lambda entry: entry.get("server_url"))

    def set(
        self,
        server_url: str,
        filename: str,
        app_url: str,
        app_id: str,
        app_guid: str,
        title: str,
        app_mode: AppMode | str,
    ):
        """
        Remember the metadata for the app last deployed to the specified server.

        :param server_url: the URL of the server the app was deployed to.
        :param filename: the name of the deployed manifest file.
        :param app_url: the URL of the application itself.
        :param app_id: the ID of the application.
        :param app_guid: the UUID of the application.
        :param title: the title of the application.
        :param app_mode: the mode of the application.
        ."""
        self._set(
            server_url,
            {
                "server_url": server_url,
                "filename": filename,
                "app_url": app_url,
                "app_id": app_id,
                "app_guid": app_guid,
                "title": title,
                "app_mode": app_mode.name() if isinstance(app_mode, AppMode) else app_mode,
                "app_store_version": self.version,
            },
        )

    def resolve(self, server: str, app_id: Optional[str], app_mode: Optional[AppMode]):
        metadata = self.get(server)
        if metadata is None:
            logger.debug("No previous deployment to this server was found; this will be a new deployment.")
            return app_id, app_mode, self.version

        logger.debug("Found previous deployment data in %s" % self.get_path())

        if app_id is None:
            app_id = metadata.get("app_guid") or metadata.get("app_id")
            logger.debug("Using saved app ID: %s" % app_id)

        # app mode cannot be changed on redeployment
        app_mode = AppModes.get_by_name(metadata.get("app_mode"))

        app_store_version = metadata.get("app_store_version")
        return app_id, app_mode, app_store_version


DEFAULT_BUILD_DIR = join(os.getcwd(), "rsconnect-build")


# A trimmed version of TaskStatusV1 which doesn't contain `output` and `last` fields.
class TaskStatusV1Trimmed(TypedDict):
    id: str
    finished: bool
    code: int
    error: str
    result: TaskStatusResult | None


class ContentItemWithBuildState(ContentItemV1, TypedDict):
    rsconnect_build_status: str
    rsconnect_last_build_time: NotRequired[str]
    rsconnect_last_build_log: NotRequired[str | None]
    rsconnect_build_task_result: NotRequired[TaskStatusV1Trimmed]


class ContentBuildStoreData(TypedDict):
    rsconnect_build_running: bool
    rsconnect_content: dict[str, ContentItemWithBuildState]


# Python<=3.8 needs `Dict`. After dropping 3.8 support it can be changed to `dict`.
class ContentBuildStore(DataStore[Dict[str, object]]):
    """
    Defines a metadata store for information about content builds.

    The metadata directory for a content build is written in the directory specified by
    CONNECT_CONTENT_BUILD_DIR or the current working directory is none is supplied.

    A build-state file contains "tracked" content for a single connect server.
    The file is named using the normalized server URL for the target server.
    The structure is as follows:
    {
        "rsconnect_build_running": <bool>,
        "rsconnect_content": {
            "<content guid 1>": {
                "rsconnect_build_status": <models.BuildStatus>,
                ..., // various content metadata fields returned by the v1/content api
            },
            "<content guid 2>": {
                ...,
            }
        }
    }
    """

    _BUILD_ABORTED: bool = False

    def __init__(
        self,
        server: RSConnectServer,
        base_dir: str = os.getenv("CONNECT_CONTENT_BUILD_DIR", DEFAULT_BUILD_DIR),
    ):
        # This type declaration is a bit of a hack. It is needed because data model used
        # in this class doesn't quite match the one used in the superclass.
        self._data: ContentBuildStoreData
        self._server = server
        self._base_dir = os.path.abspath(base_dir)
        self._build_logs_dir = join(self._base_dir, "logs", _normalize_server_url(server.url))
        self._build_state_file = join(self._base_dir, "%s.json" % _normalize_server_url(server.url))
        super(ContentBuildStore, self).__init__(self._build_state_file, chmod=True)

    def aborted(self) -> bool:
        return ContentBuildStore._BUILD_ABORTED

    def get_build_logs_dir(self, guid: str) -> str:
        return join(self._build_logs_dir, guid)

    def ensure_logs_dir(self, guid: str) -> None:
        log_dir = self.get_build_logs_dir(guid)
        os.makedirs(log_dir, exist_ok=True)
        if self._chmod:
            os.chmod(log_dir, 0o700)

    def get_build_log(self, guid: str, task_id: Optional[str] = None) -> str | None:
        """
        Returns the path to the build log file. This method does not check
        whether the file exists if a task_id is provided.
        If task_id is not provided, we will return the latest log,
        specified by rsconnect_last_build_log.
        If no log file is found, returns None
        """
        log_dir = self.get_build_logs_dir(guid)
        if task_id:
            return join(log_dir, "%s.log" % task_id)
        else:
            content = self.get_content_item(guid)
            return content.get("rsconnect_last_build_log")

    def get_build_history(self, guid: str) -> list[dict[str, str]]:
        """
        Returns the build history for a given content guid.
        """
        log_dir = self.get_build_logs_dir(guid)
        log_files = glob.glob(join(log_dir, "*.log"))
        history: list[dict[str, str]] = []
        for f in log_files:
            task_id = basename(f).split(".log")[0]
            t = datetime.fromtimestamp(os.path.getctime(f), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")
            history.append({"time": t, "task_id": task_id})
        history.sort(key=lambda x: x["time"])
        return history

    def get_build_running(self) -> bool:
        return self._data.get("rsconnect_build_running")

    def set_build_running(self, is_running: bool, defer_save: bool = False) -> None:
        with self._lock:
            self._data["rsconnect_build_running"] = is_running
            if not defer_save:
                self.save()

    def add_content_item(self, content: ContentItemV1, defer_save: bool = False) -> None:
        """
        Add an item to the tracked content store
        """
        with self._lock:
            if "rsconnect_content" not in self._data:
                self._data["rsconnect_content"] = {}

            self._data["rsconnect_content"][content["guid"]] = dict(
                guid=content["guid"],
                bundle_id=content["bundle_id"],
                title=content["title"],
                name=content["name"],
                app_mode=content["app_mode"],
                content_url=content["content_url"],
                dashboard_url=content["dashboard_url"],
                created_time=content["created_time"],
                last_deployed_time=content["last_deployed_time"],
                owner_guid=content["owner_guid"],
            )
            if not defer_save:
                self.save()

    def get_content_item(self, guid: str) -> ContentItemWithBuildState:
        """
        Get a content item from the tracked content store by guid
        """
        item = self._data.get("rsconnect_content", {}).get(guid)
        if item is None:
            raise RSConnectException(f"Content item with guid {guid} not found.")
        return item

    def _cleanup_content_log_dir(self, guid: str) -> None:
        """
        Delete the local logs directory for a given content item.
        """
        logs_dir = self.get_build_logs_dir(guid)
        try:
            shutil.rmtree(logs_dir)
        except FileNotFoundError:
            pass

    def remove_content_item(self, guid: str, purge: bool = False, defer_save: bool = False) -> None:
        """
        Remove a content item from the tracked content from the state-file.
        If purge is True, cleanup the log files on the local filesystem.
        """
        if purge:
            self._cleanup_content_log_dir(guid)

        with self._lock:
            try:
                self._data.get("rsconnect_content", {}).pop(guid)
            except KeyError:
                pass
            if not defer_save:
                self.save()

    def set_content_item_build_status(self, guid: str, status: str, defer_save: bool = False) -> None:
        """
        Set the latest status for a content build
        """
        with self._lock:
            content = self.get_content_item(guid)
            content["rsconnect_build_status"] = str(status)
            if not defer_save:
                self.save()

    def update_content_item_last_build_time(self, guid: str, defer_save: bool = False) -> None:
        """
        Set the last_build_time for a content build
        """
        with self._lock:
            content = self.get_content_item(guid)
            content["rsconnect_last_build_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if not defer_save:
                self.save()

    def update_content_item_last_build_log(self, guid: str, log_file: str | None, defer_save: bool = False) -> None:
        """
        Set the last_build_log filepath for a content build
        """
        with self._lock:
            content = self.get_content_item(guid)
            content["rsconnect_last_build_log"] = log_file
            if not defer_save:
                self.save()

    def set_content_item_last_build_task_result(self, guid: str, task: TaskStatusV1, defer_save: bool = False) -> None:
        """
        Set the latest task_result for a content build
        """
        with self._lock:
            content = self.get_content_item(guid)
            # status contains the log lines for the build. We have already recorded these in the
            # log file on disk so we can remove them from the task result before storing it
            # to reduce the data stored in our state-file.
            task_copy: TaskStatusV1Trimmed = {
                "id": task["id"],
                "finished": task["finished"],
                "code": task["code"],
                "error": task["error"],
                "result": task["result"],
            }
            content["rsconnect_build_task_result"] = task_copy
            if not defer_save:
                self.save()

    def get_content_items(self, status: Optional[str] = None) -> list[ContentItemWithBuildState]:
        """
        Get all the content items that are tracked for build in the state-file.
        :param status: Filter results by build status
        :return: A list of content items
        """
        all_content = list(self._data.get("rsconnect_content", {}).values())
        if status:
            return [item for item in all_content if item["rsconnect_build_status"] == status]
        else:
            return all_content
