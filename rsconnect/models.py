"""
Data models
"""

from __future__ import annotations

import fnmatch
import pathlib
import re
import sys
from typing import Callable, Literal, Optional, cast

import click
import semver
from click import ParamType
from click.types import StringParamType

# Even though TypedDict is available in Python 3.8, because it's used with NotRequired,
# they should both come from the same typing module.
# https://peps.python.org/pep-0655/#usage-in-python-3-11
if sys.version_info >= (3, 11):
    from typing import TypedDict
else:
    from typing_extensions import TypedDict

_version_search_pattern = r"(^[=><]{0,2})(.*)"
_content_guid_pattern = r"([^,]*),?(.*)"


class BuildStatus:
    NEEDS_BUILD = "NEEDS_BUILD"  # marked for build
    RUNNING = "RUNNING"  # running now
    ABORTED = "ABORTED"  # cancelled while running
    COMPLETE = "COMPLETE"  # completed successfully
    ERROR = "ERROR"  # completed with an error

    _all = [NEEDS_BUILD, RUNNING, ABORTED, COMPLETE, ERROR]


class AppMode:
    """
    Data class defining an "app mode" as understood by Posit
    Connect
    """

    def __init__(
        self,
        ordinal: int,
        name: AppModes.Modes,
        text: str,
        ext: Optional[str] = None,
    ):
        self._ordinal = ordinal
        self._name: AppModes.Modes = name
        self._text = text
        self._ext = ext

    def ordinal(self):
        return self._ordinal

    def name(self) -> AppModes.Modes:
        return self._name

    def desc(self):
        return self._text

    def extension(self):
        return self._ext

    def __str__(self):
        return self.name()

    def __repr__(self):
        return self.desc()


class AppModes:
    """
    Enumeration-like collection of known `AppMode`s with lookup
    functions
    """

    UNKNOWN = AppMode(0, "unknown", "<unknown>")
    SHINY = AppMode(1, "shiny", "Shiny App", ".R")
    RMD = AppMode(3, "rmd-static", "R Markdown", ".Rmd")
    SHINY_RMD = AppMode(2, "rmd-shiny", "Shiny App (Rmd)")
    STATIC = AppMode(4, "static", "Static HTML", ".html")
    PLUMBER = AppMode(5, "api", "API")
    TENSORFLOW = AppMode(6, "tensorflow-saved-model", "TensorFlow Model")
    JUPYTER_NOTEBOOK = AppMode(7, "jupyter-static", "Jupyter Notebook", ".ipynb")
    PYTHON_API = AppMode(8, "python-api", "Python API")
    DASH_APP = AppMode(9, "python-dash", "Dash Application")
    STREAMLIT_APP = AppMode(10, "python-streamlit", "Streamlit Application")
    BOKEH_APP = AppMode(11, "python-bokeh", "Bokeh Application")
    PYTHON_FASTAPI = AppMode(12, "python-fastapi", "Python FastAPI")
    SHINY_QUARTO = AppMode(13, "quarto-shiny", "Shiny Quarto Document")
    STATIC_QUARTO = AppMode(14, "quarto-static", "Quarto Document", ".qmd")
    PYTHON_SHINY = AppMode(15, "python-shiny", "Python Shiny Application")
    JUPYTER_VOILA = AppMode(16, "jupyter-voila", "Jupyter Voila Application")
    PYTHON_GRADIO = AppMode(17, "python-gradio", "Gradio Application")

    _modes = [
        UNKNOWN,
        SHINY,
        RMD,
        SHINY_RMD,
        STATIC,
        PLUMBER,
        TENSORFLOW,
        JUPYTER_NOTEBOOK,
        PYTHON_API,
        DASH_APP,
        STREAMLIT_APP,
        BOKEH_APP,
        PYTHON_FASTAPI,
        SHINY_QUARTO,
        STATIC_QUARTO,
        PYTHON_SHINY,
        JUPYTER_VOILA,
        PYTHON_GRADIO,
    ]

    Modes = Literal[
        "unknown",
        "shiny",
        "rmd-static",
        "rmd-shiny",
        "static",
        "api",
        "tensorflow-saved-model",
        "jupyter-static",
        "python-api",
        "python-dash",
        "python-streamlit",
        "python-bokeh",
        "python-fastapi",
        "quarto-shiny",
        "quarto-static",
        "python-shiny",
        "jupyter-voila",
        "python-gradio",
    ]

    _cloud_to_connect_modes = {
        "shiny": SHINY,
        "rmarkdown_static": RMD,
        "rmarkdown": SHINY_RMD,
        "plumber": PLUMBER,
        "flask": PYTHON_API,
        "dash": DASH_APP,
        "streamlit": STREAMLIT_APP,
        "fastapi": PYTHON_FASTAPI,
        "bokeh": BOKEH_APP,
    }

    @classmethod
    def get_by_ordinal(cls, ordinal: int, return_unknown: bool = False) -> AppMode:
        """Get an AppMode by its associated ordinal (integer)"""
        return cls._find_by(
            lambda mode: mode.ordinal() == ordinal,
            "with ordinal %s" % ordinal,
            return_unknown,
        )

    @classmethod
    def get_by_name(cls, name: str, return_unknown: bool = False) -> AppMode:
        """Get an AppMode by name"""
        return cls._find_by(lambda mode: mode.name() == name, "named %s" % name, return_unknown)

    @classmethod
    def get_by_extension(cls, extension: Optional[str], return_unknown: bool = False) -> AppMode:
        """Get an app mode by its associated extension"""
        # We can't allow a lookup by None since some modes have that for an extension.
        if extension is None:
            if return_unknown:
                return cls.UNKNOWN
            raise ValueError("No app mode with extension %s" % extension)

        return cls._find_by(
            lambda mode: mode.extension() == extension,
            "with extension: %s" % extension,
            return_unknown,
        )

    @classmethod
    def get_by_cloud_name(cls, name: str) -> AppMode:
        return cls._cloud_to_connect_modes.get(name, cls.UNKNOWN)

    @classmethod
    def _find_by(cls, predicate: Callable[[AppMode], bool], message: str, return_unknown: bool) -> AppMode:
        for mode in cls._modes:
            if predicate(mode):
                return mode
        if return_unknown:
            return cls.UNKNOWN
        raise ValueError("No app mode %s" % message)


