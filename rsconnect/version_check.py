"""Background version update check against PyPI.

Checked only on deploy commands. The latest known version from PyPI is cached on
disk and refreshed at most once per :data:`_CACHE_TTL_SECONDS`, so the common case
adds no network traffic and no latency.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.client import HTTPSConnection
from os.path import join
from typing import Optional, Tuple

from packaging.version import Version

from . import VERSION
from .metadata import config_dirname, makedirs

RSCONNECT_DISABLE_VERSION_CHECK = "RSCONNECT_DISABLE_VERSION_CHECK"
_PYPI_HOST = "pypi.org"
_PYPI_PATH = "/pypi/rsconnect-python/json"
_PYPI_TIMEOUT_SECONDS = 2
_JOIN_TIMEOUT_SECONDS = 0.5
_CACHE_TTL_SECONDS = 24 * 60 * 60  # Re-check PyPI at most once a day.
_CACHE_FILENAME = "version_check.json"


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


def _read_cache() -> Tuple[bool, Optional[str]]:
    """Return ``(is_fresh, latest)``.

    ``is_fresh`` is True when a non-expired cache entry exists; ``latest`` is the
    cached PyPI version (or None, e.g. when the last fetch failed). When the cache
    is missing, expired, or unreadable, returns ``(False, None)``.
    """
    try:
        with open(_cache_path()) as f:
            data = json.load(f)
        if time.time() - float(data["checked_at"]) > _CACHE_TTL_SECONDS:
            return (False, None)
        latest = data.get("latest")
        return (True, latest if isinstance(latest, str) else None)
    except Exception:
        return (False, None)


def _write_cache(latest: Optional[str]) -> None:
    """Persist the latest known version (or None) with the current timestamp.

    A None value is still cached so repeated failures don't re-hit PyPI on every
    deploy until the TTL expires.
    """
    try:
        path = _cache_path()
        makedirs(path)
        with open(path, "w") as f:
            json.dump({"checked_at": time.time(), "latest": latest}, f)
    except Exception:
        pass


def _fetch_latest_version() -> Optional[str]:
    conn = None
    try:
        conn = HTTPSConnection(_PYPI_HOST, timeout=_PYPI_TIMEOUT_SECONDS)
        conn.request("GET", _PYPI_PATH, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            return None
        data = json.loads(response.read())
        return data.get("info", {}).get("version")
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()


def _update_message(latest: Optional[str]) -> Optional[str]:
    """Return an upgrade warning if ``latest`` is newer than the running version."""
    try:
        if latest is not None and Version(latest) > Version(VERSION):
            return (
                f"A new version of rsconnect-python is available: {latest} "
                f"(you have {VERSION}).\n"
                f"Upgrade with: pip install --upgrade rsconnect-python"
            )
    except Exception:
        pass
    return None


class BackgroundVersionCheck:
    """Resolves the latest available version, using a cache and a background fetch."""

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[str] = None

    def start(self) -> None:
        if _is_check_disabled() or _is_dev_version(VERSION):
            return
        is_fresh, latest = _read_cache()
        if is_fresh:
            # Use the cached value directly; no network, no thread.
            self._latest = latest
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        latest = _fetch_latest_version()
        _write_cache(latest)
        self._latest = latest

    def get_warning_message(self) -> Optional[str]:
        if self._thread is not None:
            self._thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        return _update_message(self._latest)
