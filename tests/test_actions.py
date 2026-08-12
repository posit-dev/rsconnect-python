import logging
import os
from unittest import TestCase

import pytest

from rsconnect.actions import _verify_server, cli_feedback, quarto_inputs_from_inspect, set_verbosity
from rsconnect.api import RSConnectServer
from rsconnect.exception import RSConnectException
from rsconnect.log import console_logger, logger, warn_user


class TestActions(TestCase):
    @staticmethod
    def optional_target(default):
        return os.environ.get("CONNECT_DEPLOY_TARGET", default)

    def test_verify_server(self):
        with self.assertRaises(RSConnectException):
            _verify_server(RSConnectServer("fake-url", None))

        # noinspection PyUnusedLocal
        def fake_cap(details):
            return False

        # noinspection PyUnusedLocal
        def fake_cap_with_doc(details):
            """A docstring."""
            return False


@pytest.fixture
def quiet_mode():
    logger.set_quiet(True)
    yield
    logger.set_quiet(False)
    logger.setLevel(logging.INFO)
    console_logger.setLevel(logging.DEBUG)


def test_cli_feedback_quiet_suppresses_step_labels(quiet_mode, capsys):
    with cli_feedback("Some step"):
        pass
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_cli_feedback_quiet_routes_error_to_stderr(quiet_mode, capsys):
    with pytest.raises(SystemExit):
        with cli_feedback("Some step"):
            raise RSConnectException("boom")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "boom" in captured.err


def test_warn_user_writes_to_stderr_in_quiet_mode(quiet_mode, capsys):
    warn_user("careful")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "careful" in captured.err


def test_set_verbosity_resets_quiet_state(quiet_mode):
    set_verbosity(0, quiet=True)
    assert logger.quiet
    assert console_logger.level == logging.WARNING

    # A later non-quiet invocation in the same process must fully undo quiet mode.
    set_verbosity(0)
    assert not logger.quiet
    assert console_logger.level == logging.DEBUG


def test_quarto_inputs_from_inspect_relativizes_in_render_order(tmp_path):
    inspect = {
        "quarto": {"version": "1.4.0"},
        "engines": ["markdown"],
        "files": {
            "input": [
                str(tmp_path / "zebra.qmd"),
                str(tmp_path / "docs" / "about.qmd"),
            ],
        },
    }
    assert quarto_inputs_from_inspect(str(tmp_path), inspect) == ["zebra.qmd", "docs/about.qmd"]


def test_quarto_inputs_from_inspect_is_empty_for_a_standalone_document(tmp_path):
    doc = tmp_path / "report.qmd"
    doc.write_text("# hi")
    inspect = {"quarto": {"version": "1.4.0"}, "engines": ["markdown"]}
    assert quarto_inputs_from_inspect(str(doc), inspect) == []
