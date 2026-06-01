"""
Public API for managing execution environments on Posit Connect.
"""

from __future__ import annotations

from typing import Optional, Union

from .api import RSConnectClient, RSConnectServer, SPCSConnectServer
from .models import (
    EnvironmentCreateInput,
    EnvironmentPermissionInput,
    EnvironmentPermissionV1,
    EnvironmentUpdateInput,
    EnvironmentV1,
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
            "python": existing["python"],
            "quarto": existing["quarto"],
            "r": existing["r"],
            "tensorflow": existing["tensorflow"],
            "volume_mounts": existing["volume_mounts"],
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


def _sync_permissions(
    client: RSConnectClient,
    env_guid: str,
    user_guids: Optional[list[str]],
    group_guids: Optional[list[str]],
) -> list[EnvironmentPermissionV1]:
    existing = client.environment_permission_list(env_guid)
    for perm in existing:
        client.environment_permission_delete(env_guid, perm["guid"])

    results: list[EnvironmentPermissionV1] = []
    for g in user_guids or []:
        body: EnvironmentPermissionInput = {"user_guid": g}
        results.append(client.environment_permission_add(env_guid, body))
    for g in group_guids or []:
        body = {"group_guid": g}
        results.append(client.environment_permission_add(env_guid, body))
    return results
