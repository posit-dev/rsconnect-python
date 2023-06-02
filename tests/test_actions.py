import os

try:
    import typing
except ImportError:
    typing = None

from os.path import join
from unittest import TestCase

from rsconnect.actions import (
    _verify_server,
    create_api_deployment_bundle,
    create_notebook_deployment_bundle,
    deploy_dash_app,
    deploy_python_api,
    deploy_streamlit_app,
    deploy_bokeh_app,
)
from rsconnect.api import RSConnectServer
from rsconnect.environment import MakeEnvironment
from rsconnect.exception import RSConnectException

from .utils import get_api_path, get_dir


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

    def test_deploy_python_api_validates(self):
        directory = get_api_path("flask")
        server = RSConnectServer("https://www.bogus.com", "bogus")
        with self.assertRaises(RSConnectException):
            deploy_python_api(server, directory, [], [], "bogus", False, None, None, None, False, False, None, None)

    def test_deploy_dash_app_docs(self):
        self.assertTrue("Dash app" in deploy_dash_app.__doc__)

    def test_deploy_streamlit_app_docs(self):
        self.assertTrue("Streamlit app" in deploy_streamlit_app.__doc__)

    def test_deploy_bokeh_app_docs(self):
        self.assertTrue("Bokeh app" in deploy_bokeh_app.__doc__)

    def test_create_notebook_deployment_bundle_validates(self):
        file_name = get_dir(join("pip1", "requirements.txt"))
        with self.assertRaises(RSConnectException):
            create_notebook_deployment_bundle(
                file_name, [], None, None, None, True, hide_all_input=False, hide_tagged_input=False, image=None
            )
        file_name = get_dir(join("pip1", "dummy.ipynb"))
        with self.assertRaises(RSConnectException):
            create_notebook_deployment_bundle(
                file_name, ["bogus"], None, None, None, True, hide_all_input=False, hide_tagged_input=False, image=None
            )

    def test_create_api_deployment_bundle_validates(self):
        directory = get_api_path("flask")
        with self.assertRaises(RSConnectException):
            create_api_deployment_bundle(directory, [], [], "bogus:bogus:bogus", None, None, None, None)
        with self.assertRaises(RSConnectException):
            create_api_deployment_bundle(directory, ["bogus"], [], "app:app", MakeEnvironment(), None, True, None)
