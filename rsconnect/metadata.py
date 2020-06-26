"""
Metadata management objects and utility functions
"""

import base64
import hashlib
import json
import os
import sys
from os.path import abspath, basename, dirname, exists, join

from rsconnect import api
from rsconnect.log import logger
from rsconnect.models import AppMode, AppModes


def config_dirname(platform=sys.platform, env=os.environ):
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
def makedirs(filepath):
    """Create the parent directories of filepath.

    `filepath` itself is not created.
    It is not an error if the directories already exist.
    """
    try:
        os.makedirs(dirname(filepath))
    except OSError:
        pass


class DataStore(object):
    """
    Defines a base class for a persistent store.  The store supports a primary location and
    an optional secondary one.
    """

    def __init__(self, primary_path, secondary_path=None, chmod=False):
        self._primary_path = primary_path
        self._secondary_path = secondary_path
        self._chmod = chmod
        self._data = {}
        self._real_path = None

        self.load()

    def count(self):
        """
        Return the number of items in the data store.

        :return: the number of items currently in the data store.
        """
        return len(self._data)

    def _load_from(self, path):
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

    def _get_by_key(self, key):
        """
        Return a stored value by its key.

        :param key: the key for the value to return.
        :return: the associated value or None if there isn't one.
        """
        return self._data.get(key)

    def _get_by_value_attr(self, attr, value):
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

    def _get_first_value(self):
        """
        A convenience function that returns the (arbitrary) first value in the
        store.  This is most useful when the store contains one, and only one,
        value

        :return: the first value in the store.
        """
        return list(self._data.values())[0]

    def _get_sorted_values(self, sort_by):
        """
        Return all the values in the store sorted by the given lambda expression.

        :param sort_by: a lambda expression to use to sort the values..
        :return: the sorted values.
        """
        return sorted(self._data.values(), key=sort_by)

    def _set(self, key, value):
        """
        Store a new (or updated) value in the store.  This will automatically rewrite
        the backing file.

        :param key: the key to store the data under.
        :param value: the data to store.
        """
        self._data[key] = value
        self.save()

    def _remove_by_key(self, key):
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

    def _remove_by_value_attr(self, key_attr, attr, value):
        """
        Remove a stored value by an attribute of its value.

        :param key_attr: the name of the attribute which is on the value and kee
        to the store.
        :param attr: the value attribute to search for.
        :param value: the value of the attribute to search for.
        :return: True if the associated value was removed.
        """
        value = self._get_by_value_attr(attr, value)
        if value:
            del self._data[value[key_attr]]
            self.save()
            return True
        return False

    def get_path(self):
        return self._real_path or self._primary_path

    # noinspection PyShadowingBuiltins
    def save_to(self, path, data, open=open):
        """
        Save our data to the specified file.
        """
        with open(path, "wb") as f:
            f.write(data)
        self._real_path = path

    # noinspection PyShadowingBuiltins
    def save(self, open=open):
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

        if self._chmod:
            os.chmod(self._real_path, 0o600)


class ServerStore(DataStore):
    """Defines a metadata store for server information.

    Servers consist of a user-supplied name, URL, and API key.
    Data is stored in the customary platform-specific location
    (typically a subdirectory of the user's home directory).
    """

    def __init__(self, base_dir=config_dirname()):
        super(ServerStore, self).__init__(join(base_dir, "servers.json"), chmod=True)

    def get_by_name(self, name):
        """
        Get the server information for the given nickname..

        :param name: the nickname of the server to get information for.
        """
        return self._get_by_key(name)

    def get_by_url(self, url):
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

    def set(self, name, url, api_key, insecure=False, ca_data=None):
        """
        Add (or update) information about a Connect server

        :param name: the nickname for the Connect server.
        :param url: the full URL for the Connect server.
        :param api_key: the API key to use to authenticate with the Connect server.
        :param insecure: a flag to disable TLS verification.
        :param ca_data: client side certificate data to use for TLS.
        """
        self._set(
            name, dict(name=name, url=url, api_key=api_key, insecure=insecure, ca_cert=ca_data,),
        )

    def remove_by_name(self, name):
        """
        Remove the server information for the given nickname.

        :param name: the nickname of the server to remove.
        """
        return self._remove_by_key(name)

    def remove_by_url(self, url):
        """
        Remove the server information for the given URL..

        :param url: the Connect URL of the server to remove.
        """
        return self._remove_by_value_attr("name", "url", url)

    def resolve(self, name, url, api_key, insecure, ca_data):
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
        :param api_key: the API key provided on the command line.
        :param insecure: the insecure flag provided on the command line.
        :param ca_data: the CA certification data provided on the command line.
        :return: the information needed to interact with the resolved server and whether
        it came from the store or the arguments.
        """
        if name:
            entry = self.get_by_name(name)
            if not entry:
                raise api.RSConnectException('The nickname, "%s", does not exist.' % name)
        elif url:
            entry = self.get_by_url(url)
        else:
            # if there is a single server, default to it
            if self.count() == 1:
                entry = self._get_first_value()
            else:
                entry = None

        if entry:
            return (
                entry["url"],
                entry["api_key"],
                entry["insecure"],
                entry["ca_cert"],
                True,
            )
        else:
            return url, api_key, insecure, ca_data, False


def sha1(s):
    m = hashlib.sha1()
    if hasattr(s, "encode"):
        s = s.encode("utf-8")
    m.update(s)
    return base64.urlsafe_b64encode(m.digest()).decode("utf-8").rstrip("=")


class AppStore(DataStore):
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

    The metadata file for an app is written in the same directory as the app's
    entry point file, if that directory is writable.  Otherwise, it is stored
    in the user's config directory under `applications/{hash}.json` where the
    hash is derived from the entry point file name.
    """

    def __init__(self, app_file):
        base_name = str(basename(app_file).rsplit(".", 1)[0]) + ".json"
        super(AppStore, self).__init__(
            join(dirname(app_file), "rsconnect-python", base_name),
            join(config_dirname(), "applications", sha1(abspath(app_file)) + ".json"),
        )

    def get(self, server_url):
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

    def set(self, server_url, filename, app_url, app_id, app_guid, title, app_mode):
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
            dict(
                server_url=server_url,
                filename=filename,
                app_url=app_url,
                app_id=app_id,
                app_guid=app_guid,
                title=title,
                app_mode=app_mode.name() if isinstance(app_mode, AppMode) else app_mode,
            ),
        )

    def resolve(self, server, app_id, app_mode):
        metadata = self.get(server)
        if metadata is None:
            logger.debug("No previous deployment to this server was found; this will be a new deployment.")
            return app_id, app_mode

        logger.debug("Found previous deployment data in %s" % self.get_path())

        if app_id is None:
            app_id = metadata.get("app_guid") or metadata.get("app_id")
            logger.debug("Using saved app ID: %s" % app_id)

        # app mode cannot be changed on redeployment
        app_mode = AppModes.get_by_name(metadata.get("app_mode"))
        return app_id, app_mode
