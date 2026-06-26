import json
import os
import threading
import time
from unittest.mock import patch

import click
import click.testing
import pytest

from rsconnect.exception import RSConnectException
from rsconnect.actions import cli_feedback
from rsconnect.main import cli, deploy
from rsconnect.version_check import (
    RSCONNECT_DISABLE_VERSION_CHECK,
    BackgroundVersionCheck,
    _is_check_disabled,
    _is_dev_version,
    _read_cache,
    _update_message,
    _write_cache,
)


def _cli_runner() -> click.testing.CliRunner:
    """Build a CliRunner with stdout/stderr kept separate across Click versions.

    Click < 8.2 needs ``mix_stderr=False`` to expose ``result.stderr``; Click >= 8.2
    removed the argument and always separates the streams.
    """
    try:
        return click.testing.CliRunner(mix_stderr=False)
    except TypeError:
        return click.testing.CliRunner()


# A throwaway deploy subcommand so we can exercise the deploy group's result
# callback without contacting a real server.
@deploy.command(name="_version_check_test_noop", hidden=True)
def _version_check_test_noop():
    click.echo("noop-ran")


# A deploy subcommand that fails the way real ones do: cli_feedback catches the
# exception and calls sys.exit(1). The upgrade hint should still print.
@deploy.command(name="_version_check_test_fail", hidden=True)
def _version_check_test_fail():
    with cli_feedback(""):
        raise RSConnectException("boom")


class TestIsCheckDisabled:
    def test_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _is_check_disabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_disabled(self, value):
        with patch.dict(os.environ, {RSCONNECT_DISABLE_VERSION_CHECK: value}):
            assert _is_check_disabled() is True

    @pytest.mark.parametrize("value", ["0", "no", "false", ""])
    def test_not_disabled(self, value):
        with patch.dict(os.environ, {RSCONNECT_DISABLE_VERSION_CHECK: value}):
            assert _is_check_disabled() is False


class TestIsDevVersion:
    def test_dev_version(self):
        assert _is_dev_version("1.29.1.dev10+g68dd1934d.d20260622") is True

    def test_release_version(self):
        assert _is_dev_version("1.29.1") is False

    def test_prerelease_version(self):
        assert _is_dev_version("1.29.1rc1") is False

    def test_unparseable(self):
        assert _is_dev_version("NOTSET") is True


class TestUpdateMessage:
    @patch("rsconnect.version_check.VERSION", "1.28.0")
    def test_update_available(self):
        message = _update_message("1.29.0")
        assert message is not None
        assert "1.29.0" in message
        assert "pip install --upgrade rsconnect-python" in message

    @patch("rsconnect.version_check.VERSION", "1.29.0")
    def test_up_to_date(self):
        assert _update_message("1.29.0") is None

    @patch("rsconnect.version_check.VERSION", "1.30.0")
    def test_ahead_of_pypi(self):
        assert _update_message("1.29.0") is None

    def test_none_latest(self):
        assert _update_message(None) is None

    @patch("rsconnect.version_check.VERSION", "1.28.0")
    def test_unparseable_latest(self):
        assert _update_message("not-a-version") is None


class TestCache:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "version_check.json")
        with patch("rsconnect.version_check._cache_path", return_value=path):
            _write_cache("1.29.0")
            assert _read_cache() == (True, "1.29.0")

    def test_caches_none(self, tmp_path):
        path = str(tmp_path / "version_check.json")
        with patch("rsconnect.version_check._cache_path", return_value=path):
            _write_cache(None)
            assert _read_cache() == (True, None)

    def test_missing_cache(self, tmp_path):
        path = str(tmp_path / "nope.json")
        with patch("rsconnect.version_check._cache_path", return_value=path):
            assert _read_cache() == (False, None)

    def test_expired_cache(self, tmp_path):
        # A stale entry is reported as not-fresh but still surfaces its value, so
        # the upgrade hint can use it while a refresh runs in the background.
        path = tmp_path / "version_check.json"
        path.write_text(json.dumps({"checked_at": time.time() - 999999, "latest": "1.29.0"}))
        with patch("rsconnect.version_check._cache_path", return_value=str(path)):
            assert _read_cache() == (False, "1.29.0")

    def test_corrupt_cache(self, tmp_path):
        path = tmp_path / "version_check.json"
        path.write_text("{not json")
        with patch("rsconnect.version_check._cache_path", return_value=str(path)):
            assert _read_cache() == (False, None)


