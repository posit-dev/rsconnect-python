"""
This provides our "database" handling.  It defines our object models along
with appropriate storage/retrieval actions.
"""
import datetime
import io
import json
import sys
import tarfile
import uuid
from enum import Enum
from json import JSONDecodeError
from os import environ
from os.path import isfile
from typing import Union

def timestamp():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def default_url():
    return "http://127.0.0.1:3939"

class DBObject(object):
    excludes = [] # remove fields from the json response
    show = ["id"] # show these fields in the generated HTML
    generated_id = {}
    instances = {}

    @classmethod
    def _get_all_ids(cls):
        name = cls.__name__
        if name in cls.instances:
            return cls.instances[name].keys()
        return []

    @classmethod
    def _next_id(cls):
        name = cls.__name__
        if name not in cls.generated_id:
            cls.generated_id[name] = range(1, sys.maxsize ** 10).__iter__()
        new_id = next(cls.generated_id[name])
        existing_ids = cls._get_all_ids()
        while new_id in existing_ids:
            existing_ids = cls._get_all_ids()
        return new_id

    @classmethod
    def get_object(cls, db_id: Union[int, str]):
        name = cls.__name__
        if name in cls.instances:
            if db_id in cls.instances[name]:
                return cls.instances[name][db_id]
            elif isinstance(db_id, str): # if guid was provided, find by guid instead of id
                return next(filter(lambda x: x['guid'] == db_id, cls.instances[name].values()), None)
        return None

    @classmethod
    def get_all_objects(cls):
        name = cls.__name__
        if name in cls.instances:
            return cls.instances[name].values()
        return []

    @classmethod
    def _save(cls, instance):
        name = cls.__name__
        if name not in cls.instances:
            cls.instances[name] = {}
        cls.instances[name][instance.id] = instance

    @classmethod
    def get_table_headers(cls):
        return "<tr><th>%s</th></tr>" % "</th><th>".join(cls.show)

    def __init__(self, id: str = None, needs_uuid: bool = False):
        self.id = id if id else self._next_id()
        if needs_uuid:
            self.guid = str(uuid.uuid4())
        self._save(self)

    def update_from(self, data: dict):
        self.__dict__.update(data)

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    def get_table_row(self):
        items = [str(self.__getattribute__(item)) for item in self.show]
        return "<tr><td>%s</td></tr>" % "</td><td>".join(items)


class AppMode(Enum):
    STATIC = 4
    JUPYTER_STATIC = 7

    @staticmethod
    def value_of(name: str):
        name = name.upper().replace("-", "_")
        return AppMode[name].value if name in AppMode else None


class Application(DBObject):
    show = ["id", "guid", "name", "title", "url"]

    @classmethod
    def get_app_by_name(cls, name: str):
        for app in cls.get_all_objects():
            if name == app.name:
                return app
        return None

    def __init__(self, **kwargs):
        super(Application, self).__init__(needs_uuid=True)
        self._base_url = kwargs.get('base_url', default_url())
        self.name = kwargs.get('name')
        self.title = kwargs.get('title')
        self.url = "{0}content/{1}".format(self._base_url, self.id)
        self.owner_username = kwargs.get('owner_username')
        self.owner_first_name = kwargs.get('owner_first_name')
        self.owner_last_name = kwargs.get('owner_last_name')
        self.owner_email = kwargs.get('owner_email')
        self.owner_locked = kwargs.get('owner_locked')
        self.bundle_id = None
        self.needs_config = True
        self.access_type = None
        self.description = ""
        self.app_mode = None
        self.created_time = timestamp()
        self.last_deployed_time = None

    def bundle_deployed(self, bundle, new_app_mode):
        self.bundle_id = bundle.id
        self.app_mode = new_app_mode
        self.last_deployed_time = timestamp()

    def get_bundle(self):
        if self.bundle_id is not None:
            return Bundle.get_object(self.bundle_id)
        return None


