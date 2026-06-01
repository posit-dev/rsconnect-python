"""
Public API for managing execution environments on Posit Connect.
"""

from __future__ import annotations

from typing import Optional, Union

from .api import RSConnectClient, RSConnectServer, SPCSConnectServer
from .models import (
    EnvironmentCreateInput,
    EnvironmentInstallation,
    EnvironmentInstallations,
    EnvironmentPermissionInput,
    EnvironmentPermissionV1,
    EnvironmentUpdateInput,
    EnvironmentV1,
    EnvironmentVolumeMount,
)


def list_environments(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
) -> list[EnvironmentV1]:
    with RSConnectClient(connect_server) as client:
        return client.environment_list()


def get_environment(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
) -> EnvironmentV1:
    with RSConnectClient(connect_server) as client:
        return client.environment_get(guid)


def create_environment(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    image: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    matching: Optional[str] = None,
    supervisor: Optional[str] = None,
    python: Optional[list[EnvironmentInstallation]] = None,
    quarto: Optional[list[EnvironmentInstallation]] = None,
    r: Optional[list[EnvironmentInstallation]] = None,
    tensorflow: Optional[list[EnvironmentInstallation]] = None,
    volume_mounts: Optional[list[EnvironmentVolumeMount]] = None,
    user_guids: Optional[list[str]] = None,
    group_guids: Optional[list[str]] = None,
) -> EnvironmentV1:
    body: EnvironmentCreateInput = {
        "cluster_name": "Kubernetes",
        "name": image,
    }
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if matching is not None:
        body["matching"] = matching
    if supervisor is not None:
        body["supervisor"] = supervisor
    if python is not None:
        body["python"] = _make_installations(python)
    if quarto is not None:
        body["quarto"] = _make_installations(quarto)
    if r is not None:
        body["r"] = _make_installations(r)
    if tensorflow is not None:
        body["tensorflow"] = _make_installations(tensorflow)
    if volume_mounts is not None:
        body["volume_mounts"] = volume_mounts

    with RSConnectClient(connect_server) as client:
        result = client.environment_create(body)
        if user_guids is not None or group_guids is not None:
            _sync_permissions(client, result["guid"], user_guids, group_guids)
        return client.environment_get(result["guid"])


def update_environment(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    matching: Optional[str] = None,
    supervisor: Optional[str] = None,
    python: Optional[list[EnvironmentInstallation]] = None,
    quarto: Optional[list[EnvironmentInstallation]] = None,
    r: Optional[list[EnvironmentInstallation]] = None,
    tensorflow: Optional[list[EnvironmentInstallation]] = None,
    volume_mounts: Optional[list[EnvironmentVolumeMount]] = None,
    user_guids: Optional[list[str]] = None,
    group_guids: Optional[list[str]] = None,
) -> EnvironmentV1:
    with RSConnectClient(connect_server) as client:
        existing = client.environment_get(guid)

        body: EnvironmentUpdateInput = {
            "title": title if title is not None else existing["title"],
            "description": description if description is not None else existing["description"],
            "matching": matching if matching is not None else existing["matching"],
            "supervisor": supervisor if supervisor is not None else existing["supervisor"],
            "python": _make_installations(python) if python is not None else existing["python"],
            "quarto": _make_installations(quarto) if quarto is not None else existing["quarto"],
            "r": _make_installations(r) if r is not None else existing["r"],
            "tensorflow": _make_installations(tensorflow) if tensorflow is not None else existing["tensorflow"],
            "volume_mounts": volume_mounts if volume_mounts is not None else existing["volume_mounts"],
        }

        result = client.environment_update(guid, body)

        if user_guids is not None or group_guids is not None:
            _sync_permissions(client, guid, user_guids, group_guids)
            return client.environment_get(guid)

        return result


def delete_environment(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
) -> None:
    with RSConnectClient(connect_server) as client:
        client.environment_delete(guid)


def _make_installations(items: list[EnvironmentInstallation]) -> EnvironmentInstallations:
    return {"installations": items}


def _sync_permissions(
    client: RSConnectClient,
    env_guid: str,
    user_guids: Optional[list[str]],
    group_guids: Optional[list[str]],
) -> list[EnvironmentPermissionV1]:
    existing = client.environment_permission_list(env_guid)

    desired_users = set(user_guids or [])
    desired_groups = set(group_guids or [])

    existing_users = {p["user_guid"]: p for p in existing if p["user_guid"] is not None}
    existing_groups = {p["group_guid"]: p for p in existing if p["group_guid"] is not None}

    results: list[EnvironmentPermissionV1] = []
    for g in desired_users - set(existing_users.keys()):
        body: EnvironmentPermissionInput = {"user_guid": g}
        results.append(client.environment_permission_add(env_guid, body))
    for g in desired_groups - set(existing_groups.keys()):
        body = {"group_guid": g}
        results.append(client.environment_permission_add(env_guid, body))

    for g in set(existing_users.keys()) - desired_users:
        client.environment_permission_delete(env_guid, existing_users[g]["guid"])
    for g in set(existing_groups.keys()) - desired_groups:
        client.environment_permission_delete(env_guid, existing_groups[g]["guid"])

    return results
