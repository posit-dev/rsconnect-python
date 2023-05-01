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
    create_python_environment,
    get_python_env_info,
    inspect_environment,
    list_files,
    make_api_bundle,
    make_api_manifest,
    make_html_bundle,
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
            elif sys.platform == "win32":
                ipynb_hash = "6cd380f003642754cf95dc65bc9d3f4e"
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
            elif sys.platform == "win32":
                ipynb_hash = "6cd380f003642754cf95dc65bc9d3f4e"
                data_csv_hash = "56a7e0581160202c8045351ef2591df1"
            else:
                ipynb_hash = "36873800b48ca5ab54760d60ba06703a"
                data_csv_hash = "f2bd77cc2752b3efbb732b761d2aa3c3"

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
                        "data.csv": {"checksum": data_csv_hash},
                    },
                },
            )

    def test_list_files(self):
        # noinspection SpellCheckingInspection
        paths = [
            "notebook.ipynb",
            "somedata.csv",
            os.path.join("subdir", "subfile"),
            os.path.join("subdir2", "subfile2"),
            os.path.join(".ipynb_checkpoints", "notebook.ipynb"),
            os.path.join(".git", "config"),
        ]

        def walk(base_dir):
            dir_names = []
            file_names = []

            for path in paths:
                if os.sep in path:
                    dir_name, file_name = path.split(os.sep, 1)
                    dir_names.append(dir_name)
                else:
                    file_names.append(path)

            yield base_dir, dir_names, file_names

            for subdir in dir_names:
                for path in paths:
                    if path.startswith(subdir + os.sep):
                        yield base_dir + os.sep + subdir, [], [path.split(os.sep, 1)[1]]

        files = list_files(".", True, walk=walk)
        self.assertEqual(files, paths[:4])

        files = list_files(os.sep, False, walk=walk)
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

        if sys.platform == "win32":
            req_hash = "74203044cc283b7b3e775559b6e986fa"
        else:
            req_hash = "6f83f7f33bf6983dd474ecbc6640a26b"

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
                "files": {"requirements.txt": {"checksum": req_hash}},
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

        if sys.platform == "win32":
            checksum_hash = "74203044cc283b7b3e775559b6e986fa"
            a_hash = "f4751c084b3ade4d736c6293ab8468c9"
            b_hash = "4976d559975b5232cf09a10afaf8d0a8"
            c_hash = "09c56e1b9e6ae34c6662717c47a7e187"
        else:
            checksum_hash = "6f83f7f33bf6983dd474ecbc6640a26b"
            a_hash = "4a3eb92956aa3e16a9f0a84a43c943e7"
            b_hash = "b249e5b536d30e6282cea227f3a73669"
            c_hash = "53b36f1d5b6f7fb2cfaf0c15af7ffb2d"

        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-shiny"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {
                    "a": {"checksum": a_hash},
                    "b": {"checksum": b_hash},
                    "c": {"checksum": c_hash},
                    "requirements.txt": {"checksum": checksum_hash},
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
                    "a": {"checksum": a_hash},
                    "b": {"checksum": b_hash},
                    "c": {"checksum": c_hash},
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

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="os.X_OK always returns True")
    def test_is_not_executable(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            with self.assertRaises(RSConnectException):
                which_python(tmpfile.name)


cur_dir = os.path.dirname(__file__)
bqplot_dir = os.path.join(cur_dir, "testdata", "voila", "bqplot", "")
bqplot_ipynb = os.path.join(bqplot_dir, "bqplot.ipynb")
dashboard_dir = os.path.join(cur_dir, "testdata", "voila", "dashboard", "")
dashboard_ipynb = os.path.join(dashboard_dir, "dashboard.ipynb")
multivoila_dir = os.path.join(cur_dir, "testdata", "voila", "multi-voila", "")
nonexistent_dir = os.path.join(cur_dir, "testdata", "nonexistent", "")
dashboard_extra_ipynb = os.path.join(dashboard_dir, "bqplot.ipynb")
nonexistent_file = os.path.join(cur_dir, "nonexistent.txt")


class Test_guess_deploy_dir(TestCase):
    def test_guess_deploy_dir(self):
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(None, None)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(None, bqplot_dir)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(bqplot_dir, bqplot_dir)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(nonexistent_dir, None)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(None, nonexistent_file)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(nonexistent_dir, nonexistent_file)
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_dir, None))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_ipynb, None))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_ipynb, bqplot_ipynb))
        self.assertEqual(abspath(bqplot_dir), guess_deploy_dir(bqplot_dir, bqplot_ipynb))


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

    if sys.platform == "win32":
        checksum_hash = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
    else:
        checksum_hash = "79f8622228eded646a3038848de5ffd9"

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
            "bqplot.ipynb": {"checksum": checksum_hash},
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

    if sys.platform == "win32":
        bqplot_hash = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
        dashboard_hash = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        bqplot_hash = "79f8622228eded646a3038848de5ffd9"
        dashboard_hash = "6b42a0730d61e5344a3e734f5bbeec25"

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
            "bqplot.ipynb": {"checksum": bqplot_hash},
            "dashboard.ipynb": {"checksum": dashboard_hash},
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


