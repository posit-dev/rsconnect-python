"""
Tests for git metadata detection and integration
"""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from rsconnect.git_metadata import (
    detect_git_metadata,
    get_git_branch,
    get_git_commit,
    get_git_remote_url,
    has_uncommitted_changes,
    is_git_repo,
    normalize_git_url_to_https,
)


class TestGitUrlNormalization:
    def test_already_https(self):
        url = "https://github.com/user/repo.git"
        assert normalize_git_url_to_https(url) == url

    def test_git_ssh_format(self):
        url = "git@github.com:user/repo.git"
        expected = "https://github.com/user/repo.git"
        assert normalize_git_url_to_https(url) == expected

    def test_ssh_url_format(self):
        url = "ssh://git@github.com/user/repo.git"
        expected = "https://github.com/user/repo.git"
        assert normalize_git_url_to_https(url) == expected

    def test_none_input(self):
        assert normalize_git_url_to_https(None) is None

    def test_unrecognized_format(self):
        url = "file:///path/to/repo"
        assert normalize_git_url_to_https(url) == url


class TestGitDetection:
    @pytest.fixture
    def git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, check=True)

            # Create a file and commit
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test content")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"], cwd=tmpdir, check=True, capture_output=True
            )

            # Add a remote
            subprocess.run(
                ["git", "remote", "add", "origin", "git@github.com:user/repo.git"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            yield tmpdir

    def test_is_git_repo_true(self, git_repo):
        assert is_git_repo(git_repo) is True

    def test_is_git_repo_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert is_git_repo(tmpdir) is False

    def test_get_git_commit(self, git_repo):
        commit = get_git_commit(git_repo)
        assert commit is not None
        assert len(commit) == 40  # SHA-1 hash length

    def test_get_git_branch(self, git_repo):
        branch = get_git_branch(git_repo)
        # Default branch can be either 'master' or 'main' depending on git version
        assert branch in ("master", "main")

    def test_get_git_remote_url(self, git_repo):
        url = get_git_remote_url(git_repo, "origin")
        assert url == "git@github.com:user/repo.git"

    def test_has_uncommitted_changes_false(self, git_repo):
        assert has_uncommitted_changes(git_repo) is False

    def test_has_uncommitted_changes_true(self, git_repo):
        # Create an uncommitted file
        test_file = Path(git_repo) / "new_file.txt"
        test_file.write_text("new content")
        assert has_uncommitted_changes(git_repo) is True

    def test_detect_git_metadata_clean_repo(self, git_repo):
        metadata = detect_git_metadata(git_repo)

        assert metadata["source"] == "git"
        assert "source_commit" in metadata
        assert len(metadata["source_commit"]) == 40
        assert not metadata["source_commit"].endswith("-dirty")
        assert metadata["source_branch"] in ("master", "main")
        assert metadata["source_repo"] == "https://github.com/user/repo.git"

    def test_detect_git_metadata_dirty_repo(self, git_repo):
        # Create an uncommitted file
        test_file = Path(git_repo) / "uncommitted.txt"
        test_file.write_text("uncommitted content")

        metadata = detect_git_metadata(git_repo)

        assert metadata["source"] == "git"
        assert metadata["source_commit"].endswith("-dirty")

    def test_detect_git_metadata_non_git_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = detect_git_metadata(tmpdir)
            assert metadata == {}


class TestServerVersionSupport:
    def test_server_supports_git_metadata(self):
        from rsconnect.api import server_supports_git_metadata

        # Older version - no support
        assert server_supports_git_metadata("2024.01.0") is False
        assert server_supports_git_metadata("2025.10.0") is False

        # Exact version - supported
        assert server_supports_git_metadata("2025.11.0") is True

        # Newer version - supported
        assert server_supports_git_metadata("2025.12.0") is True
        assert server_supports_git_metadata("2026.01.0") is True

        # None/empty - not supported
        assert server_supports_git_metadata(None) is False
        assert server_supports_git_metadata("") is False

    def test_server_supports_git_metadata_invalid_version(self):
        from rsconnect.api import server_supports_git_metadata

        # Invalid version strings should return False
        assert server_supports_git_metadata("invalid") is False
        assert server_supports_git_metadata("not-a-version") is False


class TestMultipartFormData:
    def test_create_multipart_form_data(self):
        from rsconnect.http_support import create_multipart_form_data

        fields = {
            "text_field": "plain text value",
            "file_field": ("bundle.tar.gz", b"binary content", "application/x-tar"),
        }

        body, content_type = create_multipart_form_data(fields)

        assert isinstance(body, bytes)
        assert content_type.startswith("multipart/form-data; boundary=")
        assert b"text_field" in body
        assert b"plain text value" in body
        assert b"file_field" in body
        assert b"bundle.tar.gz" in body
        assert b"binary content" in body
        assert b"application/x-tar" in body


class TestPrepareDeployMetadata:
    @pytest.fixture
    def temp_git_repo(self):
        """Create a minimal git repo for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, check=True)

            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("test")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "test"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", "https://github.com/user/repo.git"],
                cwd=tmpdir,
                check=True,
                capture_output=True,
            )

            yield tmpdir

    def test_prepare_metadata_no_metadata_flag(self, temp_git_repo):
        from rsconnect.main import prepare_deploy_metadata

        result = prepare_deploy_metadata(temp_git_repo, tuple(), True, "2025.11.0")
        assert result is None

    def test_prepare_metadata_old_server_no_cli_overrides(self, temp_git_repo):
        from rsconnect.main import prepare_deploy_metadata

        result = prepare_deploy_metadata(temp_git_repo, tuple(), False, "2024.01.0")
        assert result is None

    def test_prepare_metadata_new_server(self, temp_git_repo):
        from rsconnect.main import prepare_deploy_metadata

        result = prepare_deploy_metadata(temp_git_repo, tuple(), False, "2025.11.0")
        assert result is not None
        assert result["source"] == "git"
        assert "source_commit" in result
        assert "source_branch" in result
        assert result["source_repo"] == "https://github.com/user/repo.git"

    def test_prepare_metadata_cli_overrides(self, temp_git_repo):
        from rsconnect.main import prepare_deploy_metadata

        # CLI overrides force metadata even on old servers
        result = prepare_deploy_metadata(
            temp_git_repo, ("source=custom", "custom_key=custom_value"), False, "2024.01.0"
        )
        assert result is not None
        assert result["source"] == "custom"
        assert result["custom_key"] == "custom_value"

    def test_prepare_metadata_cli_clears_value(self, temp_git_repo):
        from rsconnect.main import prepare_deploy_metadata

        # Empty value should clear the key
        result = prepare_deploy_metadata(temp_git_repo, ("source_repo=",), False, "2025.11.0")
        assert result is not None
        assert "source_repo" not in result  # Cleared by empty value
        assert "source" in result  # Still detected
        assert "source_commit" in result  # Still detected


class TestIntegration:
    """Integration tests for the full workflow."""

    def test_app_upload_signature_accepts_metadata(self):
        """Test that app_upload accepts metadata parameter."""
        from inspect import signature

        from rsconnect.api import RSConnectClient

        # Check that app_upload has metadata parameter
        sig = signature(RSConnectClient.app_upload)
        assert "metadata" in sig.parameters