class GlobMatcher(object):
    """
    A simplified means of matching a path against a glob pattern.  The key
    limitation is that we support at most one occurrence of the `**` pattern.
    """

    def __init__(self, pattern: str):
        pattern = pathlib.PurePath(pattern).as_posix()
        if pattern.endswith("/**/*"):
            # Note: the index used here makes sure the pattern has a trailing
            # slash.  We want that.
            self._pattern = pattern[:-4]
            self.matches = self._match_with_starts_with
        else:
            self._pattern_parts: list[str | re.Pattern[str]]
            self._wildcard_index: int | None
            self._pattern_parts, self._wildcard_index = self._to_parts_list(pattern)
            self.matches = self._match_with_list_parts

    @staticmethod
    def _to_parts_list(pattern: str) -> tuple[list[str | re.Pattern[str]], int | None]:
        """
        Converts a glob expression into a list, with an entry for each directory
        level.  Each entry will be either a string, in which case an equality
        check for that directory entry, or a regular expression, in which case
        matching will be used.  The string, '**', is special but we don't alter
        it here.  We do return its index.

        :param pattern: the glob pattern to pull apart.
        :return: a list of pattern pieces and the index of the special '**' pattern.
        The index will be None if `**` is never found.
        """
        # Incoming pattern is ALWAYS a Posix-style path.
        parts_start = pattern.split("/")
        parts_result: list[str | re.Pattern[str]] = []
        depth_wildcard_index = None
        for index, name in enumerate(parts_start):
            value = name
            if name == "**":
                if depth_wildcard_index is not None:
                    raise ValueError('Only one occurrence of the "**" pattern is allowed.')
                depth_wildcard_index = index
            elif any(ch in name for ch in "*?["):
                value = re.compile(r"\A" + fnmatch.translate(name))
            parts_result.append(value)

        return parts_result, depth_wildcard_index

    def _match_with_starts_with(self, path: str | pathlib.PurePath):
        path = pathlib.PurePath(path).as_posix()
        return path.startswith(self._pattern)

    def _match_with_list_parts(self, path: str | pathlib.PurePath):
        path = pathlib.PurePath(path).as_posix()
        parts = path.split("/")

        def items_match(i1: int, i2: int):
            if i2 >= len(parts):
                return False
            part1 = self._pattern_parts[i1]
            if isinstance(part1, str):
                return self._pattern_parts[i1] == parts[i2]
            return part1.match(parts[i2]) is not None

        wildcard_index = len(self._pattern_parts) if self._wildcard_index is None else self._wildcard_index

        # Top-down...
        for index in range(wildcard_index):
            if not items_match(index, index):
                return False

        if self._wildcard_index is None:
            return len(self._pattern_parts) == len(parts)

        # Now, bottom-up...
        pattern_index = len(self._pattern_parts) - 1
        part_index = len(parts) - 1

        while pattern_index > wildcard_index and part_index >= 0:
            if not items_match(pattern_index, part_index):
                return False
            pattern_index = pattern_index - 1
            part_index = part_index - 1

        return pattern_index == wildcard_index