def test_create_voila_manifest_extra():
    environment = Environment(
        conda=None,
        contents="numpy\nipywidgets\nbqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0.1",
        python="3.8.12",
        source="file",
    )

    if sys.platform == "win32":
        requirements_checksum = "d51994456975ff487749acc247ae6d63"
        bqplot_checksum = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
        dashboard_checksum = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        requirements_checksum = "d51994456975ff487749acc247ae6d63"
        bqplot_checksum = "79f8622228eded646a3038848de5ffd9"
        dashboard_checksum = "6b42a0730d61e5344a3e734f5bbeec25"

    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "dashboard.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": requirements_checksum},
            "bqplot.ipynb": {"checksum": bqplot_checksum},
            "dashboard.ipynb": {"checksum": dashboard_checksum},
        },
    }
    manifest = create_voila_manifest(
        dashboard_ipynb,
        None,
        environment,
        app_mode=AppModes.JUPYTER_VOILA,
        extra_files=[dashboard_extra_ipynb],
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

    bqplot_path = os.path.join("bqplot", "bqplot.ipynb")
    dashboard_path = os.path.join("dashboard", "dashboard.ipynb")

    if sys.platform == "win32":
        bqplot_hash = "ddb4070466d3c45b2f233dd39906ddf6"
        dashboard_hash = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        bqplot_hash = "9f283b29889500e6c78e83ad1257e03f"
        dashboard_hash = "6b42a0730d61e5344a3e734f5bbeec25"

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
            bqplot_path: {"checksum": bqplot_hash},
            dashboard_path: {"checksum": dashboard_hash},
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

    if sys.platform == "win32":
        checksum_hash = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
    else:
        checksum_hash = "79f8622228eded646a3038848de5ffd9"

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
            "bqplot.ipynb": {"checksum": checksum_hash},
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

    bqplot_path = os.path.join("bqplot", "bqplot.ipynb")
    dashboard_path = os.path.join("dashboard", "dashboard.ipynb")

    if sys.platform == "win32":
        bqplot_hash = "ddb4070466d3c45b2f233dd39906ddf6"
        dashboard_hash = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        bqplot_hash = "9f283b29889500e6c78e83ad1257e03f"
        dashboard_hash = "6b42a0730d61e5344a3e734f5bbeec25"

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
            bqplot_path: {"checksum": bqplot_hash},
            dashboard_path: {"checksum": dashboard_hash},
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

    if sys.platform == "win32":
        bqplot_hash = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
        dashboard_hash = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        bqplot_hash = "79f8622228eded646a3038848de5ffd9"
        dashboard_hash = "6b42a0730d61e5344a3e734f5bbeec25"

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
            "bqplot.ipynb": {"checksum": bqplot_hash},
            "dashboard.ipynb": {"checksum": dashboard_hash},
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


def test_make_voila_bundle_extra():
    if sys.platform == "win32":
        bqplot_hash = "b7ba4ec7b6721c86ab883f5e6e2ea68f"
        dashboard_hash = "b2d7dc369ac602c7d7a703b6eb868562"
    else:
        bqplot_hash = "79f8622228eded646a3038848de5ffd9"
        dashboard_hash = "6b42a0730d61e5344a3e734f5bbeec25"

    requirements_hash = "d51994456975ff487749acc247ae6d63"

    environment = Environment(
        conda=None,
        contents="numpy\nipywidgets\nbqplot\n",
        error=None,
        filename="requirements.txt",
        locale="en_US.UTF-8",
        package_manager="pip",
        pip="23.0.1",
        python="3.8.12",
        source="file",
    )
    ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "jupyter-voila", "entrypoint": "dashboard.ipynb"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": requirements_hash},
            "bqplot.ipynb": {"checksum": bqplot_hash},
            "dashboard.ipynb": {"checksum": dashboard_hash},
        },
    }
    with make_voila_bundle(
        dashboard_ipynb,
        None,
        extra_files=[dashboard_extra_ipynb],
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


single_file_index_dir = os.path.join(cur_dir, "testdata", "html_tests", "single_file_index")
single_file_index_file = os.path.join(cur_dir, "testdata", "html_tests", "single_file_index", "index.html")
single_file_nonindex_dir = os.path.join(cur_dir, "testdata", "html_tests", "single_file_nonindex")
multi_file_index_dir = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_index")
multi_file_index_file = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_index", "index.html")
multi_file_index_file2 = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_index", "main.html")
multi_file_nonindex_dir = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_nonindex")
multi_file_nonindex_fileb = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_nonindex", "b.html")
multi_file_nonindex_filea = os.path.join(cur_dir, "testdata", "html_tests", "multi_file_nonindex", "a.html")


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

    test_folder_path = os.path.join("test_folder1", "testfoldertext1.txt")

    if sys.platform == "win32":
        index_hash = "0c3d8c84223089949954d069f2eef7e9"
        txt_hash = "e6a96602853b20607831eec27dbb6cf0"
        folder_txt_hash = "14bbe9e7bfefdfe9a7863be93585d5eb"
    else:
        index_hash = "c14bd63e50295f94b761ffe9d41e3742"
        txt_hash = "3e7705498e8be60520841409ebc69bc1"
        folder_txt_hash = "0a576fd324b6985bac6aa934131d2f5c"

    single_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": index_hash}},
    }
    manifest = create_html_manifest(
        single_file_index_file,
        None,
    )
    assert single_file_index_file_ans == json.loads(manifest.flattened_copy.json)

    single_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_hash},
            "test1.txt": {"checksum": txt_hash},
            test_folder_path: {"checksum": folder_txt_hash},
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
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": index_hash}},
    }

    manifest = create_html_manifest(
        multi_file_index_file,
        None,
    )
    assert multi_file_index_file_ans == json.loads(manifest.flattened_copy.json)

    multi_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_hash},
            "main.html": {"checksum": index_hash},
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
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {"b.html": {"checksum": index_hash}},
    }

    manifest = create_html_manifest(
        multi_file_nonindex_fileb,
        None,
    )
    assert multi_file_nonindex_file_ans == json.loads(manifest.flattened_copy.json)

    multi_file_nonindex_dir_and_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {
            "a.html": {"checksum": index_hash},
            "b.html": {"checksum": index_hash},
        },
    }

    manifest = create_html_manifest(
        multi_file_nonindex_dir,
        multi_file_nonindex_fileb,
    )
    assert multi_file_nonindex_dir_and_file_ans == json.loads(manifest.flattened_copy.json)

    multi_file_nonindex_file_extras_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {
            "a.html": {"checksum": index_hash},
            "b.html": {"checksum": index_hash},
        },
    }
    manifest = create_html_manifest(
        multi_file_nonindex_fileb,
        None,
        extra_files=[multi_file_nonindex_filea],
    )
    assert multi_file_nonindex_file_extras_ans == json.loads(manifest.flattened_copy.json)

    multi_file_index_dir_extras_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_hash},
            "main.html": {"checksum": index_hash},
        },
    }

    manifest = create_html_manifest(
        multi_file_index_dir,
        None,
        extra_files=[multi_file_index_file2],
    )
    assert multi_file_index_dir_extras_ans == json.loads(manifest.flattened_copy.json)


