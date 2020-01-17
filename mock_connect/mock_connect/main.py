"""
This is the main file, run via `flask run`, for the mock Connect server.
"""
# noinspection PyPackageRequirements
from flask import Flask, Blueprint, g, request, url_for

from .data import Application, AppMode, Bundle, Task, get_data_dump
from .http_helpers import endpoint, error

app = Flask(__name__)
api = Blueprint('api', __name__)


@app.route('/')
def index():
    return """<html>
<head><title>RStudio Connect -- Mocked</title></head><body>
<h1>RStudio Connect -- Mocked</h1>
<p>Welcome to the mocked RStudio Connect!
<hr>
%s
</body></html>
""" % get_data_dump()


@api.route('me')
@endpoint(authenticated=True, writes_json=True)
def me():
    return g.user


@api.route('applications', methods=['GET', 'POST'])
@endpoint(authenticated=True, writes_json=True)
def applications():
    if request.method == 'POST':
        connect_app = request.get_json(force=True)
        name = connect_app.get('name')
        if name and Application.get_app_by_name(name) is not None:
            return error(409, 'An object with that name already exists.')
        title = connect_app['title'] if 'title' in connect_app else ''

        return Application(name, title, url_for('index', _external=True), g.user)
    else:
        count = int(request.args.get('count', 10000))
        search = request.args.get('search')

        def match(app_to_match):
            return search is None or app_to_match.title.startswith(search)

        matches = list(filter(match, Application.get_all_objects()))[:count]
        return {
            'count': len(matches),
            'total': len(matches),
            'applications': matches,
        }


# noinspection PyUnresolvedReferences
@api.route('applications/<object_id>', methods=['GET', 'POST'])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def application(connect_app):
    if request.method == 'POST':
        connect_app.update_from(request.get_json(force=True))

    return connect_app


# noinspection PyUnresolvedReferences
@api.route('applications/<object_id>/config')
@endpoint(authenticated=True, cls=Application, writes_json=True)
def config(connect_app):
    return {
        'config_url': connect_app.url
    }


# noinspection PyUnresolvedReferences
@api.route('applications/<object_id>/upload', methods=['POST'])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def upload(connect_app):
    return Bundle(connect_app, request.data)


# noinspection PyUnresolvedReferences
@api.route('applications/<object_id>/deploy', methods=['POST'])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def deploy(connect_app):
    bundle_id = request.get_json(force=True).get('bundle')
    if bundle_id is None:
        return error(400, 'bundle_id is required')  # message and status code probably wrong
    bundle = Bundle.get_object(bundle_id)
    if bundle is None:
        return error(404, 'bundle %s not found' % bundle_id)  # message and status code probably wrong

    manifest = bundle.get_manifest()
    old_app_mode = connect_app.app_mode
    # noinspection SpellCheckingInspection
    new_app_mode = AppMode.value_of(manifest['metadata']['appmode'])

    if old_app_mode is not None and old_app_mode != new_app_mode:
        return error(400, 'Cannot change app mode once deployed')  # message and status code probably wrong

    connect_app.bundle_deployed(bundle, new_app_mode)

    return Task()


# noinspection PyUnresolvedReferences
@api.route('tasks/<object_id>')
@endpoint(authenticated=True, cls=Task, writes_json=True)
def get_task(task):
    return task


@api.route('server_settings')
@endpoint(writes_json=True)
def server_settings():
    # for our purposes, any non-error response will do
    return {}


# noinspection PyUnresolvedReferences
@app.route('/content/apps/<object_id>')
@endpoint(cls=Application)
def content(connect_app):
    bundle = connect_app.get_bundle()
    if bundle is None:
        return error(400, 'The content has not been deployed.')  # message and status code probably wrong
    return bundle.get_rendered_content()


app.register_blueprint(api, url_prefix='/__api__')
