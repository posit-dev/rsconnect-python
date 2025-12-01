"""
Git metadata detection utilities for bundle uploads
"""

from __future__ import annotations

import os
import subprocess
from os.path import abspath, dirname, exists, join
from typing import Optional
from urllib.parse import urlparse

from .log import logger


def _run_git_command(args: list[str], cwd: str) -> Optional[str]:
    """
    Run a git command and return its output.

    :param args: git command arguments
    :param cwd: working directory
    :return: command output or None if command failed
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def is_git_repo(directory: str) -> bool:
    """
    Check if directory is inside a git repository.

    :param directory: directory to check
    :return: True if inside a git repo, False otherwise
    """
    result = _run_git_command(["rev-parse", "--git-dir"], directory)
    return result is not None


def has_uncommitted_changes(directory: str) -> bool:
    """
    Check if the git repository has uncommitted changes.

    :param directory: directory to check
    :return: True if there are uncommitted changes
    """
    # Check for staged and unstaged changes
    result = _run_git_command(["status", "--porcelain"], directory)
    return bool(result)


def get_git_commit(directory: str) -> Optional[str]:
    """
    Get the current git commit SHA.

    :param directory: directory to check
    :return: commit SHA or None
    """
    return _run_git_command(["rev-parse", "HEAD"], directory)


def get_git_branch(directory: str) -> Optional[str]:
    """
    Get the current git branch name or tag.

    :param directory: directory to check
    :return: branch/tag name or None
    """
    # First try to get branch name
    branch = _run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], directory)

    # If we're in detached HEAD state, try to get tag
    if branch == "HEAD":
        tag = _run_git_command(["describe", "--exact-match", "--tags"], directory)
        if tag:
            return tag

    return branch


def get_git_remote_url(directory: str, remote: str = "origin") -> Optional[str]:
    """
    Get the URL of a git remote.

    :param directory: directory to check
    :param remote: remote name (default: "origin")
    :return: remote URL or None
    """
    return _run_git_command(["remote", "get-url", remote], directory)


def normalize_git_url_to_https(url: Optional[str]) -> Optional[str]:
    """
    Normalize a git URL to HTTPS format.

    Converts SSH URLs like git@github.com:user/repo.git to
    https://github.com/user/repo.git

    :param url: git URL to normalize
    :return: normalized HTTPS URL or original if already HTTPS/not recognized
    """
    if not url:
        return url

    # Already HTTPS
    if url.startswith("https://"):
        return url

    # Handle git@ SSH format
    if url.startswith("git@"):
        # git@github.com:user/repo.git -> https://github.com/user/repo.git
        # Remove git@ prefix
        url = url[4:]
        # Replace first : with /
        url = url.replace(":", "/", 1)
        # Add https://
        return f"https://{url}"

    # Handle ssh:// format
    if url.startswith("ssh://"):
        # ssh://git@github.com/user/repo.git -> https://github.com/user/repo.git
        parsed = urlparse(url)
        if parsed.hostname:
            path = parsed.path
            return f"https://{parsed.hostname}{path}"

    # Return as-is if we can't normalize
    return url


def detect_git_metadata(directory: str, remote: str = "origin") -> dict[str, str]:
    """
    Detect git metadata for the given directory.

    :param directory: directory to inspect
    :param remote: git remote name to use (default: "origin")
    :return: dictionary with source, source_repo, source_branch, source_commit keys
    """
    metadata: dict[str, str] = {}

    if not is_git_repo(directory):
        logger.debug(f"Directory {directory} is not a git repository")
        return metadata

    # Get commit SHA
    commit = get_git_commit(directory)
    if commit:
        # Check for uncommitted changes
        if has_uncommitted_changes(directory):
            commit = f"{commit}-dirty"
        metadata["source_commit"] = commit

    # Get branch/tag
    branch = get_git_branch(directory)
    if branch:
        metadata["source_branch"] = branch

    # Get remote URL and normalize to HTTPS
    remote_url = get_git_remote_url(directory, remote)
    if remote_url:
        normalized_url = normalize_git_url_to_https(remote_url)
        if normalized_url:
            metadata["source_repo"] = normalized_url

    # Always set source to "git" if we got any metadata
    if metadata:
        metadata["source"] = "git"
        logger.debug(f"Detected git metadata: {metadata}")

    return metadata
