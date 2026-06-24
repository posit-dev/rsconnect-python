import json
import os
import time
from unittest.mock import patch

import click
import click.testing
import pytest

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


# A throwaway deploy subcommand so we can exercise the deploy group's result
# callback without contacting a real server.
@deploy.command(name="_version_check_test_noop", hidden=True)
def _version_check_test_noop():
    click.echo("noop-ran")


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
        path = tmp_path / "version_check.json"
        path.write_text(json.dumps({"checked_at": time.time() - 999999, "latest": "1.29.0"}))
        with patch("rsconnect.version_check._cache_path", return_value=str(path)):
            assert _read_cache() == (False, None)

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
    @patch("rsconnect.version_check._fetch_latest_version", return_value="2.0.0")
    @patch("rsconnect.version_check._read_cache", return_value=(False, None))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_stale_cache_fetches_and_writes(self, _disabled, _dev, _read, mock_fetch, mock_write):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker._thread is not None
        message = checker.get_warning_message()
        assert message is not None
        assert "2.0.0" in message
        mock_fetch.assert_called_once()
        mock_write.assert_called_once_with("2.0.0")

    @patch("rsconnect.version_check._read_cache", return_value=(True, None))
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_warning_when_cache_has_no_version(self, _disabled, _dev, _read):
        checker = BackgroundVersionCheck()
        checker.start()
        assert checker.get_warning_message() is None

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
        runner = click.testing.CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["deploy", "_version_check_test_noop"])
        assert result.exit_code == 0
        assert "99.0.0" not in result.output
        assert "99.0.0" in result.stderr

    @patch("rsconnect.version_check._read_cache", return_value=(True, None))
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_warning_when_current(self, _disabled, _dev, _read):
        runner = click.testing.CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["deploy", "_version_check_test_noop"])
        assert result.exit_code == 0
        assert "new version" not in result.stderr

    @patch("rsconnect.version_check._read_cache", return_value=(True, "99.0.0"))
    @patch("rsconnect.version_check.VERSION", "1.0.0")
    @patch("rsconnect.version_check._is_dev_version", return_value=False)
    @patch("rsconnect.version_check._is_check_disabled", return_value=False)
    def test_no_check_on_non_deploy_command(self, _disabled, _dev, _read):
        runner = click.testing.CliRunner(mix_stderr=False)
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "99.0.0" not in result.stderr
        # The check never runs for non-deploy commands, so the cache isn't even read.
        _read.assert_not_called()
