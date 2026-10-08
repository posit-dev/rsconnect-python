"""End-to-end CLI tests for resumable OAuth login and runtime preflight."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from rsconnect.metadata import AppStore

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTENT_GUID = "11111111-1111-4111-8111-111111111111"
_DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

_CLI_BOOTSTRAP = """
import os
import runpy

cloud_base = os.environ.get("RSCONNECT_E2E_CLOUD_BASE_URL")
if cloud_base:
    from rsconnect import connect_cloud

    connect_cloud._ENVIRONMENTS["production"] = connect_cloud.ConnectCloudUrls(
        api=cloud_base + "/v1",
        ui=cloud_base,
        auth=cloud_base,
        logs=cloud_base + "/v1",
    )

runpy.run_module("rsconnect.main", run_name="__main__")
"""


class _Handler(BaseHTTPRequestHandler):
    def _record(self) -> dict[str, object]:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        headers = {key.lower(): value for key, value in self.headers.items()}
        record: dict[str, object] = {
            "method": self.command,
            "path": self.path,
            "headers": headers,
            "body": body,
            "received_at": time.monotonic(),
        }
        with self.server.lock:  # type: ignore[attr-defined]
            self.server.requests.append(record)  # type: ignore[attr-defined]
        return record

    def _json(self, status: int, data: object) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self) -> None:
        record = self._record()
        path = urlsplit(str(record["path"])).path
        if path == "/.well-known/oauth-authorization-server":
            self._json(
                200,
                {
                    "device_authorization_endpoint": self.server.base_url + "/oauth/device/authorize",  # type: ignore[attr-defined]
                    "token_endpoint": self.server.base_url + "/oauth/token",  # type: ignore[attr-defined]
                    "registration_endpoint": self.server.base_url + "/oauth/register",  # type: ignore[attr-defined]
                },
            )
        elif path == "/__api__/server_settings":
            status = self.server.server_settings_status  # type: ignore[attr-defined]
            if status is None:
                self._json(200, {"version": "2025.03.0"})
            else:
                self._json(status, {"error": "server temporarily unavailable"})
        elif path == "/__api__/v1/user":
            if self.server.reject_api_key:  # type: ignore[attr-defined]
                self._json(
                    401,
                    {
                        "code": 30,
                        "error": "unauthorized",
                        "error_description": "preflight-auth-secret",
                    },
                )
            else:
                self._json(200, {"guid": "local-user"})
        elif path == "/__api__/v1/server_settings/python":
            self._json(200, {"api_enabled": True, "installations": self.server.python_installations})  # type: ignore[attr-defined]
        elif path == "/__api__/v1/server_settings/nodejs":
            self._json(200, self.server.nodejs_settings)  # type: ignore[attr-defined]
        elif path.startswith("/__api__/v1/content/"):
            content_id = path.rsplit("/", 1)[-1]
            status = self.server.content_statuses.get(content_id)  # type: ignore[attr-defined]
            if status is not None and status != 200:
                self._json(status, {"error": "content lookup failed"})
            else:
                self._json(200, {"py_version": "3.12.8", "node_version": "22.22.2"})
        elif path == "/v1/accounts":
            self._cloud_accounts(record)
        else:
            self._json(404, {"error": "not found"})

    def _cloud_accounts(self, record: dict[str, object]) -> None:
        with self.server.lock:  # type: ignore[attr-defined]
            status = self.server.account_statuses.pop(0) if self.server.account_statuses else 200  # type: ignore[attr-defined]
            delay = self.server.account_delays.pop(0) if self.server.account_delays else 0.0  # type: ignore[attr-defined]
        if delay:
            time.sleep(delay)
        if status != 200:
            self._json(status, {"error": "temporary account lookup failure"})
            return
        self._json(200, {"data": [{"id": "account-123", "name": "team"}], "total": 1})

    def do_POST(self) -> None:
        record = self._record()
        path = urlsplit(str(record["path"])).path
        body = record["body"]
        fields = parse_qs(body.decode("utf-8")) if isinstance(body, bytes) else {}
        if path == "/oauth/register":
            self._json(201, {"client_id": "local-oauth-client"})
        elif path == "/oauth/device/authorize":
            self._device_authorization()
        elif path == "/oauth/token":
            self._token_response(fields)
        else:
            self._json(404, {"error": "not found"})

    def _device_authorization(self) -> None:
        error = self.server.authorization_error  # type: ignore[attr-defined]
        if error:
            self._json(
                400,
                {
                    "error": error,
                    "error_description": self.server.authorization_error_description,  # type: ignore[attr-defined]
                },
            )
            return
        self._json(
            200,
            {
                "device_code": "local-device-code",
                "user_code": "ABCD-EFGH",
                "verification_uri": self.server.base_url + "/verify",  # type: ignore[attr-defined]
                "expires_in": 600,
                "interval": self.server.device_interval,  # type: ignore[attr-defined]
            },
        )

    def _token_response(self, fields: dict[str, list[str]]) -> None:
        grant_type = fields.get("grant_type", [""])[0]
        if grant_type == "refresh_token":
            time.sleep(self.server.refresh_delay)  # type: ignore[attr-defined]
            self._json(
                200,
                {
                    "access_token": "refreshed-access-token",
                    "refresh_token": "refreshed-refresh-token",
                    "expires_in": 3600,
                },
            )
            return
        if grant_type != _DEVICE_GRANT:
            self._json(400, {"error": "unsupported_grant_type"})
            return
        if self.server.concurrent_device_polls:  # type: ignore[attr-defined]
            self._concurrent_device_token_response()
            return
        if self.server.device_error:  # type: ignore[attr-defined]
            self._json(400, {"error": self.server.device_error})  # type: ignore[attr-defined]
        elif not self.server.approved:  # type: ignore[attr-defined]
            self._json(400, {"error": "authorization_pending"})
        else:
            self._json(
                200,
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            )

    def _concurrent_device_token_response(self) -> None:
        with self.server.lock:  # type: ignore[attr-defined]
            self.server.device_poll_count += 1  # type: ignore[attr-defined]
            poll_number = self.server.device_poll_count  # type: ignore[attr-defined]
        if poll_number == 1:
            self.server.first_device_poll_started.set()  # type: ignore[attr-defined]
            self.server.allow_first_device_poll.wait(timeout=15)  # type: ignore[attr-defined]
            self._json(
                200,
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            )
            return
        self.server.second_device_poll_started.set()  # type: ignore[attr-defined]
        self.server.allow_second_device_poll.wait(timeout=15)  # type: ignore[attr-defined]
        self._json(400, {"error": "invalid_grant"})

    def log_message(self, format: str, *args: object) -> None:
        pass


class _LocalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.lock = threading.Lock()
        self.requests: list[dict[str, object]] = []
        self.approved = False
        self.device_error: str | None = None
        self.authorization_error: str | None = None
        self.authorization_error_description = "device-code-secret"
        self.device_interval = 1
        self.account_statuses: list[int] = []
        self.account_delays: list[float] = []
        self.refresh_delay = 0.0
        self.server_settings_status: int | None = None
        self.reject_api_key = False
        self.content_statuses: dict[str, int] = {}
        self.concurrent_device_polls = False
        self.device_poll_count = 0
        self.first_device_poll_started = threading.Event()
        self.second_device_poll_started = threading.Event()
        self.allow_first_device_poll = threading.Event()
        self.allow_second_device_poll = threading.Event()
        local_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
        versions = {local_minor + ".0", "3.12.8", "3.11.9"}
        self.python_installations = [{"version": version, "publishable": True} for version in sorted(versions)]
        self.nodejs_settings = {
            "enabled": True,
            "installations": [
                {"version": "20.19.0", "publishable": True},
                {"version": "22.22.2", "publishable": True},
                {"version": "24.14.0", "publishable": False},
            ],
            "status": {"configured": True, "licensed": True},
        }

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


@pytest.fixture
def local_http_server():
    server = _LocalHTTPServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _cli_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True)
    environment = os.environ.copy()
    for name in (
        "CONNECT_SERVER",
        "CONNECT_API_KEY",
        "CONNECT_IDENTITY_TOKEN",
        "CONNECT_IDENTITY_TOKEN_FILE",
        "CONNECT_CA_CERTIFICATE",
        "CONNECT_INSECURE",
        "CONNECT_CLOUD_ACCOUNT",
        "CONNECT_CLOUD_CLIENT_ID",
        "CONNECT_CLOUD_CLIENT_SECRET",
        "CONNECT_CLOUD_OAUTH_CLIENT_ID",
        "SHINYAPPS_ACCOUNT",
        "RSCONNECT_E2E_CLOUD_BASE_URL",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "xdg"),
            "APPDATA": str(home / "appdata"),
            "CONNECT_CLOUD_ENVIRONMENT": "production",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
            "RSCONNECT_DISABLE_VERSION_CHECK": "1",
        }
    )
    return environment


def _run_cli(arguments: list[str], environment: dict[str, str], cloud_base_url: str | None = None):
    child_environment = environment.copy()
    if cloud_base_url:
        child_environment["RSCONNECT_E2E_CLOUD_BASE_URL"] = cloud_base_url
    return subprocess.run(
        [sys.executable, "-c", _CLI_BOOTSTRAP, *arguments],
        cwd=str(_REPO_ROOT),
        env=child_environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _start_cli(arguments: list[str], environment: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", _CLI_BOOTSTRAP, *arguments],
        cwd=str(_REPO_ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _collect_cli(process: subprocess.Popen[str]) -> subprocess.CompletedProcess[str]:
    stdout, stderr = process.communicate(timeout=20)
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def _json_output(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert len(result.stdout.splitlines()) == 1, result.stdout
    return json.loads(result.stdout)


def _login_connect(name: str, environment: dict[str, str], server: _LocalHTTPServer) -> None:
    started = _run_cli(
        ["login", "--name", name, "--server", server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)
    server.approved = True
    finished = _run_cli(
        ["login", "--name", name, "--finish", "--timeout", "5"],
        environment,
    )
    assert finished.returncode == 0, _output(finished)


def _device_states(home: Path, kind: str) -> list[Path]:
    return list(home.rglob(f"device-login-{kind}-*.json"))


def _saved_servers(home: Path) -> dict[str, dict[str, object]]:
    paths = list(home.rglob("servers.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _requests(server: _LocalHTTPServer, path: str) -> list[dict[str, object]]:
    with server.lock:
        records = list(server.requests)
    return [record for record in records if urlsplit(str(record["path"])).path == path]


def _form(record: dict[str, object]) -> dict[str, list[str]]:
    body = record["body"]
    assert isinstance(body, bytes)
    return parse_qs(body.decode("utf-8"))


def _assert_private_file(path: Path) -> None:
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _write_node_project(path: Path, name: str, node_requirement: str | None = None) -> dict[str, str]:
    path.mkdir()
    package: dict[str, object] = {"name": name, "version": "1.0.0"}
    if node_requirement is not None:
        package["engines"] = {"node": node_requirement}
    contents = {
        "package.json": json.dumps(package),
        "package-lock.json": json.dumps(
            {
                "name": name,
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": name, "version": "1.0.0"}},
            }
        ),
        "index.js": "console.log('ready');\n",
    }
    for filename, value in contents.items():
        (path / filename).write_text(value, encoding="utf-8")
    return contents


def test_connect_login_resumes_across_processes_and_preflight_uses_saved_oauth(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "connect-e2e"
    start_args = ["login", "--name", name, "--server", local_http_server.base_url, "--no-wait"]

    started = _run_cli(start_args, environment)
    assert started.returncode == 0, _output(started)
    start_result = _json_output(started)
    assert start_result["status"] == "pending"
    assert start_result["verification_uri"] == local_http_server.base_url + "/verify"
    assert start_result["user_code"] == "ABCD-EFGH"

    state_paths = _device_states(home, "connect")
    assert len(state_paths) == 1
    _assert_private_file(state_paths[0])
    state = json.loads(state_paths[0].read_text(encoding="utf-8"))
    assert state["name"] == name
    assert state["tokens"] is None

    repeated = _run_cli(start_args, environment)
    assert repeated.returncode == 0, _output(repeated)
    assert _json_output(repeated)["user_code"] == start_result["user_code"]
    assert len(_requests(local_http_server, "/.well-known/oauth-authorization-server")) == 1
    assert len(_requests(local_http_server, "/oauth/register")) == 1
    assert len(_requests(local_http_server, "/oauth/device/authorize")) == 1

    pending = _run_cli(["login", "--name", name, "--finish", "--timeout", "1"], environment)
    assert pending.returncode == 0, _output(pending)
    assert _json_output(pending)["status"] == "pending"
    assert json.loads(state_paths[0].read_text(encoding="utf-8"))["tokens"] is None

    local_http_server.approved = True
    finished = _run_cli(["login", "--name", name, "--finish", "--timeout", "5"], environment)
    assert finished.returncode == 0, _output(finished)
    assert _json_output(finished) == {
        "status": "done",
        "name": name,
        "server": local_http_server.base_url,
    }
    assert _device_states(home, "connect") == []

    saved_path = next(home.rglob("servers.json"))
    _assert_private_file(saved_path)
    saved = _saved_servers(home)[name]
    assert saved["url"] == local_http_server.base_url
    assert saved["oauth_client_id"] == "local-oauth-client"
    assert saved["oauth_access_token"] == "access-token"
    assert saved["oauth_refresh_token"] == "refresh-token"
    assert saved["default"] is True

    fixed_project = tmp_path / "fixed-project"
    fixed_project.mkdir()
    fixed = _run_cli(
        ["preflight", "--name", name, str(fixed_project), "--fix", "--new"],
        environment,
    )
    assert fixed.returncode == 0, _output(fixed)
    fixed_result = _json_output(fixed)
    assert fixed_result["status"] == "ok"
    assert fixed_result["changed_files"] == [".python-version"]
    assert (fixed_project / ".python-version").read_text(encoding="utf-8") == (
        f"{sys.version_info.major}.{sys.version_info.minor}\n"
    )

    read_only_project = tmp_path / "read-only-project"
    read_only_project.mkdir()
    read_only_metadata = '[project]\nrequires-python = "==9.9.*"\n'
    (read_only_project / "pyproject.toml").write_text(read_only_metadata, encoding="utf-8")
    read_only = _run_cli(
        ["preflight", "--name", name, str(read_only_project), "--new"],
        environment,
    )
    assert read_only.returncode == 3, _output(read_only)
    read_only_result = _json_output(read_only)
    assert read_only_result["status"] == "incompatible"
    assert read_only_result["changed_files"] == []
    assert (read_only_project / "pyproject.toml").read_text(encoding="utf-8") == read_only_metadata

    existing_project = tmp_path / "existing-project"
    existing_project.mkdir()
    (existing_project / "pyproject.toml").write_text('[project]\nrequires-python = "==3.12.*"\n', encoding="utf-8")
    existing = _run_cli(
        [
            "preflight",
            "--name",
            name,
            str(existing_project),
            "--app-id",
            _CONTENT_GUID,
        ],
        environment,
    )
    assert existing.returncode == 0, _output(existing)
    existing_result = _json_output(existing)
    assert existing_result["status"] == "ok"
    assert existing_result["existing_content"]["exists"] is True  # type: ignore[index]
    assert existing_result["existing_content"]["app_id"] == _CONTENT_GUID  # type: ignore[index]
    assert existing_result["existing_content"]["installed_python_version"] == "3.12.8"  # type: ignore[index]

    rest_requests = [record for record in local_http_server.requests if str(record["path"]).startswith("/__api__/")]
    assert len(rest_requests) >= 4
    assert all(record["headers"]["authorization"] == "Bearer access-token" for record in rest_requests)  # type: ignore[index]
    grants = [_form(record)["grant_type"][0] for record in _requests(local_http_server, "/oauth/token")]
    assert grants == [_DEVICE_GRANT, _DEVICE_GRANT]


def test_node_preflight_uses_saved_oauth_and_preserves_project_files(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    if not shutil.which("node") or not shutil.which("npm"):
        pytest.skip("Node.js and npm are required for this integration test.")
    node_path = shutil.which("node")
    assert node_path is not None
    local_node_version = subprocess.check_output([node_path, "--version"], text=True).strip().lstrip("v")

    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "node-preflight-e2e"
    started = _run_cli(
        ["login", "--name", name, "--server", local_http_server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)
    local_http_server.approved = True
    finished = _run_cli(["login", "--name", name, "--finish", "--timeout", "5"], environment)
    assert finished.returncode == 0, _output(finished)

    ranged_project = tmp_path / "ranged-node-project"
    ranged_files = _write_node_project(ranged_project, "ranged-node-project", ">=22 <23")

    ranged_result = _run_cli(
        ["preflight", "--name", name, str(ranged_project), "--runtime", "nodejs", "--new"],
        environment,
    )
    assert ranged_result.returncode == 0, _output(ranged_result)
    ranged_report = _json_output(ranged_result)
    assert ranged_report["status"] == "ok"
    assert ranged_report["runtime"] == "nodejs"
    assert ranged_report["local_node"] == local_node_version
    assert ranged_report["node_requires"] == ">=22 <23"
    assert ranged_report["publishable_node_versions"] == ["20.19.0", "22.22.2"]
    assert ranged_report["changed_files"] == []
    assert {path.name: path.read_text(encoding="utf-8") for path in ranged_project.iterdir()} == ranged_files
    rejected_fix = _run_cli(
        ["preflight", "--name", name, str(ranged_project), "--runtime", "nodejs", "--new", "--fix"],
        environment,
    )
    assert rejected_fix.returncode == 2
    assert rejected_fix.stdout == ""
    assert "--fix applies only to python projects" in _output(rejected_fix).lower()
    assert {path.name: path.read_text(encoding="utf-8") for path in ranged_project.iterdir()} == ranged_files

    unsupported_project = tmp_path / "unsupported-node-project"
    unsupported_files = _write_node_project(unsupported_project, "unsupported-node-project", ">=25 <26")
    unsupported_result = _run_cli(
        ["preflight", "--name", name, str(unsupported_project), "--runtime", "nodejs", "--new"],
        environment,
    )
    assert unsupported_result.returncode == 3, _output(unsupported_result)
    unsupported_report = _json_output(unsupported_result)
    assert unsupported_report["status"] == "incompatible"
    assert unsupported_report["node_requires"] == ">=25 <26"
    assert unsupported_report["changed_files"] == []
    assert {path.name: path.read_text(encoding="utf-8") for path in unsupported_project.iterdir()} == unsupported_files

    unconstrained_project = tmp_path / "unconstrained-node-project"
    _write_node_project(unconstrained_project, "unconstrained-node-project")
    unconstrained_before = {path.name: path.read_bytes() for path in unconstrained_project.iterdir()}
    unconstrained_result = _run_cli(
        ["preflight", "--name", name, str(unconstrained_project), "--runtime", "nodejs", "--new"],
        environment,
    )
    assert unconstrained_result.returncode == 0, _output(unconstrained_result)
    unconstrained_report = _json_output(unconstrained_result)
    assert unconstrained_report["status"] == "ok"
    assert unconstrained_report["node_requires"] is None
    assert unconstrained_report["publishable_node_versions"] == ["20.19.0", "22.22.2"]
    assert unconstrained_report["changed_files"] == []
    assert {path.name: path.read_bytes() for path in unconstrained_project.iterdir()} == unconstrained_before

    node_settings_requests = _requests(local_http_server, "/__api__/v1/server_settings/nodejs")
    assert len(node_settings_requests) == 3
    assert all(
        record["headers"]["authorization"] == "Bearer access-token"  # type: ignore[index]
        for record in node_settings_requests
    )
    assert len(_requests(local_http_server, "/oauth/token")) == 1


@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.parametrize("runtime", ["python", "nodejs"])
def test_unreadable_explicit_content_returns_actionable_unknown(
    tmp_path: Path,
    local_http_server: _LocalHTTPServer,
    status: int,
    runtime: str,
) -> None:
    if runtime == "nodejs" and (not shutil.which("node") or not shutil.which("npm")):
        pytest.skip("Node.js and npm are required for this integration test.")

    environment = _cli_environment(tmp_path / "home")
    name = "missing-content-" + runtime
    _login_connect(name, environment, local_http_server)
    project = tmp_path / ("project-" + runtime)
    if runtime == "nodejs":
        _write_node_project(project, project.name, "^22")
        runtime_args = ["--runtime", "nodejs"]
    else:
        project.mkdir()
        runtime_args = []

    local_http_server.content_statuses[_CONTENT_GUID] = status
    result = _run_cli(
        ["preflight", "--name", name, str(project), "--app-id", _CONTENT_GUID, *runtime_args],
        environment,
    )

    assert result.returncode == 0, _output(result)
    report = _json_output(result)
    assert report["status"] == "unknown"
    existing = report["existing_content"]
    assert existing["exists"] is True  # type: ignore[index]
    assert existing["app_id"] == _CONTENT_GUID  # type: ignore[index]
    assert report["warnings"]
    assert report["actions"]
    if status == 404:
        assert any("--new" in action for action in report["actions"])  # type: ignore[union-attr]
    content_requests = _requests(local_http_server, "/__api__/v1/content/" + _CONTENT_GUID)
    assert len(content_requests) == 1
    assert content_requests[0]["headers"]["authorization"] == "Bearer access-token"  # type: ignore[index]


@pytest.mark.parametrize("filename", ["manifest.json", "notebook.ipynb", "bundle.tar.gz", "report.qmd"])
def test_file_deployment_appstore_records_are_seen_by_preflight(
    tmp_path: Path,
    local_http_server: _LocalHTTPServer,
    filename: str,
) -> None:
    environment = _cli_environment(tmp_path / "home")
    name = "file-appstore-" + filename.replace(".", "-")
    _login_connect(name, environment, local_http_server)

    project = tmp_path / "file-project"
    project.mkdir()
    deployment_file = project / filename
    deployment_file.write_bytes(b"deployment input")
    store = AppStore(str(deployment_file))
    store.set(
        local_http_server.base_url,
        str(deployment_file),
        "https://connect.example.com/content/" + _CONTENT_GUID,
        _CONTENT_GUID,
        _CONTENT_GUID,
        "saved content",
        "python-api",
    )

    result = _run_cli(
        ["preflight", "--name", name, str(deployment_file), "--fix"],
        environment,
    )

    assert result.returncode == 0, _output(result)
    report = _json_output(result)
    assert report["status"] == "ok"
    assert report["changed_files"] == []
    existing = report["existing_content"]
    assert existing["exists"] is True  # type: ignore[index]
    assert existing["app_id"] == _CONTENT_GUID  # type: ignore[index]
    assert existing["installed_python_version"] == "3.12.8"  # type: ignore[index]
    assert not (project / ".python-version").exists()
    assert len(_requests(local_http_server, "/__api__/v1/content/" + _CONTENT_GUID)) == 1


def test_invalid_python_metadata_returns_actionable_unknown_json(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    environment = _cli_environment(tmp_path / "home")
    name = "invalid-metadata"
    _login_connect(name, environment, local_http_server)
    project = tmp_path / "invalid-metadata-project"
    project.mkdir()
    metadata = project / "pyproject.toml"
    original = b"[project\nrequires-python = '>=3.11'\n"
    metadata.write_bytes(original)

    result = _run_cli(["preflight", "--name", name, str(project), "--fix", "--new"], environment)

    assert result.returncode == 0, _output(result)
    report = _json_output(result)
    assert report["status"] == "unknown"
    assert report["changed_files"] == []
    assert report["warnings"]
    assert report["actions"]
    assert metadata.read_bytes() == original
    assert not (project / ".python-version").exists()


def test_preflight_operational_errors_emit_the_documented_json_shape(tmp_path: Path) -> None:
    environment = _cli_environment(tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()

    result = _run_cli(["preflight", "--name", "missing-server", str(project)], environment)

    assert result.returncode == 1
    report = _json_output(result)
    assert set(report) == {"status", "runtime", "error", "changed_files", "warnings", "actions"}
    assert report["status"] == "error"
    assert report["runtime"] == "python"
    assert isinstance(report["error"], str) and report["error"]
    assert report["changed_files"] == []
    assert report["warnings"] == []
    assert report["actions"]


@pytest.mark.parametrize(
    ("failure", "request_path"),
    [
        ("auth", "/__api__/v1/user"),
        ("connection", "/__api__/server_settings"),
    ],
)
def test_preflight_http_auth_and_connection_errors_emit_error_json(
    tmp_path: Path,
    local_http_server: _LocalHTTPServer,
    failure: str,
    request_path: str,
) -> None:
    environment = _cli_environment(tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    if failure == "auth":
        local_http_server.reject_api_key = True
    else:
        local_http_server.server_settings_status = 503

    result = _run_cli(
        [
            "preflight",
            "--server",
            local_http_server.base_url,
            "--api-key",
            "synthetic-api-key",
            str(project),
            "--new",
            "-v",
        ],
        environment,
    )

    assert result.returncode == 1, _output(result)
    report = _json_output(result)
    assert set(report) == {"status", "runtime", "error", "changed_files", "warnings", "actions"}
    assert report["status"] == "error"
    assert report["runtime"] == "python"
    assert isinstance(report["error"], str) and report["error"]
    assert report["changed_files"] == []
    assert report["warnings"] == []
    assert report["actions"]
    assert "Checking python runtime availability." in result.stderr
    assert "synthetic-api-key" not in _output(result)
    assert "preflight-auth-secret" not in _output(result)
    requests = _requests(local_http_server, request_path)
    assert len(requests) == 1
    if failure == "auth":
        assert requests[0]["headers"]["authorization"] == "Key synthetic-api-key"  # type: ignore[index]


def test_symlinked_python_metadata_returns_actionable_unknown_json(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    environment = _cli_environment(tmp_path / "home")
    name = "symlink-metadata"
    _login_connect(name, environment, local_http_server)
    project = tmp_path / "symlink-metadata-project"
    project.mkdir()
    target = tmp_path / "real-pyproject.toml"
    target.write_text('[project]\nrequires-python = ">=3.11"\n', encoding="utf-8")
    metadata = project / "pyproject.toml"
    try:
        metadata.symlink_to(target)
    except (NotImplementedError, OSError) as err:
        pytest.skip(f"Cannot create a symlink in this environment: {err}")

    result = _run_cli(["preflight", "--name", name, str(project), "--fix", "--new"], environment)

    assert result.returncode == 0, _output(result)
    report = _json_output(result)
    assert report["status"] == "unknown"
    assert report["changed_files"] == []
    assert report["warnings"]
    assert report["actions"]
    assert metadata.is_symlink()
    assert metadata.read_text(encoding="utf-8") == target.read_text(encoding="utf-8")
    assert not (project / ".python-version").exists()


def test_incomplete_appstore_record_returns_actionable_unknown_without_fixing(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    environment = _cli_environment(tmp_path / "home")
    name = "incomplete-appstore"
    _login_connect(name, environment, local_http_server)
    project = tmp_path / "incomplete-record-project"
    project.mkdir()
    app_file = project / (project.name + ".py")
    app_file.write_text("pass\n", encoding="utf-8")
    AppStore(str(app_file)).set(local_http_server.base_url, str(app_file), "", "", None, "unfinished", "python-api")

    result = _run_cli(["preflight", "--name", name, str(project), "--fix"], environment)

    assert result.returncode == 0, _output(result)
    report = _json_output(result)
    assert report["status"] == "unknown"
    assert report["changed_files"] == []
    assert report["warnings"]
    assert any("--new" in action or "--app-id" in action for action in report["actions"])  # type: ignore[union-attr]
    assert not (project / ".python-version").exists()


@pytest.mark.parametrize(
    ("device_error", "message"),
    [
        ("access_denied", "denied"),
        ("expired_token", "expired"),
        ("invalid_grant", "invalid"),
    ],
)
def test_terminal_device_oauth_errors_remove_pending_state(
    tmp_path: Path,
    local_http_server: _LocalHTTPServer,
    device_error: str,
    message: str,
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    local_http_server.device_error = device_error
    started = _run_cli(
        ["login", "--name", "terminal-login", "--server", local_http_server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)
    assert len(_device_states(home, "connect")) == 1

    finished = _run_cli(
        ["login", "--name", "terminal-login", "--finish", "--timeout", "5"],
        environment,
    )
    assert finished.returncode == 1
    assert finished.stdout == ""
    assert message in finished.stderr.lower()
    assert "local-device-code" not in _output(finished)
    assert _device_states(home, "connect") == []
    assert len(_requests(local_http_server, "/oauth/token")) == 1


def test_expired_persisted_device_login_is_removed_without_polling(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    started = _run_cli(
        ["login", "--name", "old-login", "--server", local_http_server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)

    state_path = _device_states(home, "connect")[0]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["expires_at"] = time.time() - 1
    state_path.write_text(json.dumps(state), encoding="utf-8")
    finished = _run_cli(["login", "--name", "old-login", "--finish"], environment)

    assert finished.returncode == 1
    assert "expired" in _output(finished).lower()
    assert _device_states(home, "connect") == []
    assert _requests(local_http_server, "/oauth/token") == []


def test_authorization_pending_retry_obeys_the_saved_poll_interval(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "poll-interval-e2e"
    local_http_server.device_interval = 2
    started = _run_cli(
        ["login", "--name", name, "--server", local_http_server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)

    # Let the initial interval pass so the first finish call receives a real
    # authorization_pending response before its one-second deadline.
    time.sleep(2.05)
    first = _run_cli(["login", "--name", name, "--finish", "--timeout", "1"], environment)
    assert first.returncode == 0, _output(first)
    assert _json_output(first)["status"] == "pending"
    first_polls = _requests(local_http_server, "/oauth/token")
    assert len(first_polls) == 1

    retried = _run_cli(["login", "--name", name, "--finish", "--timeout", "1"], environment)
    assert retried.returncode == 0, _output(retried)
    assert _json_output(retried)["status"] == "pending"
    polls = _requests(local_http_server, "/oauth/token")
    assert len(polls) <= 2
    if len(polls) == 2:
        assert polls[1]["received_at"] - polls[0]["received_at"] >= 1.8  # type: ignore[operator]


def test_concurrent_finish_cannot_resurrect_stale_pending_state(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "concurrent-finish-e2e"
    started = _run_cli(
        ["login", "--name", name, "--server", local_http_server.base_url, "--no-wait"],
        environment,
    )
    assert started.returncode == 0, _output(started)
    state_paths = _device_states(home, "connect")
    assert len(state_paths) == 1

    local_http_server.approved = True
    local_http_server.concurrent_device_polls = True
    finish_args = ["login", "--name", name, "--finish", "--timeout", "5"]
    first = _start_cli(finish_args, environment)
    second: subprocess.Popen[str] | None = None
    try:
        assert local_http_server.first_device_poll_started.wait(timeout=10)
        second = _start_cli(["login", "--name", name, "--finish", "--timeout", "1"], environment)
        second_result = _collect_cli(second)
        assert second_result.returncode == 0, _output(second_result)
        second_report = _json_output(second_result)
        assert set(second_report) == {"status", "name", "server"}
        assert second_report == {"status": "pending", "name": name, "server": None}

        local_http_server.allow_first_device_poll.set()
        first_result = _collect_cli(first)
        assert first_result.returncode == 0, _output(first_result)
        assert _json_output(first_result)["status"] == "done"
    finally:
        local_http_server.allow_first_device_poll.set()
        local_http_server.allow_second_device_poll.set()
        for process in (first, second):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    assert _device_states(home, "connect") == []
    device_polls = [
        request
        for request in _requests(local_http_server, "/oauth/token")
        if _form(request)["grant_type"] == [_DEVICE_GRANT]
    ]
    assert len(device_polls) == 1


@pytest.mark.parametrize("verbose", ["-v", "-vv"])
def test_device_login_verbose_output_keeps_json_clean_and_hides_secrets(
    tmp_path: Path, local_http_server: _LocalHTTPServer, verbose: str
) -> None:
    environment = _cli_environment(tmp_path / "home")
    name = "verbose-login-e2e"
    started = _run_cli(
        ["login", "--name", name, "--server", local_http_server.base_url, "--no-wait", verbose],
        environment,
    )

    assert started.returncode == 0, _output(started)
    assert _json_output(started)["status"] == "pending"
    assert "Starting device authentication." in started.stderr
    local_http_server.approved = True

    finished = _run_cli(
        ["login", "--name", name, "--finish", "--timeout", "5", verbose],
        environment,
    )

    assert finished.returncode == 0, _output(finished)
    assert _json_output(finished)["status"] == "done"
    assert "Finishing device authentication." in finished.stderr
    if verbose == "-vv":
        assert "[DEBUG]" in started.stderr
        assert "Request: POST" in started.stderr
        assert "Request: POST" in finished.stderr
        assert "<redacted>" in started.stderr
        assert "<redacted>" in finished.stderr
    else:
        assert "[DEBUG]" not in started.stderr
        assert "[DEBUG]" not in finished.stderr
    for secret in ("local-device-code", "access-token", "refresh-token"):
        assert secret not in _output(started)
        assert secret not in _output(finished)


def test_device_login_errors_use_stderr_and_redact_server_descriptions(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    environment = _cli_environment(tmp_path / "home")
    local_http_server.authorization_error = "invalid_request"
    result = _run_cli(
        [
            "login",
            "--name",
            "failed-login-e2e",
            "--server",
            local_http_server.base_url,
            "--no-wait",
            "-v",
        ],
        environment,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip()
    assert "Error:" in result.stderr
    assert "device-code-secret" not in _output(result)


def test_cloud_finish_checkpoints_tokens_and_retries_account_lookup(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    local_http_server.account_statuses = [500, 401, 200]
    cloud_args = ["add", "--connect-cloud", "--account", "team", "--name", "cloud-e2e", "--no-wait"]

    started = _run_cli(cloud_args, environment, cloud_base_url=local_http_server.base_url)
    assert started.returncode == 0, _output(started)
    assert _json_output(started)["status"] == "pending"
    state_paths = _device_states(home, "cloud")
    assert len(state_paths) == 1

    repeated = _run_cli(cloud_args, environment, cloud_base_url=local_http_server.base_url)
    assert repeated.returncode == 0, _output(repeated)
    assert len(_requests(local_http_server, "/oauth/device/authorize")) == 1
    device_form = _form(_requests(local_http_server, "/oauth/device/authorize")[0])
    assert device_form["scope"] == ["vivid"]

    pending = _run_cli(
        ["add", "--connect-cloud", "--name", "cloud-e2e", "--finish", "--timeout", "1"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert pending.returncode == 0, _output(pending)
    assert _json_output(pending)["status"] == "pending"

    local_http_server.approved = True
    failed_lookup = _run_cli(
        ["add", "--connect-cloud", "--name", "cloud-e2e", "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert failed_lookup.returncode == 1
    checkpoint = json.loads(state_paths[0].read_text(encoding="utf-8"))["tokens"]
    assert checkpoint["access_token"] == "access-token"
    assert checkpoint["refresh_token"] == "refresh-token"
    assert checkpoint["expires_at"] > time.time()

    finished = _run_cli(
        ["add", "--connect-cloud", "--name", "cloud-e2e", "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert finished.returncode == 0, _output(finished)
    assert _json_output(finished) == {
        "status": "done",
        "name": "cloud-e2e",
        "server": local_http_server.base_url + "/v1",
        "account": "team",
    }
    assert _device_states(home, "cloud") == []

    saved_path = next(home.rglob("servers.json"))
    _assert_private_file(saved_path)
    saved = _saved_servers(home)["cloud-e2e"]
    assert saved["connect_cloud_account_name"] == "team"
    assert saved["connect_cloud_account_id"] == "account-123"
    assert saved["connect_cloud_access_token"] == "refreshed-access-token"
    assert saved["connect_cloud_refresh_token"] == "refreshed-refresh-token"

    account_requests = _requests(local_http_server, "/v1/accounts")
    assert [record["headers"]["authorization"] for record in account_requests] == [  # type: ignore[index]
        "Bearer access-token",
        "Bearer access-token",
        "Bearer refreshed-access-token",
    ]
    grants = [_form(record)["grant_type"][0] for record in _requests(local_http_server, "/oauth/token")]
    assert grants == [_DEVICE_GRANT, _DEVICE_GRANT, "refresh_token"]


def test_cloud_unknown_account_clears_state_for_a_corrected_start(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "cloud-account-correction"
    started = _run_cli(
        ["add", "--connect-cloud", "--account", "teem", "--name", name, "--no-wait"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert started.returncode == 0, _output(started)
    local_http_server.approved = True

    failed_lookup = _run_cli(
        ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )

    assert failed_lookup.returncode == 1
    assert _device_states(home, "cloud") == []
    assert "access-token" not in _output(failed_lookup)

    corrected_start = _run_cli(
        ["add", "--connect-cloud", "--account", "team", "--name", name, "--no-wait"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert corrected_start.returncode == 0, _output(corrected_start)
    corrected_finish = _run_cli(
        ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )

    assert corrected_finish.returncode == 0, _output(corrected_finish)
    assert _json_output(corrected_finish)["status"] == "done"
    assert _device_states(home, "cloud") == []
    assert len(_requests(local_http_server, "/oauth/device/authorize")) == 2


def test_cloud_rotated_tokens_are_checkpointed_after_transient_account_lookup_failure(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "cloud-rotated-checkpoint"
    local_http_server.account_statuses = [401, 500]
    start_args = ["add", "--connect-cloud", "--account", "team", "--name", name, "--no-wait"]
    started = _run_cli(start_args, environment, cloud_base_url=local_http_server.base_url)
    assert started.returncode == 0, _output(started)
    state_path = _device_states(home, "cloud")[0]

    local_http_server.approved = True
    failed_lookup = _run_cli(
        ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert failed_lookup.returncode == 1
    checkpoint = json.loads(state_path.read_text(encoding="utf-8"))["tokens"]
    assert checkpoint["access_token"] == "refreshed-access-token"
    assert checkpoint["refresh_token"] == "refreshed-refresh-token"

    local_http_server.account_statuses = [200]
    retried = _run_cli(
        ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert retried.returncode == 0, _output(retried)
    assert _json_output(retried)["status"] == "done"
    assert _device_states(home, "cloud") == []
    account_requests = _requests(local_http_server, "/v1/accounts")
    assert [request["headers"]["authorization"] for request in account_requests] == [  # type: ignore[index]
        "Bearer access-token",
        "Bearer refreshed-access-token",
        "Bearer refreshed-access-token",
    ]
    grants = [_form(record)["grant_type"][0] for record in _requests(local_http_server, "/oauth/token")]
    assert grants == [_DEVICE_GRANT, "refresh_token"]


def test_cloud_finish_deadline_covers_delayed_refresh_and_keeps_checkpoint(
    tmp_path: Path, local_http_server: _LocalHTTPServer
) -> None:
    home = tmp_path / "home"
    environment = _cli_environment(home)
    name = "cloud-deadline-e2e"
    cloud_args = ["add", "--connect-cloud", "--account", "team", "--name", name, "--no-wait"]
    started = _run_cli(cloud_args, environment, cloud_base_url=local_http_server.base_url)
    assert started.returncode == 0, _output(started)
    state_path = _device_states(home, "cloud")[0]

    local_http_server.approved = True
    # Let the one-second device-poll interval pass so the finish budget covers the
    # account lookup and standalone token refresh, not an initial polling sleep.
    time.sleep(1.1)
    local_http_server.account_statuses = [401]
    local_http_server.account_delays = [1.5]
    local_http_server.refresh_delay = 1.5
    finish_args = ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "2"]
    started_at = time.monotonic()
    timed_out = _run_cli(finish_args, environment, cloud_base_url=local_http_server.base_url)
    elapsed = time.monotonic() - started_at

    assert timed_out.returncode == 0, _output(timed_out)
    assert _json_output(timed_out) == {
        "status": "pending",
        "name": name,
        "server": local_http_server.base_url + "/v1",
    }
    assert elapsed < 2.8, f"finish exceeded its two-second budget: {elapsed:.2f}s"
    checkpoint = json.loads(state_path.read_text(encoding="utf-8"))["tokens"]
    assert checkpoint["access_token"] == "access-token"
    assert checkpoint["refresh_token"] == "refresh-token"
    account_requests = _requests(local_http_server, "/v1/accounts")
    assert [record["headers"]["authorization"] for record in account_requests] == ["Bearer access-token"]
    grants = [_form(record)["grant_type"][0] for record in _requests(local_http_server, "/oauth/token")]
    assert grants == [_DEVICE_GRANT, "refresh_token"]

    local_http_server.refresh_delay = 0
    retried = _run_cli(
        ["add", "--connect-cloud", "--name", name, "--finish", "--timeout", "5"],
        environment,
        cloud_base_url=local_http_server.base_url,
    )
    assert retried.returncode == 0, _output(retried)
    assert _json_output(retried)["status"] == "done"
    assert _device_states(home, "cloud") == []
    account_requests = _requests(local_http_server, "/v1/accounts")
    assert [record["headers"]["authorization"] for record in account_requests] == [
        "Bearer access-token",
        "Bearer access-token",
    ]
    assert [_form(record)["grant_type"][0] for record in _requests(local_http_server, "/oauth/token")] == [
        _DEVICE_GRANT,
        "refresh_token",
    ]
    saved = _saved_servers(home)[name]
    assert saved["connect_cloud_access_token"] == "access-token"
    assert saved["connect_cloud_refresh_token"] == "refresh-token"