class User(DBObject):
    show = ["id", "guid", "username", "first_name", "last_name"]

    @classmethod
    def get_user_by_api_key(cls, key: str):
        if key in api_keys:
            return User.get_object(api_keys[key])
        return None

    def __init__(self, **kwargs):
        super(User, self).__init__(needs_uuid=True)
        self.username = kwargs.get('username')
        self.first_name = kwargs.get('first_name')
        self.last_name = kwargs.get('last_name')
        self.email = kwargs.get('email')
        self.user_role = kwargs.get('user_role')
        self.password = kwargs.get('password')
        self.confirmed = kwargs.get('confirmed')
        self.locked = kwargs.get('locked')
        self.created_time = kwargs.get('created_time')
        self.updated_time = kwargs.get('updated_time')
        self.active_time = kwargs.get('active_time')
        self.privileges = kwargs.get('privileges')


class Bundle(DBObject):
    excludes = ["tarball"]
    show = ["id", "app_id"]

    def __init__(self, **kwargs):
        super(Bundle, self).__init__()
        self.app_id = kwargs.get('app_id')
        self.created_time = timestamp()
        self.updated_time = self.created_time
        self.tarball = kwargs.get('tarball')

    def read_bundle_file(self, file_name):
        raw_bytes = io.BytesIO(self.tarball)
        with tarfile.open("r:gz", fileobj=raw_bytes) as tar:
            return tar.extractfile(file_name).read()

    def get_manifest(self):
        manifest_data = self.read_bundle_file("manifest.json").decode("utf-8")
        return json.loads(manifest_data)

    def get_rendered_content(self):
        manifest = self.get_manifest()
        meta = manifest["metadata"]
        # noinspection SpellCheckingInspection
        file_name = meta.get("primary_html") or meta.get("entrypoint")
        return self.read_bundle_file(file_name).decode("utf-8")


class Task(DBObject):
    def __init__(self, **kwargs):
        super(Task, self).__init__()
        self.user_id = kwargs.get('user_id', 0)
        self.finished = kwargs.get('finished', True)
        self.code = kwargs.get('code', 0)
        self.error = kwargs.get('error', "")
        self.last_status = kwargs.get('last_status', 0)
        self.status = kwargs.get('status', ["Building static content", "Deploying static content"])


class Content(DBObject):
    show = ["guid", "name", "app_mode", "r_version", "py_version", "quarto_version"]

    def __init__(self, **kwargs):
        super(Content, self).__init__(needs_uuid=True)
        self.name = kwargs.get('name')
        self.title = self.name + "+ title"
        self.description = self.name + "+ description"
        self.bundle_id = kwargs.get('bundle_id')
        self.app_mode = kwargs.get('app_mode')
        self.content_category = kwargs.get('content_category')
        self.content_url = "%scontent/%s/" % (base_url(), self.guid)
        self.dashboard_url = "%sconnect/#/apps/{1}" % (base_url(), self.guid)
        self.created_time = timestamp()
        self.last_deployed_time = timestamp()
        self.r_version = self.get('r_version', '4.1.1')
        self.py_version = self.get('py_version', '3.9.9')
        self.quarto_version = self.get('quarto_version', '0.2.318')
        self.owner_guid = kwargs.get('owner_guid')
        self.access_type = kwargs.get('access_type', 'acl')
        self.connection_timeout = kwargs.get('connection_timeout')
        self.read_timeout = kwargs.get('read_timeout')
        self.init_timeout = kwargs.get('init_timeout')
        self.idle_timeout = kwargs.get('idle_timeout')
        self.max_processes = kwargs.get('max_processes')
        self.min_processes = kwargs.get('min_processes')
        self.max_conns_per_process = kwargs.get('max_conns_per_process')
        self.load_factor = kwargs.get('load_factor')
        self.parameterized = kwargs.get('parameterized', False)
        self.cluster_name = kwargs.get('cluster_name')
        self.image_name = kwargs.get('image_name')
        self.run_as = kwargs.get('run_as')
        self.run_as_current_user = kwargs.get('run_as_current_user', False)
        self.app_role = kwargs.get('app_role', "owner")


def _apply_pre_fetch_data(data: dict):
    for key, value in data.items():
        if key in tag_map:
            if isinstance(value, dict):
                value = [value]
            cls = tag_map[key]
            for item in value:
                new_object = cls(**item)
                if cls == User and "api_key" in item:
                    api_keys[item["api_key"]] = new_object.id
        else:
            print("WARNING: Unknown pre-fetch data type: %s" % key)


