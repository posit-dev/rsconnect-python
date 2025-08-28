import asyncio
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from typing import Any, Dict, List, Optional

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    print("MCP not available. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

import click

from .log import logger


class ClickToMCPConverter:
    """Converts Click CLI commands to MCP tools automatically"""

    def __init__(self, cli_group: click.Group, include_tools: Optional[List[str]] = None, exclude_tools: Optional[List[str]] = None):
        self.cli_group = cli_group
        self.include_tools = include_tools or []
        self.exclude_tools = exclude_tools or []
        self.tools: list[Tool] = []
        self._discover_commands()

    def _discover_commands(self):
        """Recursively discover all CLI commands and subcommands"""
        self._process_group(self.cli_group, "")

    def _process_group(self, group: click.Group, prefix: str):
        """Process a Click group and its commands"""
        for name, command in group.commands.items():
            full_name = f"{prefix}{name}" if prefix else name

            if isinstance(command, click.Group):
                # Process subcommands recursively
                self._process_group(command, f"{full_name}_")
            elif isinstance(command, click.Command):
                # Convert command to MCP tool
                tool = self._command_to_tool(command, full_name)
                if tool:
                    self.tools.append(tool)

    def _command_to_tool(self, command: click.Command, tool_name: str) -> Optional[Tool]:
        """Convert a Click command to an MCP tool"""
        try:
            # Check inclusion/exclusion filters
            if not self._should_include_tool(tool_name):
                return None

            # Skip certain commands that shouldn't be exposed
            skip_commands = {"mcp", "version"}
            if any(skip in tool_name for skip in skip_commands):
                return None

            # Get command help/description
            description = command.help or command.short_help or f"Execute {tool_name} command"

            # Build input schema from click parameters
            schema = self._build_schema_from_params(command.params)

            if tool_name == "list":
                print(schema)

            return Tool(
                name=tool_name,
                description=description,
                inputSchema=schema
            )
        except Exception as e:
            logger.debug(f"Failed to convert command {tool_name}: {e}")
            return None

    def _should_include_tool(self, tool_name: str) -> bool:
        """Check if a tool should be included based on include/exclude filters"""
        # If include_tools is specified, only include tools in that list
        if self.include_tools:
            return tool_name in self.include_tools

        # If exclude_tools is specified, exclude tools in that list
        if self.exclude_tools:
            return tool_name not in self.exclude_tools

        # By default, include all tools
        return True

    def _build_schema_from_params(self, params: List[click.Parameter]) -> Dict[str, Any]:
        """Build JSON schema from Click parameters"""
        properties = {}
        required = []

        for param in params:
            if isinstance(param, click.Context):
                continue

            if param.name in ["verbose", "v"]:
                continue

            param_name = param.name
            param_schema = {"type": "string"}  # Default type

            # Set description from help text
            help_text = getattr(param, 'help', None)
            if help_text:
                param_schema["description"] = help_text

            # Handle different parameter types
            if isinstance(param, click.Option):
                # Handle boolean flags
                if param.is_flag:
                    param_schema["type"] = "boolean"
                    param_schema["default"] = param.default or False

                # Handle choices
                elif param.type and hasattr(param.type, 'choices'):
                    param_schema["enum"] = list(param.type.choices)

                # Handle multiple values
                elif param.multiple:
                    param_schema = {
                        "type": "array",
                        "items": {"type": "string"}
                    }

                # Handle integer types
                elif isinstance(param.type, click.IntRange):
                    param_schema["type"] = "integer"
                    if param.type.min is not None:
                        param_schema["minimum"] = param.type.min
                    if param.type.max is not None:
                        param_schema["maximum"] = param.type.max

                # Handle file paths
                elif isinstance(param.type, click.Path):
                    param_schema["type"] = "string"
                    param_schema["description"] = f"File path{' (must exist)' if param.type.exists else ''}"

                # Set default value if available
                if param.default is not None and not param.is_flag:
                    param_schema["default"] = param.default

            elif isinstance(param, click.Argument):
                # Arguments are typically required
                if not param.required:
                    required.append(param_name)

            # Mark required parameters
            if param.required and param_name not in required:
                required.append(param_name)

            properties[param_name] = param_schema

        return {
            "type": "object",
            "properties": properties,
            "required": required
        }


class RSConnectMCPServer:
    def __init__(self, cli_group: click.Group, converter: ClickToMCPConverter):
        self.server = Server("rsconnect-python", version="0.0.1")
        self.cli_group = cli_group
        self.converter = converter
        self.setup_tools()

    def setup_tools(self):
        """Register all available tools dynamically"""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return self.converter.tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            try:
                result = await self._execute_cli_command(name, arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            except Exception as e:
                error_result = {"error": str(e), "tool": name, "arguments": arguments}
                return [TextContent(type="text", text=json.dumps(error_result, indent=2))]

    async def _execute_cli_command(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a CLI command with the given arguments"""
        try:
            # Find the command by traversing the CLI structure
            command = self._find_command(tool_name)
            if not command:
                return {"error": f"Command not found: {tool_name}"}

            # Build CLI arguments from the tool arguments
            cli_args = self._build_cli_args(command, arguments)

            # Capture stdout and stderr
            stdout_capture = StringIO()
            stderr_capture = StringIO()

            # Execute the command in a separate context
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                self._run_command_sync,
                command,
                cli_args,
                stdout_capture,
                stderr_capture
            )

            return result

        except Exception as e:
            return {"error": str(e), "tool": tool_name}

    def _find_command(self, tool_name: str) -> Optional[click.Command]:
        """Find a command by its tool name"""
        parts = tool_name.split("_")
        current = self.cli_group

        for part in parts:
            if isinstance(current, click.Group) and part in current.commands:
                current = current.commands[part]
            else:
                return None

        return current if isinstance(current, click.Command) else None

    def _build_cli_args(self, command: click.Command, arguments: Dict[str, Any]) -> List[str]:
        """Build CLI argument list from tool arguments"""
        args = []

        for param in command.params:
            if param.name in arguments:
                value = arguments[param.name]

                if isinstance(param, click.Option):
                    # Handle option parameters
                    if param.is_flag and value:
                        args.append(f"--{param.name.replace('_', '-')}")
                    elif not param.is_flag and value is not None:
                        args.extend([f"--{param.name.replace('_', '-')}", str(value)])
                    elif param.multiple and isinstance(value, list):
                        for v in value:
                            args.extend([f"--{param.name.replace('_', '-')}", str(v)])

                elif isinstance(param, click.Argument):
                    # Handle positional arguments
                    if isinstance(value, list):
                        args.extend([str(v) for v in value])
                    else:
                        args.append(str(value))

        return args

    def _run_command_sync(self, command: click.Command, args: List[str],
                         stdout_capture: StringIO, stderr_capture: StringIO) -> Dict[str, Any]:
        """Run a CLI command synchronously and capture output"""
        try:
            # Create a new Click context
            ctx = command.make_context(command.name, args)

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                try:
                    with ctx:
                        # Call the command function
                        rv = command.invoke(ctx)

                        return {
                            "success": True,
                            "command": command.name,
                            "arguments": args,
                            "ctx_params": ctx.params,
                            "stdout": stdout_capture.getvalue(),
                            "stderr": stderr_capture.getvalue(),
                            "return_value": rv
                        }

                except click.ClickException as e:
                    return {
                        "success": False,
                        "error": str(e),
                        "stacktrace": traceback.format_exc(),
                        "stdout": stdout_capture.getvalue(),
                        "stderr": stderr_capture.getvalue()
                    }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "stacktrace": traceback.format_exc(),
                "stdout": stdout_capture.getvalue(),
                "stderr": stderr_capture.getvalue()
            }

    async def run(self):
        """Run the MCP server"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


async def run_mcp_server():
    """Entry point for running the MCP server"""
    from .main import cli  # Import the main CLI group

    server = RSConnectMCPServer(cli, ClickToMCPConverter(cli))
    await server.run()
