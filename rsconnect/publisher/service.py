"""Public, non-CLI services for initializing and publishing projects."""

from __future__ import annotations

import dataclasses
import os
import typing

from ..api import PublisherContext, RSConnectExecutor
from ..deploy import BundleOptions, execute_deploy, plan_deploy_bundle
from ..exception import RSConnectException
from ..metadata import ServerDataDict, ServerStore
from . import config as config_mod
from . import schema, store


@dataclasses.dataclass(frozen=True)
class ContentTypeSpec:
    """Metadata a frontend can use to present content-type choices."""

    type: str
    label: str
    deploy_commands: typing.Tuple[str, ...]
    language: typing.Optional[str]
    entrypoint_example: str


CONTENT_TYPES: typing.Tuple[ContentTypeSpec, ...] = (
    ContentTypeSpec("python-streamlit", "Streamlit", ("streamlit",), "python", "app.py"),
    ContentTypeSpec("python-shiny", "Shiny for Python", ("shiny",), "python", "app.py"),
    ContentTypeSpec("python-fastapi", "FastAPI", ("fastapi",), "python", "app.py:app"),
    ContentTypeSpec("python-flask", "Flask API", ("api", "flask"), "python", "app.py:app"),
    ContentTypeSpec("python-dash", "Dash", ("dash",), "python", "app.py:app"),
    ContentTypeSpec("python-bokeh", "Bokeh", ("bokeh",), "python", "app.py"),
    ContentTypeSpec("python-gradio", "Gradio", ("gradio",), "python", "app.py"),
    ContentTypeSpec("python-panel", "Panel", ("panel",), "python", "app.py"),
    ContentTypeSpec("jupyter-notebook", "Jupyter Notebook", ("notebook",), "python", "report.ipynb"),
    ContentTypeSpec("jupyter-voila", "Voila", ("voila",), "python", "report.ipynb"),
    ContentTypeSpec("quarto-static", "Quarto", ("quarto",), None, "report.qmd"),
    ContentTypeSpec("quarto-shiny", "Quarto Shiny", ("quarto",), None, "report.qmd"),
    ContentTypeSpec("html", "Static HTML", ("html",), None, "index.html"),
    ContentTypeSpec("nodejs", "Node.js", ("nodejs",), None, "app.js"),
)
_CONTENT_TYPES_BY_NAME = {spec.type: spec for spec in CONTENT_TYPES}


def _mapping(value: typing.Any) -> typing.Mapping[str, typing.Any]:
    return typing.cast(typing.Mapping[str, typing.Any], value) if isinstance(value, dict) else {}


def _optional_str(value: typing.Any) -> typing.Optional[str]:
    return value if isinstance(value, str) and value else None


def _optional_bool(value: typing.Any) -> typing.Optional[bool]:
    return value if isinstance(value, bool) else None


@dataclasses.dataclass(frozen=True)
class InitRequest:
    """Inputs used to create one Publisher project configuration."""

    project_dir: str
    content_type: str
    entrypoint: str
    config_name: typing.Optional[str] = None
    product_type: str = schema.PRODUCT_TYPE_CONNECT
    source: typing.Optional[str] = None
    title: typing.Optional[str] = None
    description: typing.Optional[str] = None
    validate: bool = True
    files: typing.Tuple[str, ...] = tuple()
    has_parameters: bool = False
    python: typing.Optional[typing.Mapping[str, typing.Any]] = None
    r: typing.Optional[typing.Mapping[str, typing.Any]] = None
    quarto: typing.Optional[typing.Mapping[str, typing.Any]] = None
    jupyter: typing.Optional[typing.Mapping[str, typing.Any]] = None
    environment: typing.Mapping[str, str] = dataclasses.field(default_factory=lambda: {})
    secrets: typing.Tuple[str, ...] = tuple()
    integration_requests: typing.Tuple[typing.Mapping[str, typing.Any], ...] = tuple()
    connect: typing.Optional[typing.Mapping[str, typing.Any]] = None
    connect_cloud: typing.Optional[typing.Mapping[str, typing.Any]] = None
    overwrite: bool = False


@dataclasses.dataclass(frozen=True)
class InitResult:
    config_name: str
    config_path: str
    config: config_mod.PublisherConfig


