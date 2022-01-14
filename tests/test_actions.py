import os
import shutil
import subprocess
import sys
import tempfile

try:
    import typing
except ImportError:
    typing = None

from os.path import basename, dirname, join
from unittest import TestCase

import pytest

from funcsigs import signature

import rsconnect.actions

from rsconnect import api

from rsconnect.actions import (
    _default_title,
    _default_title_from_manifest,
    _make_deployment_name,
    _to_server_check_list,
    _validate_title,
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
    inspect_environment,
    is_conda_supported_on_server,
    validate_entry_point,
    validate_extra_files,
    which_python,
)
from rsconnect.api import RSConnectException, RSConnectServer
from rsconnect.environment import MakeEnvironment

from .utils import get_manifest_path, get_api_path, get_dir


class TestActions(TestCase):
    @staticmethod
    def optional_target(default):
        return os.environ.get("CONNECT_DEPLOY_TARGET", default)

    def test_which_python(self):
        with self.assertRaises(RSConnectException):
            which_python("fake.file")

        self.assertEqual(which_python(sys.executable), sys.executable)
        self.assertEqual(which_python(None), sys.executable)
        self.assertEqual(which_python(None, {"RETICULATE_PYTHON": "fake-python"}), "fake-python")

    def test_verify_server(self):
        with self.assertRaises(RSConnectException):
            _verify_server(RSConnectServer("fake-url", None))

    def test_to_server_check_list(self):
        a_list = _to_server_check_list("no-scheme")

        self.assertEqual(a_list, ["https://no-scheme", "http://no-scheme"])

        a_list = _to_server_check_list("//no-scheme")

        self.assertEqual(a_list, ["https://no-scheme", "http://no-scheme"])

        a_list = _to_server_check_list("scheme://no-scheme")

        self.assertEqual(a_list, ["scheme://no-scheme"])

    def test_check_server_capabilities(self):
        no_api_support = {"python": {"api_enabled": False}}
        api_support = {"python": {"api_enabled": True}}

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: no_api_support)
        self.assertEqual(
            str(context.exception),
            "The RStudio Connect server does not allow for Python APIs.",
        )

        check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: api_support)

        no_conda = api_support
        conda_not_supported = {"conda": {"supported": False}}
        conda_supported = {"conda": {"supported": True}}

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: no_conda)
        self.assertEqual(
            str(context.exception),
            "Conda is not supported on the target server.  " + "Try deploying without requesting Conda.",
        )

        with self.assertRaises(api.RSConnectException) as context:
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

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (fake_cap,), lambda x: None)
        self.assertEqual(
            str(context.exception),
            "The server does not satisfy the fake_cap capability check.",
        )

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (fake_cap_with_doc,), lambda x: None)
        self.assertEqual(
            str(context.exception),
            "The server does not satisfy the fake_cap_with_doc capability check.",
        )

    def test_validate_title(self):
        with self.assertRaises(RSConnectException):
            _validate_title("12")

        with self.assertRaises(RSConnectException):
            _validate_title("1" * 1025)

        _validate_title("123")
        _validate_title("1" * 1024)

    def test_validate_entry_point(self):
        directory = tempfile.mkdtemp()

        try:
            self.assertEqual(validate_entry_point(None, directory), "app")
            self.assertEqual(validate_entry_point("app", directory), "app")
            self.assertEqual(validate_entry_point("app:app", directory), "app:app")

            with self.assertRaises(RSConnectException):
                validate_entry_point("x:y:z", directory)

                with open(join(directory, "onlysource.py"), "w") as f:
                    f.close()
                    self.assertEqual(validate_entry_point(None, directory), "onlysource")

                    with open(join(directory, "main.py"), "w") as f:
                        f.close()
                        self.assertEqual(validate_entry_point(None, directory), "main")
        finally:
            shutil.rmtree(directory)

    def test_make_deployment_name(self):
        self.assertEqual(_make_deployment_name(None, "title", False), "title")
        self.assertEqual(_make_deployment_name(None, "Title", False), "title")
        self.assertEqual(_make_deployment_name(None, "My Title", False), "my_title")
        self.assertEqual(_make_deployment_name(None, "My  Title", False), "my_title")
        self.assertEqual(_make_deployment_name(None, "My _ Title", False), "my_title")
        self.assertEqual(_make_deployment_name(None, "My-Title", False), "my-title")
        # noinspection SpellCheckingInspection
        self.assertEqual(_make_deployment_name(None, u"M\ry\n \tT\u2103itle", False), "my_title")
        self.assertEqual(_make_deployment_name(None, u"\r\n\t\u2103", False), "___")
        self.assertEqual(_make_deployment_name(None, u"\r\n\tR\u2103", False), "__r")

    def test_default_title(self):
        self.assertEqual(_default_title("testing.txt"), "testing")
        self.assertEqual(_default_title("this.is.a.test.ext"), "this.is.a.test")
        self.assertEqual(_default_title("1.ext"), "001")
        self.assertEqual(_default_title("%s.ext" % ("n" * 2048)), "n" * 1024)

    def test_default_title_from_manifest(self):
        self.assertEqual(_default_title_from_manifest({}, "dir/to/manifest.json"), "0to")
        # noinspection SpellCheckingInspection
        m = {"metadata": {"entrypoint": "point"}}
        self.assertEqual(_default_title_from_manifest(m, "dir/to/manifest.json"), "point")
        m = {"metadata": {"primary_rmd": "file.Rmd"}}
        self.assertEqual(_default_title_from_manifest(m, "dir/to/manifest.json"), "file")
        m = {"metadata": {"primary_html": "page.html"}}
        self.assertEqual(_default_title_from_manifest(m, "dir/to/manifest.json"), "page")
        m = {"metadata": {"primary_wat?": "my-cool-thing.wat"}}
        self.assertEqual(_default_title_from_manifest(m, "dir/to/manifest.json"), "0to")
        # noinspection SpellCheckingInspection
        m = {"metadata": {"entrypoint": "module:object"}}
        self.assertEqual(_default_title_from_manifest(m, "dir/to/manifest.json"), "0to")

    def test_validate_extra_files(self):
        # noinspection SpellCheckingInspection
        directory = dirname(get_manifest_path("shinyapp"))

        with self.assertRaises(RSConnectException):
            validate_extra_files(directory, ["../other_dir/file.txt"])

        with self.assertRaises(RSConnectException):
            validate_extra_files(directory, ["not_a_file.txt"])

        self.assertEqual(validate_extra_files(directory, None), [])
        self.assertEqual(validate_extra_files(directory, []), [])
        self.assertEqual(
            validate_extra_files(directory, [join(directory, "index.htm")]),
            ["index.htm"],
        )

    def test_deploy_python_api_validates(self):
        directory = get_api_path("flask")
        server = RSConnectServer("https://www.bogus.com", "bogus")
        with self.assertRaises(RSConnectException):
            deploy_python_api(server, directory, [], [], "bogus")

    def test_deploy_dash_app_signature(self):
        self.assertEqual(
            str(signature(deploy_dash_app)),
            "({})".format(
                ", ".join(
                    [
                        "connect_server",
                        "directory",
                        "extra_files",
                        "excludes",
                        "entry_point",
                        "new=False",
                        "app_id=None",
                        "title=None",
                        "python=None",
                        "conda_mode=False",
                        "force_generate=False",
                        "log_callback=None",
                    ]
                )
            ),
        )

    def test_deploy_dash_app_docs(self):
        self.assertTrue("Dash app" in deploy_dash_app.__doc__)

    def test_deploy_streamlit_app_signature(self):
        self.assertEqual(
            str(signature(deploy_streamlit_app)),
            "({})".format(
                ", ".join(
                    [
                        "connect_server",
                        "directory",
                        "extra_files",
                        "excludes",
                        "entry_point",
                        "new=False",
                        "app_id=None",
                        "title=None",
                        "python=None",
                        "conda_mode=False",
                        "force_generate=False",
                        "log_callback=None",
                    ]
                )
            ),
        )

    def test_deploy_streamlit_app_docs(self):
        self.assertTrue("Streamlit app" in deploy_streamlit_app.__doc__)

    def test_deploy_bokeh_app_signature(self):
        self.assertEqual(
            str(signature(deploy_bokeh_app)),
            "({})".format(
                ", ".join(
                    [
                        "connect_server",
                        "directory",
                        "extra_files",
                        "excludes",
                        "entry_point",
                        "new=False",
                        "app_id=None",
                        "title=None",
                        "python=None",
                        "conda_mode=False",
                        "force_generate=False",
                        "log_callback=None",
                    ]
                )
            ),
        )

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
            create_notebook_deployment_bundle(file_name, [], None, None, None)
        file_name = get_dir(join("pip1", "dummy.ipynb"))
        with self.assertRaises(RSConnectException):
            create_notebook_deployment_bundle(file_name, ["bogus"], None, None, None)

    def test_create_api_deployment_bundle_validates(self):
        directory = get_api_path("flask")
        with self.assertRaises(RSConnectException):
            create_api_deployment_bundle(directory, [], [], "bogus:bogus:bogus", None, None)
        with self.assertRaises(RSConnectException):
            create_api_deployment_bundle(directory, ["bogus"], [], "app:app", None, None)

    def test_inspect_environment(self):
        environment = inspect_environment(sys.executable, get_dir("pip1"))
        assert environment is not None
        assert environment.python != ""


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
        with pytest.raises(api.RSConnectException):
            _, _ = get_python_env_info(file_name, python, conda_mode=conda_mode, force_generate=force_generate)
    else:
        python, environment = get_python_env_info(
            file_name, python, conda_mode=conda_mode, force_generate=force_generate
        )

        assert python == expected_python
        assert environment == expected_environment
