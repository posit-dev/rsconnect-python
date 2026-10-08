"""Native preflight checks for Python deployments to Posit Connect."""

from __future__ import annotations

import configparser
import os
import platform
import shutil
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple, Union, cast

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .api import ConnectCloudServer, RSConnectClient, RSConnectExecutor, RSConnectServer, SPCSConnectServer
from .environment import fake_module_file_from_directory
from .exception import RSConnectException
from .metadata import AppStore
from .validation import require_posix
from .pyproject import (
    InvalidVersionConstraintError,
    TOMLDecodeError,
    detect_python_version_requirement,
    get_python_version_requirement_parser,
    lookup_metadata_file,
)

_METADATA_FILES = (".python-version", "pyproject.toml", "setup.cfg")
_APP_STORE_READ_ERRORS = (OSError, ValueError, RecursionError, AttributeError, TypeError)


def _invalid_declared_metadata(project_path: Path) -> Optional[str]:
    for filename, metadata_file in lookup_metadata_file(project_path):
        parser = get_python_version_requirement_parser(metadata_file)
        try:
            constraint = parser(metadata_file)
        except InvalidVersionConstraintError:
            return filename
        if constraint is None:
            continue
        if not isinstance(constraint, str) or not constraint.strip():
            return filename
        try:
            SpecifierSet(constraint)
        except InvalidSpecifier:
            return filename
        return None
    return None


def _project_constraint(project: str, warnings: list[str]) -> tuple[Optional[str], Optional[str]]:
    project_path = Path(project)
    for filename in _METADATA_FILES:
        if (project_path / filename).is_symlink():
            warnings.append(f"{filename} is a symlink; refusing to read it.")
            return None, filename
    try:
        constraint = detect_python_version_requirement(project)
        invalid_metadata = _invalid_declared_metadata(project_path)
    except (OSError, UnicodeError, TOMLDecodeError, configparser.Error, AttributeError) as err:
        warnings.append(f"Could not read Python version metadata in {project}: {err}")
        return None, "Python version metadata"
    if invalid_metadata is None and constraint is None and os.path.lexists(project_path / ".python-version"):
        invalid_metadata = ".python-version"
    if invalid_metadata:
        warnings.append(f"{invalid_metadata} has an unusable Python requirement; it was left unchanged.")
        if not isinstance(constraint, str):
            constraint = None
    return constraint, invalid_metadata


def _server_python_versions(settings: Any) -> tuple[list[str], list[str], bool, bool]:
    if not isinstance(settings, Mapping):
        return [], [], False, False
    settings_mapping = cast(Mapping[str, Any], settings)
    raw_installations = settings_mapping.get("installations")
    if not isinstance(raw_installations, list):
        return [], [], False, False

    installations = cast(List[Any], raw_installations)
    installed: list[str] = []
    publishable: list[str] = []
    flags_complete = True
    for item in installations:
        if not isinstance(item, Mapping):
            flags_complete = False
            continue
        installation = cast(Mapping[str, Any], item)
        version = cast(str, installation.get("version"))
        try:
            parsed = Version(version)
        except (InvalidVersion, TypeError):
            flags_complete = False
            continue
        if len(parsed.release) < 2:
            flags_complete = False
            continue
        installed.append(version)

        flag = installation.get("publishable")
        if not isinstance(flag, bool):
            flags_complete = False
        elif flag:
            publishable.append(version)
    return installed, publishable, bool(installations), flags_complete


def _minor(version: str) -> tuple[int, int]:
    release = Version(version).release
    if len(release) < 2:
        raise InvalidVersion(f"Python version has no minor component: {version}")
    return release[0], release[1]


def _pick_python_pin(versions: list[str], local_python: str) -> Optional[str]:
    minors = sorted({_minor(version) for version in versions})
    if not minors:
        return None
    local_minor = _minor(local_python)
    if local_minor in minors:
        selected = local_minor
    else:
        newer = [version for version in minors if version > local_minor]
        selected = newer[0] if newer else minors[-1]
    return f"{selected[0]}.{selected[1]}"


