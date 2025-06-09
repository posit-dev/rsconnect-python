# -*- coding: utf-8 -*-
import json
import os
import sys
import tarfile
import tempfile
from os.path import abspath, basename, dirname, join
from pathlib import Path
from unittest import TestCase, mock

import pytest

from rsconnect.bundle import (
    Manifest,
    _default_title,
    _default_title_from_manifest,
    create_html_manifest,
    create_voila_manifest,
    guess_deploy_dir,
    keep_manifest_specified_file,
    list_files,
    make_api_bundle,
    make_api_manifest,
    make_html_bundle,
    make_html_manifest,
    make_manifest_bundle,
    make_notebook_html_bundle,
    make_notebook_source_bundle,
    make_quarto_manifest,
    make_quarto_source_bundle,
    make_source_manifest,
    make_tensorflow_bundle,
    make_tensorflow_manifest,
    make_voila_bundle,
    to_bytes,
    validate_entry_point,
    validate_extra_files,
)
from rsconnect.environment import Environment
from rsconnect.exception import RSConnectException
from rsconnect.models import AppModes

from .utils import get_dir, get_manifest_path


def create_fake_quarto_rendered_output(target_dir, name):
    with open(join(target_dir, f"{name}.html"), "w") as fp:
        fp.write(f"<html><body>fake rendering: {name}</body></html>\n")
    files_dir = join(target_dir, f"{name}_files")
    os.mkdir(files_dir)
    with open(join(files_dir, "resource.js"), "w") as fp:
        fp.write("// fake resource.js\n")


