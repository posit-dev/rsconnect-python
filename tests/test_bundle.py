# -*- coding: utf-8 -*-
import json
import sys
import tarfile
import tempfile

from unittest import TestCase
from os.path import dirname, join

from rsconnect.environment import detect_environment
from rsconnect.bundle import (
    list_files,
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    keep_manifest_specified_file,
    to_bytes,
    make_source_manifest,
    make_quarto_manifest,
    make_html_manifest,
)
from rsconnect.models import AppModes
from rsconnect.environment import Environment
from .utils import get_dir


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
        with make_notebook_source_bundle(nb_path, environment) as bundle, tarfile.open(
            mode="r:gz", fileobj=bundle
        ) as tar:

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
            nb_path, environment, image="rstudio/connect:bionic", extra_files=["data.csv"]
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

        bundle = make_notebook_html_bundle(nb_path, sys.executable)

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
        self.assertTrue(keep_manifest_specified_file("rsconnect"))
        self.assertFalse(keep_manifest_specified_file("rsconnect/bogus.file"))
        self.assertTrue(keep_manifest_specified_file("rsconnect-python"))
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
        manifest = make_source_manifest(AppModes.PYTHON_API)
        self.assertEqual(
            manifest,
            {"version": 1, "metadata": {"appmode": "python-api"}, "files": {}},
        )

        # include image parameter
        manifest = make_source_manifest(AppModes.PYTHON_API, image="rstudio/connect:bionic")
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
            environment=Environment(
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
            entrypoint="main.py",
        )
        print(f"{manifest}")
        self.assertEqual(
            manifest,
            {"version": 1, "metadata": {"appmode": "python-api", "entrypoint": "main.py"}, "files": {}},
        )

        # include quarto_inspection parameter
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            quarto_inspection={
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
        )
        print(f"{manifest}")
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
            image="rstudio/connect:bionic",
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
            environment=Environment(
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
            extra_files=["a", "b", "c"],
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
            extra_files=["a", "b", "c"],
            excludes=["requirements.txt"],
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
        print(f"{manifest}")
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
        print(f"{manifest}")
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
