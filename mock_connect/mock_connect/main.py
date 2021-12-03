"""
This is the main file, run via `flask run`, for the mock Connect server.
"""
import sys
from os.path import basename

# noinspection PyPackageRequirements
from flask import Flask, Blueprint, g, request, url_for, send_file

from .data import (
    Application,
    AppMode,
    Bundle,
    Content,
    Task,
    get_data_dump,
    default_server_settings,
)
from .http_helpers import endpoint, error

app = Flask(__name__)
api = Blueprint("api", __name__)


@app.route("/")
def index():
    return (
        """<html>
<head><title>RStudio Connect -- Mocked</title></head><body>
<h1>RStudio Connect -- Mocked</h1>
<p>Welcome to the mocked RStudio Connect!
<hr>
%s
</body></html>
"""
        % get_data_dump()
    )


@api.route("me")
@endpoint(authenticated=True, writes_json=True)
def me():
    return g.user


@api.route("applications", methods=["GET", "POST"])
@endpoint(authenticated=True, writes_json=True)
def applications():
    if request.method == "POST":
        connect_app = request.get_json(force=True)
        name = connect_app.get("name")
        if name and Application.get_app_by_name(name) is not None:
            return error(409, "An object with that name already exists.")
        title = connect_app["title"] if "title" in connect_app else ""
        return Application(
            name=name,
            title=title,
            owner_username=g.user.username,
            owner_first_name = g.user.first_name,
            owner_last_name = g.user.last_name,
            owner_email = g.user.email,
            owner_locked = g.user.locked,
            _base_url=url_for("index", _external=True),
        )
    else:
        count = int(request.args.get("count", 10000))
        search = request.args.get("search")

        def match(app_to_match):
            return search is None or app_to_match.title.startswith(search)

        matches = list(filter(match, Application.get_all_objects()))[:count]
        return {
            "count": len(matches),
            "total": len(matches),
            "applications": matches,
        }


# noinspection PyUnresolvedReferences
@api.route("applications/<object_id>", methods=["GET", "POST"])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def get_application(connect_app):
    if request.method == "POST":
        connect_app.update_from(request.get_json(force=True))

    return connect_app


# noinspection PyUnresolvedReferences
@api.route("applications/<object_id>/config")
@endpoint(authenticated=True, cls=Application, writes_json=True)
def config(connect_app):
    return {"config_url": connect_app.url}


# noinspection PyUnresolvedReferences
@api.route("applications/<object_id>/upload", methods=["POST"])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def upload(connect_app):
    return Bundle(app_id=connect_app.id, _tar_data=request.data)


# noinspection PyUnresolvedReferences
@api.route("applications/<object_id>/deploy", methods=["POST"])
@endpoint(authenticated=True, cls=Application, writes_json=True)
def deploy(connect_app):
    bundle_id = request.get_json(force=True).get("bundle")
    if bundle_id is None:
        return error(400, "bundle_id is required")  # message and status code probably wrong
    bundle = Bundle.get_object(bundle_id)
    if bundle is None:
        return error(404, "bundle %s not found" % bundle_id)  # message and status code probably wrong

    manifest = bundle.get_manifest()
    old_app_mode = connect_app.app_mode
    # noinspection SpellCheckingInspection
    new_app_mode = AppMode.value_of(manifest["metadata"]["appmode"])

    if old_app_mode is not None and old_app_mode != new_app_mode:
        return error(400, "Cannot change app mode once deployed")  # message and status code probably wrong

    connect_app.bundle_deployed(bundle, new_app_mode)

    return Task()


# noinspection PyUnresolvedReferences
@api.route("tasks/<object_id>")
@endpoint(authenticated=True, cls=Task, writes_json=True)
def get_task(task):
    return task


@api.route("server_settings")
@endpoint(authenticated=True, auth_optional=True, writes_json=True)
def server_settings():
    settings = default_server_settings.copy()

    # If the endpoint was hit with a valid user, fill in some extra stuff.
    if g.user is not None:
        settings["version"] = "1.8.1-9999"
        settings["build"] = '"9709a0fd93"'
        settings["about"] = "RStudio Connect v1.8.1-9999"

    return settings


@api.route("v1/server_settings/python")
@endpoint(authenticated=True, writes_json=True)
def python_settings():
    v = sys.version_info
    v = "%d.%d.%d" % (v[0], v[1], v[2])

    return {
        "installations": [{"version": v}],
        "api_enabled": True,
        "conda_enabled": False,
    }


# noinspection PyUnresolvedReferences
@app.route("/content/apps/<object_id>")
@endpoint(cls=Application)
def get_content(connect_app):
    bundle = connect_app.get_bundle()
    if bundle is None:
        return error(400, "The content has not been deployed.")  # message and status code probably wrong
    return bundle.get_rendered_content()


# noinspection PyUnresolvedReferences
@api.route("v1/content/<object_id>")
@endpoint(authenticated=True, cls=Content, writes_json=True)
def v1_get_content(content):
    return content


# noinspection PyUnresolvedReferences
@api.route("v1/content")
@endpoint(authenticated=True, writes_json=True)
def v1_content():
    return list(Content.get_all_objects())


# This endpoint is kind of a cheat, we dont actually do any validation
#  that the requested bundle belongs to this piece of content
# noinspection PyUnresolvedReferences
@api.route("v1/content/<content_id>/bundles/<object_id>/download")
@endpoint(authenticated=True, cls=Bundle)
def v1_content_bundle_download(bundle:Bundle, content_id):
    print(content_id)
    return send_file(
        bundle.read_bundle_data(),
        mimetype="application/tar+gzip",
        as_attachment=True,
        attachment_filename=basename(bundle._tar_file) if bundle._tar_file else None,
    )


@api.route("v1/content/<object_id>/build", methods=["POST"])
@endpoint(authenticated=True, writes_json=True)
def v1_content_build():
    bundle_id = request.get_json(force=True).get("bundle_id")
    if bundle_id is None:
        return error(400, "bundle_id is required")  # message and status code probably wrong

    task = Task()
    return {"task_id": task.id}


app.register_blueprint(api, url_prefix="/__api__")
