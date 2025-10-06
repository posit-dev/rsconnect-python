"""
Programmatically discover all parameters for rsconnect deploy commands.
This helps MCP tools understand exactly how to use `rsconnect deploy ...`
"""

import json
from typing import Any, Dict

import click


def extract_parameter_info(param: click.Parameter) -> Dict[str, Any]:
    """Extract detailed information from a Click parameter."""
    info: Dict[str, Any] = {}

    if isinstance(param, click.Option) and param.opts:
        # Use the longest option name (usually the full form without dashes)
        mcp_arg_name = max(param.opts, key=len).lstrip('-').replace('-', '_')
        info["name"] = mcp_arg_name
        info["cli_flags"] = param.opts
        info["param_type"] = "option"
    else:
        info["name"] = param.name
        if isinstance(param, click.Argument):
            info["param_type"] = "argument"

    # extract help text for added context
    help_text = getattr(param, 'help', None)
    if help_text:
        info["description"] = help_text

    if isinstance(param, click.Option):
        # Boolean flags
        if param.is_flag:
            info["type"] = "boolean"
            info["default"] = param.default or False

        # choices
        elif param.type and hasattr(param.type, 'choices'):
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
            info["default"] = param.default

    # required params
    info["required"] = param.required

    return info


def discover_deploy_commands(cli_group: click.Group) -> Dict[str, Any]:
    """Discover all deploy commands and their parameters."""

    if "deploy" not in cli_group.commands:
        return {"error": "deploy command group not found"}

    deploy_group = cli_group.commands["deploy"]

    if not isinstance(deploy_group, click.Group):
        return {"error": "deploy is not a command group"}

    result = {
        "group_name": "deploy",
        "description": deploy_group.help or "Deploy content to Posit Connect, Posit Cloud, or shinyapps.io.",
        "app_type": {}
    }

    for cmd_name, cmd in deploy_group.commands.items():
        cmd_info = {
            "name": cmd_name,
            "description": cmd.help or cmd.short_help or f"Deploy {cmd_name}",
            "short_help": cmd.short_help,
            "parameters": []
        }
        for param in cmd.params:
            if isinstance(param, click.Context):
                continue

            if param.name in ["verbose", "v"]:
                continue

            param_info = extract_parameter_info(param)
            cmd_info["parameters"].append(param_info)

        result["app_type"][cmd_name] = cmd_info

    return result


if __name__ == "__main__":
    from rsconnect.main import cli

    deploy_commands_info = discover_deploy_commands(cli)["app_type"]["shiny"]
    print(json.dumps(deploy_commands_info, indent=2))
