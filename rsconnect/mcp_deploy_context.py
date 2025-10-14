"""
Programmatically discover all parameters for rsconnect commands.
This helps MCP tools understand how to use the cli.
"""

import json
from typing import Any, Dict

import click


def extract_parameter_info(param: click.Parameter) -> Dict[str, Any]:
    """Extract detailed information from a Click parameter."""
    info: Dict[str, Any] = {}

    if isinstance(param, click.Option) and param.opts:
        # Use the longest option name (usually the full form without dashes)
        mcp_arg_name = max(param.opts, key=len).lstrip("-").replace("-", "_")
        info["name"] = mcp_arg_name
        info["cli_flags"] = param.opts
        info["param_type"] = "option"
    else:
        info["name"] = param.name
        if isinstance(param, click.Argument):
            info["param_type"] = "argument"

    # extract help text for added context
    help_text = getattr(param, "help", None)
    if help_text:
        info["description"] = help_text

    if isinstance(param, click.Option):
        # Boolean flags
        if param.is_flag:
            info["type"] = "boolean"
            info["default"] = param.default or False

        # choices
        elif param.type and hasattr(param.type, "choices"):
            info["type"] = "string"
            info["choices"] = list(param.type.choices)

        # multiple
        elif param.multiple:
            info["type"] = "array"
            info["items"] = {"type": "string"}

        # files
        elif isinstance(param.type, click.Path):
            info["type"] = "string"
            info["format"] = "path"
            if param.type.exists:
                info["path_must_exist"] = True
            if param.type.file_okay and not param.type.dir_okay:
                info["path_type"] = "file"
            elif param.type.dir_okay and not param.type.file_okay:
                info["path_type"] = "directory"

        # default
        else:
            info["type"] = "string"

        # defaults (important to avoid noise in returned command)
        if param.default is not None and not param.is_flag:
            if isinstance(param.default, tuple):
                info["default"] = list(param.default)
            elif isinstance(param.default, (str, int, float, bool, list, dict)):
                info["default"] = param.default

    # required params
    info["required"] = param.required

    return info


def discover_single_command(cmd: click.Command) -> Dict[str, Any]:
    """Discover a single command and its parameters."""
    cmd_info = {"name": cmd.name, "description": cmd.help, "parameters": []}

    for param in cmd.params:
        if param.name in ["verbose", "v"]:
            continue

        param_info = extract_parameter_info(param)
        cmd_info["parameters"].append(param_info)

    return cmd_info


def discover_command_group(group: click.Group) -> Dict[str, Any]:
    """Discover all commands in a command group and their parameters."""
    result = {"name": group.name, "description": group.help, "commands": {}}

    for cmd_name, cmd in group.commands.items():
        if isinstance(cmd, click.Group):
            # recursively discover nested command groups
            result["commands"][cmd_name] = discover_command_group(cmd)
        else:
            result["commands"][cmd_name] = discover_single_command(cmd)

    return result


def discover_all_commands(cli: click.Group) -> Dict[str, Any]:
    """Discover all commands in the CLI and their parameters."""
    return discover_command_group(cli)


if __name__ == "__main__":
    from rsconnect.main import cli

    # Discover all commands in the CLI
    # use this for testing/debugging
    all_commands = discover_all_commands(cli)
    print(json.dumps(all_commands, indent=2))
