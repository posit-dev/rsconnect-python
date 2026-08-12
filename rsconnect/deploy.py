"""Reusable deployment planning and execution helpers.

This module contains no Click command definitions. CLI frontends can build their
own user experience while reusing rsconnect-python's bundle builders and deploy
executor.
"""

from __future__ import annotations

import dataclasses
import typing
from pathlib import Path

from .actions import (
    cli_feedback,
    create_quarto_deployment_bundle,
    quarto_inspect,
    validate_quarto_engines,
    which_quarto,
)
from .api import RSConnectClient, RSConnectExecutor, server_supports_git_metadata
from .bundle import (
    make_api_bundle,
    make_html_bundle,
    make_nodejs_bundle,
    make_notebook_source_bundle,
    make_voila_bundle,
    resolve_shiny_express_entrypoint,
)
from .environment import Environment, PackageInstaller
from .environment_node import NodeEnvironment
from .environment_r import REnvironment
from .exception import RSConnectException
from .git_metadata import detect_git_metadata
from .log import logger
from .models import AppMode, AppModes


@dataclasses.dataclass(frozen=True)
class DeployPlan:
    """A selected bundle builder and its arguments."""

    path: str
    builder: typing.Callable[..., typing.Any]
    args: typing.Tuple[typing.Any, ...]
    kwargs: typing.Dict[str, typing.Any]


@dataclasses.dataclass(frozen=True)
class BundleOptions:
    """Config-backed options that affect manifest and bundle generation."""

    python_version: typing.Optional[str] = None
    python_requires: typing.Optional[str] = None
    package_installer: typing.Optional[str] = None
    image: typing.Optional[str] = None
    env_management_py: typing.Optional[bool] = None
    env_management_r: typing.Optional[bool] = None
    hide_all_input: bool = False
    hide_tagged_input: bool = False


def _package_installer(value: typing.Optional[str]) -> typing.Optional[PackageInstaller]:
    if value in (None, "", "none"):
        return None
    try:
        return PackageInstaller(value)
    except ValueError as exc:
        raise RSConnectException(
            "rsconnect-python supports the 'pip', 'uv', and 'none' Python package managers; got '{}'.".format(value)
        ) from exc


def _python_environment(
    directory: str,
    requirements_file: str,
    options: BundleOptions,
) -> Environment:
    environment = Environment.create_python_environment(
        directory,
        requirements_file=requirements_file,
        override_python_version=options.python_version,
        package_manager=_package_installer(options.package_installer),
    )
    if options.python_requires:
        environment.python_version_requirement = options.python_requires
    return environment


