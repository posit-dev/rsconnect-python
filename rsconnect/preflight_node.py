"""Preflight checks for Node.js deployments to Posit Connect."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping as MappingABC
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

from .api import ConnectCloudServer, RSConnectClient, RSConnectExecutor, RSConnectServer, SPCSConnectServer
from .environment_node import NodeEnvironment
from .exception import RSConnectException
from .preflight import _deployment_target

_SEMVER_SCRIPT = """
const fs = require("fs");
const path = require("path");
const npmRoot = path.dirname(path.dirname(process.argv[1]));
const semver = require(path.join(npmRoot, "node_modules", "semver"));
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const hasRange = input.range !== null;
const rangeValid = !hasRange || semver.validRange(input.range) !== null;
const validVersions = input.versions.map(version => semver.valid(version) !== null);
const matches = rangeValid
  ? input.versions.map((version, index) =>
      validVersions[index] &&
      (!hasRange || semver.satisfies(version, input.range)))
  : [];
process.stdout.write(JSON.stringify({ range_valid: rangeValid, valid_versions: validVersions, matches }));
"""

_NODEJS_STATUS_FLAGS = ("enabled", "licensed", "available", "usable", "configured")


def _project_directory(project: str) -> str:
    path = Path(project)
    return str(path if path.is_dir() else path.parent)


def _project_node_requirement(project: str, warnings: List[str], actions: List[str]) -> Tuple[Optional[str], bool]:
    directory = Path(project)
    package_path = directory / "package.json"
    lock_path = directory / "package-lock.json"
    for path in (package_path, lock_path):
        if path.is_symlink():
            warnings.append(f"{path.name} is a symlink; refusing to read it.")
            actions.append(f"Replace the symlinked {path.name} with a regular file before deploying Node.js content.")
            return None, False

    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        warnings.append(f"Could not read package.json: {err}")
        actions.append("Repair package.json before deploying Node.js content.")
        return None, False

    if not isinstance(package, dict):
        warnings.append("package.json must contain a JSON object.")
        actions.append("Repair package.json before deploying Node.js content.")
        return None, False
    package = cast(Dict[str, Any], package)

    engines = package.get("engines")
    if "engines" in package and not isinstance(engines, dict):
        warnings.append("package.json engines must be an object.")
        actions.append("Repair package.json engines metadata before deploying.")
        return None, False

    if not isinstance(engines, dict):
        return None, True
    engines = cast(Dict[str, Any], engines)
    if "node" not in engines:
        return None, True
    requirement = engines["node"]
    if not isinstance(requirement, str):
        warnings.append("package.json engines.node must be a string.")
        actions.append("Repair package.json engines.node before deploying.")
        return None, False
    return requirement, True


def _local_node_version(project: str, node: Optional[str], warnings: List[str], actions: List[str]) -> Optional[str]:
    try:
        return NodeEnvironment.create(project, node_executable=node).node_version
    except (RSConnectException, OSError, UnicodeDecodeError) as err:
        warnings.append(f"Could not inspect local Node.js/npm prerequisites: {err}")
        actions.append("Install Node.js and npm, and ensure package.json and package-lock.json are available.")
        return None


def _is_npm_installation(npm_cli: Path) -> bool:
    npm_root = npm_cli.parent.parent
    if npm_cli.name != "npm-cli.js" or npm_root.name != "npm":
        return False
    try:
        npm_metadata = json.loads((npm_root / "package.json").read_text(encoding="utf-8"))
        semver_metadata = json.loads(
            (npm_root / "node_modules" / "semver" / "package.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(npm_metadata, dict) or not isinstance(semver_metadata, dict):
        return False
    npm_package = cast(Dict[str, Any], npm_metadata)
    semver_package = cast(Dict[str, Any], semver_metadata)
    return npm_package.get("name") == "npm" and semver_package.get("name") == "semver"


def _npm_cli_path() -> Optional[str]:
    npm = shutil.which("npm")
    if not npm:
        return None
    if os.name == "nt":
        npm_cli = Path(npm).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    else:
        npm_cli = Path(os.path.realpath(npm))
    return str(npm_cli) if npm_cli.is_file() and _is_npm_installation(npm_cli) else None


def _parse_node_evaluation(stdout: str, version_count: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        evaluation = json.loads(stdout)
    except json.JSONDecodeError as err:
        return None, f"npm's semver evaluator returned invalid output: {err}"
    if not isinstance(evaluation, dict):
        return None, "npm's semver evaluator returned incomplete output."
    evaluation = cast(Dict[str, Any], evaluation)
    if (
        not isinstance(evaluation.get("range_valid"), bool)
        or not isinstance(evaluation.get("valid_versions"), list)
        or not isinstance(evaluation.get("matches"), list)
    ):
        return None, "npm's semver evaluator returned incomplete output."
    valid_versions = cast(List[Any], evaluation["valid_versions"])
    matches = cast(List[Any], evaluation["matches"])
    if not _valid_node_results(evaluation["range_valid"], valid_versions, matches, version_count):
        return None, "npm's semver evaluator returned incomplete version results."
    return evaluation, None


def _valid_node_results(range_valid: bool, valid_versions: List[Any], matches: List[Any], version_count: int) -> bool:
    if len(valid_versions) != version_count:
        return False
    if any(not isinstance(value, bool) for value in valid_versions + matches):
        return False
    if range_valid:
        return len(matches) == version_count
    return not matches


def _evaluate_node_range(
    node: str, requirement: Optional[str], versions: List[str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    npm_cli = _npm_cli_path()
    if npm_cli is None:
        return None, "Could not locate npm's local semver module."

    try:
        result = subprocess.run(
            [node, "-e", _SEMVER_SCRIPT, npm_cli],
            input=json.dumps({"range": requirement, "versions": versions}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as err:
        return None, f"Could not run npm's semver evaluator: {err}"

    if result.returncode != 0:
        detail = result.stderr.strip()[:400]
        return None, f"Could not load npm's semver module: {detail or result.returncode}"

    return _parse_node_evaluation(result.stdout, len(versions))


def _server_status(value: Any, warnings: List[str]) -> Tuple[Optional[Dict[str, Any]], bool]:
    if not isinstance(value, MappingABC):
        warnings.append("Connect did not return Node.js status metadata; compatibility is unknown.")
        return None, False
    status = dict(cast(Mapping[str, Any], value))
    complete = True
    for field in _NODEJS_STATUS_FLAGS:
        if field not in status:
            continue
        if not isinstance(status[field], bool):
            warnings.append(f"Connect returned an invalid Node.js {field} status flag.")
            complete = False
        elif status[field] is False:
            warnings.append(f"Connect reports Node.js is not {field}.")
    return status, complete


def _server_installations(value: Any, warnings: List[str]) -> Tuple[List[Tuple[str, Optional[bool]]], bool, bool]:
    if not isinstance(value, list):
        warnings.append("Connect did not return Node.js installations; compatibility is unknown.")
        return [], False, False
    installations: List[Tuple[str, Optional[bool]]] = []
    metadata_complete = True
    publishability_complete = True
    for raw_item in cast(List[Any], value):
        if not isinstance(raw_item, MappingABC):
            metadata_complete = False
            publishability_complete = False
            warnings.append("Connect returned an invalid Node.js installation record.")
            continue
        item = cast(Mapping[str, Any], raw_item)
        version = item.get("version")
        if not isinstance(version, str) or not version:
            metadata_complete = False
            publishability_complete = False
            warnings.append("Connect returned a Node.js installation without a version.")
            continue
        publishable = item.get("publishable")
        if not isinstance(publishable, bool):
            publishability_complete = False
            warnings.append(f"Connect did not report whether Node.js {version} is publishable.")
            publishable = None
        installations.append((version, publishable))
    return installations, metadata_complete, publishability_complete


def _server_nodejs_info(settings: Any, warnings: List[str]) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "enabled": None,
        "status": None,
        "installations": [],
        "metadata_complete": False,
        "publishability_complete": False,
    }
    if not isinstance(settings, MappingABC):
        warnings.append("Connect did not return Node.js settings; compatibility is unknown.")
        return info

    settings = cast(Mapping[str, Any], settings)
    enabled = settings.get("enabled")
    if not isinstance(enabled, bool):
        warnings.append("Connect did not report whether Node.js is enabled; compatibility is unknown.")
    status, status_complete = _server_status(settings.get("status"), warnings)
    installations, installations_complete, publishability_complete = _server_installations(
        settings.get("installations"), warnings
    )
    info["enabled"] = enabled if isinstance(enabled, bool) else None
    info["status"] = status
    info["installations"] = installations
    info["metadata_complete"] = isinstance(enabled, bool) and status_complete and installations_complete
    info["publishability_complete"] = publishability_complete
    return info


def _nodejs_status_failures(info: Dict[str, Any]) -> List[str]:
    status = info["status"]
    if not isinstance(status, MappingABC):
        return []
    status = cast(Mapping[str, Any], status)
    return [field for field in _NODEJS_STATUS_FLAGS if status.get(field) is False]


def _eligible_installations(installations: List[Tuple[str, Optional[bool]]], is_new: bool) -> List[int]:
    return [index for index, (_, publishable) in enumerate(installations) if not is_new or publishable is True]


def _valid_node_evaluation(evaluation: Optional[Dict[str, Any]]) -> bool:
    return evaluation is not None and evaluation["range_valid"]


def _has_matching_installation(indices: List[int], evaluation: Dict[str, Any]) -> bool:
    valid_versions = evaluation["valid_versions"]
    matches = evaluation["matches"]
    return any(valid_versions[index] and matches[index] for index in indices)


def _unmatched_server_compatibility(
    indices: List[int], is_new: bool, info: Dict[str, Any], evaluation: Dict[str, Any]
) -> str:
    versions_complete = all(evaluation["valid_versions"][index] for index in indices)
    flags_complete = info["publishability_complete"] or not is_new
    return "incompatible" if versions_complete and flags_complete else "unknown"


def _server_compatibility(info: Dict[str, Any], is_new: bool, evaluation: Optional[Dict[str, Any]]) -> str:
    if info["enabled"] is False or _nodejs_status_failures(info):
        return "incompatible"
    if info["enabled"] is not True or not info["metadata_complete"]:
        return "unknown"

    installations = info["installations"]
    indices = _eligible_installations(installations, is_new)
    flags_complete = info["publishability_complete"] or not is_new
    if not indices:
        return "incompatible" if flags_complete else "unknown"
    if not _valid_node_evaluation(evaluation):
        return "unknown"
    if _has_matching_installation(indices, cast(Dict[str, Any], evaluation)):
        return "compatible"
    return _unmatched_server_compatibility(indices, is_new, info, cast(Dict[str, Any], evaluation))


def _existing_content_version(
    client: RSConnectClient, app_id: str, warnings: List[str], actions: List[str]
) -> Tuple[Optional[str], bool]:
    try:
        content = client.get_content_by_id(app_id)
    except RSConnectException as err:
        warnings.append(f"Could not read existing content's Node.js version: {err}")
        if err.status == 404:
            actions.append("Use --new to publish as new content, or verify the existing content ID.")
        else:
            actions.append("Verify the existing content ID and your permission to read it.")
        return None, False
    if not isinstance(content, MappingABC):
        warnings.append("Connect returned invalid metadata for existing content.")
        actions.append("Check the existing content ID and retry preflight.")
        return None, False
    value = cast(Mapping[str, Any], content).get("node_version")
    return (value if isinstance(value, str) else None), True


def _existing_content(
    client: RSConnectClient,
    exists: bool,
    app_id: Optional[str],
    compatibility: str,
    warnings: List[str],
    actions: List[str],
    target_issue: Optional[str],
) -> Tuple[Dict[str, Any], bool]:
    node_version = None
    readable = not exists
    if exists and app_id:
        node_version, readable = _existing_content_version(client, app_id, warnings, actions)
    elif exists and not target_issue:
        warnings.append("The existing deployment has no content ID to inspect.")
        actions.append("Use --new or provide a valid content ID before checking a redeployment.")
    return {
        "exists": exists,
        "app_id": app_id,
        "node_version": node_version,
        "compatibility": compatibility if readable and exists else ("unknown" if exists else "not_applicable"),
    }, readable


def _validated_executor(executor: RSConnectExecutor) -> Tuple[Any, RSConnectClient]:
    server = executor.remote_server
    if isinstance(server, ConnectCloudServer) or not isinstance(server, (RSConnectServer, SPCSConnectServer)):
        raise RSConnectException("Node.js preflight supports self-hosted Posit Connect and Connect in SPCS.")
    if executor.new and executor.app_id:
        raise RSConnectException("Specify either a new deploy or an app ID but not both.")
    client = executor.client
    if not isinstance(client, RSConnectClient):
        raise RSConnectException("Node.js preflight requires a self-hosted Connect client.")
    return server, client


def _read_server_nodejs_info(client: RSConnectClient, warnings: List[str], actions: List[str]) -> Dict[str, Any]:
    try:
        settings = client.nodejs_settings()
    except RSConnectException as err:
        warnings.append(f"Could not read server Node.js settings: {err}")
        actions.append("Check whether this Connect server exposes Node.js runtime settings.")
        settings = None
    return _server_nodejs_info(settings, warnings)


def _evaluate_project_range(
    node: str,
    requirement: Optional[str],
    versions: List[str],
    project_metadata_valid: bool,
    warnings: List[str],
    actions: List[str],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not project_metadata_valid:
        return None, None
    evaluation, error = _evaluate_node_range(node, requirement, versions)
    if error:
        warnings.append(error)
        actions.append("Verify the local Node.js and npm installation before checking engines.node.")
    elif evaluation is not None and not evaluation["range_valid"]:
        warnings.append(f"package.json engines.node {requirement!r} is not a valid npm semver range.")
        actions.append("Repair package.json engines.node before deploying.")
    return evaluation, error


def _project_details(
    project: str, node: Optional[str], warnings: List[str], actions: List[str]
) -> Tuple[str, Optional[str], bool, Optional[str]]:
    directory = _project_directory(project)
    requirement, metadata_valid = _project_node_requirement(directory, warnings, actions)
    local_node = _local_node_version(directory, node, warnings, actions) if metadata_valid else None
    return directory, requirement, metadata_valid, local_node


def _local_checks_complete(
    metadata_valid: bool,
    local_node: Optional[str],
    evaluation: Optional[Dict[str, Any]],
    evaluation_error: Optional[str],
) -> bool:
    return (
        metadata_valid
        and local_node is not None
        and evaluation_error is None
        and evaluation is not None
        and evaluation["range_valid"]
    )


def _add_status_failure_actions(info: Dict[str, Any], actions: List[str]) -> List[str]:
    failures = _nodejs_status_failures(info)
    if info["enabled"] is False:
        actions.append("Enable Node.js on the Connect server before publishing.")
    if "enabled" in failures:
        actions.append("Enable Node.js in the Connect server settings before publishing.")
    if "configured" in failures:
        actions.append("Configure Node.js on the Connect server before publishing.")
    if "licensed" in failures:
        actions.append("Check or update the Connect license to include Node.js support.")
    if "available" in failures or "usable" in failures:
        actions.append("Make a supported Node.js runtime available and usable on Connect before publishing.")
    return failures


def _add_server_advice(
    info: Dict[str, Any],
    compatibility: str,
    exists: bool,
    warnings: List[str],
    actions: List[str],
) -> None:
    failures = _add_status_failure_actions(info, actions)
    if info["enabled"] is False or failures or compatibility != "incompatible":
        return
    if exists:
        warnings.append("No installed server Node.js version satisfies package.json engines.node.")
        actions.append("Align package.json engines.node with an installed server version before redeploying.")
    else:
        warnings.append("No publishable server Node.js version satisfies this new content.")
        actions.append("Choose a supported engines.node range or mark a server version publishable.")


def _reported_status(
    compatibility: str,
    enabled: Optional[bool],
    local_checks_complete: bool,
    target_resolved: bool,
    content_readable: bool,
) -> str:
    if not target_resolved or not content_readable:
        return "unknown"
    if enabled is False or compatibility == "incompatible":
        return "incompatible"
    if not local_checks_complete:
        return "unknown"
    return "ok" if compatibility == "compatible" else compatibility


def run_node_preflight(executor: RSConnectExecutor, project: str, node: Optional[str] = None) -> Dict[str, Any]:
    """Check Node.js project metadata against a validated Connect executor."""
    server, client = _validated_executor(executor)
    warnings: List[str] = []
    actions: List[str] = []
    target = project
    _, requirement, project_metadata_valid, local_node = _project_details(project, node, warnings, actions)
    info = _read_server_nodejs_info(client, warnings, actions)
    installations = info["installations"]
    versions = [version for version, _ in installations]
    evaluation, evaluation_error = _evaluate_project_range(
        node or "node", requirement, versions, project_metadata_valid, warnings, actions
    )

    exists, app_id, target_issue = _deployment_target(executor, target)
    if target_issue:
        warnings.append(target_issue)
        actions.append("Resolve the local deployment record with --app-id or use --new for a separate content item.")
    compatibility = "unknown" if target_issue else _server_compatibility(info, not exists, evaluation)
    existing_content, content_readable = _existing_content(
        client, exists, app_id, compatibility, warnings, actions, target_issue
    )
    if not content_readable:
        compatibility = "unknown"
        existing_content["compatibility"] = "unknown"
    status = _reported_status(
        compatibility,
        info["enabled"],
        _local_checks_complete(project_metadata_valid, local_node, evaluation, evaluation_error),
        target_issue is None,
        content_readable,
    )
    _add_server_advice(info, compatibility, exists, warnings, actions)
    server_node_versions = [version for version, _ in installations]
    publishable_versions = [version for version, publishable in installations if publishable is True]
    return {
        "status": status,
        "runtime": "nodejs",
        "server": server.url,
        "local_node": local_node,
        "node_requires": requirement,
        "server_node_versions": server_node_versions,
        "publishable_node_versions": publishable_versions,
        "nodejs_enabled": info["enabled"],
        "nodejs_status": info["status"],
        "existing_content": existing_content,
        "changed_files": [],
        "warnings": warnings,
        "actions": actions,
    }
