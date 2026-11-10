import importlib
import json
import platform
import threading
import time

import click.testing
import httpretty
import pytest

import rsconnect
import rsconnect.version_check
from rsconnect.main import cli
from rsconnect.metadata import config_dirname


@pytest.fixture
def release_cli(monkeypatch, tmp_path):
    # The checkout normally has a development version, which skips the check.
    with monkeypatch.context() as env:
        env.setattr(rsconnect, "VERSION", "1.0.0")
        env.setenv("HOME", str(tmp_path))
        env.setenv("XDG_CONFIG_HOME", str(tmp_path))
        env.setenv("APPDATA", str(tmp_path))
        env.delenv("RSCONNECT_DISABLE_VERSION_CHECK", raising=False)
        importlib.reload(rsconnect.version_check)
        yield tmp_path
    importlib.reload(rsconnect.version_check)


def _runner():
    try:
        return click.testing.CliRunner(mix_stderr=False)
    except TypeError:
        return click.testing.CliRunner()


def _deploy():
    # A real deploy that fails quickly, while still running the exit callback.
    return _runner().invoke(cli, ["deploy", "html", "nonexistent-file.html"])


def _pypi(info):
    httpretty.register_uri(
        httpretty.GET,
        "https://pypi.org/pypi/rsconnect-python/json",
        body=json.dumps({"info": info}),
        content_type="application/json",
    )


def _cache_path():
    from pathlib import Path

    return Path(config_dirname()) / "version_check.json"


def _write_cache(**data):
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": time.time(), **data}))


@httpretty.activate(allow_net_connect=False)
def test_incompatible_latest_is_reported_and_cached(release_cli):
    _pypi({"version": "99.0.0", "requires_python": ">=100"})
    result = _deploy()
    python_version = platform.python_version()
    assert result.exit_code != 0
    assert "99.0.0" not in result.stdout
    assert "99.0.0" in result.stderr
    assert ">=100" in result.stderr
    assert f"Python {python_version}" in result.stderr
    assert "uv tool install rsconnect-python" in result.stderr
    assert "pip install --upgrade" not in result.stderr
    assert json.loads(_cache_path().read_text())["requires_python"] == ">=100"

    httpretty.reset()
    cached = _deploy()
    assert "uv tool install rsconnect-python" in cached.stderr
    assert not httpretty.latest_requests()


@pytest.mark.parametrize("requirement", [">=3.0", None, "not a specifier", 42])
@httpretty.activate(allow_net_connect=False)
def test_compatible_or_unknown_requirement_keeps_upgrade_hint(release_cli, requirement):
    _pypi({"version": "99.0.0", "requires_python": requirement})
    result = _deploy()
    assert (
        "A new version of rsconnect-python is available: 99.0.0 (you have 1.0.0).\n"
        "Upgrade with: pip install --upgrade rsconnect-python"
    ) in result.stderr
    assert "uv tool install" not in result.stderr


@httpretty.activate(allow_net_connect=False)
def test_missing_requirement_in_pypi_response_is_compatible(release_cli):
    _pypi({"version": "99.0.0"})
    assert "pip install --upgrade rsconnect-python" in _deploy().stderr
    assert json.loads(_cache_path().read_text())["requires_python"] is None


@httpretty.activate(allow_net_connect=False)
def test_legacy_cache_refreshes_without_blocking(release_cli):
    _write_cache(latest="98.0.0")
    request_started = threading.Event()
    allow_response = threading.Event()
    response_sent = threading.Event()

    def response(request, uri, headers):
        request_started.set()
        allow_response.wait(timeout=5)
        response_sent.set()
        return (200, headers, json.dumps({"info": {"version": "99.0.0", "requires_python": ">=100"}}))

    httpretty.register_uri(httpretty.GET, "https://pypi.org/pypi/rsconnect-python/json", body=response)
    try:
        result = _deploy()
        assert "98.0.0" in result.stderr
        assert "pip install --upgrade rsconnect-python" in result.stderr
        assert request_started.wait(timeout=2)
    finally:
        allow_response.set()
    assert response_sent.wait(timeout=2)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            data = json.loads(_cache_path().read_text())
        except json.JSONDecodeError:
            continue
        if data.get("requires_python") == ">=100":
            break
        time.sleep(0.01)
    assert data["latest"] == "99.0.0"
    assert data["requires_python"] == ">=100"
    assert "uv tool install rsconnect-python" in _deploy().stderr