def initialize_project(request: InitRequest) -> InitResult:
    """Create a `.posit/publish` config from explicit, frontend-supplied values."""
    project_dir = os.path.abspath(request.project_dir)
    if not os.path.isdir(project_dir):
        raise RSConnectException("Project directory does not exist: {}".format(project_dir))
    if request.content_type not in _CONTENT_TYPES_BY_NAME:
        raise RSConnectException(
            "Unsupported content type '{}'. Choose one of: {}.".format(
                request.content_type, ", ".join(spec.type for spec in CONTENT_TYPES)
            )
        )
    if not request.entrypoint.strip():
        raise RSConnectException("An entrypoint is required.")
    if request.product_type not in (
        schema.PRODUCT_TYPE_CONNECT,
        schema.PRODUCT_TYPE_SNOWFLAKE,
        schema.PRODUCT_TYPE_CONNECT_CLOUD,
    ):
        raise RSConnectException("Unsupported product type '{}'.".format(request.product_type))

    config_name = request.config_name or store._new_config_name(  # noqa: SLF001 - same-package naming policy
        project_dir, request.title or os.path.basename(request.entrypoint)
    )
    if (
        not config_name
        or config_name in (".", "..", "deployments")
        or os.path.basename(config_name) != config_name
        or config_name.endswith(".toml")
    ):
        raise RSConnectException("Config name must be a filename stem without directories or '.toml'.")
    config_path = schema.config_path(project_dir, config_name)
    if os.path.exists(config_path) and not request.overwrite:
        raise RSConnectException(
            "Publisher config '{}' already exists; choose another name or allow overwrite.".format(config_name)
        )

    spec = _CONTENT_TYPES_BY_NAME[request.content_type]
    python = dict(request.python) if request.python is not None else None
    r = dict(request.r) if request.r is not None else None
    quarto = dict(request.quarto) if request.quarto is not None else None
    if spec.language == "python" and python is None:
        python = {"package_file": "requirements.txt", "package_manager": "pip"}
    if spec.language == "r" and r is None:
        r = {"package_file": "renv.lock", "package_manager": "renv"}
    if request.content_type.startswith("quarto-") and (not quarto or not quarto.get("version")):
        raise RSConnectException("Quarto content requires a quarto mapping with a version.")

    cfg = config_mod.PublisherConfig(
        type=request.content_type,
        entrypoint=request.entrypoint,
        source=request.source,
        title=request.title,
        description=request.description,
        validate=request.validate,
        files=list(request.files),
        has_parameters=request.has_parameters,
        product_type=request.product_type,
        python=python,
        r=r,
        quarto=quarto,
        jupyter=dict(request.jupyter) if request.jupyter is not None else None,
        environment=dict(request.environment),
        secrets=list(request.secrets),
        integration_requests=[dict(item) for item in request.integration_requests],
        connect=dict(request.connect) if request.connect is not None else None,
        connect_cloud=dict(request.connect_cloud) if request.connect_cloud is not None else None,
    )
    if not cfg.files:
        cfg.files = store._default_config_file_patterns()  # noqa: SLF001 - same-package policy
    package_pattern = store._python_package_file_pattern(cfg)  # noqa: SLF001 - same-package policy
    for path in package_pattern + store._posit_bundle_paths(project_dir, config_name, None):  # noqa: SLF001
        if path not in cfg.files:
            cfg.files.append(path)

    config_mod.write_config(project_dir, config_name, cfg, merge_existing=False)
    return InitResult(config_name=config_name, config_path=config_path, config=cfg)


@dataclasses.dataclass(frozen=True)
class PublishRequest:
    """Operational inputs for publishing an initialized project."""

    project_dir: str
    config_name: typing.Optional[str] = None
    deployment_name: typing.Optional[str] = None
    server: typing.Optional[str] = None
    server_name: typing.Optional[str] = None
    api_key: typing.Optional[str] = None
    snowflake_connection_name: typing.Optional[str] = None
    insecure: bool = False
    cacert: typing.Optional[str] = None
    content_id: typing.Optional[str] = None
    draft: bool = False
    verify: typing.Optional[bool] = None
    exclude_renv: bool = False
    metadata: typing.Tuple[str, ...] = tuple()
    no_metadata: bool = False
    ctx: typing.Any = None


@dataclasses.dataclass(frozen=True)
class PublishResult:
    content_id: str
    content_guid: typing.Optional[str]
    content_url: str
    dashboard_url: typing.Optional[str]
    bundle_id: typing.Optional[str]
    config_name: str
    deployment_name: str


def _saved_server_by_url(
    server_store: ServerStore, server_url: typing.Optional[str]
) -> typing.Optional[ServerDataDict]:
    if not server_url:
        return None
    target = store.normalize_url(server_url)
    matches = [
        entry
        for entry in server_store.get_all_servers()
        if entry.get("url") and store.normalize_url(entry["url"]) == target
    ]
    if len(matches) > 1:
        raise RSConnectException(
            "Multiple saved servers match {} ({}); select one by name.".format(
                server_url, ", ".join(sorted(str(match.get("name")) for match in matches))
            )
        )
    return matches[0] if matches else None