def _local_publishable(
    local_python: str, versions: list[str], has_installations: bool, flags_complete: bool
) -> Optional[bool]:
    if any(_minor(version) == _minor(local_python) for version in versions):
        return True
    return False if has_installations and flags_complete else None


def _constraint_compatibility(constraint: Optional[str], versions: list[str]) -> str:
    if constraint is None:
        return "unconstrained"
    if not versions:
        return "unknown"
    try:
        specifier = SpecifierSet(constraint)
    except (InvalidSpecifier, TypeError):
        return "unknown"
    return "compatible" if any(specifier.contains(version) for version in versions) else "incompatible"


def _deployment_store_paths(target: str) -> list[str]:
    paths = [target]
    if os.path.isdir(target):
        paths.extend((fake_module_file_from_directory(target), os.path.join(target, "manifest.json")))
    return paths


def load_preflight_app_store(path: str) -> AppStore:
    """Load safe deployment history for executor target inference."""
    module_file = fake_module_file_from_directory(path)
    try:
        store = AppStore(module_file, strict_read=True)
        records = store.get_all()
        if not isinstance(records, list) or any(
            not isinstance(record, Mapping) or not isinstance(record.get("server_url"), str) or not record["server_url"]
            for record in records
        ):
            raise TypeError("Malformed local deployment metadata.")
    except _APP_STORE_READ_ERRORS:
        return AppStore(module_file, autoload=False, strict_read=True)
    return store


def _read_app_store_record(store: Any, server_key: str) -> tuple[Optional[Mapping[str, Any]], Optional[str]]:
    try:
        record = store.get(server_key)
    except _APP_STORE_READ_ERRORS as err:
        return None, f"Could not read local deployment metadata: {err}"
    if record is None:
        return None, None
    if not isinstance(record, Mapping):
        return None, "The local deployment record is malformed."
    return cast(Mapping[str, Any], record), None


def _read_deployment_records(executor: RSConnectExecutor, target: str) -> tuple[list[Mapping[str, Any]], Optional[str]]:
    directory = os.path.isdir(target)
    module_file = fake_module_file_from_directory(target) if directory else None
    executor_module = fake_module_file_from_directory(executor.path)
    try:
        stores: list[Any] = []
        for path in _deployment_store_paths(target):
            stores.append(AppStore(executor_module if path == module_file else path, strict_read=True))
        if not directory:
            stores.append(AppStore(executor_module, strict_read=True))
    except _APP_STORE_READ_ERRORS as err:
        return [], f"Could not read local deployment metadata: {err}"

    records: list[Mapping[str, Any]] = []
    server_key = executor.record_server_key()
    for store in stores:
        record, issue = _read_app_store_record(store, server_key)
        if issue:
            return [], issue
        if record is not None:
            records.append(record)
    return records, None


def _file_deployment_records(source: Path, server_key: str) -> tuple[list[Mapping[str, Any]], Optional[str]]:
    records: list[Mapping[str, Any]] = []
    try:
        for app_file in (str(source), fake_module_file_from_directory(str(source))):
            record, issue = _read_app_store_record(AppStore(app_file, strict_read=True), server_key)
            if issue:
                return [], issue
            if record is not None:
                records.append(record)
    except _APP_STORE_READ_ERRORS as err:
        return [], f"Could not check file deployment metadata: {err}"
    return records, None


def _directory_file_deployments(
    executor: RSConnectExecutor, target: str
) -> tuple[list[Mapping[str, Any]], Optional[str]]:
    records: list[Mapping[str, Any]] = []
    server_key = executor.record_server_key()
    try:
        for source in Path(target).iterdir():
            if not source.is_file():
                continue
            source_records, issue = _file_deployment_records(source, server_key)
            if issue:
                return [], issue
            records.extend(source_records)
    except _APP_STORE_READ_ERRORS as err:
        return [], f"Could not check file deployment metadata: {err}"
    return records, None


def _target_from_records(records: list[Mapping[str, Any]]) -> tuple[bool, Optional[str], Optional[str]]:
    if len(records) > 1:
        return True, None, "Multiple local deployment records match this target."
    if not records:
        return False, None, None
    record_id = records[0].get("app_guid") or records[0].get("app_id")
    if not isinstance(record_id, str) or not record_id:
        return True, None, "The local deployment record has no content ID."
    return True, record_id, None