@pytest.mark.parametrize("requirement", [">=3.0", ">=100"])
@httpretty.activate(allow_net_connect=False)
def test_disabled_suppresses_both_messages(release_cli, monkeypatch, requirement):
    _write_cache(latest="99.0.0", requires_python=requirement)
    monkeypatch.setenv("RSCONNECT_DISABLE_VERSION_CHECK", "true")
    result = _deploy()
    assert "99.0.0" not in result.stderr
    assert "pip install --upgrade" not in result.stderr
    assert "uv tool install" not in result.stderr
    assert not httpretty.latest_requests()


@httpretty.activate(allow_net_connect=False)
def test_non_deploy_and_current_release_do_not_warn(release_cli):
    _pypi({"version": "1.0.0", "requires_python": ">=100"})
    result = _runner().invoke(cli, ["version"])
    assert "99.0.0" not in result.stderr
    assert not httpretty.latest_requests()
    result = _deploy()
    assert "uv tool install" not in result.stderr
    assert "pip install --upgrade" not in result.stderr


@httpretty.activate(allow_net_connect=False)
def test_expired_cache_refreshes(release_cli):
    _write_cache(latest=None, requires_python=None, checked_at=time.time() - 90000)
    _pypi({"version": "99.0.0", "requires_python": ">=100"})
    assert "uv tool install rsconnect-python" in _deploy().stderr


@httpretty.activate(allow_net_connect=False)
def test_cold_cache_waits_for_slow_response(release_cli):
    def response(request, uri, headers):
        time.sleep(0.2)
        return (200, headers, json.dumps({"info": {"version": "99.0.0", "requires_python": ">=100"}}))

    httpretty.register_uri(httpretty.GET, "https://pypi.org/pypi/rsconnect-python/json", body=response)
    assert "uv tool install rsconnect-python" in _deploy().stderr


@httpretty.activate(allow_net_connect=False)
def test_failed_fetch_is_cached(release_cli):
    httpretty.register_uri(httpretty.GET, "https://pypi.org/pypi/rsconnect-python/json", status=503, body="")
    assert "pip install --upgrade" not in _deploy().stderr
    assert json.loads(_cache_path().read_text())["latest"] is None
    httpretty.reset()
    assert "pip install --upgrade" not in _deploy().stderr
    assert not httpretty.latest_requests()


@httpretty.activate(allow_net_connect=False)
def test_development_release_skips_check(release_cli, monkeypatch):
    monkeypatch.setattr(rsconnect, "VERSION", "1.0.0.dev1")
    importlib.reload(rsconnect.version_check)
    _write_cache(latest="99.0.0", requires_python=">=100")
    assert "99.0.0" not in _deploy().stderr
    assert not httpretty.latest_requests()


@httpretty.activate(allow_net_connect=False)
def test_corrupt_cache_refreshes(release_cli):
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{invalid json")
    _pypi({"version": "99.0.0", "requires_python": ">=100"})
    assert "uv tool install rsconnect-python" in _deploy().stderr


@httpretty.activate(allow_net_connect=False)
def test_cold_cache_wait_is_bounded(release_cli):
    release_response = threading.Event()
    request_started = threading.Event()

    def response(request, uri, headers):
        request_started.set()
        release_response.wait(timeout=10)
        return (200, headers, json.dumps({"info": {"version": "99.0.0", "requires_python": ">=100"}}))

    httpretty.register_uri(httpretty.GET, "https://pypi.org/pypi/rsconnect-python/json", body=response)
    try:
        started = time.monotonic()
        result = _deploy()
        elapsed = time.monotonic() - started
        assert request_started.is_set()
        assert elapsed < 5
        assert "99.0.0" not in result.stderr
    finally:
        release_response.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            if "requires_python" in json.loads(_cache_path().read_text()):
                break
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.01)
    else:
        pytest.fail("Background refresh did not finish")