class TestBundle(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def setUp(self):
        self.maxDiff = None

    def test_to_bytes(self):
        self.assertEqual(to_bytes(b"abc123"), b"abc123")
        self.assertEqual(to_bytes(b"\xc3\xa5bc123"), b"\xc3\xa5bc123")
        self.assertEqual(to_bytes(b"\xff\xffabc123"), b"\xff\xffabc123")

        self.assertEqual(to_bytes("abc123"), b"abc123")
        self.assertEqual(to_bytes("åbc123"), b"\xc3\xa5bc123")

        self.assertEqual(to_bytes("abc123"), b"abc123")
        self.assertEqual(to_bytes("åbc123"), b"\xc3\xa5bc123")

    def test_make_notebook_source_bundle1(self):
        directory = get_dir("pip1")
        nb_path = join(directory, "dummy.ipynb")

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = Environment.create_python_environment(directory, require_requirements_txt=False)
        with make_notebook_source_bundle(
            nb_path,
            environment,
            None,
            hide_all_input=False,
            hide_tagged_input=False,
            image=None,
            env_management_py=None,
            env_management_r=None,
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

    def test_make_notebook_source_bundle2(self):
        directory = get_dir("pip2")
        nb_path = join(directory, "dummy.ipynb")

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = Environment.create_python_environment(directory, require_requirements_txt=False)

        with make_notebook_source_bundle(
            nb_path,
            environment,
            ["data.csv"],
            hide_all_input=False,
            hide_tagged_input=False,
            image="rstudio/connect:bionic",
            env_management_py=False,
            env_management_r=False,
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
                    "environment": {
                        "image": "rstudio/connect:bionic",
                        "environment_management": {
                            "python": False,
                            "r": False,
                        },
                    },
                    "files": {
                        "dummy.ipynb": {
                            "checksum": ipynb_hash,
                        },
                        "data.csv": {"checksum": data_csv_hash},
                    },
                },
            )

    def test_make_quarto_source_bundle_from_simple_project(self):
        temp_proj = tempfile.mkdtemp()

        # This is a simple project; it has a _quarto.yml and one Markdown file.
        with open(join(temp_proj, "_quarto.yml"), "w") as fp:
            fp.write("project:\n")
            fp.write('  title: "project with one rendered file"\n')

        with open(join(temp_proj, "myquarto.qmd"), "w") as fp:
            fp.write("---\n")
            fp.write("title: myquarto\n")
            fp.write("jupyter: python3\n")
            fp.write("---\n\n")
            fp.write("```{python}\n")
            fp.write("1 + 1\n")
            fp.write("```\n")

        # Create some files that should not make it into the manifest; they
        # should be automatically ignored because myquarto.qmd is a project
        # input file.
        create_fake_quarto_rendered_output(temp_proj, "myquarto")

        environment = Environment.create_python_environment(temp_proj, require_requirements_txt=False)

        # mock the result of running of `quarto inspect <project_dir>`
        inspect = {
            "quarto": {"version": "1.3.433"},
            "dir": temp_proj,
            "engines": ["jupyter"],
            "config": {"project": {"title": "myquarto"}, "editor": "visual", "language": {}},
            "files": {
                "input": [temp_proj + "/myquarto.qmd"],
                "resources": [],
                "config": [temp_proj + "/_quarto.yml"],
                "configResources": [],
            },
        }

        with make_quarto_source_bundle(
            temp_proj, inspect, AppModes.STATIC_QUARTO, environment, [], [], None
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "_quarto.yml",
                    "manifest.json",
                    "myquarto.qmd",
                    "requirements.txt",
                ],
            )

            reqs = tar.extractfile("requirements.txt").read()
            self.assertIsNotNone(reqs)

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "locale": mock.ANY,
                    "metadata": {"appmode": "quarto-static"},
                    "python": {
                        "version": self.python_version(),
                        "package_manager": {
                            "name": "pip",
                            "package_file": "requirements.txt",
                            "version": mock.ANY,
                        },
                    },
                    "quarto": {"engines": ["jupyter"], "version": mock.ANY},
                    "files": {
                        "_quarto.yml": {"checksum": mock.ANY},
                        "myquarto.qmd": {"checksum": mock.ANY},
                        "requirements.txt": {"checksum": mock.ANY},
                    },
                },
            )

    def test_make_quarto_source_bundle_from_complex_project(self):
        temp_proj = tempfile.mkdtemp()

        # This is a complex project; it has a _quarto.yml and multiple
        # Markdown files.
        with open(join(temp_proj, "_quarto.yml"), "w") as fp:
            fp.write("project:\n")
            fp.write("  type: website\n")
            fp.write('  title: "myquarto"\n')

        with open(join(temp_proj, "index.qmd"), "w") as fp:
            fp.write("---\n")
            fp.write("title: home\n")
            fp.write("jupyter: python3\n")
            fp.write("---\n\n")
            fp.write("```{python}\n")
            fp.write("1 + 1\n")
            fp.write("```\n")

        with open(join(temp_proj, "about.qmd"), "w") as fp:
            fp.write("---\n")
            fp.write("title: about\n")
            fp.write("---\n\n")
            fp.write("math, math, math.\n")

        # Create some files that should not make it into the manifest; they
        # should be automatically ignored because myquarto.qmd is a project
        # input file.
        #
        # Create files both in the current directory and beneath _site (the
        # implicit output-dir for websites).
        create_fake_quarto_rendered_output(temp_proj, "index")
        create_fake_quarto_rendered_output(temp_proj, "about")
        site_dir = join(temp_proj, "_site")
        os.mkdir(site_dir)
        create_fake_quarto_rendered_output(site_dir, "index")
        create_fake_quarto_rendered_output(site_dir, "about")

        environment = Environment.create_python_environment(temp_proj, require_requirements_txt=False)

        # mock the result of running of `quarto inspect <project_dir>`
        inspect = {
            "quarto": {"version": "1.3.433"},
            "dir": temp_proj,
            "engines": [
                "markdown",
                "jupyter",
            ],
            "config": {
                "project": {
                    "type": "website",
                    "output-dir": "_site",
                },
            },
            "files": {
                "input": [
                    temp_proj + "/index.qmd",
                    temp_proj + "/about.qmd",
                ],
                "resources": [],
                "config": [temp_proj + "/_quarto.yml"],
                "configResources": [],
            },
        }

        with make_quarto_source_bundle(
            temp_proj, inspect, AppModes.STATIC_QUARTO, environment, [], [], None
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "_quarto.yml",
                    "about.qmd",
                    "index.qmd",
                    "manifest.json",
                    "requirements.txt",
                ],
            )

            reqs = tar.extractfile("requirements.txt").read()
            self.assertIsNotNone(reqs)

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "locale": mock.ANY,
                    "metadata": {
                        "appmode": "quarto-static",
                        "content_category": "site",
                    },
                    "python": {
                        "version": self.python_version(),
                        "package_manager": {
                            "name": "pip",
                            "package_file": "requirements.txt",
                            "version": mock.ANY,
                        },
                    },
                    "quarto": {
                        "engines": ["markdown", "jupyter"],
                        "version": mock.ANY,
                    },
                    "files": {
                        "_quarto.yml": {"checksum": mock.ANY},
                        "index.qmd": {"checksum": mock.ANY},
                        "about.qmd": {"checksum": mock.ANY},
                        "requirements.txt": {"checksum": mock.ANY},
                    },
                },
            )

    def test_make_quarto_source_bundle_from_project_with_requirements(self):
        temp_proj = tempfile.mkdtemp()

        # add project files
        fp = open(join(temp_proj, "myquarto.qmd"), "w")
        fp.write("---\n")
        fp.write("title: myquarto\n")
        fp.write("jupyter: python3\n")
        fp.write("---\n\n")
        fp.write("```{python}\n")
        fp.write("1 + 1\n")
        fp.write("```\n")
        fp.close()

        fp = open(join(temp_proj, "_quarto.yml"), "w")
        fp.write("project:\n")
        fp.write('  title: "myquarto"\n')
        fp.write("editor: visual\n")

        fp = open(join(temp_proj, "requirements.txt"), "w")
        fp.write("dash\n")
        fp.write("pandas\n")
        fp.close()

        environment = Environment.create_python_environment(temp_proj, require_requirements_txt=False)

        # mock the result of running of `quarto inspect <project_dir>`
        inspect = {
            "quarto": {"version": "1.3.433"},
            "dir": temp_proj,
            "engines": ["jupyter"],
            "config": {"project": {"title": "myquarto"}, "editor": "visual", "language": {}},
            "files": {
                "input": [temp_proj + "/myquarto.qmd"],
                "resources": [],
                "config": [temp_proj + "/_quarto.yml"],
                "configResources": [],
            },
        }

        with make_quarto_source_bundle(
            temp_proj, inspect, AppModes.STATIC_QUARTO, environment, [], [], None
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "_quarto.yml",
                    "manifest.json",
                    "myquarto.qmd",
                    "requirements.txt",
                ],
            )

            reqs = tar.extractfile("requirements.txt").read()
            self.assertIsNotNone(reqs)

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "locale": mock.ANY,
                    "metadata": {"appmode": "quarto-static"},
                    "python": {
                        "version": self.python_version(),
                        "package_manager": {
                            "name": "pip",
                            "package_file": "requirements.txt",
                            "version": mock.ANY,
                        },
                    },
                    "quarto": {"engines": ["jupyter"], "version": mock.ANY},
                    "files": {
                        "_quarto.yml": {"checksum": mock.ANY},
                        "myquarto.qmd": {"checksum": mock.ANY},
                        "requirements.txt": {"checksum": mock.ANY},
                    },
                },
            )

    def test_make_quarto_source_bundle_from_file(self):
        temp_proj = tempfile.mkdtemp()

        filename = join(temp_proj, "myquarto.qmd")
        # add single qmd file with markdown engine
        with open(filename, "w") as fp:
            fp.write("---\n")
            fp.write("title: myquarto\n")
            fp.write("engine: markdown\n")
            fp.write("---\n\n")
            fp.write("### This is a test\n")

        # Create some files that should not make it into the manifest; they
        # should be automatically ignored because myquarto.qmd is the input
        # file.
        create_fake_quarto_rendered_output(temp_proj, "myquarto")

        # mock the result of running of `quarto inspect <qmd_file>`
        inspect = {
            "quarto": {"version": "1.3.433"},
            "engines": ["markdown"],
        }

        with make_quarto_source_bundle(
            filename, inspect, AppModes.STATIC_QUARTO, None, [], [], None
        ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
            names = sorted(tar.getnames())
            self.assertEqual(
                names,
                [
                    "manifest.json",
                    "myquarto.qmd",
                ],
            )

            manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))

            # noinspection SpellCheckingInspection
            self.assertEqual(
                manifest,
                {
                    "version": 1,
                    "metadata": {"appmode": "quarto-static"},
                    "quarto": {"engines": ["markdown"], "version": mock.ANY},
                    "files": {
                        "myquarto.qmd": {"checksum": mock.ANY},
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
        nb_path = join(directory, "dummy.ipynb")

        bundle = make_notebook_html_bundle(
            nb_path,
            sys.executable,
            hide_all_input=False,
            hide_tagged_input=False,
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
                    "files": {},
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
        # noinspection SpellCheckingInspection
        self.assertFalse(keep_manifest_specified_file(".Rproj.user/bogus.file"))

    def test_manifest_bundle(self):
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
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None)
        self.assertEqual(
            manifest,
            {"version": 1, "metadata": {"appmode": "python-api"}, "files": {}},
        )

        # include image parameter
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None, image="rstudio/connect:bionic")
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "python-api"},
                "environment": {
                    "image": "rstudio/connect:bionic",
                },
                "files": {},
            },
        )

        # include env_management_py parameter
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None, env_management_py=False)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "python-api"},
                "environment": {"environment_management": {"python": False}},
                "files": {},
            },
        )

        # include env_management_r parameter
        manifest = make_source_manifest(AppModes.PYTHON_API, None, None, None, env_management_r=False)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "python-api"},
                "environment": {"environment_management": {"r": False}},
                "files": {},
            },
        )

        # include all runtime environment parameters
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            None,
            None,
            None,
            image="rstudio/connect:bionic",
            env_management_py=False,
            env_management_r=False,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "python-api"},
                "environment": {
                    "image": "rstudio/connect:bionic",
                    "environment_management": {"r": False, "python": False},
                },
                "files": {},
            },
        )

        # include environment parameter
        manifest = make_source_manifest(
            AppModes.PYTHON_API,
            Environment.from_dict(
                dict(
                    contents="",
                    error=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip="22.0.4",
                    python="3.9.12",
                    source="file",
                )
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

    def test_make_quarto_manifest_project_no_opt_params(self):
        temp_proj = tempfile.mkdtemp()

        # Verify the optional parameters
        # image=None,  # type: str
        # environment=None,  # type: typing.Optional[Environment]
        # extra_files=None,  # type: typing.Optional[typing.List[str]]
        # excludes=None,  # type: typing.Optional[typing.List[str]]

        # No optional parameters
        manifest, _ = make_quarto_manifest(
            temp_proj,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            [],
            [],
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

    def test_make_quarto_manifest_doc_no_opt_params(self):
        _, temp_doc = tempfile.mkstemp()

        # Verify the optional parameters
        # image=None,  # type: str
        # environment=None,  # type: typing.Optional[Environment]
        # extra_files=None,  # type: typing.Optional[typing.List[str]]
        # excludes=None,  # type: typing.Optional[typing.List[str]]

        # No optional parameters
        manifest, _ = make_quarto_manifest(
            temp_doc,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.STATIC_QUARTO,
            None,
            [],
            [],
            None,
        )
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "quarto-static"},
                "quarto": {"version": "0.9.16", "engines": ["jupyter"]},
                "files": {basename(temp_doc): {"checksum": mock.ANY}},
            },
        )

    def test_make_quarto_manifest_project_with_image(self):
        temp_proj = tempfile.mkdtemp()

        # include image parameter
        manifest, _ = make_quarto_manifest(
            temp_proj,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            [],
            [],
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

    def test_make_quarto_manifest_project_with_env(self):
        temp_proj = tempfile.mkdtemp()

        # add a requirements.txt file in the project dir
        fp = open(join(temp_proj, "requirements.txt"), "w")
        fp.write("dash\n")
        fp.write("pandas\n")
        fp.close()

        # include environment parameter
        manifest, _ = make_quarto_manifest(
            temp_proj,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            Environment.from_dict(
                dict(
                    contents="",
                    error=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip="22.0.4",
                    python="3.9.12",
                    source="file",
                )
            ),
            [],
            [],
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
                "files": {"requirements.txt": {"checksum": mock.ANY}},
            },
        )

    def test_make_quarto_manifest_project_with_extra_files(self):
        temp_proj = tempfile.mkdtemp()

        # include extra_files parameter
        fp = open(join(temp_proj, "a"), "w")
        fp.write("This is file a\n")
        fp.close()
        fp = open(join(temp_proj, "b"), "w")
        fp.write("This is file b\n")
        fp.close()
        fp = open(join(temp_proj, "c"), "w")
        fp.write("This is file c\n")
        fp.close()

        manifest, _ = make_quarto_manifest(
            temp_proj,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            ["a", "b", "c"],
            [],
            None,
        )

        if sys.platform == "win32":
            a_hash = "f4751c084b3ade4d736c6293ab8468c9"
            b_hash = "4976d559975b5232cf09a10afaf8d0a8"
            c_hash = "09c56e1b9e6ae34c6662717c47a7e187"
        else:
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
                },
            },
        )

    def test_make_quarto_manifest_project_with_excludes(self):
        temp_proj = tempfile.mkdtemp()

        # add a requirements.txt file in the project dir
        fp = open(join(temp_proj, "requirements.txt"), "w")
        fp.write("dash\n")
        fp.write("pandas\n")
        fp.close()

        # add other files
        fp = open(join(temp_proj, "d"), "w")
        fp.write("This is file d\n")
        fp.close()
        fp = open(join(temp_proj, "e"), "w")
        fp.write("This is file e\n")
        fp.close()
        fp = open(join(temp_proj, "f"), "w")
        fp.write("This is file f\n")
        fp.close()

        # exclude the requirements.txt file, but not the other files
        manifest, _ = make_quarto_manifest(
            temp_proj,
            {
                "quarto": {"version": "0.9.16"},
                "engines": ["jupyter"],
                "config": {"project": {"title": "quarto-proj-py"}, "editor": "visual", "language": {}},
            },
            AppModes.SHINY_QUARTO,
            None,
            ["d", "e", "f"],
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
                    "d": {"checksum": mock.ANY},
                    "e": {"checksum": mock.ANY},
                    "f": {"checksum": mock.ANY},
                },
            },
        )

    def test_make_tensorflow_manifest_empty(self):
        temp_proj = tempfile.mkdtemp()
        manifest = make_tensorflow_manifest(temp_proj, [], [])
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "tensorflow-saved-model"},
                "files": {},
            },
        )

    def test_make_tensorflow_bundle_empty(self):
        temp_proj = tempfile.mkdtemp()
        with self.assertRaises(RSConnectException):
            _ = make_tensorflow_bundle(temp_proj, [], [])

    def test_make_tensorflow_manifest(self):
        temp_proj = tempfile.mkdtemp()
        os.mkdir(join(temp_proj, "1"))
        model_file = join(temp_proj, "1", "saved_model.pb")
        with open(model_file, "w") as fp:
            fp.write("fake model file\n")
        manifest = make_tensorflow_manifest(temp_proj, [], [])
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {"appmode": "tensorflow-saved-model"},
                "files": {
                    "1/saved_model.pb": {"checksum": mock.ANY},
                },
            },
        )

    def test_make_tensorflow_bundle(self):
        temp_proj = tempfile.mkdtemp()
        os.mkdir(join(temp_proj, "1"))
        model_file = join(temp_proj, "1", "saved_model.pb")
        with open(model_file, "w") as fp:
            fp.write("fake model file\n")
        with make_tensorflow_bundle(temp_proj, [], []) as bundle:
            with tarfile.open(mode="r:gz", fileobj=bundle) as tar:
                names = sorted(tar.getnames())
                self.assertEqual(
                    names,
                    [
                        "1/saved_model.pb",
                        "manifest.json",
                    ],
                )
                manifest_data = tar.extractfile("manifest.json").read().decode("utf-8")
                manifest = json.loads(manifest_data)
                self.assertEqual(
                    manifest,
                    {
                        "version": 1,
                        "metadata": {"appmode": "tensorflow-saved-model"},
                        "files": {
                            "1/saved_model.pb": {"checksum": mock.ANY},
                        },
                    },
                )

    def test_make_html_manifest(self):
        # Verify the optional parameters
        # image=None,  # type: str

        # No optional parameters
        manifest = make_html_manifest("abc.html")
        # print(manifest)
        self.assertEqual(
            manifest,
            {
                "version": 1,
                "metadata": {
                    "appmode": "static",
                    "primary_html": "abc.html",
                },
                "files": {},
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

    def test_validate_entry_point(self):
        # Simple cases
        for case in ["app", "application", "main", "api", "app-example", "app_example", "example-app", "example_app"]:
            self._entry_point_case(["helper.py", f"{case}.py"], None, case)

        # only one Python file means we assume it's the entrypoint
        self._entry_point_case(["onlysource.py"], None, "onlysource")

        # Explicit entrypoint specifiers, no need to infer
        self._entry_point_case(["helper.py", "app.py"], "app", "app")
        self._entry_point_case(["helper.py", "app.py"], "app:app", "app:app")
        self._entry_point_case(["helper.py", "app.py"], "foo:bar", "foo:bar")

    def test_validate_entry_point_failure(self):
        # Invalid entrypoint specifier
        self._entry_point_case(["app.py"], "x:y:z", False)
        # Nothing relevant found
        self._entry_point_case(["one.py", "two.py"], "x:y:z", False)
        # Too many app-*.py files
        self._entry_point_case(["app-one.py", "app-two.py"], "x:y:z", False)

    def _entry_point_case(self, files, entry_point, expected):
        with tempfile.TemporaryDirectory() as directory:
            dir = Path(directory)

            for file in files:
                (dir / file).touch()

            if expected is False:
                with self.assertRaises(RSConnectException):
                    validate_entry_point(entry_point, directory)
            else:
                self.assertEqual(validate_entry_point(entry_point, directory), expected)

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
            guess_deploy_dir(bqplot_dir, bqplot_dir)
        with self.assertRaises(RSConnectException):
            guess_deploy_dir(nonexistent_dir, None)
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
    environment = Environment.from_dict(
        dict(
            contents="bqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
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
            extra_files=None,
            excludes=None,
            force_generate=True,
            image=None,
            multi_notebook=False,
        )
        assert ans == json.loads(manifest.get_flattened_copy().json)


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
    environment = Environment.from_dict(
        dict(
            contents="numpy\nipywidgets\nbqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
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
        extra_files=None,
        excludes=None,
        force_generate=True,
        image=None,
        multi_notebook=False,
    )
    assert ans == json.loads(manifest.get_flattened_copy().json)


def test_create_voila_manifest_extra():
    environment = Environment.from_dict(
        dict(
            contents="numpy\nipywidgets\nbqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0.1",
            python="3.8.12",
            source="file",
        )
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
        extra_files=[dashboard_extra_ipynb],
        excludes=None,
        force_generate=True,
        image=None,
        multi_notebook=False,
    )
    assert ans == json.loads(manifest.get_flattened_copy().json)


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
    environment = Environment.from_dict(
        dict(
            contents="bqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
    )

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
            "bqplot/bqplot.ipynb": {"checksum": bqplot_hash},
            "dashboard/dashboard.ipynb": {"checksum": dashboard_hash},
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
            extra_files=None,
            excludes=None,
            force_generate=True,
            image=None,
            multi_notebook=True,
        )
        assert json.loads(manifest.get_flattened_copy().json) == ans


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
    environment = Environment.from_dict(
        dict(
            contents="bqplot",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
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
    environment = Environment.from_dict(
        dict(
            contents="bqplot",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
    )

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
            "bqplot/bqplot.ipynb": {"checksum": bqplot_hash},
            "dashboard/dashboard.ipynb": {"checksum": dashboard_hash},
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
            assert json.loads(tar.extractfile("manifest.json").read().decode("utf-8")) == ans


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
    environment = Environment.from_dict(
        dict(
            contents="numpy\nipywidgets\nbqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0",
            python="3.8.12",
            source="file",
        )
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

    environment = Environment.from_dict(
        dict(
            contents="numpy\nipywidgets\nbqplot\n",
            error=None,
            filename="requirements.txt",
            locale="en_US.UTF-8",
            package_manager="pip",
            pip="23.0.1",
            python="3.8.12",
            source="file",
        )
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
        )
    with pytest.raises(RSConnectException) as _:
        _, _ = create_html_manifest(
            None,
            single_file_index_file,
            extra_files=None,
            excludes=None,
        )
    with pytest.raises(RSConnectException) as _:
        _, _ = create_html_manifest(
            multi_file_nonindex_dir,
            None,
            extra_files=None,
            excludes=None,
        )

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
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert single_file_index_file_ans == json.loads(manifest.get_flattened_copy().json)

    single_file_index_dir_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {
            "index.html": {"checksum": index_hash},
            "test1.txt": {"checksum": txt_hash},
            "test_folder1/testfoldertext1.txt": {"checksum": folder_txt_hash},
        },
    }

    manifest = create_html_manifest(
        single_file_index_dir,
        None,
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert single_file_index_dir_ans == json.loads(manifest.get_flattened_copy().json)

    manifest = create_html_manifest(
        single_file_index_dir,
        single_file_index_file,
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert single_file_index_dir_ans == json.loads(manifest.get_flattened_copy().json)

    multi_file_index_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "index.html", "entrypoint": "index.html"},
        "files": {"index.html": {"checksum": index_hash}},
    }

    manifest = create_html_manifest(
        multi_file_index_file,
        None,
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert multi_file_index_file_ans == json.loads(manifest.get_flattened_copy().json)

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
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert multi_file_index_dir_ans == json.loads(manifest.get_flattened_copy().json)

    manifest = create_html_manifest(
        multi_file_index_dir,
        multi_file_index_file,
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert multi_file_index_dir_ans == json.loads(manifest.get_flattened_copy().json)

    multi_file_nonindex_file_ans = {
        "version": 1,
        "metadata": {"appmode": "static", "primary_html": "b.html", "entrypoint": "b.html"},
        "files": {"b.html": {"checksum": index_hash}},
    }

    manifest = create_html_manifest(
        multi_file_nonindex_fileb,
        None,
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert multi_file_nonindex_file_ans == json.loads(manifest.get_flattened_copy().json)

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
        extra_files=tuple(),
        excludes=tuple(),
    )
    assert multi_file_nonindex_dir_and_file_ans == json.loads(manifest.get_flattened_copy().json)

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
        excludes=tuple(),
    )
    assert multi_file_nonindex_file_extras_ans == json.loads(manifest.get_flattened_copy().json)

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
        excludes=tuple(),
    )
    assert multi_file_index_dir_extras_ans == json.loads(manifest.get_flattened_copy().json)


def test_make_html_bundle():
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
        extra_files=tuple(),
        excludes=tuple(),
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
            "test_folder1/testfoldertext1.txt": {"checksum": folder_txt_hash},
        },
    }
    with make_html_bundle(
        single_file_index_dir,
        None,
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=tuple(),
        excludes=tuple(),
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
        extra_files=[multi_file_nonindex_filea],
        excludes=tuple(),
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
        extra_files=[multi_file_index_file2],
        excludes=tuple(),
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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

    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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
    environment = Environment.create_python_environment(
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


gradio_dir = os.path.join(cur_dir, "./testdata/gradio")
gradio_file = os.path.join(cur_dir, "./testdata/gradio/app.py")


def test_make_api_manifest_gradio():
    gradio_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-gradio"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "381ccadfb8d4848add470e33033b198f"},
            "app.py": {"checksum": "22feec76e9c02ac6b5a34a083e2983b6"},
        },
    }
    environment = Environment.create_python_environment(
        gradio_dir,
    )
    manifest, _ = make_api_manifest(
        gradio_dir,
        None,
        AppModes.PYTHON_GRADIO,
        environment,
        None,
        None,
    )

    assert gradio_dir_ans["metadata"] == manifest["metadata"]
    assert gradio_dir_ans["files"].keys() == manifest["files"].keys()


def test_make_api_bundle_gradio():
    gradio_dir_ans = {
        "version": 1,
        "locale": "en_US.UTF-8",
        "metadata": {"appmode": "python-gradio"},
        "python": {
            "version": "3.8.12",
            "package_manager": {"name": "pip", "version": "23.0.1", "package_file": "requirements.txt"},
        },
        "files": {
            "requirements.txt": {"checksum": "381ccadfb8d4848add470e33033b198f"},
            "app.py": {"checksum": "22feec76e9c02ac6b5a34a083e2983b6"},
        },
    }
    environment = Environment.create_python_environment(
        gradio_dir,
    )
    with make_api_bundle(
        gradio_dir,
        None,
        AppModes.PYTHON_GRADIO,
        environment,
        None,
        None,
    ) as bundle, tarfile.open(mode="r:gz", fileobj=bundle) as tar:
        names = sorted(tar.getnames())
        assert names == [
            "app.py",
            "manifest.json",
            "requirements.txt",
        ]
        bundle_json = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        assert gradio_dir_ans["metadata"] == bundle_json["metadata"]
        assert gradio_dir_ans["files"].keys() == bundle_json["files"].keys()


empty_manifest_file = os.path.join(cur_dir, "./testdata/Manifest_data/empty_manifest.json")
missing_file_manifest = os.path.join(cur_dir, "./testdata/Manifest_data/missing_file_manifest.json")


def test_make_bundle_empty_manifest():
    with pytest.raises(Exception):
        make_manifest_bundle(empty_manifest_file)


def test_make_bundle_missing_file_in_manifest():
    with pytest.raises(FileNotFoundError):
        make_manifest_bundle(missing_file_manifest)
