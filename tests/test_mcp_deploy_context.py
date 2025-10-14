"""Tests for MCP deploy context."""

from unittest import TestCase

from rsconnect.main import cli
from rsconnect.mcp_deploy_context import discover_all_commands


class TestDiscoverAllCommands(TestCase):
    def test_discover_rsconnect_cli(self):
        result = discover_all_commands(cli)

        self.assertIn("commands", result)
        self.assertIsNotNone(result["description"])

    def test_top_level_commands(self):
        result = discover_all_commands(cli)

        expected = ["version", "mcp-server", "add", "list", "remove", "details", "info", "deploy", "write-manifest", "content", "system", "bootstrap"]
        for cmd in expected:
            self.assertIn(cmd, result["commands"])

    def test_deploy_is_command_group(self):
        result = discover_all_commands(cli)
        self.assertIn("commands", result["commands"]["deploy"])

    def test_deploy_subcommands(self):
        result = discover_all_commands(cli)

        deploy = result["commands"]["deploy"]
        expected = ["notebook", "voila", "manifest", "quarto", "tensorflow", "html", "api", "flask", "fastapi", "dash", "streamlit", "bokeh", "shiny", "gradio"]
        for subcmd in expected:
            self.assertIn(subcmd, deploy["commands"])

    def test_content_is_command_group(self):
        result = discover_all_commands(cli)
        self.assertIn("commands", result["commands"]["content"])

    def test_content_subcommands(self):
        result = discover_all_commands(cli)

        content = result["commands"]["content"]
        expected = ["search", "describe", "download-bundle", "build"]
        for subcmd in expected:
            self.assertIn(subcmd, content["commands"])

    def test_content_build_nested_group(self):
        result = discover_all_commands(cli)

        build = result["commands"]["content"]["commands"]["build"]
        self.assertIn("commands", build)

        expected = ["add", "rm", "ls", "history", "logs", "run"]
        for subcmd in expected:
            self.assertIn(subcmd, build["commands"])

    def test_system_caches_nested_group(self):
        result = discover_all_commands(cli)

        caches = result["commands"]["system"]["commands"]["caches"]
        self.assertIn("commands", caches)

        expected = ["list", "delete"]
        for subcmd in expected:
            self.assertIn(subcmd, caches["commands"])

    def test_write_manifest_is_command_group(self):
        result = discover_all_commands(cli)
        self.assertIn("commands", result["commands"]["write-manifest"])

    def test_version_is_simple_command(self):
        result = discover_all_commands(cli)

        version = result["commands"]["version"]
        self.assertNotIn("commands", version)
        self.assertIn("parameters", version)

    def test_mcp_server_command_exists(self):
        result = discover_all_commands(cli)
        self.assertIn("mcp-server", result["commands"])
        self.assertIn("parameters", result["commands"]["mcp-server"])

    def test_deploy_notebook_has_parameters(self):
        result = discover_all_commands(cli)

        notebook = result["commands"]["deploy"]["commands"]["notebook"]
        param_names = [p["name"] for p in notebook["parameters"]]

        self.assertIn("file", param_names)
        self.assertIn("name", param_names)
        self.assertIn("server", param_names)
        self.assertIn("api_key", param_names)

    def test_add_command_has_parameters(self):
        result = discover_all_commands(cli)

        add = result["commands"]["add"]
        param_names = [p["name"] for p in add["parameters"]]

        self.assertIn("name", param_names)
        self.assertIn("server", param_names)
        self.assertIn("api_key", param_names)
        self.assertIn("insecure", param_names)

    def test_parameter_has_required_fields(self):
        result = discover_all_commands(cli)

        for param in result["commands"]["add"]["parameters"]:
            self.assertIn("name", param)
            self.assertIn("param_type", param)
            self.assertIn("required", param)

            if param["param_type"] == "option":
                self.assertIn("cli_flags", param)
                self.assertGreater(len(param["cli_flags"]), 0)

    def test_boolean_flags_identified(self):
        result = discover_all_commands(cli)

        add = result["commands"]["add"]
        insecure = next((p for p in add["parameters"] if p["name"] == "insecure"), None)

        self.assertIsNotNone(insecure)
        self.assertEqual(insecure["type"], "boolean")

    def test_parameters_have_descriptions(self):
        result = discover_all_commands(cli)

        add = result["commands"]["add"]
        server = next((p for p in add["parameters"] if p["name"] == "server"), None)

        self.assertIsNotNone(server)
        self.assertIn("description", server)
        self.assertGreater(len(server["description"]), 0)

    def test_verbose_parameters_excluded(self):
        result = discover_all_commands(cli)

        param_names = [p["name"] for p in result["commands"]["add"]["parameters"]]
        self.assertNotIn("verbose", param_names)
        self.assertNotIn("v", param_names)

    def test_all_commands_have_valid_structure(self):
        def validate_command(cmd_info, path=""):
            self.assertIn("name", cmd_info)

            if "commands" in cmd_info:
                self.assertIsInstance(cmd_info["commands"], dict)
                for subcmd_name, subcmd_info in cmd_info["commands"].items():
                    validate_command(subcmd_info, f"{path}/{subcmd_name}")
            else:
                self.assertIn("parameters", cmd_info)
                self.assertIsInstance(cmd_info["parameters"], list)

                for param in cmd_info["parameters"]:
                    self.assertIn("name", param)
                    self.assertIn("param_type", param)
                    self.assertIn("required", param)

        result = discover_all_commands(cli)
        validate_command(result, "cli")

    def test_multiple_value_parameters(self):
        result = discover_all_commands(cli)

        quarto = result["commands"]["deploy"]["commands"]["quarto"]
        exclude = next((p for p in quarto["parameters"] if p["name"] == "exclude"), None)

        self.assertIsNotNone(exclude)
        self.assertEqual(exclude["type"], "array")

    def test_required_parameters_marked(self):
        result = discover_all_commands(cli)

        describe = result["commands"]["content"]["commands"]["describe"]
        guid = next((p for p in describe["parameters"] if p["name"] == "guid"), None)

        self.assertIsNotNone(guid)
        self.assertTrue(guid["required"])

    def test_cli_flags_format(self):
        result = discover_all_commands(cli)

        add = result["commands"]["add"]
        name = next((p for p in add["parameters"] if p["name"] == "name"), None)

        self.assertIsNotNone(name)
        self.assertIn("cli_flags", name)
        self.assertGreater(len(name["cli_flags"]), 0)

        for flag in name["cli_flags"]:
            self.assertTrue(flag.startswith("-"))
