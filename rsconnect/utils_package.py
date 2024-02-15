"""
Utility functions related to packages and versions.
"""

from __future__ import annotations

import re
from typing import Literal, NamedTuple, cast

import semver

ComparisonOperator = Literal[">=", "<=", ">", "<", "==", "!="]


class VersionInfo(NamedTuple):
    operator: ComparisonOperator
    version: str


class PackageInfo(NamedTuple):
    name: str
    specs: list[VersionInfo]


def compare_semvers(version1: str, version2: str) -> Literal[-1, 0, 1]:
    """
    This is a wrapper for semver.VersionInfo.compare(), but it can handle some version
    strings that are not valid semver strings. Specifically, it can handle strings like
    "2024.01.0", which have a leading '0' in a version part. The leading zero in "01"
    makes it an invalid semver string.

    Note that semvers always have three parts, so "0.12" is not a valid semver. This
    function can be safely used for comparing Connect version numbers, but not for
    comparing Python package numbers, because they may not have exactly three parts.

    This function is better for comparing Connect version numbers than
    compare_package_versions(), because the latter doesn't handle the prerelease and
    build components of the version string. For "2024.01.0-dev+20-abcd", the prerelease
    and build components are "dev" and "20-abcd", respectively.

    :return: -1 if version1 < version2, 0 if version1 == version2, or 1 if version1 >
        version2.
    """

    version1 = _remove_leading_zeros(version1)
    version2 = _remove_leading_zeros(version2)

    return semver.VersionInfo.parse(version1).compare(version2)  # type: ignore


def _remove_leading_zeros(version: str) -> str:
    """
    Given a version string like "2024.01.0-dev+20-abcd", remove any leading zeros in a
    version part, so that the result is "2024.1.0-dev+20-abcd".
    """
    parts = version.split(".")
    parts = [re.sub(r"^0+(\d)", "\\1", x) for x in parts]
    return ".".join(parts)


def compare_package_versions(version1: str, version2: str) -> Literal[-1, 0, 1]:
    """
    Compare two package versions. This function is similar to compare_semvers(), but it
    can accept version numbers with any number of parts (instead of exactly three). It
    is used to compare package versions, which may not be valid semver strings.
    """
    parts1 = [int(x) for x in version1.split(".")]
    parts2 = [int(x) for x in version2.split(".")]

    max_length = max(len(parts1), len(parts2))
    parts1 += [0] * (max_length - len(parts1))
    parts2 += [0] * (max_length - len(parts2))

    for part1, part2 in zip(parts1, parts2):
        if part1 > part2:
            return 1
        elif part1 < part2:
            return -1

    return 0


def parse_requirements_txt(requirements_txt: str) -> list[PackageInfo]:
    """
    Given a string of requirements (like the contents of a requirements.txt file), find
    the version of the package that is installed. This is done by finding the line that
    starts with the package name, and then extracting the version from that line.

    :param requirements_txt: The contents of a requirements.txt file.
    :param package: The name of the package to find.

    :return: A list of PackageInfo objects.
    """
    # Note that this parser is not perfect. If we want to perfectly parse a
    # requirements.txt file, we could use the requirements-parser package, but that
    # would introduce another dependency.

    package_info: list[PackageInfo] = []

    for line in requirements_txt.split("\n"):
        # Skip blank lines or comment lines
        if re.match(r"^\s*$", line) or re.match(r"^\s*#", line):
            continue

        pkg_match = re.match(r"^([A-Z0-9][A-Z0-9][A-Z0-9._-]*[A-Z0-9])(.*)", line, flags=re.IGNORECASE)
        if pkg_match is None:
            continue

        # If the line is "foo>=1.0", this is "foo".
        pkg_name = cast(str, pkg_match.group(1))

        # If the line is "foo>=1.0", this is ">=1.0".
        pkg_version_string = cast(str, pkg_match.group(2)).strip()
        # Remove comment from version string, if present.
        pkg_version_string = re.sub(r"#.*$", "", pkg_version_string).strip()
        pkg_version_specs = _parse_version_specs(pkg_version_string)

        package_info.append(PackageInfo(name=pkg_name, specs=pkg_version_specs))

    return package_info


def _parse_version_specs(version_specs: str) -> list[VersionInfo]:
    """
    Parse a version spec string like ">=1.0,<=2.0" into a list of tuples like [(">=",
    "1.0"), ("<=", "2.0")]. If there is a semicolon, as in "==1.0;
    python_version<'3.8'", then the semicolon and everything after it is ignored.
    If it finds a spec string that it is unable to parse, it will ignore that string.
    """

    version_specs = version_specs.split(";")[0].strip()
    if version_specs.strip() == "":
        return []
    version_spec_strings = [x.strip() for x in version_specs.split(",")]

    version_infos: list[VersionInfo] = []
    for version_spec_string in version_spec_strings:
        spec = _parse_version_spec(version_spec_string)
        if spec is not None:
            version_infos.append(spec)

    return version_infos


def _parse_version_spec(version_spec: str) -> VersionInfo | None:
    """
    Parse a version spec string like ">=1.0" into a tuple like (">=", "1.0"). If it is
    unable to parse the string, return None.
    """
    for op in (">=", "<=", ">", "<", "==", "!="):
        if version_spec.startswith(op):
            return VersionInfo(op, version_spec[len(op) :].strip())
    return None


def find_package_info(package: str, requirements: list[PackageInfo]) -> PackageInfo | None:
    """
    Given a package name and a list of PackageInfo objects, find the PackageInfo object
    that corresponds to the package name. If the package is not found, return None.
    """
    for pkg_info in requirements:
        if pkg_info.name == package:
            return pkg_info
    return None


def replace_requirement(package_name: str, replacement: str, requirements_txt: str) -> str:
    """
    Given a requirements.txt file and a package name, replace the line of
    requirements.txt for that package, with the replacement string, and return the
    modified requirements.txt.

    Note that package_name is a regular expression, so if the target package name
    contains a ".", it should be escaped, as in "foo\\.bar".
    """
    lines = requirements_txt.split("\n")
    new_lines: list[str] = []

    for line in lines:
        new_line = re.sub(f"^{package_name}([^a-zA-Z0-9._-].*?)?$", replacement, line)
        new_lines.append(new_line)

    return "\n".join(new_lines)