def publish_project(request: PublishRequest) -> PublishResult:
    """Publish a project solely from its `.posit/publish` configuration."""
    if request.server and request.server_name:
        raise RSConnectException("Specify either server or server_name, not both.")

    server_store = ServerStore()
    selected_server = request.server
    if request.server_name:
        saved = server_store.get_by_name(request.server_name)
        if saved is None:
            raise RSConnectException("Unknown server name '{}'.".format(request.server_name))
        selected_server = saved.get("url")

    target = store.resolve_publish_target(
        os.path.abspath(request.project_dir),
        config_name=request.config_name,
        record_name=request.deployment_name,
        server=selected_server,
    )
    if target.config.product_type == schema.PRODUCT_TYPE_CONNECT_CLOUD:
        raise RSConnectException("Publishing to Posit Connect Cloud is not supported by rsconnect-python.")
    if target.app_mode == schema.app_mode_from_type("unknown"):
        raise RSConnectException("Unknown Publisher content type '{}'.".format(target.config.type))
    if not target.entrypoint:
        raise RSConnectException("Publisher config '{}' has no entrypoint.".format(target.config_name))
    if target.record is None and not selected_server:
        raise RSConnectException(
            "This configuration has not been published; specify server or server_name for the first publish."
        )

    server_name = request.server_name
    deploy_server = request.server or target.server_url
    if not server_name and not request.server and not request.api_key:
        saved = _saved_server_by_url(server_store, target.server_url)
        if saved:
            server_name = saved.get("name")
            deploy_server = None

    python = _mapping(target.config.python)
    jupyter = _mapping(target.config.jupyter)
    connect = _mapping(target.config.connect)
    kubernetes = _mapping(connect.get("kubernetes"))
    package_installer = _optional_str(python.get("package_manager"))
    env_management_py = _optional_bool(kubernetes.get("default_py_environment_management"))
    if package_installer == "none" and env_management_py is None:
        env_management_py = False
    options = BundleOptions(
        python_version=_optional_str(python.get("version")),
        python_requires=_optional_str(python.get("requires_python")),
        package_installer=package_installer,
        image=_optional_str(kubernetes.get("default_image_name")),
        env_management_py=env_management_py,
        env_management_r=_optional_bool(kubernetes.get("default_r_environment_management")),
        hide_all_input=bool(jupyter.get("hide_all_input", False)),
        hide_tagged_input=bool(jupyter.get("hide_tagged_input", False)),
    )
    plan = plan_deploy_bundle(
        target.project_dir,
        target.app_mode,
        target.entrypoint,
        target.requirements_file or "requirements.txt",
        exclude_renv=request.exclude_renv,
        options=options,
    )
    context = PublisherContext(
        project_dir=target.project_dir,
        config_name=target.config_name,
        record_name=target.record_name,
        include_files=store.resolve_bundle_files(
            target.project_dir,
            target.entrypoint,
            target.config_name,
        ),
        manifest_overlay=store.config_manifest_overlay(target.config),
    )
    executor = RSConnectExecutor(
        ctx=request.ctx,
        name=server_name,
        server=deploy_server,
        api_key=request.api_key,
        snowflake_connection_name=request.snowflake_connection_name,
        insecure=request.insecure,
        cacert=request.cacert,
        path=plan.path,
        app_id=request.content_id or target.app_id,
        title=target.title,
        env_vars=target.config.environment,
        publisher_context=context,
    )
    verify = target.config.validate if request.verify is None else request.verify
    execute_deploy(
        executor,
        target.project_dir,
        target.app_mode,
        plan,
        draft=request.draft,
        verify=verify,
        metadata=request.metadata,
        no_metadata=request.no_metadata,
    )
    deployed = executor.deployed_info
    paths = executor.publisher_metadata_paths
    if deployed is None or paths is None:
        raise RSConnectException("Publish completed without deployment metadata.")
    deployment_name = os.path.splitext(os.path.basename(paths[1]))[0]
    return PublishResult(
        content_id=deployed["app_id"],
        content_guid=deployed.get("app_guid"),
        content_url=deployed["app_url"],
        dashboard_url=deployed.get("dashboard_url"),
        bundle_id=deployed.get("bundle_id"),
        config_name=target.config_name,
        deployment_name=deployment_name,
    )