def _saved_deployment_target(executor: RSConnectExecutor, target: str) -> tuple[bool, Optional[str], Optional[str]]:
    records, issue = _read_deployment_records(executor, target)
    if issue:
        return True, None, issue
    if not records and os.path.isdir(target):
        records, issue = _directory_file_deployments(executor, target)
        if issue:
            return True, None, issue
        if records:
            return True, None, "This directory has a single-file deployment; pass its exact file path or --app-id."
    return _target_from_records(records)


def _deployment_target(executor: RSConnectExecutor, target: str) -> tuple[bool, Optional[str], Optional[str]]:
    if executor.new:
        return False, None, None
    if executor.app_id:
        return True, str(executor.app_id), None
    return _saved_deployment_target(executor, target)


def _current_python(
    client: RSConnectClient, app_id: str, warnings: list[str], actions: list[str]
) -> tuple[Optional[str], bool]:
    try:
        content = client.get_content_by_id(app_id)
    except RSConnectException as err:
        warnings.append(f"Could not read existing content's current Python version: {err}")
        if err.status == 404:
            actions.append("The content item was not found; verify its ID or use --new to publish a new item.")
        elif err.status == 403:
            actions.append("Check access to the existing content before redeploying, or use --new for a separate item.")
        else:
            actions.append("Check the existing content ID and Connect access before redeploying.")
        return None, False
    if not isinstance(content, Mapping):
        warnings.append("Connect returned an invalid response for the existing content.")
        actions.append("Check the existing content ID and Connect access before redeploying.")
        return None, False

    version = content.get("py_version")
    if isinstance(version, str) and version:
        return version, True
    warnings.append("Connect did not report the existing content's current py_version; it is informational.")
    return None, True


def _existing_content(
    client: RSConnectClient,
    exists: bool,
    app_id: Optional[str],
    constraint: Optional[str],
    installed_versions: list[str],
    warnings: list[str],
    actions: list[str],
) -> tuple[dict[str, Any], bool]:
    current_python: Optional[str] = None
    content_readable = True
    if exists and app_id:
        current_python, content_readable = _current_python(client, app_id, warnings, actions)
    return (
        {
            "exists": exists,
            "app_id": app_id,
            "installed_python_version": current_python,
            "server_python_versions": installed_versions,
            "python_compatibility": (
                _constraint_compatibility(constraint, installed_versions) if exists else "not_applicable"
            ),
        },
        content_readable,
    )


def _write_python_pin(project: str, version: str) -> bool:
    pin_path = Path(project) / ".python-version"
    if os.path.lexists(pin_path):
        return False
    try:
        with pin_path.open("x", encoding="utf-8") as pin_file:
            pin_file.write(version + "\n")
    except FileExistsError:
        return False
    except OSError as err:
        raise RSConnectException(f"Could not create {pin_path}: {err}") from err
    return True


def _recommend_python_pin(
    project: str,
    is_new: bool,
    constraint: Optional[str],
    invalid_metadata: Optional[str],
    versions: list[str],
    local_python: str,
    fix: bool,
    warnings: list[str],
    actions: list[str],
) -> tuple[Optional[str], Optional[str], list[str], Optional[str]]:
    if not is_new or constraint is not None or invalid_metadata:
        return constraint, None, [], invalid_metadata
    recommendation = _pick_python_pin(versions, local_python)
    if recommendation is None:
        return constraint, None, [], invalid_metadata

    changed_files: list[str] = []
    if fix:
        if _write_python_pin(project, recommendation):
            changed_files.append(".python-version")
            constraint, invalid_metadata = _project_constraint(project, warnings)
            actions.append(f"Created .python-version with Python {recommendation}.")
        else:
            warnings.append(".python-version already exists; it was not overwritten.")
            actions.append("Review the existing .python-version before deploying.")
            constraint, invalid_metadata = _project_constraint(project, warnings)
    else:
        actions.append(f"Add .python-version = {recommendation} to pin new content to an advertised Python version.")

    if _minor(recommendation) != _minor(local_python):
        warnings.append(
            f"The Python {recommendation} recommendation differs from local Python {local_python}; "
            "dependency compatibility has not been tested."
        )
    return constraint, recommendation, changed_files, invalid_metadata


