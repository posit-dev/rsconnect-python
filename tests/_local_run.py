"""Run a scaffolded quickstart project locally and probe whether it boots.

Test-internal helpers used by ``test_quickstart_per_mode_boot_smoke`` to
verify that the local-run command documented for each mode (the one
``rsconnect quickstart`` prints under "To run locally:") actually starts
the project. Owns:

- free-port allocation for HTTP modes
- subprocess spawn under ``uv run`` with POSIX process-group teardown
- HTTP readiness polling (4xx accepted; child liveness short-circuit)
- artifact-existence checks for render modes (notebook, quarto)
- the per-mode command/env table that maps an app type to its launch shape

Callers in the smoke test stay short delegations: pick the readiness
shape from the matrix, derive the command from the helpers, spawn,
probe.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator, Mapping, Optional, Sequence, Tuple


def find_free_port() -> int:
    """Bind a transient socket on loopback and return the OS-assigned port.

    The port is released the instant the socket closes, so there is a
    short window in which another process could grab it. The boot-smoke
    matrix runs serially and the spawned child binds within ~1-2s, so
    the race is acceptable in practice. A future move to ``pytest-xdist``
    would invalidate that assumption and require port-hold-until-spawn or
    a per-worker port range.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextlib.contextmanager
def spawn(
    cmd: Sequence[str],
    *,
    cwd: Path,
    extra_env: Optional[Mapping[str, str]] = None,
) -> Iterator[subprocess.Popen]:
    """Run ``uv run <cmd>`` in ``cwd`` and tear down the whole process group on exit.

    ``uv run`` forks the framework worker (uvicorn, streamlit, ...) as a
    child. Sending SIGTERM to ``uv`` alone leaves the worker orphaned and
    keeps the port bound, so the child is started in its own process
    group (``start_new_session=True``) and the group is signaled as a
    unit on context exit.

    :param Sequence[str] cmd: Argv tail passed to ``uv run``; the harness prepends ``uv run``.
    :param Path cwd: Project directory containing ``pyproject.toml`` and ``.venv``.
    :param Mapping[str, str] extra_env: Extra environment overrides merged into ``os.environ``.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    # stdout is captured via PIPE (kernel buffer ~64KB on Linux). On the
    # artifact path ``wait_for_artifact`` drains it; on the HTTP path the
    # buffer is never read until teardown, so a child that emits more than
    # ~64KB during the readiness window would block on ``write()`` and look
    # like a boot timeout. The current frameworks (streamlit, shiny,
    # uvicorn, flask, voila) emit only a few hundred bytes of startup
    # banner, so we accept the risk for the simpler ``PIPE`` shape and
    # keep stdout available for failure dumps. If a chattier framework
    # joins the matrix, swap to a spooled tempfile or a drain thread.
    proc = subprocess.Popen(
        ["uv", "run", *cmd],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                # Swallow a stuck second wait: the OS will reap the pid
                # when the test process exits. A propagated TimeoutExpired
                # here would mask the original test failure.
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)


def wait_for_http(
    port: int,
    *,
    proc: Optional[subprocess.Popen] = None,
    timeout: float = 60.0,
) -> None:
    """Poll ``http://127.0.0.1:<port>/`` until any non-5xx response arrives.

    4xx counts as success: it means the framework is bound and serving,
    just without a route at ``/`` (FastAPI without a root handler, Voila
    without a notebook list). Only 5xx and transport errors keep polling.

    When ``proc`` is supplied, each poll first checks that the child is
    still alive; an early exit short-circuits the wait with a useful
    error instead of waiting for the full timeout. This also closes the
    free-port race window: if some unrelated process happens to bind the
    allocated port between :func:`find_free_port` and the child's bind,
    the liveness check still requires our child to be running.
    """
    deadline = time.monotonic() + timeout
    last_error: Optional[BaseException] = None
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise AssertionError(f"child exited with code {proc.returncode} before {url} was ready")
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status < 500:
                    return
                last_error = AssertionError(f"server responded {resp.status}")
        except urllib.error.HTTPError as err:
            if err.code < 500:
                return
            last_error = err
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as err:
            last_error = err
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {url}: {last_error!r}")


def wait_for_artifact(
    proc: subprocess.Popen,
    artifact: Path,
    *,
    timeout: float = 120.0,
) -> None:
    """Wait for a render command to exit cleanly and assert its output exists.

    On timeout the process group is killed so the test does not leak a
    runaway renderer, and any captured stdout is included in the failure
    message.
    """
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        output = _drain_stdout(proc)
        raise AssertionError(f"render timed out after {timeout}s; output:\n{output}")
    if proc.returncode != 0:
        output = _drain_stdout(proc)
        raise AssertionError(f"render exited {proc.returncode}; output:\n{output}")
    assert artifact.exists(), f"expected artifact missing: {artifact}"
    assert artifact.stat().st_size > 0, f"expected artifact empty: {artifact}"


def http_command(app_type: str, port: int) -> Tuple[Sequence[str], Mapping[str, str]]:
    """Return the argv tail and env overrides that boot ``app_type`` on ``port``.

    Different frameworks accept their bind port through different channels:
    streamlit/shiny/voila take a ``--port``-style CLI flag, while fastapi
    and api receive the port through the ``PORT`` env var because their
    template ``__main__.py`` reads it (and falls back to a production
    default when unset). Returning both pieces from one call keeps callers
    free of per-mode env-vs-flag branching.
    """
    if app_type == "streamlit":
        return ("streamlit", "run", "app.py", f"--server.port={port}", "--server.headless=true"), {}
    if app_type == "shiny":
        return ("shiny", "run", "app.py", "--port", str(port)), {}
    if app_type == "voila":
        return ("voila", "notebook.ipynb", f"--port={port}", "--no-browser"), {}
    if app_type in ("fastapi", "api"):
        return ("python", "-m", "hello_app"), {"PORT": str(port)}
    raise ValueError(f"no http command for app_type={app_type!r}")


def artifact_command(app_type: str) -> Tuple[str, ...]:
    """Return the argv tail (after ``uv run``) that renders ``app_type`` to disk."""
    if app_type == "notebook":
        # ``--to notebook`` is required by recent nbconvert versions and yields
        # the default ``notebook.nbconvert.ipynb`` output suffix.
        return ("jupyter", "nbconvert", "--to", "notebook", "--execute", "notebook.ipynb")
    if app_type == "quarto":
        return ("quarto", "render", "report.qmd")
    raise ValueError(f"no artifact command for app_type={app_type!r}")


def artifact_path(app_type: str, project_dir: Path) -> Path:
    """Return the on-disk path produced by ``artifact_command(app_type)``."""
    if app_type == "notebook":
        # jupyter nbconvert default: ``<stem>.nbconvert.ipynb`` next to source.
        return project_dir / "notebook.nbconvert.ipynb"
    if app_type == "quarto":
        # quarto render default for a single .qmd: ``<stem>.html`` next to source.
        return project_dir / "report.html"
    raise ValueError(f"no artifact path for app_type={app_type!r}")


def _drain_stdout(proc: subprocess.Popen) -> str:
    if proc.stdout is None:
        return ""
    try:
        return proc.stdout.read() or ""
    except (ValueError, OSError):
        return ""
