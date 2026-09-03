"""Shared fixtures for the target-selection tests.

Used by test_connect_cloud.py, test_validation.py, and test_target_inference.py:
the executor resolves a target before it knows which service it is talking to, so
the same store, click-context, and CLI-introspection helpers serve all three.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import pathlib
import tempfile
from typing import Any, Dict, Optional
from unittest import mock

import click
import httpretty
from click.core import ParameterSource

from rsconnect import api
from rsconnect import main as rsconnect_main
from rsconnect.api import ConnectCloudServer, RSConnectExecutor
from rsconnect.main import cli
from rsconnect.metadata import ServerData, ServerStore

ENV = ParameterSource.ENVIRONMENT
TYPED = ParameterSource.COMMANDLINE
DEFAULT = ParameterSource.DEFAULT


API = "https://api.connect.posit.cloud/v1"


def _ctx(**sources: ParameterSource) -> click.Context:
    """A click context recording where each named parameter's value came from.

    Each name is declared as an option, since validation distinguishes options
    from same-named arguments.
    """
    params: list[click.Parameter] = [click.Option(["--%s" % param.replace("_", "-")]) for param in sources]
    ctx = click.Context(click.Command("deploy", params=params))
    for param, source in sources.items():
        ctx.set_parameter_source(param, source)  # pyright: ignore[reportAttributeAccessIssue]
    return ctx


def _deploy_option_flags() -> Dict[str, set[frozenset[str]]]:
    """The flags each `deploy` subcommand option is spelled with, by parameter name."""
    flags: Dict[str, set[frozenset[str]]] = {}
    for command in cli.commands["deploy"].commands.values():
        for param in command.params:
            if isinstance(param, click.Option) and param.name:
                flags.setdefault(param.name, set()).add(frozenset(param.opts + param.secondary_opts))
    return flags


def _commands_defined_in_main(group: Any) -> dict[str, Any]:
    """Return subcommands declared in main.py, excluding test registrations."""
    return {
        name: command
        for name, command in sorted(group.commands.items())
        if getattr(command.callback, "__module__", None) == rsconnect_main.__name__
    }


def _executor_keywords(callback: Any) -> list[set[str]]:
    """Return keyword names passed to executors in a command callback."""
    tree = ast.parse(pathlib.Path(rsconnect_main.__file__).read_text())
    functions = {
        node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    node = functions.get(callback.__name__)
    assert node is not None, "no source found for %s" % callback.__name__

    def builds_an_executor(call: ast.Call) -> bool:
        # Include deploy html's fromConnectServer branch.
        if isinstance(call.func, ast.Name):
            return call.func.id == "RSConnectExecutor"
        return (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and (call.func.value.id == "RSConnectExecutor")
        )

    return [
        {keyword.arg for keyword in call.keywords if keyword.arg}
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and builds_an_executor(call)
    ]


def _json_response(payload: Any, status: int = 200) -> Any:
    return httpretty.Response(
        body=json.dumps(payload), adding_headers={"Content-Type": "application/json"}, status=status
    )


def _register_json(method: Any, url: str, payload: Any, status: int = 200) -> None:
    httpretty.register_uri(
        method, url, body=json.dumps(payload), adding_headers={"Content-Type": "application/json"}, status=status
    )


def _register_pages(url: str, *pages: Any) -> None:
    httpretty.register_uri(httpretty.GET, url, responses=[_json_response(p) for p in pages])


def _register_accounts(*accounts: Any) -> None:
    _register_json(httpretty.GET, f"{API}/accounts", {"data": list(accounts), "total": len(accounts)})


def _cloud_entry(**fields: Any) -> ServerData:
    """A resolved store entry for a saved Connect Cloud server named "cloud"."""
    fields.setdefault("connect_cloud_account_name", "acme")
    return ServerData("cloud", API, True, **fields)


def _store_with_cloud_entry(**fields: Any) -> ServerStore:
    """A temp-dir ServerStore holding one saved Connect Cloud server named "cloud"."""
    store = ServerStore(base_dir=tempfile.mkdtemp())
    fields.setdefault("connect_cloud_account_name", "acme")
    fields.setdefault("connect_cloud_access_token", "at")
    store.set("cloud", API, **fields)
    return store


def _setup_remote_server(
    ctx: Optional[click.Context] = None,
    store: Optional[ServerStore] = None,
    resolve: Optional[ServerData] = None,
    default: Optional[ServerData] = None,
    has_cloud_account: Optional[bool] = None,
    environ: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> RSConnectExecutor:
    """Run setup_remote_server on a bare executor with the store interactions mocked.

    `store` replaces the ServerStore the executor opens; `resolve` short-circuits
    the lookup with a prepared entry; `default` additionally makes that entry the
    default server. `environ` replaces os.environ for the call.
    """
    executor = RSConnectExecutor.__new__(RSConnectExecutor)
    executor.logger = None
    executor.ctx = None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(api.RSConnectExecutor, "setup_client"))
        if store is not None:
            stack.enter_context(mock.patch("rsconnect.api.ServerStore", return_value=store))
        if default is not None:
            resolve = default
            stack.enter_context(mock.patch.object(ServerStore, "get_default", return_value={"name": default.name}))
        if resolve is not None:
            stack.enter_context(mock.patch.object(ServerStore, "resolve", return_value=resolve))
        if has_cloud_account is not None:
            stack.enter_context(
                mock.patch.object(ServerStore, "has_connect_cloud_account", return_value=has_cloud_account)
            )
        if environ is not None:
            stack.enter_context(mock.patch.dict(os.environ, environ, clear=True))
        executor.setup_remote_server(ctx=ctx, **kwargs)
    return executor


def _cloud_server(**kwargs: Any) -> ConnectCloudServer:
    """Like _setup_remote_server, but returns the resulting ConnectCloudServer."""
    server = _setup_remote_server(**kwargs).remote_server
    assert isinstance(server, ConnectCloudServer)
    return server
