"""Optional live Posit Connect integration tests for the preflight CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from rsconnect.api import RSConnectClient, RSConnectServer
from rsconnect.certificates import read_certificate_file
from rsconnect.exception import RSConnectException

from .utils import optional_ca_data, require_api_key, require_connect


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Agent login and preflight require POSIX.")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _insecure() -> bool:
    return os.environ.get("CONNECT_INSECURE", "").strip().lower() in _TRUE_VALUES


def _live_client(server_url: str, api_key: str) -> RSConnectClient:
    ca_path = optional_ca_data()
    ca_data = read_certificate_file(ca_path) if ca_path else None
    return RSConnectClient(RSConnectServer(server_url, api_key, insecure=_insecure(), ca_data=ca_data))


def _cli_environment(home: Path, api_key: str) -> Dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in (
        "CONNECT_SERVER",
        "CONNECT_INSECURE",
        "CONNECT_CA_CERTIFICATE",
        "CONNECT_IDENTITY_TOKEN",
        "CONNECT_IDENTITY_TOKEN_FILE",
        "CONNECT_CLOUD_ACCOUNT",
        "CONNECT_CLOUD_CLIENT_ID",
        "CONNECT_CLOUD_CLIENT_SECRET",
        "SHINYAPPS_ACCOUNT",
        "RSCONNECT_E2E_CLOUD_BASE_URL",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "xdg"),
            "APPDATA": str(home / "appdata"),
            "CONNECT_API_KEY": api_key,
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
            "RSCONNECT_DISABLE_VERSION_CHECK": "1",
        }
    )
    return environment


def _run_preflight(
    server_url: str,
    api_key: str,
    project: Path,
    home: Path,
    runtime: str | None = None,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable,
        "-m",
        "rsconnect.main",
        "preflight",
        "--server",
        server_url,
    ]
    ca_path = optional_ca_data()
    if ca_path:
        arguments.extend(["--cacert", ca_path])
    if _insecure():
        arguments.append("--insecure")
    arguments.extend([str(project), "--new"])
    if runtime:
        arguments.extend(["--runtime", runtime])
    return subprocess.run(
        arguments,
        cwd=str(_REPO_ROOT),
        env=_cli_environment(home, api_key),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _report(result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as err:
        pytest.fail(
            f"The preflight CLI did not return JSON (exit {result.returncode}): {result.stdout}{result.stderr}: {err}"
        )
    assert isinstance(report, dict), result.stdout
    return report


def _files(project: Path) -> Dict[str, bytes]:
    return {path.name: path.read_bytes() for path in project.iterdir()}


def test_live_python_preflight_checks_a_server_runtime_without_writing_project_files(tmp_path: Path) -> None:
    server_url = require_connect()
    api_key = require_api_key()
    settings = _live_client(server_url, api_key).python_settings()
    installations = settings.get("installations")
    assert isinstance(installations, list), settings
    publishable_versions = [
        item["version"]
        for item in installations
        if isinstance(item, dict) and item.get("publishable") is True and isinstance(item.get("version"), str)
    ]
    if not publishable_versions:
        pytest.skip("Configured Connect server has no publishable Python runtime to check.")

    requirement = "==" + publishable_versions[0]
    project = tmp_path / "python-project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "preflight-live-python"\nversion = "1.0.0"\nrequires-python = "%s"\n' % requirement,
        encoding="utf-8",
    )
    before = _files(project)

    result = _run_preflight(server_url, api_key, project, tmp_path / "home")
    report = _report(result)

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "ok"
    assert report["server"].rstrip("/") == server_url.rstrip("/")
    assert report["python_requires"] == requirement
    assert report["publishable_python_versions"] == publishable_versions
    assert report["changed_files"] == []
    assert _files(project) == before


def test_live_nodejs_preflight_checks_server_settings_without_writing_project_files(tmp_path: Path) -> None:
    server_url = require_connect()
    api_key = require_api_key()
    try:
        settings = _live_client(server_url, api_key).nodejs_settings()
    except RSConnectException as err:
        if err.status == 404:
            pytest.skip(f"Configured Connect server does not expose Node.js settings (HTTP 404): {err}")
        raise

    installations = settings.get("installations")
    assert isinstance(installations, list), settings
    versions: List[str] = [
        item["version"] for item in installations if isinstance(item, dict) and isinstance(item.get("version"), str)
    ]
    publishable_versions = [
        item["version"]
        for item in installations
        if isinstance(item, dict) and item.get("publishable") is True and isinstance(item.get("version"), str)
    ]
    requirement = publishable_versions[0] if publishable_versions else (versions[0] if versions else "*")

    project = tmp_path / "node-project"
    project.mkdir()
    (project / "package.json").write_text(
        json.dumps(
            {
                "name": "preflight-live-node",
                "version": "1.0.0",
                "engines": {"node": requirement},
            }
        ),
        encoding="utf-8",
    )
    (project / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "preflight-live-node",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": "preflight-live-node", "version": "1.0.0"}},
            }
        ),
        encoding="utf-8",
    )
    before = _files(project)

    result = _run_preflight(server_url, api_key, project, tmp_path / "home", runtime="nodejs")
    report = _report(result)
    if report["local_node"] is None:
        diagnostic = next(
            (
                warning
                for warning in report["warnings"]
                if "Could not inspect local Node.js/npm prerequisites" in warning
            ),
            None,
        )
        assert diagnostic is not None, report
        pytest.skip(f"Local Node.js/npm is unavailable: {diagnostic}")

    assert not any("Could not read server Node.js settings" in warning for warning in report["warnings"]), report
    assert result.returncode == (3 if report["status"] == "incompatible" else 0), result.stdout + result.stderr
    assert report["runtime"] == "nodejs"
    assert report["server"].rstrip("/") == server_url.rstrip("/")
    assert report["node_requires"] == requirement
    assert report["nodejs_enabled"] == settings.get("enabled")
    assert report["nodejs_status"] == settings.get("status")
    assert report["publishable_node_versions"] == publishable_versions
    assert report["changed_files"] == []
    assert _files(project) == before
