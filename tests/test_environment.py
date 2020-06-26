import re
import sys

from unittest import TestCase
from os.path import dirname, join

from rsconnect.environment import (
    Environment,
    EnvironmentException,
    detect_environment,
    get_default_locale,
    get_python_version,
)
from .test_data_util import get_dir

version_re = re.compile(r"\d+\.\d+(\.\d+)?")


class TestEnvironment(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def test_get_python_version(self):
        self.assertEqual(
            get_python_version(Environment(package_manager="pip")), self.python_version(),
        )

    def test_get_default_locale(self):
        self.assertEqual(get_default_locale(lambda: ("en_US", "UTF-8")), "en_US.UTF-8")
        self.assertEqual(get_default_locale(lambda: (None, "UTF-8")), ".UTF-8")
        self.assertEqual(get_default_locale(lambda: ("en_US", None)), "en_US.")
        self.assertEqual(get_default_locale(lambda: (None, None)), "")

    def test_file(self):
        result = detect_environment(get_dir("pip1"))

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment(
            contents="numpy\npandas\nmatplotlib\n",
            filename="requirements.txt",
            locale=result.locale,
            package_manager="pip",
            pip=result.pip,
            python=self.python_version(),
            source="file",
        )
        self.assertEqual(expected, result)

    def test_pip_freeze(self):
        result = detect_environment(get_dir("pip2"))

        # these are the dependencies declared in our setup.py
        self.assertIn("six", result.contents)
        self.assertIn("click", result.contents.lower())

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment(
            contents=result.contents,
            filename="requirements.txt",
            locale=result.locale,
            package_manager="pip",
            pip=result.pip,
            python=self.python_version(),
            source="pip_freeze",
        )
        self.assertEqual(expected, result)

    def test_conda_env_export(self):
        fake_conda = join(dirname(__file__), "testdata", "fake_conda.sh")
        result = detect_environment(get_dir("conda1"), conda_mode=True, force_generate=True, conda=fake_conda)
        self.assertEqual(result.source, "conda_env_export")
        self.assertEqual(result.conda, "1.0.0")
        self.assertEqual(result.contents, "this is a conda environment\n")

        fake_broken_conda = join(dirname(__file__), "testdata", "fake_broken_conda.sh")
        self.assertRaises(
            EnvironmentException,
            detect_environment,
            get_dir("conda1"),
            conda_mode=True,
            force_generate=True,
            conda=fake_broken_conda,
        )
