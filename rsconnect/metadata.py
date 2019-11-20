
import json
import os
import sys
from os.path import dirname, exists, join


def config_dirname(platform=sys.platform, env=os.environ):
    """Get the user's configuration directory path for this platform."""
    home = env.get('HOME', '~')

    if platform.startswith('linux'):
        base_dir = env.get('XDG_CONFIG_HOME', home)
    elif platform == 'darwin':
        base_dir = join(home, 'Library', 'Application Support')
    elif platform == 'win32':
        base_dir = env.get('APPDATA', home)

    if base_dir == home:
        return join(base_dir, '.rsconnect-python')
    else:
        return join(base_dir, 'rsconnect-python')


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
    def __init__(self):
        self.path = join(config_dirname(), 'servers.json')
        self.servers = {}

    def add(self, name, url, api_key, insecure, ca_cert):
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
            for name, server in self.servers:
                if server['url'] == name_or_url:
                    del self.servers[name]
                    return True
            return False 

    def get(self, name_or_url):
        if name_or_url in self.servers:
            return self.servers[name_or_url]
        else:
            for name, server in self.servers:
                if server['url'] == name_or_url:
                    return self.servers[name]

    def resolve(self, name_or_url, api_key, insecure, ca_cert):
        entry = self.get(name_or_url)
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


class AppStore(object):
    """Defines a metadata store for server information.

    Metadata for an app consists of one entry for each server
    where the app was deployed, containing:
    * Server URL
    * App ID
    * App GUID
    * Title

    The metadata file for an app is written in the same directory
    as the app's entrypoint file, if that directory is writable.
    Otherwise, it is stored in the user's config directory
    under applications/{app_guid}.json.
    """
    def __init__(self, app_file, app_guid):
        self.app_path = join(dirname(app_file), '.rsconnect-python.json')
        self.global_path = join(config_dirname(), 'applications', app_guid + '.json')
        self.data = dict(
            server_url=None,
            app_id=None,
            app_guid=None,
            title=None,
        )

    def set(self, server_url, app_id, app_guid, title):
        """Set the metadata for this app."""
        self.data = dict(
            server_url=server_url,
            app_id=app_id,
            app_guid=app_guid,
            title=title,
        )

    def load_from(self, path):
        """Load the data from the specified path.

        Returns True if the data was successfully loaded.
        """
        if exists(path):
            with open(path, 'rb') as f:
                self.data = json.loads(f.read())
                return True
        return False

    def load(self):
        """Load the data from file.

        The app directory is checked first, 
        then the global config location.
        """
        if not self.load_from(self.app_path):
            self.load_from(self.global_path)

    def save_to(self, path):
        """Save the data to the specified file."""
        data = json.dumps(self.data, indent=4)
        with open(path, 'wb') as f:
            f.write(data)

    def save(self):
        """Save the data to file.

        The app directory is tried first. If that fails,
        then we write to the global config location.
        """
        try:
            self.save_to(self.app_path)
        except OSError:
            makedirs(self.global_path)
            self.save_to(self.global_path)
