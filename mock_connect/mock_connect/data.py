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
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


class DBObject(object):
    generated_id = {}
    instances = {}
    attrs = ['id']
    show = ['id']

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
            cls.generated_id[name] = range(1, sys.maxsize**10).__iter__()
        new_id = next(cls.generated_id[name])
        existing_ids = cls._get_all_ids()
        while new_id in existing_ids:
            existing_ids = cls._get_all_ids()
        return new_id

    @classmethod
    def get_object(cls, db_id: Union[int, str]):
        name = cls.__name__
        if name in cls.instances and db_id in cls.instances[name]:
            return cls.instances[name][db_id]
        return None

    @classmethod
    def get_all_objects(cls):
        name = cls.__name__
        if name in cls.instances:
            return cls.instances[name].values()
        return []

    @classmethod
    def create_from(cls, data: dict):
        if 'id' in data:
            result = cls.__new__(cls)
            if 'guid' in cls.attrs and 'guid' not in data:
                result.guid = str(uuid.uuid4())
        else:
            result = cls()

        result.update_from(data)

        if 'id' in data:
            cls._save(result)

        return result

    @classmethod
    def _save(cls, instance):
        name = cls.__name__
        if name not in cls.instances:
            cls.instances[name] = {}
        cls.instances[name][instance.id] = instance
        if 'guid' in instance.attrs:
            cls.instances[name][instance.guid] = instance

    @classmethod
    def get_table_headers(cls):
        return '<tr><th>%s</th></tr>' % '</th><th>'.join(cls.show)

    def __init__(self, needs_uuid: bool = False):
        self.id = self._next_id()

        if needs_uuid:
            self.guid = str(uuid.uuid4())

        self._save(self)

    def update_from(self, data: dict):
        for attr in self.attrs:
            if attr in data:
                self.__setattr__(attr, data[attr])

    def to_dict(self) -> dict:
        result = {}
        for attr in self.attrs:
            result[attr] = self.__getattribute__(attr)
        return result

    def get_table_row(self):
        items = [str(self.__getattribute__(item)) for item in self.show]
        return '<tr><td>%s</td></tr>' % '</td><td>'.join(items)


class AppMode(Enum):
    STATIC = 4
    JUPYTER_STATIC = 7

    @staticmethod
    def value_of(name: str):
        name = name.upper().replace('-', '_')
        return AppMode[name].value if name in AppMode else None


class Application(DBObject):
    attrs = ['id', 'guid', 'name', 'url', 'owner_username', 'owner_first_name', 'owner_last_name', 'owner_email',
             'owner_locked', 'bundle_id', 'needs_config', 'access_type', 'description', 'app_mode', 'created_time',
             'title', 'last_deployed_time']
    show = ['id', 'name', 'title', 'url']

    @classmethod
    def get_app_by_name(cls, name: str):
        for app in cls.get_all_objects():
            if name == app.name:
                return app
        return None

    def __init__(self, name, title, url, user):
        super(Application, self).__init__(needs_uuid=True)
        self.name = name
        self.title = title
        self.url = '{0}content/{1}'.format(url, self.id)
        self.owner_username = user.username
        self.owner_first_name = user.first_name
        self.owner_last_name = user.last_name
        self.owner_email = user.email
        self.owner_locked = user.locked
        self.bundle_id = None
        self.needs_config = True
        self.access_type = None
        self.description = ''
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
    attrs = ['id', 'guid', 'username', 'first_name', 'last_name', 'email', 'user_role', 'password', 'confirmed',
             'locked', 'created_time', 'updated_time', 'active_time', 'privileges']
    show = ['id', 'username', 'first_name', 'last_name']

    @classmethod
    def get_user_by_api_key(cls, key: str):
        if key in api_keys:
            return User.get_object(api_keys[key])
        return None

    def __init__(self):
        super(User, self).__init__(needs_uuid=True)


