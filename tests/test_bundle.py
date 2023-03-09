# -*- coding: utf-8 -*-
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import pytest
from unittest import TestCase
from os.path import dirname, join, basename, abspath

from rsconnect.bundle import (
    _default_title,
    _default_title_from_manifest,
    _validate_title,
    create_html_manifest,
    get_python_env_info,
    inspect_environment,
    list_files,
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    keep_manifest_specified_file,
    make_voila_bundle,
    to_bytes,
    make_source_manifest,
    make_quarto_manifest,
    make_html_manifest,
    validate_entry_point,
    validate_extra_files,
    which_python,
    guess_deploy_dir,
    Manifest,
    create_voila_manifest,
)
import rsconnect.bundle
from rsconnect.exception import RSConnectException
from rsconnect.models import AppModes
from rsconnect.environment import MakeEnvironment, detect_environment, Environment
from .utils import get_dir, get_manifest_path


class TestBundle(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def test_to_bytes(self):
        self.assertEqual(to_bytes(b"abc123"), b"abc123")
        self.assertEqual(to_bytes(b"\xc3\xa5bc123"), b"\xc3\xa5bc123")
        self.assertEqual(to_bytes(b"\xff\xffabc123"), b"\xff\xffabc123")

        self.assertEqual(to_bytes("abc123"), b"abc123")
        self.assertEqual(to_bytes("åbc123"), b"\xc3\xa5bc123")

        self.assertEqual(to_bytes("abc123"), b"abc123")
        self.assertEqual(to_bytes("åbc123"), b"\xc3\xa5bc123")

    def test_source_bundle1(self):
        self.maxDiff = 5000
        directory = get_dir("pip1")
        nb_path = join(directory, "dummy.ipynb")

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = detect_environment(directory)
        with make_notebook_source_bundle(
            nb_path, environment, None, hide_all_input=False, hide_tagged_input=False, image=None
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:

            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "dummy.ipynb",
                    "manifest.json",
                    "requirements.txt",
                ],
            )

            reqs = tar.extractfile("requirements.txt").read()
            self.assertEqual(reqs, b"numpy\npandas\nmatplotlib\n")

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # don't check locale value, just require it be present
            del manifest["locale"]
            del manifest["python"]["package_manager"]["version"]

            if sys.version_info[0] == 2:
                ipynb_hash = "38aa30662bc16e91e6804cf21d7722f7"
            else:
                ipynb_hash = "36873800b48ca5ab54760d60ba06703a"

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "metadata": {
                        "appmode": "jupyter-static",
                        "entrypoint": "dummy.ipynb",
                    },
                    "python": {
                        "version": self.python_version(),
                        "package_manager": {
                            "name": "pip",
                            "package_file": "requirements.txt",
                        },
                    },
                    "files": {
                        "dummy.ipynb": {
                            "checksum": ipynb_hash,
                        },
                        "requirements.txt": {"checksum": "5f2a5e862fe7afe3def4a57bb5cfb214"},
                    },
                },
            )

    def test_source_bundle2(self):
        self.maxDiff = 5000
        directory = get_dir("pip2")
        nb_path = join(directory, "dummy.ipynb")

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = detect_environment(directory)

        with make_notebook_source_bundle(
            nb_path,
            environment,
            ["data.csv"],
            hide_all_input=False,
            hide_tagged_input=False,
            image="rstudio/connect:bionic",
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:

            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "data.csv",
                    "dummy.ipynb",
                    "manifest.json",
                    "requirements.txt",
                ],
            )

            reqs = tar.extractfile("requirements.txt").read()

            # these are the dependencies declared in our setup.py
            self.assertIn(b"six", reqs)

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # don't check requirements.txt since we don't know the checksum
            del manifest["files"]["requirements.txt"]

            # also don't check locale value, just require it be present
            del manifest["locale"]
            del manifest["python"]["package_manager"]["version"]

            if sys.version_info[0] == 2:
                ipynb_hash = "38aa30662bc16e91e6804cf21d7722f7"
            else:
                ipynb_hash = "36873800b48ca5ab54760d60ba06703a"

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "metadata": {
                        "appmode": "jupyter-static",
                        "entrypoint": "dummy.ipynb",
                    },
                    "python": {
                        "version": self.python_version(),
                        "package_manager": {
                            "name": "pip",
                            "package_file": "requirements.txt",
                        },
                    },
                    "environment": {"image": "rstudio/connect:bionic"},
                    "files": {
                        "dummy.ipynb": {
                            "checksum": ipynb_hash,
                        },
                        "data.csv": {"checksum": "f2bd77cc2752b3efbb732b761d2aa3c3"},
                    },
                },
            )

    def test_list_files(self):
        # noinspection SpellCheckingInspection
        paths = [
            "notebook.ipynb",
            "somedata.csv",
            "subdir/subfile",
            "subdir2/subfile2",
            ".ipynb_checkpoints/notebook.ipynb",
            ".git/config",
        ]

        def walk(base_dir):
            dir_names = []
            file_names = []

            for path in paths:
                if "/" in path:
                    dir_name, file_name = path.split("/", 1)
                    dir_names.append(dir_name)
                else:
                    file_names.append(path)

            yield base_dir, dir_names, file_names

            for subdir in dir_names:
                for path in paths:
                    if path.startswith(subdir + "/"):
                        yield base_dir + "/" + subdir, [], [path.split("/", 1)[1]]

        files = list_files("/", True, walk=walk)
        self.assertEqual(files, paths[:4])

        files = list_files("/", False, walk=walk)
        self.assertEqual(files, paths[:2])

    def test_html_bundle1(self):
        self.do_test_html_bundle(get_dir("pip1"))

    def test_html_bundle2(self):
        self.do_test_html_bundle(get_dir("pip2"))

    def do_test_html_bundle(self, directory):
        self.maxDiff = 5000
        nb_path = join(directory, "dummy.ipynb")

        bundle = make_notebook_html_bundle(
            nb_path,
            sys.executable,
            hide_all_input=False,
            hide_tagged_input=False,
            image=None,
        )

        tar = tarfile.open(mode="r:gz", fileobj=bundle)

        try:
            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "dummy.html",
                    "manifest.json",
                ],
            )

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "metadata": {
                        "appmode": "static",
                        "primary_html": "dummy.html",
                    },
                },
            )
        finally:
            tar.close()
            bundle.close()

    def test_keep_manifest_specified_file(self):
        self.assertTrue(keep_manifest_specified_file("app.R"))
        self.assertFalse(keep_manifest_specified_file("packrat/packrat.lock"))
        self.assertFalse(keep_manifest_specified_file("rsconnect"))
        self.assertFalse(keep_manifest_specified_file("rsconnect/bogus.file"))
        self.assertFalse(keep_manifest_specified_file("rsconnect-python"))
        self.assertFalse(keep_manifest_specified_file("rsconnect-python/bogus.file"))
        self.assertFalse(keep_manifest_specified_file(".svn/bogus.file"))
        self.assertFalse(keep_manifest_specified_file(".env/share/jupyter/kernels/python3/kernel.json"))
        self.assertFalse(keep_manifest_specified_file(".venv/bin/activate"))
        self.assertFalse(keep_manifest_specified_file("env/pyvenv.cfg"))
        self.assertFalse(keep_manifest_specified_file("venv/lib/python3.8/site-packages/wheel/__init__.py"))
        # noinspection SpellCheckingInspection
        self.assertFalse(keep_manifest_specified_file(".Rproj.user/bogus.file"))

    def test_manifest_bundle(self):
        self.maxDiff = 5000
        # noinspection SpellCheckingInspection
        manifest_path = join(dirname(__file__), "testdata", "R", "shinyapp", "manifest.json")

        with make_manifest_bundle(manifest_path) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            tar_names = sorted(tar.getnames())
            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
            manifest_names = sorted(filter(keep_manifest_specified_file, manifest["files"].keys()))
            self.assertEqual(tar_names, manifest_names)

    def test_make_source_manifest(self):
        # Verify the optional parameters
        # image=None,  # type: str
        # environment=None,  # type: typing.Optional[Environment]
        # entrypoint=None,  # type: typing.Optional[str]
        # quarto_inspection=None,  # type: typing.Optional[typing.Dict[str, typing.Any]]

        # No optional parameters
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None, None)
        self.assertEqual(
            manifest,
            {"version": 1, "metadata": {"appmode": "python-api"}, "files": {}},
        )

        # include image parameter
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None, "rstudio/connect:bionic")
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "python-api"},
                "environment": {"image": "rstudio/connect:bionic"},
                "files": {},
            },
        )

        # include environment parameter
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            Environment(
                conda=None,
                contents="",
                error=None,
                filename="requirements.txt",
                locale="en_US.UTF-8",
                package_manager="pip",
                pip="22.0.4",
                python="3.9.12",
                source="file",
            ),
            None,
            None,
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "locale": "en_US.UTF-8",
                "metadata": {"appmode": "python-api"},
                "python": {
                    "version": "3.9.12",
                    "package_manager": {"name": "pip", "version": "22.0.4", "package_file": "requirements.txt"},
                },
                "files": {},
            },
        )

        # include entrypoint parameter
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            None,
            "main.py",
            None,
            None,
        )
        # print(manifest)
        self.assertEqual(
            manifest,
            {"version": 1, "metadata": {"appmode": "python-api", "entrypoint": "main.py"}, "files": {}},
        )

        # include quarto_inspection parameter
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            None,
            None,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            None,
        )
        # print(manifest)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {
                    "appmode": "python-api",
                },
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {},
            },
        )

    def test_make_quarto_manifest(self):
        temp = tempfile.mkdtemp()

        # Verify the optional parameters
        # image=None,  # type: str
        # environment=None,  # type: typing.Optional[Environment]
        # extra_files=None,  # type: typing.Optional[typing.List[str]]
        # excludes=None,  # type: typing.Optional[typing.List[str]]

        # No optional parameters
        manifest, _ = make_quarto_manifest(
            temp,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {},
            },
        )

        # include image parameter
        manifest, _ = make_quarto_manifest(
            temp,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            None,
            None,
            "rstudio/connect:bionic",
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "environment": {"image": "rstudio/connect:bionic"},
                "files": {},
            },
        )

        # Files used within this test
        fp = open(join(temp, "requirements.txt"), "w")
        fp.write("dash\n")
        fp.write("pandas\n")
        fp.close()

        # include environment parameter
        manifest, _ = make_quarto_manifest(
            temp,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            Environment(
                conda=None,
                contents="",
                error=None,
                filename="requirements.txt",
                locale="en_US.UTF-8",
                package_manager="pip",
                pip="22.0.4",
                python="3.9.12",
                source="file",
            ),
            None,
            None,
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "locale": "en_US.UTF-8",
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "python": {
                    "version": "3.9.12",
                    "package_manager": {"name": "pip", "version": "22.0.4", "package_file": "requirements.txt"},
                },
                "files": {"requirements.txt": {"checksum": "6f83f7f33bf6983dd474ecbc6640a26b"}},
            },
        )

        # include extra_files parameter
        fp = open(join(temp, "a"), "w")
        fp.write("This is file a\n")
        fp.close()
        fp = open(join(temp, "b"), "w")
        fp.write("This is file b\n")
        fp.close()
        fp = open(join(temp, "c"), "w")
        fp.write("This is file c\n")
        fp.close()
        manifest, _ = make_quarto_manifest(
            temp,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            ["a", "b", "c"],
            None,
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {
                    "a": {"checksum": "4a3eb92956aa3e16a9f0a84a43c943e7"},
                    "b": {"checksum": "b249e5b536d30e6282cea227f3a73669"},
                    "c": {"checksum": "53b36f1d5b6f7fb2cfaf0c15af7ffb2d"},
                    "requirements.txt": {"checksum": "6f83f7f33bf6983dd474ecbc6640a26b"},
                },
            },
        )

        # include excludes parameter
        manifest, _ = make_quarto_manifest(
            temp,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            ["a", "b", "c"],
            ["requirements.txt"],
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {
                    "a": {"checksum": "4a3eb92956aa3e16a9f0a84a43c943e7"},
                    "b": {"checksum": "b249e5b536d30e6282cea227f3a73669"},
                    "c": {"checksum": "53b36f1d5b6f7fb2cfaf0c15af7ffb2d"},
                },
            },
        )

    def test_make_html_manifest(self):
        # Verify the optional parameters
        # image=None,  # type: str

        # No optional parameters
        manifest = make_html_manifest("abc.html", None)
        # print(manifest)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {
                    "appmode": "static",
                    "primary_html": "abc.html",
                },
            },
        )

        # include image parameter
        manifest = make_html_manifest("abc.html", image="rstudio/connect:bionic")
        # print(manifest)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {
                    "appmode": "static",
                    "primary_html": "abc.html",
                },
                "environment": {"image": "rstudio/connect:bionic"},
            },
        )

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

    monkeypatch.setattr(rsconnect.bundle, "inspect_environment", fake_inspect_environment)

    monkeypatch.setattr(rsconnect.bundle, "which_python", fake_which_python)

    if expected_environment.error is not None:
        with pytest.raises(RSConnectException):
            _, _ = get_python_env_info(file_name, python, conda_mode=conda_mode, force_generate=force_generate)
    else:
        python, environment = get_python_env_info(
            file_name, python, conda_mode=conda_mode, force_generate=force_generate
        )

        assert python == expected_python
        assert environment == expected_environment


