#!/usr/bin/env python
"""
Environment data class abstraction that is usable as an executable script

```bash
python -I path/to/inspect_environment.py --python /path/to/python --requirements-file none DIRECTORY
```
"""

from __future__ import annotations

import argparse
import datetime
import json
import locale
import ntpath
import os
import posixpath
import tempfile
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, List, Optional, cast
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import url2pathname

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

version_re = re.compile(r"\d+\.\d+(\.\d+)?")
module_cwd = os.path.dirname(os.path.abspath(__file__))
rsconnect_project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
excluded_distributions = {"rsconnect", "rsconnect-python"}


@dataclass(frozen=True)
class EnvironmentData:
    contents: str
    filename: str
    locale: str
    package_manager: str
    pip: Optional[str]
    python: str
    source: str
    python_requires: Optional[str]
    error: Optional[str]

    def _asdict(self):
        return asdict(self)

    def _replace(self, **kwargs: object):
        return replace(self, **kwargs)


def MakeEnvironmentData(
    contents: str,
    filename: str,
    locale: str,
    package_manager: str,
    pip: Optional[str],
    python: str,
    source: str,
    python_requires: Optional[str] = None,
    error: Optional[str] = None,
    **kwargs: object,  # provides compatibility where we no longer support some older properties
) -> EnvironmentData:
    return EnvironmentData(contents, filename, locale, package_manager, pip, python, source, python_requires, error)


class EnvironmentException(Exception):
    pass


def detect_environment(
    dirname: str,
    requirements_file: Optional[str] = "requirements.txt",
    uv_path: str = "uv",
    python: str = sys.executable,
) -> EnvironmentData:
    """Determine the python dependencies in the environment.

    `pip freeze` will be used to introspect the environment.

    :param: dirname Directory name
    :param: requirements_file The requirements file to read. If None, generate using pip freeze.
    :return: a dictionary containing the package spec filename and contents if successful,
    or a dictionary containing `error` on failure.
    """

    python_version = get_python_version(python)
    pip_version = get_version("pip", python)
    result: dict[str, Any]
    if requirements_file is None:
        # --force-generate sets requirements_file to None
        result = pip_freeze(python, uv_path, pip_version, python_version)
    elif os.path.basename(requirements_file) == "uv.lock":
        result = uv_export(dirname, requirements_file, uv_path)
    elif os.path.basename(requirements_file) == "pyproject.toml":
        result = pyproject_dependencies(dirname, requirements_file)
    else:
        file_result = output_file(dirname, requirements_file, "pip")
        if file_result is None:
            raise EnvironmentException(
                "The requirements file '%s' was not found in '%s'. "
                "Please create it or use --force-generate to use pip freeze." % (requirements_file, dirname)
            )
        result = file_result

    if result is not None:
        result["contents"] = normalize_editables(result["contents"] or "", dirname)
        result["python"] = python_version
        result["pip"] = pip_version
        result["locale"] = get_default_locale()

    return MakeEnvironmentData(**result)