def _pre_fetch_data():
    file_name = environ.get("PRE_FETCH_FILE")
    if file_name is not None and len(file_name) > 0:
        if isfile(file_name):
            try:
                with open(file_name) as fd:
                    _apply_pre_fetch_data(json.load(fd))
            except JSONDecodeError:
                print("WARNING: Unable to read pre-fetch file %s as JSON." % file_name)
        else:
            print("WARNING: Pre-fetch file %s does not exist." % file_name)


def _format_section(sections, name, rows):
    table = "<table>\n%s</table>\n" % "\n".join(rows)
    sections.append("<h2>%ss</h2>\n%s" % (name, table))


def get_data_dump():
    ts = ' style="border-style: solid; border-width: 1px"'
    sections = []
    for cls in (Application, Content, Bundle, Task, User):
        rows = [item.get_table_row() for item in cls.get_all_objects()]
        rows.insert(0, cls.get_table_headers())
        _format_section(sections, cls.__name__, rows)
    rows = ["<tr><th>API Key</th><th>User ID</th></tr>"]
    for key, value in api_keys.items():
        rows.append("<tr><td>%s</td><td>%s</td></tr>" % (key, value))
    _format_section(sections, "API Key", rows)
    text = "\n".join(sections)
    text = text.replace("<th>", "<th%s>" % ts)
    text = text.replace("<td>", "<td%s>" % ts)
    return text


default_server_settings = {
    "version": "",
    "build": "",
    "about": "",
    "authentication": {
        "handles_credentials": True,
        "handles_login": True,
        "external_user_data": False,
        "external_user_search": False,
        "groups_enabled": True,
        "external_group_data": False,
        "unique_usernames": True,
        "name_editable_by": "adminandself",
        "email_editable_by": "adminandself",
        "username_editable_by": "adminandself",
        "role_editable_by": "adminandself",
        "challenge_response_enabled": False,
        "name": "RStudio Connect",
        "notice": "",
    },
    "license": {
        "ts": 1581001093714,
        "status": "activated",
        "expiration": 1835136000000,
        "days-left": 2942,
        "edition": "",
        "cores": "0",
        "connections": "0",
        "has-key": True,
        "has-trial": False,
        "type": "local",
        "shiny-users": "5",
        "users": "15",
        "user-activity-days": "365",
        "allow-apis": "1",
    },
    "google_analytics_tracking_id": "",
    "viewer_kiosk": False,
    "mail_all": False,
    "mail_configured": True,
    "recent_visibility": "viewer",
    "public_warning": "",
    "logged_in_warning": "",
    "logout_url": "__logout__",
    "metrics_rrd_enabled": True,
    "metrics_instrumentation": True,
    "customized_landing": False,
    "self_registration": True,
    "prohibited_usernames": [
        "connect",
        "apps",
        "users",
        "groups",
        "setpassword",
        "user-completion",
        "confirm",
        "recent",
        "reports",
        "plots",
        "unpublished",
        "settings",
        "metrics",
        "tokens",
        "help",
        "login",
        "welcome",
        "register",
        "resetpassword",
        "content",
    ],
    "username_validator": "default",
    "viewers_can_only_see_themselves": False,
    "http_warning": False,
    "queue_ui": True,
    "v1_dev_api": False,
    "license_expiration_ui_warning": True,
    "runtimes": ["R", "Python"],
    "dashboard_build_guid_based_routes": False,
    "dashboard_fail_id_based_routes": False,
    "expanded_view_ui": True,
    "default_content_list_view": "compact",
    "maximum_app_image_size": 10000000,
    "server_settings_toggler": True,
    "vue_logs_panel": True,
    "vue_web_sudo_login": False,
    "vue_content_list": False,
    "git_enabled": True,
    "git_available": True,
    "documentation_dashboard": False,
}

tag_map = {
    "apps": Application,
    "users": User,
    "bundles": Bundle,
    "tasks": Task,
    "content": Content
}

api_keys = {}

# Handle any pre-fetching we should do.
_pre_fetch_data()