class WhichPythonTestCase(TestCase):
    def test_default(self):
        self.assertEqual(which_python(), sys.executable)

    def test_none(self):
        self.assertEqual(which_python(None), sys.executable)

    def test_sys(self):
        self.assertEqual(which_python(sys.executable), sys.executable)

    def test_does_not_exist(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            name = tmpfile.name
        with self.assertRaises(RSConnectException):
            which_python(name)

    def test_is_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RSConnectException):
                which_python(tmpdir)

    def test_is_not_executable(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            with self.assertRaises(RSConnectException):
                which_python(tmpfile.name)


cur_dir = os.path.dirname(__file__)
bqplot_dir = os.path.join(cur_dir, "./testdata/voila/bqplot/")
bqplot_ipynb = os.path.join(bqplot_dir, "bqplot.ipynb")
dashboard_dir = os.path.join(cur_dir, "./testdata/voila/dashboard/")
dashboard_ipynb = os.path.join(dashboard_dir, "dashboard.ipynb")
multivoila_dir = os.path.join(cur_dir, "./testdata/voila/multi-voila/")


class Test_guess_deploy_dir(TestCase):
    def test_guess_deploy_dir(self):
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(None, None)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(None, bqplot_dir)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(bqplot_dir, bqplot_dir)
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_dir, None))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_ipynb, None))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_ipynb, bqplot_ipynb))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_dir, "bqplot.ipynb"))


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            None,
            None,
        ),
        (
            None,
            bqplot_ipynb,
        ),
        (
            bqplot_dir,
            bqplot_dir,
        ),
        (
            bqplot_dir,
            None,
        ),
        (
            bqplot_ipynb,
            None,
        ),
        (
            bqplot_ipynb,
            bqplot_ipynb,
        ),
        (
            bqplot_dir,
            bqplot_ipynb,
        ),
    ],
)
def test_create_voila_manifest_1(path, entrypoint):
    environment = Environment(
        conda=None,
        contents="bqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "bqplot.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "9cce1aac313043abd5690f67f84338ed"},
            "bqplot.ipynb": {"checksum": "79f8622228eded646a3038848de5ffd9"},
        },
    }
    manifest = Manifest()
    if (path, entrypoint) in (
        (None, None),
        (None, bqplot_ipynb),
        (bqplot_dir, bqplot_dir),
    ):
        with pytest.raises(RSConnectException) as _:
            manifest = create_voila_manifest(
                path,
                entrypoint,
                environment,
                app_mode=AppModes.JUPYTER_VOILA,
                extra_files=None,
                excludes=None,
                force_generate=True,
                image=None,
                multi_notebook=False,
            )
    else:
        manifest = create_voila_manifest(
            path,
            entrypoint,
            environment,
            app_mode=AppModes.JUPYTER_VOILA,
            extra_files=None,
            excludes=None,
            force_generate=True,
            image=None,
            multi_notebook=False,
        )
        assert ans == json.loads(manifest.flattened_copy.json)


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            dashboard_dir,
            dashboard_ipynb,
        ),
    ],
)
def test_create_voila_manifest_2(path, entrypoint):
    environment = Environment(
        conda=None,
        contents="numpy\nipywidgets\nbqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "dashboard.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "d51994456975ff487749acc247ae6d63"},
            "bqplot.ipynb": {"checksum": "79f8622228eded646a3038848de5ffd9"},
            "dashboard.ipynb": {"checksum": "6b42a0730d61e5344a3e734f5bbeec25"},
        },
    }
    manifest = create_voila_manifest(
        path,
        entrypoint,
        environment,
        app_mode=AppModes.JUPYTER_VOILA,
        extra_files=None,
        excludes=None,
        force_generate=True,
        image=None,
        multi_notebook=False,
    )
    assert ans == json.loads(manifest.flattened_copy.json)


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            None,
            None,
        ),
        (
            None,
            bqplot_ipynb,
        ),
        (
            multivoila_dir,
            multivoila_dir,
        ),
        (
            multivoila_dir,
            None,
        ),
        (
            bqplot_ipynb,
            None,
        ),
        (
            bqplot_ipynb,
            bqplot_ipynb,
        ),
        (
            multivoila_dir,
            bqplot_ipynb,
        ),
    ],
)
def test_create_voila_manifest_multi_notebook(path, entrypoint):
    environment = Environment(
        conda=None,
        contents="bqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "multi-voila"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "9cce1aac313043abd5690f67f84338ed"},
            "bqplot/bqplot.ipynb": {"checksum": "9f283b29889500e6c78e83ad1257e03f"},
            "dashboard/dashboard.ipynb": {"checksum": "6b42a0730d61e5344a3e734f5bbeec25"},
        },
    }
    manifest = Manifest()
    if (path, entrypoint) in (
        (None, None),
        (None, bqplot_ipynb),
        (multivoila_dir, multivoila_dir),
        (bqplot_ipynb, None),
        (bqplot_ipynb, bqplot_ipynb),
    ):
        with pytest.raises(RSConnectException) as _:
            manifest = create_voila_manifest(
                path,
                entrypoint,
                environment,
                app_mode=AppModes.JUPYTER_VOILA,
                extra_files=None,
                excludes=None,
                force_generate=True,
                image=None,
                multi_notebook=True,
            )
    else:
        manifest = create_voila_manifest(
            path,
            entrypoint,
            environment,
            app_mode=AppModes.JUPYTER_VOILA,
            extra_files=None,
            excludes=None,
            force_generate=True,
            image=None,
            multi_notebook=True,
        )
        assert ans == json.loads(manifest.flattened_copy.json)


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            None,
            None,
        ),
        (
            None,
            bqplot_ipynb,
        ),
        (
            bqplot_dir,
            bqplot_dir,
        ),
        (
            bqplot_dir,
            None,
        ),
        (
            bqplot_ipynb,
            None,
        ),
        (
            bqplot_ipynb,
            bqplot_ipynb,
        ),
        (
            bqplot_dir,
            bqplot_ipynb,
        ),
    ],
)
def test_make_voila_bundle(
    path,
    entrypoint,
):
    environment = Environment(
        conda=None,
        contents="bqplot",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "bqplot.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "9395f3162b7779c57c86b187fa441d96"},
            "bqplot.ipynb": {"checksum": "79f8622228eded646a3038848de5ffd9"},
        },
    }
    if (path, entrypoint) in (
        (None, None),
        (None, bqplot_ipynb),
        (bqplot_dir, bqplot_dir),
    ):
        with pytest.raises(RSConnectException) as _:
            bundle = make_voila_bundle(
                path,
                entrypoint,
                extra_files=None,
                excludes=None,
                force_generate=True,
                environment=environment,
                image=None,
                multi_notebook=False,
            )
    else:
        with make_voila_bundle(
            path,
            entrypoint,
            extra_files=None,
            excludes=None,
            force_generate=True,
            environment=environment,
            image=None,
            multi_notebook=False,
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            assert names == [
                "bqplot.ipynb",
                "manifest.json",
                "requirements.txt",
            ]
            reqs = tar.extractfile("requirements.txt").read()
            assert reqs == b"bqplot"
            assert ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            None,
            None,
        ),
        (
            None,
            bqplot_ipynb,
        ),
        (
            multivoila_dir,
            multivoila_dir,
        ),
        (
            multivoila_dir,
            None,
        ),
        (
            bqplot_ipynb,
            None,
        ),
        (
            bqplot_ipynb,
            bqplot_ipynb,
        ),
        (
            multivoila_dir,
            bqplot_ipynb,
        ),
    ],
)
def test_make_voila_bundle_multi_notebook(
    path,
    entrypoint,
):
    environment = Environment(
        conda=None,
        contents="bqplot",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": ""},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "9395f3162b7779c57c86b187fa441d96"},
            "bqplot/bqplot.ipynb": {"checksum": "9f283b29889500e6c78e83ad1257e03f"},
            "dashboard/dashboard.ipynb": {"checksum": "6b42a0730d61e5344a3e734f5bbeec25"},
        },
    }
    if (path, entrypoint) in (
        (None, None),
        (None, bqplot_ipynb),
        (multivoila_dir, multivoila_dir),
        (bqplot_ipynb, None),
        (bqplot_ipynb, bqplot_ipynb),
    ):
        with pytest.raises(RSConnectException) as _:
            bundle = make_voila_bundle(
                path,
                entrypoint,
                extra_files=None,
                excludes=None,
                force_generate=True,
                environment=environment,
                image=None,
                multi_notebook=True,
            )
    else:
        with make_voila_bundle(
            path,
            entrypoint,
            extra_files=None,
            excludes=None,
            force_generate=True,
            environment=environment,
            image=None,
            multi_notebook=True,
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            assert names == [
                "bqplot/bqplot.ipynb",
                "dashboard/dashboard.ipynb",
                "manifest.json",
                "requirements.txt",
            ]
            reqs = tar.extractfile("requirements.txt").read()
            assert reqs == b"bqplot"
            assert ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))


