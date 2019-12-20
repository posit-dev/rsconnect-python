
import base64
import hashlib
import json
import logging
import os
import sys
from os.path import abspath, basename, dirname, exists, join

logger = logging.getLogger('rsconnect')


def config_dirname(platform=sys.platform, env=os.environ):
    """Get the user's configuration directory path for this platform."""
    home = env.get('HOME', '~')
    base_dir = home

    if platform.startswith('linux'):
        base_dir = env.get('XDG_CONFIG_HOME', home)
    elif platform == 'darwin':
        base_dir = join(home, 'Library', 'Application Support')
    elif platform == 'win32':
        # noinspection SpellCheckingInspection
        base_dir = env.get('APPDATA', home)

    if base_dir == home:
        return join(base_dir, '.rsconnect-python')
    else:
        return join(base_dir, 'rsconnect-python')


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


class ServerStore(object):
    """Defines a metadata store for server information.

    Servers consist of a user-supplied name, URL, and API key.
    Data is stored in the customary platform-specific location
    (typically a subdirectory of the user's home directory).
    """
    def __init__(self, base_dir=config_dirname()):
        self.path = join(base_dir, 'servers.json')
        self.servers = {}

    def get_path(self):
        return self.path

    def add(self, name, url, api_key, insecure=False, ca_cert=None):
        """Add a new server"""
        self.servers[name] = dict(
            name=name,
            url=url,
            api_key=api_key,
            insecure=insecure,
            ca_cert=ca_cert,
        )

    def remove(self, name_or_url):
        """Remove a server by name or URL"""
        if name_or_url in self.servers:
            del self.servers[name_or_url]
            return True
        else:
            for name, server in self.servers.items():
                if server['url'] == name_or_url:
                    del self.servers[name]
                    return True
            return False

    def get(self, name_or_url):
        if name_or_url in self.servers:
            return self.servers[name_or_url]
        else:
            for name, server in self.servers.items():
                if server['url'] == name_or_url:
                    return self.servers[name]

    def list(self):
        return sorted(self.servers.values(), key=lambda s: s['name'])

    def resolve(self, name_or_url, api_key, insecure, ca_cert):
        if name_or_url:
            entry = self.get(name_or_url)
        else:
            # if there is a single server, default to it
            if len(self.servers) == 1:
                entry = list(self.servers.values())[0]
            else:
                entry = None

        if entry:
            return entry['url'], entry['api_key'], entry['insecure'], entry['ca_cert']
        else:
            return name_or_url, api_key, insecure, ca_cert

    def load(self):
        """Load the server list.

        If the file does not yet exist, no data is loaded,
        but this is not considered an error.
        """
        if exists(self.path):
            with open(self.path, 'rb') as f:
                self.servers = json.loads(f.read().decode('utf-8'))

    def save(self):
        """Save the server list.

        An error is raised if the list cannot be saved.
        On Mac/Linux, group and world permissions on the
        file are cleared since it contains user credentials.
        """
        data = json.dumps(self.servers, indent=4).encode('utf-8')
        makedirs(self.path)

        with open(self.path, 'wb') as f:
            f.write(data)
        os.chmod(self.path, 0o600)


def sha1(s):
    m = hashlib.sha1()
    if hasattr(s, 'encode'):
        s = s.encode('utf-8')
    m.update(s)
    return base64.urlsafe_b64encode(m.digest()).decode('utf-8').rstrip('=')


class AppStore(object):
    """Defines a metadata store for app information.

    Metadata for an app consists of one entry for each server
    where the app was deployed, containing:
    * Server URL
    * App ID
    * App GUID
    * Title

    The metadata file for an app is written in the same directory
    as the app's entry point file, if that directory is writable.
    Otherwise, it is stored in the user's config directory
    under applications/{hash}.json.
    """
    def __init__(self, app_file):
        base_name = str(basename(app_file).rsplit('.', 1)[0]) + '.json'
        self.app_path = join(dirname(app_file), 'rsconnect-python', base_name)
        self.global_path = join(config_dirname(), 'applications', sha1(abspath(app_file)) + '.json')
        self.data = {}
        self.filepath = None

    def set(self, server_url, filename, app_url, app_id, app_guid, title, app_mode):
        """Set the metadata for this app on a specific server."""
        self.data[server_url] = dict(
            server_url=server_url,
            filename=filename,
            app_url=app_url,
            app_id=app_id,
            app_guid=app_guid,
            title=title,
            app_mode=app_mode,
        )

    def get(self, server_url):
        """Get the metadata for this app on a specific server."""
        return self.data.get(server_url)

    def get_all(self):
        """Get all metadata for this app."""
        return sorted(self.data.values(), key=lambda entry: entry.get('server_url'))

    def load_from(self, path):
        """Load the data from the specified path.

        Returns True if the data was successfully loaded.
        """
        if exists(path):
            with open(path, 'rb') as f:
                self.data = json.loads(f.read().decode('utf-8'))
                self.filepath = path
                return True
        return False

    def load(self):
        """Load the data from file.

        The app directory is checked first,
        then the global config location.
        """
        if not self.load_from(self.app_path):
            self.load_from(self.global_path)

    # noinspection PyShadowingBuiltins
    def save_to(self, path, open=open):
        """Save the data to the specified file."""
        data = json.dumps(self.data, indent=4)
        with open(path, 'wb') as f:
            f.write(data.encode('utf-8'))
            self.filepath = path

    # noinspection PyShadowingBuiltins
    def save(self, open=open):
        """Save the data to file.

        The app directory is tried first. If that fails,
        then we write to the global config location.
        """
        try:
            makedirs(self.app_path)
            self.save_to(self.app_path, open)
        except OSError:
            makedirs(self.global_path)
            self.save_to(self.global_path, open)

    def get_path(self):
        return self.filepath

    def resolve(self, server, app_id, title, app_mode):
        metadata = self.get(server)
        if metadata is None:
            logger.info('No previous deployment to this server was found; this will be a new deployment.')
            return app_id, title, app_mode

        logger.debug('Found previous deployment data in %s' % self.get_path())

        if app_id is None:
            app_id = metadata.get('app_guid') or metadata.get('app_id')
            logger.debug('Using saved app ID: %s' % app_id)

        if title is None:
            title = metadata.get('title')
            logger.debug('Using saved title: "%s"' % title)

        # app mode cannot be changed on redeployment
        app_mode = metadata.get('app_mode')
        return app_id, title, app_mode
