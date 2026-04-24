"""Detects the configuration of a Node.js environment.

Given a directory containing a package.json file, this module inspects
the local Node.js/npm installation and returns information needed to
build the deployment manifest.
"""

from __future__ import annotations

import json
import locale
import os
import subprocess
from typing import Optional

from .exception import RSConnectException
from .log import logger


class NodeEnvironment:
    """A Node.js project environment for deployment.

    Captures Node.js version, npm version, and package.json contents
    needed for the manifest.
    """

    def __init__(
        self,
        node_version: str,
        npm_version: str,
        package_file: str,
        package_contents: str,
        has_lock_file: bool,
        locale: str,
    ):
        self.node_version = node_version
        self.npm_version = npm_version
        self.package_file = package_file
        self.package_contents = package_contents
        self.has_lock_file = has_lock_file
        self.locale = locale

    @classmethod
    def create(
        cls,
        directory: str,
        node_executable: Optional[str] = None,
    ) -> NodeEnvironment:
        """Detect Node.js environment from a project directory.

        :param directory: path to the project directory containing package.json.
        :param node_executable: optional path to the node binary. Defaults to "node" on PATH.
        :return: a NodeEnvironment instance.
        """
        node_executable = node_executable or "node"

        package_json_path = os.path.join(directory, "package.json")
        if not os.path.exists(package_json_path):
            raise RSConnectException(
                f"No package.json found in '{directory}'. " "A package.json file is required to deploy Node.js content."
            )

        with open(package_json_path, encoding="utf-8") as f:
            package_contents = f.read()

        try:
            json.loads(package_contents)
        except json.JSONDecodeError as e:
            raise RSConnectException(f"Failed to parse package.json: {e}")

        node_version = _detect_version(node_executable, "--version", "Node.js")
        npm_version = _detect_version("npm", "--version", "npm")

        has_lock_file = os.path.exists(os.path.join(directory, "package-lock.json"))
        if not has_lock_file:
            raise RSConnectException(
                f"No package-lock.json found in '{directory}'. "
                "Both package.json and package-lock.json are required to deploy Node.js content."
            )

        env_locale = locale.getlocale()[0] or "en_US"

        return cls(
            node_version=node_version,
            npm_version=npm_version,
            package_file="package.json",
            package_contents=package_contents,
            has_lock_file=has_lock_file,
            locale=env_locale,
        )


def _detect_version(executable: str, flag: str, label: str) -> str:
    """Run an executable with a version flag and return the version string."""
    try:
        result = subprocess.run(
            [executable, flag],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RSConnectException(f"{label} returned exit code {result.returncode}: {result.stderr.strip()}")
        version = result.stdout.strip().lstrip("v")
        if not version:
            raise RSConnectException(f"{label} returned empty version string.")
        logger.debug(f"Detected {label} version: {version}")
        return version
    except FileNotFoundError:
        raise RSConnectException(
            f"Could not find '{executable}' on PATH. " f"Please install {label} or specify the path with --node."
        )
    except subprocess.TimeoutExpired:
        raise RSConnectException(f"Timed out detecting {label} version.")