class GlobSet(object):
    """
    Matches against a set of `GlobMatcher` patterns
    """

    def __init__(self, patterns: list[str]):
        self._matchers = [GlobMatcher(pattern) for pattern in patterns]

    def matches(self, path: str):
        """
        Determines whether the given path is matched by any of our glob
        expressions.

        :param path: the path to test.
        :return: True, if the given path matches any of our glob patterns.
        """
        return any(matcher.matches(path) for matcher in self._matchers)


# Strip quotes from string arguments that might be passed in by jq
#  without the -r flag
class StrippedStringParamType(StringParamType):
    name = "StrippedString"

    def convert(self, value: str, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> str:
        value = super(StrippedStringParamType, self).convert(value, param, ctx)
        return value.strip("\"'")


class ContentGuidWithBundle(object):
    def __init__(self, guid: str, bundle_id: Optional[str] = None):
        self.guid = guid
        self.bundle_id = bundle_id

    def __repr__(self):
        if self.bundle_id:
            return "%s,%s" % (self.guid, self.bundle_id)
        return self.guid


class ContentGuidWithBundleParamType(StrippedStringParamType):
    name = "ContentGuidWithBundle"

    def convert(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        value: str | ContentGuidWithBundle,
        param: Optional[click.Parameter],
        ctx: Optional[click.Context],
    ):
        if isinstance(value, ContentGuidWithBundle):
            return value
        if isinstance(value, str):
            value = super(ContentGuidWithBundleParamType, self).convert(value, param, ctx)
            m = re.match(_content_guid_pattern, value)
            if m is not None:
                guid_with_bundle = ContentGuidWithBundle(m.group(1))
                if len(m.groups()) == 2 and len(m.group(2)) > 0:
                    try:
                        int(m.group(2))
                    except ValueError:
                        self.fail("Failed to parse bundle_id. Expected Int, but found: %s" % m.group(2))
                    guid_with_bundle.bundle_id = m.group(2)
                return guid_with_bundle
        self.fail("Failed to parse content guid arg %s" % value)


AppRole = Literal["owner", "editor", "viewer", "none"]


# Also known as AppRecord in Connect.
class ContentItemV0(TypedDict):
    id: int
    guid: str
    access_type: Literal["all", "logged_in", "acl"]
    connection_timeout: int | None
    read_timeout: int | None
    init_timeout: int | None
    idle_timeout: int | None
    max_processes: int | None
    min_processes: int | None
    max_conns_per_process: int | None
    load_factor: float | None
    memory_request: float | None
    memory_limit: int | None
    cpu_request: float | None
    cpu_limit: int | None
    amd_gpu_limit: int | None
    nvidia_gpu_limit: int | None
    url: str
    vanity_url: bool
    name: str
    title: str | None
    bundle_id: int | None
    app_mode: int
    content_category: str
    has_parameters: bool
    created_time: str
    last_deployed_time: str
    build_status: int
    cluster_name: str | None
    image_name: str | None
    default_image_name: str | None
    service_account_name: str | None
    r_version: str | None
    py_version: str | None
    quarto_version: str | None
    r_environment_management: bool | None
    default_r_environment_management: bool | None
    py_environment_management: bool | None
    default_py_environment_management: bool | None
    run_as: str | None
    run_as_current_user: bool
    description: str
    EnvironmentJson: str | None
    app_role: AppRole
    owner_first_name: str
    owner_last_name: str
    owner_username: str
    owner_guid: str
    owner_email: str
    owner_locked: bool
    is_scheduled: bool
    # Not sure how the following 4 fields are structured, so just use object for now.
    git: object | None
    users: object | None
    groups: object | None
    vanities: object | None


# Also known as V1 ContentOutputDTO in Connect (note: this is not V1 experimental).
class ContentItemV1(TypedDict):
    guid: str
    name: str
    title: str | None
    description: str
    access_type: Literal["all", "logged_in", "acl"]
    connection_timeout: int | None
    read_timeout: int | None
    init_timeout: int | None
    idle_timeout: int | None
    max_processes: int | None
    min_processes: int | None
    max_conns_per_process: int | None
    load_factor: float | None
    memory_request: float | None
    memory_limit: int | None
    cpu_request: float | None
    cpu_limit: float | None
    amd_gpu_limit: int | None
    nvidia_gpu_limit: int | None
    service_account_name: str | None
    default_image_name: str | None
    created_time: str
    last_deployed_time: str
    bundle_id: str | None
    app_mode: AppModes.Modes
    content_category: str
    parameterized: bool
    cluster_name: str | None
    image_name: str | None
    r_version: str | None
    py_version: str | None
    quarto_version: str | None
    r_environment_management: bool | None
    default_r_environment_management: bool | None
    py_environment_management: bool | None
    default_py_environment_management: bool | None
    run_as: str | None
    run_as_current_user: bool
    owner_guid: str
    content_url: str
    dashboard_url: str
    app_role: AppRole
    id: str


VersionProgramName = Literal["r_version", "py_version", "quarto_version"]
ComparisonOperator = Literal[">", "<", ">=", "<=", "=", "=="]


class VersionSearchFilter(object):
    def __init__(
        self,
        name: VersionProgramName,
        comp: ComparisonOperator,
        vers: str,
    ):
        self.name = name
        self.comp = comp
        self.vers = vers

    def __repr__(self):
        return "%s %s %s" % (self.name, self.comp, self.vers)


class VersionSearchFilterParamType(ParamType):
    name = "VersionSearchFilter"

    def __init__(self, key: VersionProgramName):
        """
        :param key: key refers to the left side of the version comparison.
        In this case any interpreter in a content result, one of [py_version, r_version, quarto_version]
        """
        self.key: VersionProgramName = key

    def convert(
        self,
        value: str | VersionSearchFilter,
        param: Optional[click.Parameter],
        ctx: Optional[click.Context],
    ):
        if isinstance(value, VersionSearchFilter):
            return value

        if isinstance(value, str):
            m = re.match(_version_search_pattern, value)
            if m is not None and len(m.groups()) == 2:
                version_search = VersionSearchFilter(
                    name=self.key,
                    comp=cast(ComparisonOperator, m.group(1)),
                    vers=m.group(2),
                )

                # default to == if no comparator was provided
                if not version_search.comp:
                    version_search.comp = "=="

                if version_search.comp not in [">", "<", ">=", "<=", "=", "=="]:
                    self.fail("Failed to parse verison filter: %s is not a valid comparitor" % version_search.comp)

                try:
                    semver.parse(version_search.vers)  # pyright: ignore[reportUnknownMemberType]
                except ValueError:
                    self.fail("Failed to parse version info: %s" % version_search.vers)
                return version_search

        self.fail("Failed to parse version filter %s" % value)


class AppSearchResults(TypedDict):
    total: int
    applications: list[ContentItemV0]
    count: int
    continuation: int


class TaskStatusResult(TypedDict):
    type: str
    data: object  # Don't know the structure of this type yet


class TaskStatusV0(TypedDict):
    id: str
    status: list[str]
    finished: bool
    code: int
    error: str
    last_status: int
    user_id: int
    result: TaskStatusResult | None


# https://docs.posit.co/connect/api/#get-/v1/tasks/-id-
class TaskStatusV1(TypedDict):
    id: str
    output: list[str]
    finished: bool
    code: int
    error: str
    last: int
    result: TaskStatusResult | None

    # redundant fields for compatibility with rsconnect-python.
    last_status: int
    status: list[str]


class BootstrapOutputDTO(TypedDict):
    api_key: str


# This not the complete specification of the server settings data structure, but it is
# sufficient for the purposes of this package.
class ServerSettings(TypedDict):
    hostname: str
    version: str


class PyInfo(TypedDict):
    installations: list[PyInstallation]
    api_enabled: bool


class PyInstallation(TypedDict):
    version: str
    cluster_name: str
    image_name: str


class BuildOutputDTO(TypedDict):
    task_id: str


class ListEntryOutputDTO(TypedDict):
    language: str
    version: str
    image_name: str


class DeleteInputDTO(TypedDict):
    language: str
    version: str
    image_name: str
    dry_run: bool


class DeleteOutputDTO(TypedDict):
    language: str
    version: str
    iamge_name: str
    task_id: str | None


class ConfigureResult(TypedDict):
    config_url: str
    logs_url: str


class UserRecord(TypedDict):
    email: str
    username: str
    first_name: str
    last_name: str
    password: str
    created_time: str
    updated_time: str
    active_time: str | None
    confirmed: bool
    locked: bool
    guid: str
    preferences: dict[str, object]
