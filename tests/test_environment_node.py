import json
import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from rsconnect.environment_node import NodeEnvironment, _detect_version, _parse_packages
from rsconnect.exception import RSConnectException


_TESTDATA = os.path.join(os.path.dirname(__file__), "testdata")
_NODE_EXPRESS = os.path.join(_TESTDATA, "node-express")


def _mock_run(cmd, **kwargs):
    """Mock subprocess.run for node/npm version detection."""
    executable = cmd[0]
    result = MagicMock()
    result.returncode = 0
    if executable == "node" or executable.endswith("/node"):
        result.stdout = "v22.22.1\n"
    elif executable == "npm":
        result.stdout = "10.9.2\n"
    else:
        raise FileNotFoundError(f"No such file: {executable}")
    result.stderr = ""
    return result


class TestNodeEnvironmentCreate:
    @patch("rsconnect.environment_node.subprocess.run", side_effect=_mock_run)
    def test_create_basic(self, mock_run):
        env = NodeEnvironment.create(_NODE_EXPRESS)
        assert env.node_version == "22.22.1"
        assert env.npm_version == "10.9.2"
        assert env.package_file == "package.json"
        assert "express" in env.packages
        assert env.packages["express"]["description"]["name"] == "express"
        assert env.packages["express"]["description"]["version"] == "4.21.0"
        assert env.packages["express"]["Source"] == "npm"
        assert not env.has_lock_file
        assert env.locale

    @patch("rsconnect.environment_node.subprocess.run", side_effect=_mock_run)
    def test_create_with_lock_file(self, mock_run, tmp_path):
        # Copy package.json and app.js to tmp_path, then add a lock file
        pkg = tmp_path / "package.json"
        pkg.write_text(json.dumps({"dependencies": {"express": "^4.21.0"}}))
        (tmp_path / "app.js").write_text("// app")
        (tmp_path / "package-lock.json").write_text("{}")

        env = NodeEnvironment.create(str(tmp_path))
        assert env.has_lock_file

    def test_create_no_package_json(self, tmp_path):
        with pytest.raises(RSConnectException, match="No package.json found"):
            NodeEnvironment.create(str(tmp_path))

    def test_create_invalid_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text("not json{{{")
        with pytest.raises(RSConnectException, match="Failed to parse package.json"):
            NodeEnvironment.create(str(tmp_path))

    @patch(
        "rsconnect.environment_node.subprocess.run",
        side_effect=FileNotFoundError("No such file"),
    )
    def test_create_node_not_found(self, mock_run):
        with pytest.raises(RSConnectException, match="Could not find 'node'"):
            NodeEnvironment.create(_NODE_EXPRESS)

    @patch("rsconnect.environment_node.subprocess.run")
    def test_create_node_error_exit(self, mock_run):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "some error"
        mock_run.return_value = result
        with pytest.raises(RSConnectException, match="returned exit code 1"):
            NodeEnvironment.create(_NODE_EXPRESS)

    @patch("rsconnect.environment_node.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=10))
    def test_create_node_timeout(self, mock_run):
        with pytest.raises(RSConnectException, match="Timed out"):
            NodeEnvironment.create(_NODE_EXPRESS)

    @patch("rsconnect.environment_node.subprocess.run", side_effect=_mock_run)
    def test_create_custom_node_executable(self, mock_run):
        env = NodeEnvironment.create(_NODE_EXPRESS, node_executable="/opt/node/22/bin/node")
        assert env.node_version == "22.22.1"
        # Verify the custom executable was used
        first_call = mock_run.call_args_list[0]
        assert first_call[0][0][0] == "/opt/node/22/bin/node"

    @patch("rsconnect.environment_node.subprocess.run", side_effect=_mock_run)
    def test_package_contents_preserved(self, mock_run):
        env = NodeEnvironment.create(_NODE_EXPRESS)
        data = json.loads(env.package_contents)
        assert data["name"] == "node-express"
        assert data["main"] == "app.js"


class TestDetectVersion:
    @patch("rsconnect.environment_node.subprocess.run")
    def test_strips_v_prefix(self, mock_run):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "v22.22.1\n"
        result.stderr = ""
        mock_run.return_value = result
        assert _detect_version("node", "--version", "Node.js") == "22.22.1"

    @patch("rsconnect.environment_node.subprocess.run")
    def test_no_v_prefix(self, mock_run):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "10.9.2\n"
        result.stderr = ""
        mock_run.return_value = result
        assert _detect_version("npm", "--version", "npm") == "10.9.2"

    @patch("rsconnect.environment_node.subprocess.run")
    def test_empty_version(self, mock_run):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "\n"
        result.stderr = ""
        mock_run.return_value = result
        with pytest.raises(RSConnectException, match="empty version"):
            _detect_version("node", "--version", "Node.js")


class TestParsePackages:
    def test_basic_dependencies(self):
        data = {"dependencies": {"express": "^4.21.0", "cors": "~2.8.5"}}
        packages = _parse_packages(data)
        assert len(packages) == 2
        assert packages["express"]["description"]["version"] == "4.21.0"
        assert packages["cors"]["description"]["version"] == "2.8.5"

    def test_no_dependencies(self):
        data = {"name": "minimal"}
        packages = _parse_packages(data)
        assert packages == {}

    def test_exact_version(self):
        data = {"dependencies": {"lodash": "4.17.21"}}
        packages = _parse_packages(data)
        assert packages["lodash"]["description"]["version"] == "4.17.21"

    def test_range_version(self):
        data = {"dependencies": {"pkg": ">=1.0.0"}}
        packages = _parse_packages(data)
        assert packages["pkg"]["description"]["version"] == "1.0.0"

    def test_dev_dependencies_excluded(self):
        data = {
            "dependencies": {"express": "^4.21.0"},
            "devDependencies": {"jest": "^29.0.0"},
        }
        packages = _parse_packages(data)
        assert "express" in packages
        assert "jest" not in packages