def _new_content_status(
    constraint: Optional[str],
    publishable_versions: list[str],
    flags_complete: bool,
    local_publishable: Optional[bool],
) -> str:
    if constraint is not None:
        compatibility = _constraint_compatibility(constraint, publishable_versions)
        if compatibility == "compatible":
            return "ok"
        if compatibility == "unknown":
            return "unknown"
        return "incompatible" if flags_complete else "unknown"
    if not publishable_versions:
        return "incompatible" if flags_complete else "unknown"
    return "ok" if local_publishable else "unknown"


def _status(
    is_new: bool,
    constraint: Optional[str],
    invalid_metadata: Optional[str],
    installed_versions: list[str],
    publishable_versions: list[str],
    flags_complete: bool,
    local_publishable: Optional[bool],
) -> str:
    if invalid_metadata or not installed_versions:
        return "unknown"
    if is_new:
        return _new_content_status(constraint, publishable_versions, flags_complete, local_publishable)
    compatibility = _constraint_compatibility(constraint, installed_versions)
    if compatibility in ("compatible", "unconstrained"):
        return "ok"
    return compatibility


def _availability_advice(
    settings_error: Optional[str],
    installed_versions: list[str],
    publishable_versions: list[str],
    has_installations: bool,
    flags_complete: bool,
    is_new: bool,
    warnings: list[str],
    actions: list[str],
) -> None:
    action: Optional[str] = None
    if settings_error:
        warnings.append(f"Could not read server Python settings: {settings_error}")
        action = "Check the server's Python installations before publishing."
    elif not has_installations or not installed_versions:
        warnings.append("The server did not report usable Python installations; compatibility is unknown.")
        action = "Check the server's Python installations before publishing."
    elif not flags_complete:
        warnings.append(
            "One or more Python installations lack a valid publishable flag; "
            "new-content legacy permissibility is unknown."
        )
        if not publishable_versions:
            action = "Check the server's Python publishability settings before publishing."
    elif not publishable_versions:
        warnings.append("The server has no Python installations marked publishable for new content.")
        action = "Mark a server Python installation publishable before publishing new content."
    if is_new and action:
        actions.append(action)


def _incompatible_advice(is_new: bool, constraint: Optional[str], warnings: list[str], actions: list[str]) -> None:
    if not is_new:
        warnings.append("No installed server Python version satisfies the project requirement.")
        actions.append("Align the project requirement with an installed version before redeploying.")
    elif constraint is None:
        warnings.append("No server Python version is publishable for new content.")
        actions.append("Mark a server Python installation publishable before publishing.")
    else:
        warnings.append("The project Python requirement matches none of the server's publishable versions.")
        actions.append("Choose a Python requirement supported by the server before publishing.")


def _unknown_advice(
    is_new: bool,
    constraint: Optional[str],
    recommended: Optional[str],
    warnings: list[str],
    actions: list[str],
) -> None:
    if not is_new:
        actions.append("Check the existing content ID, project Python metadata, and server runtime before redeploying.")
    elif constraint is not None:
        try:
            SpecifierSet(constraint)
        except (InvalidSpecifier, TypeError):
            warnings.append(f"Python requirement {constraint!r} is not a valid PEP 440 specifier.")
            actions.append("Correct the project's Python requirement metadata.")
        else:
            actions.append("Check the server's installed Python versions and publishability before deploying.")
    elif recommended is None:
        actions.append("Check the project's Python metadata and server availability before publishing.")


def _warn_local_python_mismatch(constraint: Optional[str], local_python: str, warnings: list[str]) -> None:
    if constraint is None:
        return
    try:
        matches_local = SpecifierSet(constraint).contains(local_python)
    except (InvalidSpecifier, TypeError):
        return
    if not matches_local:
        warnings.append(
            f"Local Python {local_python} does not satisfy the project requirement {constraint}; "
            "dependency compatibility has not been tested."
        )