def get_python_version(python: str = sys.executable) -> str:
    try:
        return subprocess.check_output(
            [python, "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            cwd=module_cwd,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exception:
        raise EnvironmentException(f"Error getting Python version from {python}: {exception}") from exception


def get_default_locale(locale_source: Callable[..., tuple[str | None, str | None]] = locale.getlocale):
    result = ".".join([item or "" for item in locale_source()])
    return "" if result == "." else result


def get_version(module: str, python: str = sys.executable) -> Optional[str]:
    try:
        args = [python, "-E", "-m", module, "--version"]
        proc = subprocess.Popen(
            args,
            cwd=module_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, _stderr = proc.communicate()
        if proc.returncode and module == "pip":
            return None
        match = version_re.search(stdout)
        if match:
            return match.group()

        msg = "Failed to get version of '%s' from the output of: %s" % (
            module,
            " ".join(args),
        )
        raise EnvironmentException(msg)
    except Exception as exception:
        raise EnvironmentException("Error getting '%s' version: %s" % (module, str(exception)))


def output_file(dirname: str, filename: str, package_manager: str):
    """Read an existing package spec file.

    Returns a dictionary containing the filename and contents
    if successful, None if the file does not exist,
    or a dictionary containing 'error' on failure.
    """
    try:
        path = os.path.join(dirname, filename)
        if not os.path.exists(path):
            return None

        # Keep CRLF line endings. Text mode changes them to LF.
        with open(path, "r", newline="") as f:
            data = f.read()

        data = "\n".join(line for line in data.split("\n") if not is_rsconnect_requirement(line))

        return {
            "filename": filename,
            "contents": data,
            "source": "file",
            "package_manager": package_manager,
        }
    except Exception as exception:
        raise EnvironmentException("Error reading %s: %s" % (filename, str(exception)))


def pip_freeze(python: str, uv_path: str, pip_version: Optional[str], python_version: str):
    """Inspect the environment using `pip freeze`.

    Returns a dictionary containing the filename
    (always 'requirements.txt') and contents if successful,
    or a dictionary containing 'error' on failure.
    """
    try:
        # Older pip suppresses these bootstrap packages; current pip suppresses
        # only pip itself on Python 3.12 and later.
        bootstrap_packages = {"pip"}
        if pip_version is not None or Version(python_version) < Version("3.12"):
            bootstrap_packages.update({"setuptools", "wheel", "distribute"})
        command = (
            [
                python,
                "-E",
                "-m",
                "pip",
                "freeze",
                "--disable-pip-version-check",
                *(arg for name in sorted(excluded_distributions) for arg in ("--exclude", name)),
            ]
            if pip_version and Version(pip_version) >= Version("20.3")
            else [
                uv_path,
                "pip",
                "freeze",
                "--no-cache",
                "--python",
                python,
                *(arg for name in sorted(bootstrap_packages) for arg in ("--exclude", name)),
            ]
        )
        proc = subprocess.Popen(
            command,
            cwd=module_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        pip_stdout, pip_stderr = proc.communicate()
        pip_status = proc.returncode
    except Exception as exception:
        raise EnvironmentException("Error during pip freeze: %s" % str(exception))

    if pip_status != 0:
        msg = pip_stderr or ("exited with code %d" % pip_status)
        raise EnvironmentException("Error during pip freeze: %s" % msg)

    pip_stdout = filter_pip_freeze_output(pip_stdout)

    pip_stdout = (
        "# requirements.txt generated by rsconnect-python on "
        + str(datetime.datetime.now(datetime.timezone.utc))
        + "\n"
        + pip_stdout
    )

    return {
        "filename": "requirements.txt",
        "contents": pip_stdout,
        "source": "pip_freeze",
        "package_manager": "pip",
    }


def uv_export(dirname: str, lock_filename: str, uv_path: str = "uv"):
    """
    Export requirements from a uv.lock file using `uv export`.
    """
    lock_path = lock_filename
    if not os.path.isabs(lock_filename):
        lock_path = os.path.join(dirname, lock_filename)
    lock_path = os.path.abspath(lock_path)

    if not os.path.exists(lock_path):
        raise EnvironmentException("uv.lock not found: %s" % lock_filename)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "requirements.txt.lock")
        try:
            result = subprocess.run(
                [
                    uv_path,
                    "export",
                    "--format",
                    "requirements-txt",
                    "--frozen",
                    "--no-hashes",
                    "--no-annotate",
                    "--offline",
                    "--no-header",
                    "--no-emit-project",
                    "--no-dev",
                    "--no-default-groups",
                    "--output-file",
                    output_path,
                ],
                cwd=os.path.dirname(lock_path),
                stdout=sys.stderr,
                stderr=sys.stderr,
                check=False,
            )
        except Exception as exception:
            raise EnvironmentException("Error during uv export: %s" % str(exception))

        if result.returncode != 0:
            raise EnvironmentException("Error during uv export: exited with code %d" % result.returncode)

        with open(output_path, mode="r", encoding="utf-8") as output_file:
            exported = output_file.read()

    requirements = filter_pip_freeze_output(exported)
    requirements = (
        "# requirements.txt.lock generated from uv.lock by rsconnect-python on "
        + str(datetime.datetime.now(datetime.timezone.utc))
        + "\n"
        + requirements
    )

    return {
        "filename": "requirements.txt.lock",
        "contents": requirements,
        "source": "uv_lock",
        "package_manager": "uv",
        "pip": None,
    }


def pyproject_dependencies(dirname: str, pyproject_filename: str):
    """Read project.dependencies from a pyproject.toml file as a requirements spec.

    Emits a requirements.txt file listing the top-level dependencies declared
    in ``[project].dependencies``. Unlike ``uv.lock``, the result is not a
    fully resolved lock and Connect will perform dependency resolution at
    deploy time.
    """
    pyproject_path = pyproject_filename
    if not os.path.isabs(pyproject_filename):
        pyproject_path = os.path.join(dirname, pyproject_filename)

    if not os.path.exists(pyproject_path):
        raise EnvironmentException(f"pyproject.toml not found: {pyproject_filename}")

    try:
        try:
            import tomllib
        except ImportError:
            import toml as tomllib  # type: ignore[no-redef]
        with open(pyproject_path, "r", encoding="utf-8-sig") as f:
            project_data = tomllib.loads(f.read()).get("project", {})
    except Exception as exception:
        raise EnvironmentException(f"Error reading {pyproject_filename}: {exception}")

    project = project_data or {}
    dependencies: list[object] = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(isinstance(dep, str) for dep in dependencies):
        raise EnvironmentException(f"Invalid project.dependencies in {pyproject_filename}: expected a list of strings.")

    requirements = filter_pip_freeze_output("\n".join(cast(List[str], dependencies)))
    if requirements and not requirements.endswith("\n"):
        requirements += "\n"
    requirements = (
        f"# requirements.txt generated from pyproject.toml by rsconnect-python on "
        f"{datetime.datetime.now(datetime.timezone.utc)}\n"
        f"{requirements}"
    )

    return {
        "filename": "requirements.txt",
        "contents": requirements,
        "source": "pyproject_toml",
        "package_manager": "pip",
    }


def filter_pip_freeze_output(pip_stdout: str):
    return "\n".join(
        line
        for line in pip_stdout.split("\n")
        if not is_rsconnect_requirement(line)
        and not line.startswith("[notice]")
        and not line.startswith("# Editable install with no version control (")
    )


def check_editables_are_bundleable(requirements: str, dirname: str):
    unbundleable = [line.strip() for line in requirements.split("\n") if is_unbundleable_editable(line, dirname)]
    if unbundleable:
        raise EnvironmentException(
            "Editable dependencies outside the deployment directory cannot be installed on Connect:\n"
            + "\n".join(unbundleable)
            + "\nProvide a requirements file that installs them from a package index, a VCS URL, "
            "or a relative path inside the deployment directory."
        )


def normalize_editables(requirements: str, dirname: str) -> str:
    check_editables_are_bundleable(requirements, dirname)
    lines = []
    for line in requirements.split("\n"):
        target = editable_target(line)
        if target:
            relative = bundleable_editable_path(target, dirname)
            if relative is not None:
                extras = re.search(r"\[[a-zA-Z0-9_,.\-\s]+\]$", relative)
                suffix = extras.group() if extras else ""
                path = relative[: extras.start()] if extras else relative
                escaped = quote(path, safe="/")
                if escaped != path:
                    relative = f"file:{escaped}{suffix}"
                line_ending = "\r" if line.endswith("\r") else ""
                comment = re.search(r"\s+#.*$", line.rstrip("\r"))
                line = f"-e {relative}{comment.group() if comment else ''}{line_ending}"
        lines.append(line)
    return "\n".join(lines)


def is_rsconnect_requirement(line: str) -> bool:
    target = editable_target(line)
    if target is not None:
        return is_rsconnect_editable(target)
    try:
        requirement = Requirement(line.strip())
    except InvalidRequirement:
        return False
    return canonicalize_name(requirement.name) in excluded_distributions


def editable_target(line: str) -> Optional[str]:
    line = re.split(r"\s+#", line.strip(), maxsplit=1)[0].rstrip()
    if line.startswith("--editable="):
        return line[len("--editable=") :].strip()
    for flag in ("-e", "--editable"):
        if line.startswith(flag) and line[len(flag) : len(flag) + 1].isspace():
            return line[len(flag) :].strip()
    return None


def is_rsconnect_editable(target: str) -> bool:
    url = urlsplit(target)
    # pip freeze names VCS editables with an #egg= fragment; local checkouts are only identifiable by path.
    egg = parse_qs(url.fragment).get("egg")
    if egg:
        return canonicalize_name(egg[0]) in excluded_distributions
    if url.scheme.lower() == "file" and url.netloc in ("", "localhost"):
        target = url2pathname(url.path)
    return is_path(target) and os.path.isdir(target) and os.path.samefile(target, rsconnect_project_dir)


def is_unbundleable_editable(line: str, dirname: str) -> bool:
    target = editable_target(line)
    if not target:
        return False
    if is_path(target) or urlsplit(target).scheme.lower() == "file":
        return bundleable_editable_path(target, dirname) is None
    return urlsplit(target).scheme.lower().endswith("+file")


def bundleable_editable_path(target: str, dirname: str) -> Optional[str]:
    if not is_path(target):
        url = urlsplit(target)
        if url.scheme.lower() != "file" or url.netloc not in ("", "localhost") or url.query or url.fragment:
            return None
        target = url2pathname(url.path)

    extras = re.search(r"\[[a-zA-Z0-9_,.\-\s]+\]$", target)
    suffix = extras.group() if extras else ""
    if extras:
        target = target[: extras.start()]

    # Reject paths in another platform's absolute path syntax.
    if (posixpath.isabs(target) or ntpath.isabs(target)) and not os.path.isabs(target):
        return None
    bundle_dir = os.path.realpath(dirname)
    path = os.path.realpath(os.path.join(bundle_dir, target))
    try:
        if os.path.commonpath([bundle_dir, path]) != bundle_dir:
            return None
    except ValueError:
        return None
    relative = os.path.relpath(path, bundle_dir).replace(os.sep, "/")
    return ("." if relative == "." else f"./{relative}") + suffix


def is_path(target: str) -> bool:
    # PEP 508 URLs use RFC 3986 schemes; a one-letter scheme is a Windows drive, so the target is a path.
    return len(urlsplit(target).scheme) <= 1


def strip_ref(line: str):
    # remove erroneous conda build paths that will break pip install
    # Keep a CRLF line ending. The caller splits on "\n", so the "\r" stays on the line.
    line_ending = "\r" if line.endswith("\r") else ""
    return line.split(" @ file:", 1)[0].strip() + line_ending


def exclude(line: str):
    return line and line.startswith("setuptools") and "post" in line


def main():
    """
    Run `detect_environment` and dump the result as JSON.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Inspect python environment and return dependency metadata.", add_help=True
        )
        parser.add_argument(
            "-r",
            "--requirements-file",
            dest="requirements_file",
            default="requirements.txt",
            help="Requirements file name (relative to the directory). Use 'none' to capture via pip freeze.",
        )
        parser.add_argument("--uv", default="uv", help="Path to the uv executable.")
        parser.add_argument("--python", default=sys.executable, help="Python environment to inspect.")
        parser.add_argument("directory", help="Directory to inspect.")
        args = parser.parse_args()

        requirements_file = args.requirements_file
        if requirements_file.lower() == "none":
            requirements_file = None

        envinfo = detect_environment(args.directory, requirements_file, args.uv, args.python)._asdict()
        if "contents" in envinfo:
            keepers = list(map(strip_ref, envinfo["contents"].split("\n")))
            keepers = [line for line in keepers if not exclude(line)]
            envinfo["contents"] = "\n".join(keepers)

        json.dump(
            envinfo,
            sys.stdout,
            indent=4,
        )
    except EnvironmentException as exception:
        json.dump(dict(error=str(exception)), sys.stdout, indent=4)


if __name__ == "__main__":
    main()
