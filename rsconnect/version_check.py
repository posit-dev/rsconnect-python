"""Background version update check against PyPI.

Checked only on deploy commands. The latest known version is cached on disk and
refreshed at most once per :data:`_CACHE_TTL_SECONDS` in a background thread, so a
warm cache adds no network traffic and no latency and prints on every exit path
(including fast failures). Only a cold cache -- the first run, or an ephemeral
environment where the cache never persists -- waits briefly on the fetch so it can
still warn.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from http.client import HTTPSConnection
from os.path import join
from typing import NamedTuple, Optional, Tuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from . import VERSION
from .metadata import config_dirname, makedirs

RSCONNECT_DISABLE_VERSION_CHECK = "RSCONNECT_DISABLE_VERSION_CHECK"
_PYPI_HOST = "pypi.org"
_PYPI_PATH = "/pypi/rsconnect-python/json"
_PYPI_TIMEOUT_SECONDS = 2
_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_FILENAME = "version_check.json"


class _Release(NamedTuple):
    version: str
    requires_python: Optional[str]


def _is_check_disabled() -> bool:
    value = os.environ.get(RSCONNECT_DISABLE_VERSION_CHECK, "").strip().lower()
    return value in ("1", "true", "yes")


def _is_dev_version(version_str: str) -> bool:
    try:
        return Version(version_str).is_devrelease
    except Exception:
        return True


def _cache_path() -> str:
    return join(config_dirname(), _CACHE_FILENAME)


def _read_cache() -> Tuple[bool, Optional[_Release]]:
    """Return freshness and the cached release, retaining stale data for the hint."""
    try:
        with open(_cache_path()) as f:
            data = json.load(f)
        latest = data.get("latest")
        requires_python = data.get("requires_python")
        release = (
            _Release(latest, requires_python if isinstance(requires_python, str) else None)
            if isinstance(latest, str)
            else None
        )
        is_fresh = "requires_python" in data and time.time() - float(data["checked_at"]) <= _CACHE_TTL_SECONDS
        return (is_fresh, release)
    except Exception:
        return (False, None)


def _write_cache(release: Optional[_Release]) -> None:
    """Cache failures too, so they do not trigger another request until the TTL expires."""
    try:
        path = _cache_path()
        makedirs(path)
        with open(path, "w") as f:
            json.dump(
                {
                    "checked_at": time.time(),
                    "latest": release.version if release else None,
                    "requires_python": release.requires_python if release else None,
                },
                f,
            )
    except Exception:
        pass


def _fetch_latest_version() -> Optional[_Release]:
    conn = None
    try:
        conn = HTTPSConnection(_PYPI_HOST, timeout=_PYPI_TIMEOUT_SECONDS)
        conn.request("GET", _PYPI_PATH, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            return None
        info = json.loads(response.read()).get("info", {})
        latest = info.get("version")
        requires_python = info.get("requires_python")
        if isinstance(latest, str):
            return _Release(latest, requires_python if isinstance(requires_python, str) else None)
        return None
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _update_message(release: Optional[_Release]) -> Optional[str]:
    """Return an upgrade warning if the release is newer than the running version."""
    try:
        if release is None or Version(release.version) <= Version(VERSION):
            return None
        python_version = platform.python_version()
        try:
            compatible = not release.requires_python or SpecifierSet(release.requires_python).contains(
                python_version, prereleases=True
            )
        except InvalidSpecifier:
            compatible = True
        if not compatible:
            force = "" if os.path.isfile(join(sys.prefix, "uv-receipt.toml")) else "--force "
            return (
                f"The latest version of rsconnect-python ({release.version}) requires Python "
                f"{release.requires_python}, but you are running Python {python_version}.\n"
                f'Install it with: uv tool install {force}--python "{release.requires_python}" rsconnect-python'
            )
        return (
            f"A new version of rsconnect-python is available: {release.version} "
            f"(you have {VERSION}).\n"
            "Upgrade with: pip install --upgrade rsconnect-python"
        )
    except Exception:
        return None


class BackgroundVersionCheck:
    """Resolves the latest available version, using a cache and a background fetch."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._release: Optional[_Release] = None

    def start(self) -> None:
        if _is_check_disabled() or _is_dev_version(VERSION):
            return
        is_fresh, self._release = _read_cache()
        if not is_fresh:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def _run(self) -> None:
        release = _fetch_latest_version()
        _write_cache(release)
        # Keep a usable stale value when a refresh fails.
        if release is not None:
            self._release = release

    def get_warning_message(self) -> Optional[str]:
        # Only a cold cache waits briefly for the background fetch.
        if self._release is None and self._thread is not None:
            self._thread.join(timeout=_PYPI_TIMEOUT_SECONDS)
        return _update_message(self._release)
