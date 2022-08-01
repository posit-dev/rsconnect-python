import os
import subprocess
import sys

try:
    import typing
except ImportError:
    typing = None

from os.path import basename, join
from unittest import TestCase

import pytest

import rsconnect.actions


from rsconnect.actions import (
    _verify_server,
    are_apis_supported_on_server,
    check_server_capabilities,
    create_api_deployment_bundle,
    create_notebook_deployment_bundle,
    deploy_dash_app,
    deploy_python_api,
    deploy_streamlit_app,
    deploy_bokeh_app,
    gather_basic_deployment_info_for_api,
    get_python_env_info,
    is_conda_supported_on_server,
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

    def test_check_server_capabilities(self):
        no_api_support = {"python": {"api_enabled": False}}
        api_support = {"python": {"api_enabled": True}}

        with self.assertRaises(RSConnectException) as context:
            check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: no_api_support)
        self.assertEqual(
            str(context.exception),
            "The RStudio Connect server does not allow for Python APIs.",
        )

        check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: api_support)

        no_conda = api_support
        conda_not_supported = {"conda": {"supported": False}}
        conda_supported = {"conda": {"supported": True}}

        with self.assertRaises(RSConnectException) as context:
            check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: no_conda)
        self.assertEqual(
            str(context.exception),
            "Conda is not supported on the target server.  " + "Try deploying without requesting Conda.",
        )

        with self.assertRaises(RSConnectException) as context:
            check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: conda_not_supported)
        self.assertEqual(
            str(context.exception),
            "Conda is not supported on the target server.  " + "Try deploying without requesting Conda.",
        )

        check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: conda_supported)

        # noinspection PyUnusedLocal
        def fake_cap(details):
            return False

        # noinspection PyUnusedLocal
        def fake_cap_with_doc(details):
            """A docstring."""
            return False

        with self.assertRaises(RSConnectException) as context:
            check_server_capabilities(None, (fake_cap,), lambda x: None)
        self.assertEqual(
            str(context.exception),
            "The server does not satisfy the fake_cap capability check.",
        )

        with self.assertRaises(RSConnectException) as context:
            check_server_capabilities(None, (fake_cap_with_doc,), lambda x: None)
        self.assertEqual(
            str(context.exception),
            "The server does not satisfy the fake_cap_with_doc capability check.",
        )

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

    def test_gather_basic_deployment_info_for_api_validates(self):
        directory = get_api_path("flask")
        server = RSConnectServer("https://www.bogus.com", "bogus")
        with self.assertRaises(RSConnectException):
            gather_basic_deployment_info_for_api(server, None, directory, "bogus:bogus:bogus", False, 0, "bogus")
        with self.assertRaises(RSConnectException):
            gather_basic_deployment_info_for_api(server, None, directory, "app:app", False, 0, "")

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


@pytest.mark.parametrize(
    (
        "file_name",
        "python",
        "conda_mode",
        "force_generate",
        "expected_python",
        "expected_environment",
    ),
    [
        pytest.param(
            "path/to/file.py",
            sys.executable,
            False,
            False,
            sys.executable,
            MakeEnvironment(
                conda=None,
                filename="requirements.txt",
                locale="en_US.UTF-8",
                package_manager="pip",
                source="pip_freeze",
            ),
            id="basic",
        ),
        pytest.param(
            "another/file.py",
            basename(sys.executable),
            False,
            False,
            sys.executable,
            MakeEnvironment(
                conda=None,
                filename="requirements.txt",
                locale="en_US.UTF-8",
                package_manager="pip",
                source="pip_freeze",
            ),
            id="which_python",
        ),
        pytest.param(
            "even/moar/file.py",
            "whython",
            True,
            True,
            "/very/serious/whython",
            MakeEnvironment(
                conda="/opt/Conda/bin/conda",
                filename="requirements.txt",
                locale="en_US.UTF-8",
                package_manager="pip",
                source="pip_freeze",
            ),
            id="conda_ish",
        ),
        pytest.param(
            "will/the/files/never/stop.py",
            "argh.py",
            False,
            True,
            "unused",
            MakeEnvironment(error="Could not even do things"),
            id="exploding",
        ),
    ],
)
def test_get_python_env_info(
    monkeypatch,
    file_name,
    python,
    conda_mode,
    force_generate,
    expected_python,
    expected_environment,
):
    def fake_which_python(python, env=os.environ):
        return expected_python

    def fake_inspect_environment(
        python,
        directory,
        conda_mode=False,
        force_generate=False,
        check_output=subprocess.check_output,
    ):
        return expected_environment

    monkeypatch.setattr(rsconnect.actions, "inspect_environment", fake_inspect_environment)

    monkeypatch.setattr(rsconnect.actions, "which_python", fake_which_python)

    if expected_environment.error is not None:
        with pytest.raises(RSConnectException):
            _, _ = get_python_env_info(file_name, python, conda_mode=conda_mode, force_generate=force_generate)
    else:
        python, environment = get_python_env_info(
            file_name, python, conda_mode=conda_mode, force_generate=force_generate
        )

        assert python == expected_python
        assert environment == expected_environment
