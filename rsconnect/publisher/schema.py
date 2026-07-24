"""Schema constants, content-type maps, and path helpers for ``.posit/publish``.

The content-type maps are ported verbatim from Posit Publisher's
``extensions/vscode/src/bundler/appMode.ts`` so that the ``type`` we write is
exactly what Publisher expects, and the ``app_mode`` we recover on read matches
Connect's manifest vocabulary.
"""

from __future__ import annotations

import os

from ..models import AppMode, AppModes

CONFIG_SCHEMA_URL = "https://cdn.posit.co/publisher/schemas/posit-publishing-schema-v3.json"
RECORD_SCHEMA_URL = "https://cdn.posit.co/publisher/schemas/posit-publishing-record-schema-v3.json"

# ``product_type`` (config) / ``server_type`` (record) values. Publisher's Go
# consts historically only defined connect/connect_cloud, but the published v3
# JSON schema accepts "snowflake", which is what we emit for SPCS targets.
PRODUCT_TYPE_CONNECT = "connect"
PRODUCT_TYPE_SNOWFLAKE = "snowflake"
PRODUCT_TYPE_CONNECT_CLOUD = "connect_cloud"

# Connect manifest ``app_mode`` string -> Publisher content ``type``. Keyed by
# ``AppMode.name()``. Ported from publisher appMode.ts (appModeToContentType,
# read in reverse). ``tensorflow-saved-model`` has no Publisher type, so it maps
# to "unknown"; the map-coverage test guards this.
APP_MODE_TO_TYPE = {
    "static": "html",
    "jupyter-static": "jupyter-notebook",
    "jupyter-voila": "jupyter-voila",
    "nodejs": "nodejs",
    "python-bokeh": "python-bokeh",
    "python-dash": "python-dash",
    "python-fastapi": "python-fastapi",
    "python-api": "python-flask",
    "python-shiny": "python-shiny",
    "python-streamlit": "python-streamlit",
    "python-gradio": "python-gradio",
    "python-panel": "python-panel",
    "quarto-shiny": "quarto-shiny",
    "quarto-static": "quarto-static",
    "api": "r-plumber",
    "shiny": "r-shiny",
    "rmd-shiny": "rmd-shiny",
    "rmd-static": "rmd",
    "tensorflow-saved-model": "unknown",
    "unknown": "unknown",
}

# Publisher content ``type`` -> Connect manifest ``app_mode`` string. The
# deprecated "quarto" type resolves to "quarto-static", matching publisher's
# reverse map.
TYPE_TO_APP_MODE = {
    "html": "static",
    "jupyter-notebook": "jupyter-static",
    "jupyter-voila": "jupyter-voila",
    "nodejs": "nodejs",
    "python-bokeh": "python-bokeh",
    "python-dash": "python-dash",
    "python-fastapi": "python-fastapi",
    "python-flask": "python-api",
    "python-shiny": "python-shiny",
    "python-streamlit": "python-streamlit",
    "python-gradio": "python-gradio",
    "python-panel": "python-panel",
    "quarto-shiny": "quarto-shiny",
    "quarto-static": "quarto-static",
    "quarto": "quarto-static",
    "r-plumber": "api",
    "r-shiny": "shiny",
    "rmd-shiny": "rmd-shiny",
    "rmd": "rmd-static",
    "unknown": "unknown",
}


def type_from_app_mode(app_mode: "AppMode | str") -> str:
    """Return the Publisher content ``type`` for a Connect ``app_mode``."""
    name = app_mode.name() if isinstance(app_mode, AppMode) else str(app_mode)
    return APP_MODE_TO_TYPE.get(name, "unknown")


def app_mode_from_type(content_type: str) -> AppMode:
    """Return the Connect ``AppMode`` for a Publisher content ``type``.

    Unknown types fall through to :data:`AppModes.UNKNOWN`.
    """
    name = TYPE_TO_APP_MODE.get(content_type, content_type)
    return AppModes.get_by_name(name, return_unknown=True)


# --- .posit/publish path helpers -------------------------------------------


def publish_dir(project_dir: str) -> str:
    """Return ``<project_dir>/.posit/publish``."""
    return os.path.join(project_dir, ".posit", "publish")


def deployments_dir(project_dir: str) -> str:
    """Return ``<project_dir>/.posit/publish/deployments``."""
    return os.path.join(publish_dir(project_dir), "deployments")


def config_path(project_dir: str, name: str) -> str:
    """Return the path to config ``<name>.toml``."""
    return os.path.join(publish_dir(project_dir), name + ".toml")


def record_path(project_dir: str, name: str) -> str:
    """Return the path to deployment record ``<name>.toml``."""
    return os.path.join(deployments_dir(project_dir), name + ".toml")
