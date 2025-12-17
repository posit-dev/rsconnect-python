import re
import sys
import os
import tempfile
import shutil
import subprocess
from unittest import TestCase
from unittest import mock

import rsconnect.environment
from rsconnect.exception import RSConnectException
from rsconnect.environment import Environment, which_python
from rsconnect.subprocesses.inspect_environment import get_python_version, get_default_locale, filter_pip_freeze_output

from .utils import get_dir

import pytest

version_re = re.compile(r"\d+\.\d+(\.\d+)?")
TESTDATA = os.path.join(os.path.dirname(__file__), "testdata")


class TestEnvironment(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def test_get_python_version(self):
        self.assertEqual(
            get_python_version(),
            self.python_version(),
        )

    def test_get_default_locale(self):
        self.assertEqual(get_default_locale(lambda: ("en_US", "UTF-8")), "en_US.UTF-8")
        self.assertEqual(get_default_locale(lambda: (None, "UTF-8")), ".UTF-8")
        self.assertEqual(get_default_locale(lambda: ("en_US", None)), "en_US.")
        self.assertEqual(get_default_locale(lambda: (None, None)), "")

    def test_file(self):
        result = Environment.create_python_environment(get_dir("pip1"))

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment.from_dict(
            dict(
                contents="numpy\npandas\nmatplotlib\n",
                filename="requirements.txt",
                locale=result.locale,
                package_manager="pip",
                pip=result.pip,
                python=self.python_version(),
                source="file",
            ),
            python_interpreter=sys.executable,
            python_version_requirement=">=3.8",
        )
        self.assertEqual(expected, result)

    def test_requirements_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "project")
            shutil.copytree(get_dir("pip1"), project_dir)
            os.makedirs(os.path.join(project_dir, "alt"), exist_ok=True)
            custom_requirements = os.path.join(project_dir, "alt", "custom.txt")
            with open(custom_requirements, "w") as f:
                f.write("foo==1.0\nbar>=2.0\nrsconnect==0.1\n")

            result = Environment.create_python_environment(
                project_dir, requirements_file=os.path.join("alt", "custom.txt")
            )

            assert result.filename == "alt/custom.txt"
            assert result.contents == "foo==1.0\nbar>=2.0\n"
            assert result.source == "file"

    def test_pip_freeze(self):
        result = Environment.create_python_environment(get_dir("pip2"))

        # these are the dependencies declared in our pyproject.toml
        self.assertIn("six", result.contents)
        self.assertIn("click", result.contents.lower())

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment.from_dict(
            dict(
                contents=result.contents,
                filename="requirements.txt",
                locale=result.locale,
                package_manager="pip",
                pip=result.pip,
                python=self.python_version(),
                source="pip_freeze",
            ),
            python_interpreter=sys.executable,
        )
        self.assertEqual(expected, result)

    def test_filter_pip_freeze_output(self):
        raw_stdout = "numpy\npandas\n[notice] A new release of pip is available: 23.1.2 -> 23.3\n\
[notice] To update, run: pip install --upgrade pip"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas"

        self.assertEqual(filtered, expected)

        raw_stdout = "numpy\npandas"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas"

        self.assertEqual(filtered, expected)

        raw_stdout = "numpy\npandas\nnot at beginning [notice]\n\
[notice] To update, run: pip install --upgrade pip"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas\nnot at beginning [notice]"

        self.assertEqual(filtered, expected)


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


class TestPythonVersionRequirements:
    def test_pyproject_toml(self):
        env = Environment.create_python_environment(os.path.join(TESTDATA, "python-project", "using_pyproject"))
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8"

    def test_python_version(self):
        env = Environment.create_python_environment(os.path.join(TESTDATA, "python-project", "using_pyversion"))
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8,<3.12"

    def test_all_of_them(self):
        env = Environment.create_python_environment(os.path.join(TESTDATA, "python-project", "allofthem"))
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8,<3.12"

    def test_missing(self):
        env = Environment.create_python_environment(os.path.join(TESTDATA, "python-project", "empty"))
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement is None


def test_inspect_environment():
    environment = Environment._inspect_environment(sys.executable, get_dir("pip1"))
    assert environment is not None
    assert environment.python != ""


def test_inspect_environment_catches_type_error():
    with pytest.raises(RSConnectException) as exec_info:
        Environment._inspect_environment(sys.executable, None)  # type: ignore

    assert isinstance(exec_info.value, RSConnectException)
    assert isinstance(exec_info.value.__cause__, TypeError)


@pytest.mark.parametrize(
    (
        "file_name",
        "python",
        "requirements_file",
        "expected_python",
        "expected_environment",
    ),
    [
        pytest.param(
            "path/to/file.py",
            sys.executable,
            "requirements.txt",
            sys.executable,
            Environment.from_dict(
                dict(
                    contents=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip=None,
                    python=None,
                    source="pip_freeze",
                    error=None,
                ),
                python_interpreter=sys.executable,
            ),
            id="basic",
        ),
        pytest.param(
            "another/file.py",
            os.path.basename(sys.executable),
            "requirements.txt",
            sys.executable,
            Environment.from_dict(
                dict(
                    contents=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip=None,
                    python=None,
                    source="pip_freeze",
                    error=None,
                ),
                python_interpreter=sys.executable,
            ),
            id="which_python",
        ),
        pytest.param(
            "will/the/files/never/stop.py",
            "argh.py",
            "requirements.txt",
            "unused",
            Environment.from_dict(
                dict(
                    contents=None,
                    filename=None,
                    locale=None,
                    package_manager=None,
                    pip=None,
                    python=None,
                    source=None,
                    error="Could not even do things",
                )
            ),
            id="exploding",
        ),
    ],
)
def test_get_python_env_info(
    monkeypatch,
    file_name,
    python,
    requirements_file,
    expected_python,
    expected_environment,
):
    def fake_which_python(python, env=os.environ):
        return expected_python

    def fake_inspect_environment(
        python,
        directory,
        requirements_file="requirements.txt",
        check_output=subprocess.check_output,
    ):
        return expected_environment

    monkeypatch.setattr(Environment, "_inspect_environment", fake_inspect_environment)

    monkeypatch.setattr(rsconnect.environment, "which_python", fake_which_python)

    if expected_environment.error is not None:
        with pytest.raises(RSConnectException):
            _ = Environment._get_python_env_info(file_name, python, requirements_file=requirements_file)
    else:
        environment = Environment._get_python_env_info(file_name, python, requirements_file=requirements_file)

        assert environment.python_interpreter == expected_python
        assert environment == expected_environment


class TestEnvironmentDeprecations:
    def test_override_python_version(self):
        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1-no-version"), override_python_version=None)
        assert mock_warning.call_count == 0
        assert result.python_version_requirement is None

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1-no-version"), override_python_version="3.8")
        assert mock_warning.call_count == 1
        mock_warning.assert_called_once_with(
            "The --override-python-version option is deprecated, "
            "please use a .python-version file to force a specific interpreter version."
        )
        assert result.python_version_requirement == "==3.8"

    def test_python_interpreter(self):
        current_python_version = ".".join((str(v) for v in sys.version_info[:3]))

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1"))
        assert mock_warning.call_count == 0
        assert result.python == current_python_version

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1"), python=sys.executable)
        assert mock_warning.call_count == 1
        mock_warning.assert_called_once_with(
            "On modern Posit Connect versions, the --python option won't influence "
            "the Python version used to deploy the application anymore. "
            "Please use a .python-version file to force a specific interpreter version."
        )
        assert result.python == current_python_version
