import os
from unittest import TestCase

from rsconnect.actions import _verify_server, infer_quarto_app_mode, is_quarto_shiny
from rsconnect.api import RSConnectServer
from rsconnect.exception import RSConnectException
from rsconnect.models import AppModes


class TestQuartoShinyDetection(TestCase):
    def test_is_quarto_shiny_via_formats_metadata(self):
        """Test detection via formats.<format>.metadata.server.type"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "formats": {
                "html": {
                    "metadata": {
                        "server": {"type": "shiny"},
                    },
                },
            },
        }
        self.assertTrue(is_quarto_shiny(inspect))

    def test_is_quarto_shiny_via_file_information(self):
        """Test detection via fileInformation.<path>.metadata.server"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "fileInformation": {
                "/path/to/app.qmd": {
                    "metadata": {
                        "server": "shiny",
                    },
                },
            },
        }
        self.assertTrue(is_quarto_shiny(inspect))

    def test_is_quarto_shiny_static_document(self):
        """Test that static documents are not detected as Shiny"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "formats": {
                "html": {
                    "metadata": {
                        "title": "My Document",
                    },
                },
            },
        }
        self.assertFalse(is_quarto_shiny(inspect))

    def test_is_quarto_shiny_empty_inspect(self):
        """Test with minimal inspect output"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["markdown"],
        }
        self.assertFalse(is_quarto_shiny(inspect))

    def test_is_quarto_shiny_wrong_server_type(self):
        """Test that documents with wrong server type are not detected as Shiny"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "formats": {
                "html": {
                    "metadata": {
                        "server": {"type": "other"},
                    },
                },
            },
        }
        self.assertFalse(is_quarto_shiny(inspect))

    def test_is_quarto_shiny_wrong_server_value(self):
        """Test that documents with wrong server value in fileInformation are not detected as Shiny"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "fileInformation": {
                "/path/to/app.qmd": {
                    "metadata": {
                        "server": "other",
                    },
                },
            },
        }
        self.assertFalse(is_quarto_shiny(inspect))

    def test_infer_quarto_app_mode_shiny(self):
        """Test that Shiny documents get SHINY_QUARTO mode"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["jupyter"],
            "formats": {
                "html": {
                    "metadata": {
                        "server": {"type": "shiny"},
                    },
                },
            },
        }
        self.assertEqual(infer_quarto_app_mode(inspect), AppModes.SHINY_QUARTO)

    def test_infer_quarto_app_mode_static(self):
        """Test that static documents get STATIC_QUARTO mode"""
        inspect = {
            "quarto": {"version": "1.3.0"},
            "engines": ["markdown"],
        }
        self.assertEqual(infer_quarto_app_mode(inspect), AppModes.STATIC_QUARTO)


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