@pytest.mark.parametrize(
    (
        "path",
        "entrypoint",
    ),
    [
        (
            dashboard_dir,
            dashboard_ipynb,
        ),
    ],
)
def test_make_voila_bundle_2(
    path,
    entrypoint,
):
    environment = Environment(
        conda=None,
        contents="numpy\nipywidgets\nbqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "dashboard.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "d51994456975ff487749acc247ae6d63"},
            "bqplot.ipynb": {"checksum": "79f8622228eded646a3038848de5ffd9"},
            "dashboard.ipynb": {"checksum": "6b42a0730d61e5344a3e734f5bbeec25"},
        },
    }
    with make_voila_bundle(
        path,
        entrypoint,
        extra_files=None,
        excludes=None,
        force_generate=True,
        environment=environment,
        image=None,
        multi_notebook=False,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "bqplot.ipynb",
            "dashboard.ipynb",
            "manifest.json",
            "requirements.txt",
        ]
        reqs = tar.extractfile("requirements.txt").read()
        assert reqs == b"numpy\nipywidgets\nbqplot\n"
        assert ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))


single_file_index_dir = os.path.join(cur_dir, "./testdata/html_tests/single_file_index")
single_file_index_file = os.path.join(cur_dir, "./testdata/html_tests/single_file_index/index.html")
single_file_nonindex_dir = os.path.join(cur_dir, "./testdata/html_tests/single_file_nonindex")
multi_file_index_dir = os.path.join(cur_dir, "./testdata/html_tests/multi_file_index")
multi_file_index_file = os.path.join(cur_dir, "./testdata/html_tests/multi_file_index/index.html")
multi_file_nonindex_dir = os.path.join(cur_dir, "./testdata/html_tests/multi_file_nonindex")
multi_file_nonindex_file = os.path.join(cur_dir, "./testdata/html_tests/multi_file_nonindex/b.html")