class TestBackgroundVersionCheck:
    @patch("rsconnect.version_check._read_cache", return_value=(True, "2.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_fresh_cache_avoids_thread(self, _disabled, _dev, mock_read):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker._thread is None  # No network when the cache is fresh.
        message = checker.get_warning_message()
        assert message is not None
        assert "2.0.0" in message

    @patch("rsconnect.version_check._write_cache")
    @patch("rsconnect.version_check._fetch_latest_version", return_value="3.0.0")
    @patch("rsconnect.version_check._read_cache", return_value=(False, "2.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_stale_cache_warns_from_cache_and_refreshes(self, _disabled, _dev, _read, mock_fetch, mock_write):
        checker = BackgroundVersionCheck()
        checker.start()
        # A stale cached value is enough to warn synchronously, so the message is
        # available without waiting on the network (it names either the stale
        # 2.0.0 or the freshly fetched 3.0.0, depending on thread timing -- both
        # are newer than the running version, so either is a valid hint).
        assert checker._thread is not None
        message = checker.get_warning_message()
        assert message is not None
        # The fetch also refreshes the cache for the next invocation.
        checker._thread.join()
        mock_fetch.assert_called_once()
        mock_write.assert_called_once_with("3.0.0")

    @patch("rsconnect.version_check._write_cache")
    @patch("rsconnect.version_check._fetch_latest_version", return_value="2.0.0")
    @patch("rsconnect.version_check._read_cache", return_value=(False, None))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_absent_cache_blocks_briefly_and_warns(self, _disabled, _dev, _read, mock_fetch, mock_write):
        checker = BackgroundVersionCheck()
        checker.start()
        # With no cached value, the in-flight fetch is given a bounded chance to
        # finish so even a cold cache (first run, or an ephemeral environment)
        # can still warn this run -- not just refresh for the next one.
        assert checker._thread is not None
        message = checker.get_warning_message()
        assert message is not None
        assert "2.0.0" in message
        checker._thread.join()
        mock_write.assert_called_once_with("2.0.0")

    @patch("rsconnect.version_check._read_cache", return_value=(True, None))
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_warning_when_cache_has_no_version(self, _disabled, _dev, _read):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker.get_warning_message() is None

    @patch("rsconnect.version_check._PYPI_TIMEOUT_SECONDS", 0.2)
    @patch("rsconnect.version_check._write_cache")
    @patch("rsconnect.version_check._read_cache", return_value=(False, None))
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_hung_fetch_does_not_block_beyond_timeout(self, _disabled, _dev, _read, _write):
        # A fetch that never returns (network black hole) must not hang the CLI:
        # the cold-cache wait is bounded by _PYPI_TIMEOUT_SECONDS, after which the
        # run proceeds with no hint and the daemon thread is left behind.
        release = threading.Event()

        def hung_fetch():
            release.wait(timeout=30)  # Far longer than the join timeout.
            return "99.0.0"

        try:
            with patch("rsconnect.version_check._fetch_latest_version", side_effect=hung_fetch):
                checker = BackgroundVersionCheck()
                checker.start()
                assert checker._thread is not None
                assert checker._thread.daemon  # Never blocks interpreter exit.
                start = time.monotonic()
                message = checker.get_warning_message()
                elapsed = time.monotonic() - start
            # Returned promptly (well under the 30s fetch) with no hint this run.
            assert message is None
            assert elapsed < 5
        finally:
            release.set()  # Let the background thread unwind.

    @patch("rsconnect.version_check._read_cache")
    @patch("rsconnect.version_check._is_dev_version", return_value=True)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_thread_for_dev_version(self, _disabled, _dev, mock_read):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker._thread is None
        mock_read.assert_not_called()
        assert checker.get_warning_message() is None

    @patch("rsconnect.version_check._read_cache")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=True)
    def test_no_thread_when_disabled(self, _disabled, _dev, mock_read):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker._thread is None
        mock_read.assert_not_called()
        assert checker.get_warning_message() is None


class TestCLIIntegration:
    @patch("rsconnect.version_check._read_cache", return_value=(True, "99.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_warning_on_deploy_command_stderr(self, _disabled, _dev, _read):
        runner = _cli_runner()
        result = runner.invoke(cli, ["deploy", "_version_check_test_noop"])
        assert result.exit_code == 0
        # Use stdout (not output): in Click >= 8.2 result.output is the combined
        # stream, while stdout stays stderr-free across Click versions.
        assert "99.0.0" not in result.stdout
        assert "99.0.0" in result.stderr

    @patch("rsconnect.version_check._read_cache", return_value=(True, "99.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_warning_on_failed_deploy_command(self, _disabled, _dev, _read):
        runner = _cli_runner()
        result = runner.invoke(cli, ["deploy", "_version_check_test_fail"])
        assert result.exit_code != 0
        # The hint prints even though the deploy failed and exited non-zero.
        assert "99.0.0" in result.stderr

    @patch("rsconnect.version_check._write_cache")
    @patch("rsconnect.version_check._read_cache", return_value=(False, None))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_warning_on_failed_deploy_with_cold_cache(self, _disabled, _dev, _read, _write):
        # The original regression: a fast failure (missing requirements.txt, etc.)
        # with no cache. The deploy raises and exits almost instantly, so a fetch
        # with any real latency would lose the race -- the warning only prints
        # because get_warning_message blocks briefly on the cold cache. The slow
        # fetch below makes that race deterministic: without the blocking join the
        # thread couldn't have set the version in time.
        def slow_fetch():
            time.sleep(0.3)
            return "99.0.0"

        runner = _cli_runner()
        with patch("rsconnect.version_check._fetch_latest_version", side_effect=slow_fetch):
            result = runner.invoke(cli, ["deploy", "_version_check_test_fail"])
        assert result.exit_code != 0
        assert "99.0.0" in result.stderr

    @patch("rsconnect.version_check._read_cache", return_value=(True, None))
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_warning_when_current(self, _disabled, _dev, _read):
        runner = _cli_runner()
        result = runner.invoke(cli, ["deploy", "_version_check_test_noop"])
        assert result.exit_code == 0
        assert "new version" not in result.stderr

    @patch("rsconnect.version_check._read_cache", return_value=(True, "99.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_check_on_non_deploy_command(self, _disabled, _dev, _read):
        runner = _cli_runner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "99.0.0" not in result.stderr
        # The check never runs for non-deploy commands, so the cache isn't even read.
        _read.assert_not_called()