def test_make_html_bundle():
    folder_path = os.path.join("test_folder1", "testfoldertext1.txt")

    if sys.platform == "win32":
        index_hash = "0c3d8c84223089949954d069f2eef7e9"
        txt_hash = "e6a96602853b20607831eec27dbb6cf0"
        folder_txt_hash = "14bbe9e7bfefdfe9a7863be93585d5eb"
    else:
        index_hash = "c14bd63e50295f94b761ffe9d41e3742"
        txt_hash = "3e7705498e8be60520841409ebc69bc1"
        folder_txt_hash = "0a576fd324b6985bac6aa934131d2f5c"

    single_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": index_hash}},
    }
    with make_html_bundle(
        single_file_index_file,
        None,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "manifest.json",
        ]
        assert single_file_index_file_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    single_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_hash},
            "test1.txt": {"checksum": txt_hash},
            folder_path: {"checksum": folder_txt_hash},
        },
    }
    with make_html_bundle(
        single_file_index_dir,
        None,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "manifest.json",
            "test1.txt",
            "test_folder1/testfoldertext1.txt",
        ]
        assert single_file_index_dir_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    with make_html_bundle(
        single_file_index_dir,
        single_file_index_file,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "manifest.json",
            "test1.txt",
            "test_folder1/testfoldertext1.txt",
        ]
        assert single_file_index_dir_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    if sys.platform == "win32":
        index_checksum = "0c3d8c84223089949954d069f2eef7e9"
    else:
        index_checksum = "c14bd63e50295f94b761ffe9d41e3742"

    multi_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": index_checksum}},
    }

    with make_html_bundle(
        multi_file_index_file,
        None,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "manifest.json",
        ]
        assert multi_file_index_file_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    multi_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_checksum},
            "main.html": {"checksum": index_checksum},
        },
    }
    with make_html_bundle(
        multi_file_index_dir,
        None,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "main.html",
            "manifest.json",
        ]
        assert multi_file_index_dir_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    with make_html_bundle(
        multi_file_index_dir,
        multi_file_index_file,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "main.html",
            "manifest.json",
        ]
        assert multi_file_index_dir_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    multi_file_nonindex_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {"b.html": {"checksum": index_checksum}},
    }
    with make_html_bundle(
        multi_file_nonindex_fileb,
        None,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "b.html",
            "manifest.json",
        ]
        assert multi_file_nonindex_file_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

    multi_file_nonindex_dir_and_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {
            "a.html": {"checksum": index_checksum},
            "b.html": {"checksum": index_checksum},
        },
    }
    with make_html_bundle(
        multi_file_nonindex_dir,
        multi_file_nonindex_fileb,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "a.html",
            "b.html",
            "manifest.json",
        ]
        assert multi_file_nonindex_dir_and_file_ans == json.loads(
            tar.extractfile("manifest.json").read().decode("utf-8")
        )

    multi_file_nonindex_file_extras_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {
            "a.html": {"checksum": index_checksum},
            "b.html": {"checksum": index_checksum},
        },
    }
    with make_html_bundle(
        multi_file_nonindex_fileb,
        None,
        [multi_file_nonindex_filea],
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "a.html",
            "b.html",
            "manifest.json",
        ]
        assert multi_file_nonindex_file_extras_ans == json.loads(
            tar.extractfile("manifest.json").read().decode("utf-8")
        )

    multi_file_index_dir_extras_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_checksum},
            "main.html": {"checksum": index_checksum},
        },
    }

    with make_html_bundle(
        multi_file_index_dir,
        None,
        [multi_file_index_file2],
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "index.html",
            "main.html",
            "manifest.json",
        ]
        assert multi_file_index_dir_extras_ans == json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))


