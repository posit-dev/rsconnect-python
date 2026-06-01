"""
Public API for managing OAuth integrations on Posit Connect.
"""

from __future__ import annotations

from typing import Optional, Union

from .api import RSConnectClient, RSConnectServer, SPCSConnectServer
from .models import (
    OAuthIntegration,
    OAuthIntegrationInput,
    OAuthIntegrationPermission,
    OAuthIntegrationUpdate,
    OAuthTemplate,
)


def list_oauth_integrations(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
) -> list[OAuthIntegration]:
    with RSConnectClient(connect_server) as client:
        return client.oauth_integration_list()


def get_oauth_integration(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
) -> OAuthIntegration:
    with RSConnectClient(connect_server) as client:
        return client.oauth_integration_get(guid)


def create_oauth_integration(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    template: str,
    config: dict[str, object],
    name: Optional[str] = None,
    description: Optional[str] = None,
    user_guids: Optional[list[str]] = None,
    group_guids: Optional[list[str]] = None,
) -> OAuthIntegration:
    permissions: list[OAuthIntegrationPermission] = []
    for g in user_guids or []:
        permissions.append({"user_guid": g, "group_guid": None})
    for g in group_guids or []:
        permissions.append({"user_guid": None, "group_guid": g})

    body: OAuthIntegrationInput = {
        "template": template,
        "config": config,
    }
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if permissions:
        body["permissions"] = permissions

    with RSConnectClient(connect_server) as client:
        return client.oauth_integration_create(body)


def update_oauth_integration(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
    config: Optional[dict[str, object]] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    user_guids: Optional[list[str]] = None,
    group_guids: Optional[list[str]] = None,
) -> OAuthIntegration:
    with RSConnectClient(connect_server) as client:
        body: OAuthIntegrationUpdate = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if config is not None:
            existing = client.oauth_integration_get(guid)
            merged_config = dict(existing["config"])
            merged_config.update(config)
            body["config"] = merged_config

        permissions: list[OAuthIntegrationPermission] = []
        if user_guids:
            for g in user_guids:
                permissions.append({"user_guid": g, "group_guid": None})
        if group_guids:
            for g in group_guids:
                permissions.append({"user_guid": None, "group_guid": g})
        if permissions:
            body["permissions"] = permissions

        return client.oauth_integration_update(guid, body)


def delete_oauth_integration(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    guid: str,
) -> None:
    with RSConnectClient(connect_server) as client:
        client.oauth_integration_delete(guid)


def list_oauth_templates(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
) -> list[OAuthTemplate]:
    with RSConnectClient(connect_server) as client:
        return client.oauth_template_list()


def get_oauth_template(
    connect_server: Union[RSConnectServer, SPCSConnectServer],
    key: str,
) -> OAuthTemplate:
    with RSConnectClient(connect_server) as client:
        return client.oauth_template_get(key)
