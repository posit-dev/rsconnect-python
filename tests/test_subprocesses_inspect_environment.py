import tempfile
import pytest
from unittest import mock

from rsconnect.subprocesses.inspect_environment import (
    output_file,
    detect_environment,
    EnvironmentException,
)


def test_output_file_requires_requirements_txt():
    """Test that output_file raises an exception when requirements.txt is missing"""
    with tempfile.TemporaryDirectory() as empty_dir:
        with pytest.raises(EnvironmentException) as context:
            output_file(empty_dir, "requirements.txt", "pip")

        assert "requirements.txt file is required" in str(context.value)


def test_detect_environment_requires_requirements_txt():
    """Test that detect_environment raises an exception when requirements.txt is missing"""
    with tempfile.TemporaryDirectory() as empty_dir:
        with pytest.raises(EnvironmentException) as context:
            detect_environment(empty_dir, force_generate=False)

        assert "requirements.txt file is required" in str(context.value)


def test_detect_environment_with_force_generate():
    """Test that detect_environment still works with force_generate=True"""
    with tempfile.TemporaryDirectory() as empty_dir:
        with mock.patch("rsconnect.subprocesses.inspect_environment.pip_freeze") as mock_pip_freeze:
            mock_pip_freeze.return_value = {
                "filename": "requirements.txt",
                "contents": "numpy\npandas",
                "source": "pip_freeze",
                "package_manager": "pip",
            }
            # This should not raise an exception
            environment = detect_environment(empty_dir, force_generate=True)
            assert environment.filename == "requirements.txt"
            assert "numpy" in environment.contents
            assert "pandas" in environment.contents