fastapi_dir = os.path.join(cur_dir, "./testdata/stock-api-fastapi")
fastapi_file = os.path.join(cur_dir, "./testdata/stock-api-fastapi/main.py")


def test_validate_entry_point():
    assert "main" == validate_entry_point(entry_point=None, directory=fastapi_dir)


def test_make_api_manifest_fastapi():
    fastapi_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-fastapi"},  # "entrypoint": "main"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "7bdadcb7a5f74f377b453cf6e980f114"},
            "README.md": {"checksum": "30a14a7b8eb6282d532d7fdaa36abb0f"},
            "main.py": {"checksum": "a8d8820f25be4dc8e2bf51a5ba1690b6"},
            "prices.csv": {"checksum": "012afa636c426748177b38160135307a"},
        },
    }
    environment = create_python_environment(
        fastapi_dir,
    )
    manifest, _ = make_api_manifest(
        fastapi_dir,
        None,
        AppModes.PYTHON_FASTAPI,
        environment,
        None,
        None,
    )

    assert fastapi_dir_ans["metadata"] == manifest["metadata"]
    assert fastapi_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_fastapi():
    fastapi_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-fastapi"},  # "entrypoint": "main"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "7bdadcb7a5f74f377b453cf6e980f114"},
            "README.md": {"checksum": "30a14a7b8eb6282d532d7fdaa36abb0f"},
            "main.py": {"checksum": "a8d8820f25be4dc8e2bf51a5ba1690b6"},
            "prices.csv": {"checksum": "012afa636c426748177b38160135307a"},
        },
    }
    environment = create_python_environment(
        fastapi_dir,
    )
    with make_api_bundle(
        fastapi_dir,
        None,
        AppModes.PYTHON_FASTAPI,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "main.py",
            "manifest.json",
            "prices.csv",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert fastapi_dir_ans["metadata"] == bundle_json["metadata"]
        assert fastapi_dir_ans["files"].keys() == bundle_json["files"].keys()


flask_dir = os.path.join(cur_dir, "./testdata/stock-api-flask")
flask_file = os.path.join(cur_dir, "./testdata/stock-api-flask/main.py")


def test_make_api_manifest_flask():
    flask_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-api"},  # "entrypoint": "app"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "e34bcdf75e2a80c4c0b0b53a14af5f41"},
            "README.md": {"checksum": "15659923bfe23eed7ca4450ce1adbe41"},
            "app.py": {"checksum": "9799c3b834b555cf02e5896ad2997674"},
            "prices.csv": {"checksum": "012afa636c426748177b38160135307a"},
        },
    }
    environment = create_python_environment(
        flask_dir,
    )
    manifest, _ = make_api_manifest(
        flask_dir,
        None,
        AppModes.PYTHON_API,
        environment,
        None,
        None,
    )

    assert flask_dir_ans["metadata"] == manifest["metadata"]
    assert flask_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_flask():
    flask_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-api"},  # "entrypoint": "app"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "e34bcdf75e2a80c4c0b0b53a14af5f41"},
            "README.md": {"checksum": "15659923bfe23eed7ca4450ce1adbe41"},
            "app.py": {"checksum": "9799c3b834b555cf02e5896ad2997674"},
            "prices.csv": {"checksum": "012afa636c426748177b38160135307a"},
        },
    }
    environment = create_python_environment(
        flask_dir,
    )
    with make_api_bundle(
        flask_dir,
        None,
        AppModes.PYTHON_API,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app.py",
            "manifest.json",
            "prices.csv",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert flask_dir_ans["metadata"] == bundle_json["metadata"]
        assert flask_dir_ans["files"].keys() == bundle_json["files"].keys()


streamlit_dir = os.path.join(cur_dir, "./testdata/top-5-income-share-streamlit")
streamlit_file = os.path.join(cur_dir, "./testdata/top-5-income-share-streamlit/app.py")


def test_make_api_manifest_streamlit():
    streamlit_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-streamlit"},  # "entrypoint": "app1"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "22354e5a4240bacbd3bc379cab0e73e9"},
            "README.md": {"checksum": "73b002e9ba030b3a3bc9a8a32d56a7b1"},
            "app1.py": {"checksum": "b203bc6d9512029a414ccbb63514e603"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    environment = create_python_environment(
        streamlit_dir,
    )
    manifest, _ = make_api_manifest(
        streamlit_dir,
        None,
        AppModes.STREAMLIT_APP,
        environment,
        None,
        None,
    )
    assert streamlit_dir_ans["metadata"] == manifest["metadata"]
    assert streamlit_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_streamlit():
    streamlit_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-streamlit"},  # "entrypoint": "app1"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "22354e5a4240bacbd3bc379cab0e73e9"},
            "README.md": {"checksum": "73b002e9ba030b3a3bc9a8a32d56a7b1"},
            "app1.py": {"checksum": "b203bc6d9512029a414ccbb63514e603"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    environment = create_python_environment(
        streamlit_dir,
    )
    with make_api_bundle(
        streamlit_dir,
        None,
        AppModes.STREAMLIT_APP,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app1.py",
            "data.csv",
            "manifest.json",
            "requirements.txt",
        ]

        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert streamlit_dir_ans["metadata"] == bundle_json["metadata"]
        assert streamlit_dir_ans["files"].keys() == bundle_json["files"].keys()


dash_dir = os.path.join(cur_dir, "./testdata/stock-dashboard-python")
dash_file = os.path.join(cur_dir, "./testdata/stock-dashboard-python/app.py")


def test_make_api_manifest_dash():
    dash_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-dash"},  # "entrypoint": "app2"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "2ff14ec69d1cd98ed4eb6ae2eea75554"},
            "README.md": {"checksum": "245b617d93ce26d06ad2b29f2f723206"},
            "app2.py": {"checksum": "0cb6f0261685d29243977c7318d70d6d"},
            "prices.csv": {"checksum": "3efb0ed7ad93bede9dc88f7a81ad4153"},
        },
    }
    environment = create_python_environment(
        dash_dir,
    )
    manifest, _ = make_api_manifest(
        dash_dir,
        None,
        AppModes.DASH_APP,
        environment,
        None,
        None,
    )

    assert dash_dir_ans["metadata"] == manifest["metadata"]
    assert dash_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_dash():
    dash_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-dash"},  # "entrypoint": "app2"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "2ff14ec69d1cd98ed4eb6ae2eea75554"},
            "README.md": {"checksum": "245b617d93ce26d06ad2b29f2f723206"},
            "app2.py": {"checksum": "0cb6f0261685d29243977c7318d70d6d"},
            "prices.csv": {"checksum": "3efb0ed7ad93bede9dc88f7a81ad4153"},
        },
    }
    environment = create_python_environment(
        dash_dir,
    )
    with make_api_bundle(
        dash_dir,
        None,
        AppModes.DASH_APP,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app2.py",
            "manifest.json",
            "prices.csv",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert dash_dir_ans["metadata"] == bundle_json["metadata"]
        assert dash_dir_ans["files"].keys() == bundle_json["files"].keys()


bokeh_dir = os.path.join(cur_dir, "./testdata/top-5-income-share-bokeh")
bokeh_file = os.path.join(cur_dir, "./testdata/top-5-income-share-bokeh/app.py")


def test_make_api_manifest_bokeh():
    bokeh_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-bokeh"},  # "entrypoint": "app3"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "77477063f2527bde7b55a087da0a5520"},
            "README.md": {"checksum": "842a630dc6d49e1e58ae9e36715b1da1"},
            "app3.py": {"checksum": "a5de7b460476a9ac4e02edfc2d52d9df"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    environment = create_python_environment(
        bokeh_dir,
    )
    manifest, _ = make_api_manifest(
        bokeh_dir,
        None,
        AppModes.BOKEH_APP,
        environment,
        None,
        None,
    )

    assert bokeh_dir_ans["metadata"] == manifest["metadata"]
    assert bokeh_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_bokeh():
    bokeh_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-bokeh"},  # "entrypoint": "app3"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "77477063f2527bde7b55a087da0a5520"},
            "README.md": {"checksum": "842a630dc6d49e1e58ae9e36715b1da1"},
            "app3.py": {"checksum": "a5de7b460476a9ac4e02edfc2d52d9df"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }

    environment = create_python_environment(
        bokeh_dir,
    )
    with make_api_bundle(
        bokeh_dir,
        None,
        AppModes.BOKEH_APP,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app3.py",
            "data.csv",
            "manifest.json",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert bokeh_dir_ans["metadata"] == bundle_json["metadata"]
        assert bokeh_dir_ans["files"].keys() == bundle_json["files"].keys()


shiny_dir = os.path.join(cur_dir, "./testdata/top-5-income-share-shiny")
shiny_file = os.path.join(cur_dir, "./testdata/top-5-income-share-shiny/app.py")


def test_make_api_manifest_shiny():
    shiny_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-shiny"},  # "entrypoint": "app4"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "2a4bdca32428db1f47c6a7f0ba830a9b"},
            "README.md": {"checksum": "7d083dbcdd4731d91bcb470e746b3a38"},
            "app4.py": {"checksum": "f7e4b3b7ff0ada525ec388d037ff6c6a"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    environment = create_python_environment(
        shiny_dir,
    )
    manifest, _ = make_api_manifest(
        shiny_dir,
        None,
        AppModes.PYTHON_SHINY,
        environment,
        None,
        None,
    )

    assert shiny_dir_ans["metadata"] == manifest["metadata"]
    assert shiny_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_shiny():
    shiny_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-shiny"},  # "entrypoint": "app4"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "2a4bdca32428db1f47c6a7f0ba830a9b"},
            "README.md": {"checksum": "7d083dbcdd4731d91bcb470e746b3a38"},
            "app4.py": {"checksum": "f7e4b3b7ff0ada525ec388d037ff6c6a"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    environment = create_python_environment(
        shiny_dir,
    )
    with make_api_bundle(
        shiny_dir,
        None,
        AppModes.PYTHON_SHINY,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app4.py",
            "data.csv",
            "manifest.json",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert shiny_dir_ans["metadata"] == bundle_json["metadata"]
        assert shiny_dir_ans["files"].keys() == bundle_json["files"].keys()


pyshiny_manifest_dir = os.path.join(cur_dir, "./testdata/pyshiny_with_manifest")
pyshiny_manifest_file = os.path.join(cur_dir, "./testdata/pyshiny_with_manifest/manifest.json")


def test_make_manifest_bundle():
    manifest = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-shiny", "entrypoint": "app5"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "c82f1a9894e5510b2f0c16fa63aaa004"},
            "README.md": {"checksum": "7d083dbcdd4731d91bcb470e746b3a38"},
            "app5.py": {"checksum": "f7e4b3b7ff0ada525ec388d037ff6c6a"},
            "data.csv": {"checksum": "aabd9d1210246c69403532a6a9d24286"},
        },
    }
    with make_manifest_bundle(
        pyshiny_manifest_file,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "README.md",
            "app5.py",
            "data.csv",
            "manifest.json",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert manifest["metadata"] == bundle_json["metadata"]
        assert manifest["files"].keys() == bundle_json["files"].keys()


empty_manifest_file = os.path.join(cur_dir, "./testdata/Manifest_data/empty_manifest.json")
missing_file_manifest = os.path.join(cur_dir, "./testdata/Manifest_data/missing_file_manifest.json")


def test_make_bundle_empty_manifest():
    with pytest.raises(Exception):
        make_manifest_bundle(empty_manifest_file)


def test_make_bundle_missing_file_in_manifest():
    with pytest.raises(FileNotFoundError):
        make_manifest_bundle(missing_file_manifest)
