#!/usr/bin/env python
"""
Environment data class abstraction that is usable as an executable module

```bash
python -m rsconnect.subprocesses.inspect_environment
```
"""
from __future__ import annotations

import argparse
import datetime
import json
import locale
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from typing import Callable, Optional

version_re = re.compile(r"\d+\.\d+(\.\d+)?")
exec_dir = os.path.dirname(sys.executable)


@dataclass(frozen=True)
class EnvironmentData:
    contents: str
    filename: str
    locale: str
    package_manager: str
    pip: str
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
    pip: str,
    python: str,
    source: str,
    python_requires: Optional[str] = None,
    error: Optional[str] = None,
    **kwargs: object,  # provides compatibility where we no longer support some older properties
) -> EnvironmentData:
    return EnvironmentData(contents, filename, locale, package_manager, pip, python, source, python_requires, error)


class EnvironmentException(Exception):
    pass


def detect_environment(dirname: str, requirements_file: Optional[str] = "requirements.txt") -> EnvironmentData:
    """Determine the python dependencies in the environment.

    `pip freeze` will be used to introspect the environment.

    :param: dirname Directory name
    :param: requirements_file The requirements file to read. If None, generate using pip freeze.
    :return: a dictionary containing the package spec filename and contents if successful,
    or a dictionary containing `error` on failure.
    """

    if requirements_file is None:
        result = pip_freeze()
    else:
        result = output_file(dirname, requirements_file, "pip") or pip_freeze()

    if result is not None:
        result["python"] = get_python_version()
        result["pip"] = get_version("pip")
        result["locale"] = get_default_locale()

    return MakeEnvironmentData(**result)


def get_python_version() -> str:
    v = sys.version_info
    return "%d.%d.%d" % (v[0], v[1], v[2])


def get_default_locale(locale_source: Callable[..., tuple[str | None, str | None]] = locale.getlocale):
    result = ".".join([item or "" for item in locale_source()])
    return "" if result == "." else result


def get_version(module: str):
    try:
        args = [sys.executable, "-m", module, "--version"]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        stdout, _stderr = proc.communicate()
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

        with open(path, "r") as f:
            data = f.read()

        data = "\n".join([line for line in data.split("\n") if "rsconnect" not in line])

        return {
            "filename": filename,
            "contents": data,
            "source": "file",
            "package_manager": package_manager,
        }
    except Exception as exception:
        raise EnvironmentException("Error reading %s: %s" % (filename, str(exception)))


def pip_freeze():
    """Inspect the environment using `pip freeze --disable-pip-version-check version`.

    Returns a dictionary containing the filename
    (always 'requirements.txt') and contents if successful,
    or a dictionary containing 'error' on failure.
    """
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
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


def filter_pip_freeze_output(pip_stdout: str):
    # Filter out dependency on `rsconnect` and ignore output lines from pip which start with `[notice]`
    return "\n".join(
        [line for line in pip_stdout.split("\n") if (("rsconnect" not in line) and (line.find("[notice]") != 0))]
    )


def strip_ref(line: str):
    # remove erroneous conda build paths that will break pip install
    return line.split(" @ file:", 1)[0].strip()


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
        parser.add_argument("directory", help="Directory to inspect.")
        args = parser.parse_args()

        requirements_file = args.requirements_file
        if requirements_file.lower() == "none":
            requirements_file = None

        envinfo = detect_environment(args.directory, requirements_file=requirements_file)._asdict()
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