class Bundle(DBObject):
    attrs = ['id', 'app_id', 'created_time', 'updated_time']
    show = ['id', 'app_id']

    def __init__(self, app: Application, tarball):
        super(Bundle, self).__init__()
        self.app_id = app.id
        self.created_time = timestamp()
        self.updated_time = self.created_time
        self.tarball = tarball

    def read_bundle_file(self, file_name):
        raw_bytes = io.BytesIO(self.tarball)
        with tarfile.open('r:gz', fileobj=raw_bytes) as tar:
            return tar.extractfile(file_name).read()

    def get_manifest(self):
        manifest_data = self.read_bundle_file('manifest.json').decode('utf-8')
        return json.loads(manifest_data)

    def get_rendered_content(self):
        manifest = self.get_manifest()
        meta = manifest['metadata']
        # noinspection SpellCheckingInspection
        file_name = meta.get('primary_html') or meta.get('entrypoint')
        return self.read_bundle_file(file_name).decode('utf-8')


class Task(DBObject):
    attrs = ['id', 'user_id', 'finished', 'code', 'error', 'last_status', 'status']

    def __init__(self):
        super(Task, self).__init__()
        self.user_id = 0
        self.finished = True
        self.code = 0
        self.error = ''
        self.last_status = 0
        self.status = ['Building static content', 'Deploying static content']


def _apply_pre_fetch_data(data: dict):
    for key, value in data.items():
        if key in tag_map:
            if isinstance(value, dict):
                value = [value]
            cls = tag_map[key]
            for item in value:
                new_object = cls.create_from(item)
                if cls == User and 'api_key' in item:
                    api_keys[item['api_key']] = new_object.id
        else:
            print('WARNING: Unknown pre-fetch data type: %s' % key)


def _pre_fetch_data():
    file_name = environ.get('PRE_FETCH_FILE')
    if file_name is not None and len(file_name) > 0:
        if isfile(file_name):
            try:
                with open(file_name) as fd:
                    _apply_pre_fetch_data(json.load(fd))
            except JSONDecodeError:
                print('WARNING: Unable to read pre-fetch file %s as JSON.' % file_name)
        else:
            print('WARNING: Pre-fetch file %s does not exist.' % file_name)


def _format_section(sections, name, rows):
    table = '<table>\n%s</table>\n' % '\n'.join(rows)
    sections.append('<h2>%ss</h2>\n%s' % (name, table))


def get_data_dump():
    ts = ' style="border-style: solid; border-width: 1px"'
    sections = []
    for cls in (Application, User, Bundle, Task):
        rows = [item.get_table_row() for item in cls.get_all_objects()]
        rows.insert(0, cls.get_table_headers())
        _format_section(sections, cls.__name__, rows)
    rows = ['<tr><th>API Key</th><th>User ID</th></tr>']
    for key, value in api_keys.items():
        rows.append('<tr><td>%s</td><td>%s</td</tr' % (key, value))
    _format_section(sections, 'API Key', rows)
    text = '\n'.join(sections)
    text = text.replace('<th>', '<th%s>' % ts)
    text = text.replace('<td>', '<td%s>' % ts)
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
        "notice": ""
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
        "allow-apis": "1"
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
    "prohibited_usernames": ["connect", "apps", "users", "groups", "setpassword", "user-completion", "confirm",
        "recent", "reports", "plots", "unpublished", "settings", "metrics", "tokens", "help", "login", "welcome",
        "register", "resetpassword", "content"],
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
    'apps': Application,
    'users': User,
    'bundles': Bundle,
    'tasks': Task
}
admin_user = User.create_from({
    "guid": "29a74070-2c13-4ef9-a898-cfc6bcf0f275",
    "username": "admin",
    "first_name": "Super",
    "last_name": "User",
    "email": "admin@example.com",
    "user_role": "administrator",
    "password": "",
    "confirmed": True,
    "locked": False,
    "created_time": "2018-08-29T19:25:23.68280816Z",
    "active_time": "2018-08-30T23:49:18.421238194Z",
    "updated_time": "2018-08-29T19:25:23.68280816Z",
    "privileges": [
        "add_users",
        "add_vanities",
        "change_app_permissions",
        "change_apps",
        "change_groups",
        "change_usernames",
        "change_users",
        "change_variant_schedule",
        "create_groups",
        "edit_run_as",
        "edit_runtime",
        "lock_users",
        "publish_apps",
        "remove_apps",
        "remove_groups",
        "remove_users",
        "remove_vanities",
        "view_app_settings",
        "view_apps"
    ]
})
# noinspection SpellCheckingInspection
api_keys = {
    '0123456789abcdef0123456789abcdef': admin_user.id
}

# Handle any pre-fetching we should do.
_pre_fetch_data()