def test_create_html_manifest():

    with pytest.raises(RSConnectException) as _:
        _, _ = create_html_manifest(
            None,
            None,
            extra_files=None,
            excludes=None,
            image=None,
        )
    with pytest.raises(RSConnectException) as _:
        _, _ = create_html_manifest(
            None,
            single_file_index_file,
            extra_files=None,
            excludes=None,
            image=None,
        )
    with pytest.raises(RSConnectException) as _:
        _, _ = create_html_manifest(
            multi_file_nonindex_dir,
            None,
            extra_files=None,
            excludes=None,
            image=None,
        )
    single_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"}},
    }
    manifest = create_html_manifest(
        single_file_index_file,
        None,
    )
    assert single_file_index_file_ans == json.loads(manifest.flattened_copy.json)

    single_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "test1.txt": {"checksum": "3e7705498e8be60520841409ebc69bc1"},
            "test_folder1/testfoldertext1.txt": {"checksum": "0a576fd324b6985bac6aa934131d2f5c"},
        },
    }

    manifest = create_html_manifest(
        single_file_index_dir,
        None,
    )
    assert single_file_index_dir_ans == json.loads(manifest.flattened_copy.json)

    manifest = create_html_manifest(
        single_file_index_dir,
        single_file_index_file,
    )
    assert single_file_index_dir_ans == json.loads(manifest.flattened_copy.json)

    multi_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"}},
    }

    manifest = create_html_manifest(
        multi_file_index_file,
        None,
    )
    assert multi_file_index_file_ans == json.loads(manifest.flattened_copy.json)

    multi_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "main.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
        },
    }

    manifest = create_html_manifest(
        multi_file_index_dir,
        None,
    )
    assert multi_file_index_dir_ans == json.loads(manifest.flattened_copy.json)

    manifest = create_html_manifest(
        multi_file_index_dir,
        multi_file_index_file,
    )
    assert multi_file_index_dir_ans == json.loads(manifest.flattened_copy.json)

    multi_file_nonindex_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "b.html"},
        "files": {"b.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"}},
    }

    manifest = create_html_manifest(
        multi_file_nonindex_file,
        None,
    )
    assert multi_file_nonindex_file_ans == json.loads(manifest.flattened_copy.json)

    multi_file_nonindex_dir_and_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "entrypoint": "b.html"},
        "files": {
            "a.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
            "b.html": {"checksum": "c14bd63e50295f94b761ffe9d41e3742"},
        },
    }

    manifest = create_html_manifest(
        multi_file_nonindex_dir,
        multi_file_nonindex_file,
    )
    assert multi_file_nonindex_dir_and_file_ans == json.loads(manifest.flattened_copy.json)
