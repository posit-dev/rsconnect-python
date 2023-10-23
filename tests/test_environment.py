import re
import sys

from unittest import TestCase

from rsconnect.environment import (
    MakeEnvironment,
    detect_environment,
    get_default_locale,
    get_python_version,
)
from .utils import get_dir

version_re = re.compile(r"\d+\.\d+(\.\d+)?")


class TestEnvironment(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def test_get_python_version(self):
        self.assertEqual(
            get_python_version(MakeEnvironment(package_manager="pip")),
            self.python_version(),
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

        expected = MakeEnvironment(
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

        # these are the dependencies declared in our pyproject.toml
        self.assertIn("six", result.contents)
        self.assertIn("click", result.contents.lower())

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = MakeEnvironment(
            contents=result.contents,
            filename="requirements.txt",
            locale=result.locale,
            package_manager="pip",
            pip=result.pip,
            python=self.python_version(),
            source="pip_freeze",
        )
        self.assertEqual(expected, result)