def _validated_python_executor(
    executor: RSConnectExecutor,
) -> Tuple[Union[RSConnectServer, SPCSConnectServer], RSConnectClient]:
    server = executor.remote_server
    if isinstance(server, ConnectCloudServer):
        raise RSConnectException(
            "Python preflight supports self-hosted Posit Connect and Connect in SPCS, not Connect Cloud."
        )
    if not isinstance(server, (RSConnectServer, SPCSConnectServer)):
        raise RSConnectException("Python preflight supports only self-hosted Posit Connect and Connect in SPCS.")
    if executor.new and executor.app_id:
        raise RSConnectException("Specify either a new deploy or an app ID but not both.")

    client = executor.client
    if not isinstance(client, RSConnectClient):
        raise RSConnectException("Python preflight requires a self-hosted Connect client.")
    return server, client


def _python_project_metadata(
    target: str, local_python: str, warnings: list[str]
) -> tuple[str, Optional[str], Optional[str]]:
    target_path = Path(target)
    project_dir = str(target_path.parent) if target_path.is_file() else target
    constraint, invalid_metadata = _project_constraint(project_dir, warnings)
    _warn_local_python_mismatch(constraint, local_python, warnings)
    return project_dir, constraint, invalid_metadata


def _status_advice(
    status: str,
    is_new: bool,
    constraint: Optional[str],
    invalid_metadata: Optional[str],
    recommended: Optional[str],
    warnings: list[str],
    actions: list[str],
) -> None:
    if invalid_metadata:
        actions.append(f"Repair or remove the unusable Python requirement in {invalid_metadata} before deploying.")
    elif status == "incompatible":
        _incompatible_advice(is_new, constraint, warnings, actions)
    elif status == "unknown":
        _unknown_advice(is_new, constraint, recommended, warnings, actions)


def run_preflight(executor: RSConnectExecutor, project: str, fix: bool = False) -> dict[str, Any]:
    """Check project Python metadata against a validated Connect executor."""
    require_posix("Deployment preflight")
    server, client = _validated_python_executor(executor)

    warnings: list[str] = []
    actions: list[str] = []
    local_python = platform.python_version()
    project_dir, constraint, invalid_metadata = _python_project_metadata(project, local_python, warnings)
    is_existing, app_id, target_issue = _deployment_target(executor, project)
    is_new = not is_existing
    if target_issue:
        warnings.append(target_issue)
        actions.append(
            "Pass the exact file path for single-file content, specify --app-id, "
            "or use --new for a separate content item."
        )
    try:
        settings = client.python_settings()
        settings_error = None
    except RSConnectException as err:
        settings = None
        settings_error = str(err)
    installed, publishable, has_installations, flags_complete = _server_python_versions(settings)
    local_publishable = _local_publishable(local_python, publishable, has_installations, flags_complete)
    constraint, recommended, changed_files, invalid_metadata = _recommend_python_pin(
        project_dir, is_new, constraint, invalid_metadata, publishable, local_python, fix, warnings, actions
    )
    existing_content, content_readable = _existing_content(
        client, is_existing, app_id, constraint, installed, warnings, actions
    )
    status = _status(
        is_new,
        constraint,
        invalid_metadata,
        installed,
        publishable,
        flags_complete,
        local_publishable,
    )
    if target_issue or not content_readable:
        status = "unknown"
    _availability_advice(
        settings_error, installed, publishable, has_installations, flags_complete, is_new, warnings, actions
    )
    _status_advice(status, is_new, constraint, invalid_metadata, recommended, warnings, actions)

    quarto_available = shutil.which("quarto") is not None
    if not quarto_available:
        warnings.append("Quarto CLI is unavailable; it is required only for Quarto projects.")
        actions.append("Install Quarto if this project deploys Quarto content.")
    return {
        "status": status,
        "runtime": "python",
        "server": server.url,
        "publishable_python_versions": publishable,
        "local_python": local_python,
        "local_python_publishable": local_publishable,
        "recommended_python": recommended,
        "python_requires": constraint,
        "existing_content": existing_content,
        "quarto_available": quarto_available,
        "changed_files": changed_files,
        "warnings": warnings,
        "actions": actions,
    }