def plan_deploy_bundle(
    directory: str,
    app_mode: AppMode,
    entrypoint: str,
    requirements_file: str,
    *,
    exclude_renv: bool = False,
    unsupported_message: typing.Optional[str] = None,
    options: BundleOptions = BundleOptions(),
) -> DeployPlan:
    """Plan a local bundle from a config-derived app mode and entrypoint."""
    extra_files: typing.Tuple[str, ...] = tuple()
    excludes: typing.Tuple[str, ...] = tuple()
    kwargs: typing.Dict[str, typing.Any] = {}
    path = directory
    r_environment = None if exclude_renv else REnvironment.create(directory)

    if app_mode in (
        AppModes.STREAMLIT_APP,
        AppModes.PYTHON_SHINY,
        AppModes.PYTHON_FASTAPI,
        AppModes.PYTHON_API,
        AppModes.DASH_APP,
        AppModes.BOKEH_APP,
        AppModes.PYTHON_GRADIO,
        AppModes.PYTHON_PANEL,
    ):
        if app_mode == AppModes.PYTHON_SHINY:
            entrypoint = resolve_shiny_express_entrypoint(entrypoint, directory)
        environment = _python_environment(directory, requirements_file, options)
        builder = make_api_bundle
        args = (directory, entrypoint, app_mode, environment, extra_files, excludes)
        kwargs = {
            "image": options.image,
            "env_management_py": options.env_management_py,
            "env_management_r": options.env_management_r,
            "r_environment": r_environment,
        }
    elif app_mode == AppModes.STATIC:
        builder = make_html_bundle
        args = (directory, entrypoint, extra_files, excludes)
    elif app_mode == AppModes.NODE_JS:
        node_environment = NodeEnvironment.create(directory, node_executable=None)
        builder = make_nodejs_bundle
        args = (directory, entrypoint, node_environment, extra_files, excludes)
        kwargs = {"image": options.image, "env_management_node": options.env_management_py}
    elif app_mode == AppModes.JUPYTER_NOTEBOOK:
        path = str(Path(directory) / entrypoint)
        environment = _python_environment(directory, requirements_file, options)
        builder = make_notebook_source_bundle
        args = (
            path,
            environment,
            extra_files,
            options.hide_all_input,
            options.hide_tagged_input,
        )
        kwargs = {
            "image": options.image,
            "env_management_py": options.env_management_py,
            "env_management_r": options.env_management_r,
            "r_environment": r_environment,
        }
    elif app_mode == AppModes.JUPYTER_VOILA:
        environment = _python_environment(directory, requirements_file, options)
        builder = make_voila_bundle
        args = (directory, entrypoint, extra_files, excludes, True, environment)
        kwargs = {
            "image": options.image,
            "env_management_py": options.env_management_py,
            "env_management_r": options.env_management_r,
            "r_environment": r_environment,
            "multi_notebook": False,
        }
    elif app_mode in (AppModes.STATIC_QUARTO, AppModes.SHINY_QUARTO):
        path = str(Path(directory) / entrypoint)
        with cli_feedback("Inspecting Quarto project"):
            quarto = which_quarto(None)
            logger.debug("Quarto: %s" % quarto)
            inspect = quarto_inspect(quarto, path)
            engines = validate_quarto_engines(inspect)
        environment = None
        if "jupyter" in engines:
            with cli_feedback("Inspecting Python environment"):
                environment = _python_environment(directory, requirements_file, options)
        builder = create_quarto_deployment_bundle
        args = (path, extra_files, excludes, app_mode, inspect, environment)
        kwargs = {
            "image": options.image,
            "env_management_py": options.env_management_py,
            "env_management_r": options.env_management_r,
            "r_environment": r_environment,
        }
    else:
        raise RSConnectException(
            unsupported_message or "Unsupported Publisher content type '{}'.".format(app_mode.name())
        )

    return DeployPlan(path=path, builder=builder, args=args, kwargs=kwargs)


def prepare_deploy_metadata(
    directory: typing.Optional[str],
    metadata_overrides: typing.Tuple[str, ...],
    no_metadata: bool,
    server_version: typing.Optional[str] = None,
) -> typing.Optional[typing.Dict[str, str]]:
    """Resolve git metadata and explicit metadata overrides for an upload."""
    if no_metadata:
        return None

    cli_metadata: typing.Dict[str, str] = {}
    force_metadata = bool(metadata_overrides)
    for item in metadata_overrides:
        if "=" in item:
            key, value = item.split("=", 1)
            cli_metadata[key] = value

    detected = detect_git_metadata(directory) if directory is not None else {}
    metadata = {**detected, **cli_metadata}
    metadata = {key: value for key, value in metadata.items() if value}
    if not metadata:
        return None
    if force_metadata or server_supports_git_metadata(server_version):
        return metadata
    return None


def execute_deploy(
    executor: RSConnectExecutor,
    directory: str,
    app_mode: AppMode,
    plan: DeployPlan,
    *,
    draft: bool = False,
    verify: bool = True,
    metadata: typing.Tuple[str, ...] = tuple(),
    no_metadata: bool = False,
    emit_content_url: bool = False,
) -> RSConnectExecutor:
    """Build, upload, verify, and optionally activate one deployment."""
    server_version = executor.client.server_version() if isinstance(executor.client, RSConnectClient) else None
    executor.metadata = prepare_deploy_metadata(directory, metadata, no_metadata, server_version)
    (
        executor.validate_server()
        .validate_app_mode(app_mode=app_mode)
        .make_bundle(plan.builder, *plan.args, **plan.kwargs)
        .deploy_bundle(activate=not executor.should_deploy_as_draft(draft, not verify))
        .save_deployed_info()
        .emit_task_log()
    )
    if verify:
        executor.verify_deployment()
        if not draft and executor.supports_verify_before_activate:
            executor.activate_deployment().emit_task_log()
    if emit_content_url:
        executor.emit_content_url()
    return executor
