import re
import sys

from unittest import TestCase
from os.path import dirname, join

from rsconnect.environment import detect_environment, EnvironmentException, get_python_version, get_default_locale
from rsconnect.tests.test_data_util import get_dir

version_re = re.compile(r'\d+\.\d+(\.\d+)?')


class TestEnvironment(TestCase):
    @staticmethod
    def python_version():
        return '.'.join(map(str, sys.version_info[:3]))

    def test_get_python_version(self):
        self.assertEqual(get_python_version({'package_manager': 'pip'}), self.python_version())

    def test_get_default_locale(self):
        self.assertEqual(get_default_locale(lambda: ('en_US', 'UTF-8')), 'en_US.UTF-8')
        self.assertEqual(get_default_locale(lambda: (None, 'UTF-8')), '.UTF-8')
        self.assertEqual(get_default_locale(lambda: ('en_US', None)), 'en_US.')
        self.assertEqual(get_default_locale(lambda: (None, None)), '')

    def test_file(self):
        result = detect_environment(get_dir('pip1'))

        pip_version = result.pop('pip')
        self.assertTrue(version_re.match(pip_version))

        locale = result.pop('locale')
        self.assertIsInstance(locale, str)
        self.assertIn('.', locale)

        self.assertEqual(result, {
            'package_manager': 'pip',
            'source': 'file',
            'filename': 'requirements.txt',
            'contents': 'numpy\npandas\nmatplotlib\n',
            'python': self.python_version(),
        })

    def test_pip_freeze(self):
        result = detect_environment(get_dir('pip2'))
        contents = result.pop('contents')

        # these are the dependencies declared in our setup.py
        self.assertIn('six', contents)
        self.assertIn('click', contents.lower())

        pip_version = result.pop('pip')
        self.assertTrue(version_re.match(pip_version))

        locale = result.pop('locale')
        self.assertIsInstance(locale, str)
        self.assertIn('.', locale)

        self.assertEqual(result, {
            'package_manager': 'pip',
            'source': 'pip_freeze',
            'filename': 'requirements.txt',
            'python': self.python_version(),
        })

    def test_conda_env_export(self):
        fake_conda = join(dirname(__file__), 'testdata', 'fake_conda.sh')
        result = detect_environment(
            get_dir('conda1'), compatibility_mode=False, force_generate=True, conda=fake_conda
        )
        self.assertEqual(result['source'], 'conda_env_export')
        self.assertEqual(result['conda'], '1.0.0')
        self.assertEqual(result['contents'], 'this is a conda environment\n')

        fake_broken_conda = join(dirname(__file__), 'testdata', 'fake_broken_conda.sh')
        self.assertRaises(
            EnvironmentException, detect_environment, get_dir('conda1'), compatibility_mode=False,
            force_generate=True, conda=fake_broken_conda
        )
