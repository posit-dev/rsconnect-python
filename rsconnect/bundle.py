"""
Manifest generation and bundling utilities
"""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import typing
from collections import defaultdict
from copy import deepcopy
from mimetypes import guess_type
from os.path import (
    abspath,
    basename,
    dirname,
    exists,
    isdir,
    isfile,
    join,
    relpath,
    splitext,
)
from pathlib import Path
from pprint import pformat
from typing import (
    IO,
    TYPE_CHECKING,
    Callable,
    Iterator,
    Literal,
    Optional,
    Sequence,
    Union,
    cast,
)

# Even though TypedDict is available in Python 3.8, because it's used with NotRequired,
# they should both come from the same typing module.
# https://peps.python.org/pep-0655/#usage-in-python-3-11
if sys.version_info >= (3, 11):
    from typing import NotRequired, TypedDict
else:
    from typing_extensions import NotRequired, TypedDict

import click

from .environment import Environment, MakeEnvironment
from .exception import RSConnectException
from .log import VERBOSE, logger
from .models import AppMode, AppModes, GlobSet

if TYPE_CHECKING:
    from .actions import QuartoInspectResult


_module_pattern = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$")

# From https://github.com/rstudio/rsconnect/blob/485e05a26041ab8183a220da7a506c9d3a41f1ff/R/bundle.R#L85-L88
# noinspection SpellCheckingInspection
directories_ignore_list = [
    ".Rproj.user/",
    ".git/",
    ".svn/",
    "__pycache__/",
    "packrat/",
    "renv/",
    "rsconnect-python/",
    "rsconnect/",
]
directories_to_ignore = {Path(d) for d in directories_ignore_list}

mimetypes.add_type("text/ipynb", ".ipynb")


class ManifestDataFile(TypedDict):
    checksum: str


class ManifestDataMetadata(TypedDict):
    appmode: str
    primary_html: NotRequired[str]
    entrypoint: NotRequired[str]
    primary_rmd: NotRequired[str]
    content_category: NotRequired[str]


class ManifestDataJupyter(TypedDict):
    hide_all_input: NotRequired[bool]
    hide_tagged_input: NotRequired[bool]


class ManifestDataQuarto(TypedDict):
    version: str
    engines: list[str]


class ManifestDataEnvironment(TypedDict):
    image: NotRequired[str]
    environment_management: NotRequired[dict[Literal["python", "r"], bool]]


class ManifestDataPython(TypedDict):
    version: str
    package_manager: ManifestDataPythonPackageManager


class ManifestDataPythonPackageManager(TypedDict):
    name: str
    version: str
    package_file: str


class ManifestData(TypedDict):
    version: int
    files: dict[str, ManifestDataFile]
    locale: NotRequired[str]
    metadata: ManifestDataMetadata
    jupyter: NotRequired[ManifestDataJupyter]
    quarto: NotRequired[ManifestDataQuarto]
    python: NotRequired[ManifestDataPython]
    environment: NotRequired[ManifestDataEnvironment]


class Manifest:
    def __init__(
        self,
        *,
        version: Optional[int] = None,
        environment: Optional[Environment] = None,
        app_mode: Optional[AppMode] = None,
        entrypoint: Optional[str] = None,
        quarto_inspection: Optional[QuartoInspectResult] = None,
        image: Optional[str] = None,
        env_management_py: Optional[bool] = None,
        env_management_r: Optional[bool] = None,
        primary_html: Optional[str] = None,
        metadata: Optional[ManifestDataMetadata] = None,
        files: Optional[dict[str, ManifestDataFile]] = None,
    ) -> None:
        self.data: ManifestData = cast(ManifestData, {})
        self.buffer: dict[str, str] = {}
        self.deploy_dir: str | None = None

        self.data["version"] = version if version else 1
        if environment and environment.locale is not None:
            self.data["locale"] = environment.locale

        if metadata is None:
            self.data["metadata"] = cast(ManifestDataMetadata, {})
            if app_mode is None:
                self.data["metadata"]["appmode"] = AppModes.UNKNOWN.name()
            else:
                self.data["metadata"]["appmode"] = app_mode.name()
        else:
            self.data["metadata"] = metadata

        if primary_html:
            self.data["metadata"]["primary_html"] = primary_html

        if entrypoint:
            self.data["metadata"]["entrypoint"] = entrypoint

        if quarto_inspection:
            self.data["quarto"] = {
                "version": quarto_inspection.get("quarto", {}).get("version", "99.9.9"),
                "engines": quarto_inspection.get("engines", []),
            }

            files_data = quarto_inspection.get("files", {})
            files_input_data = files_data.get("input", [])
            if len(files_input_data) > 1:
                self.data["metadata"]["content_category"] = "site"

        if environment:
            package_manager = environment.package_manager
            self.data["python"] = {
                "version": environment.python,
                "package_manager": {
                    "name": package_manager,
                    "version": getattr(environment, package_manager),
                    "package_file": environment.filename,
                },
            }

        if image or env_management_py is not None or env_management_r is not None:
            self.data["environment"] = {}
            if image:
                self.data["environment"]["image"] = image
            if env_management_py is not None or env_management_r is not None:
                self.data["environment"]["environment_management"] = {}
                if env_management_py is not None:
                    self.data["environment"]["environment_management"]["python"] = env_management_py
                if env_management_r is not None:
                    self.data["environment"]["environment_management"]["r"] = env_management_r

        self.data["files"] = {}
        if files:
            self.data["files"] = files

    @classmethod
    def from_json(cls, json_str: str):
        return cls(**json.loads(json_str))

    @classmethod
    def from_json_file(cls, json_path: str | Path):
        with open(json_path) as json_file:
            return cls(**json.load(json_file))

    @property
    def json(self):
        return json.dumps(self.data, indent=2)

    @property
    def entrypoint(self):
        if "metadata" not in self.data:
            return None
        if "entrypoint" in self.data["metadata"]:
            return self.data["metadata"]["entrypoint"]
        return None

    @entrypoint.setter
    def entrypoint(self, value: str):
        self.data["metadata"]["entrypoint"] = value

    @property
    def primary_html(self):
        if "metadata" not in self.data:
            return None
        if "primary_html" in self.data["metadata"]:
            return self.data["metadata"]["primary_html"]
        return None

    @primary_html.setter
    def primary_html(self, value: str):
        self.data["metadata"]["primary_html"] = value

    def add_file(self, path: str):
        manifestPath = Path(path).as_posix()
        self.data["files"][manifestPath] = {"checksum": file_checksum(path)}
        return self

    def discard_file(self, path: str):
        if path in self.data["files"]:
            del self.data["files"][path]
        return self

    def add_to_buffer(self, key: str, value: str):
        self.buffer[key] = value
        self.data["files"][key] = {"checksum": buffer_checksum(value)}
        return self

    def discard_from_buffer(self, key: str):
        if key in self.buffer:
            del self.buffer[key]
            del self.data["files"][key]
        return self

    def require_entrypoint(self) -> str:
        """
        If self.entrypoint is a string, return it; if it is None, raise an exception.
        """
        if self.entrypoint is None:
            raise RSConnectException("A valid entrypoint must be provided.")
        return self.entrypoint

    def get_manifest_files(self) -> dict[str, ManifestDataFile]:
        new_data_files: dict[str, ManifestDataFile] = {}
        deploy_dir: str

        entrypoint = self.require_entrypoint()
        if self.deploy_dir is not None:
            deploy_dir = self.deploy_dir
        elif entrypoint is not None and isfile(entrypoint):
            deploy_dir = dirname(entrypoint)
        else:
            # TODO: This branch might be an error case. Need to investigate.
            deploy_dir = entrypoint

        for path in self.data["files"]:
            rel_path = relpath(path, deploy_dir)
            manifestPath = Path(rel_path).as_posix()
            new_data_files[manifestPath] = self.data["files"][path]
        return new_data_files

    def get_manifest_files_from_buffer(self) -> dict[str, str]:
        new_buffer: dict[str, str] = {}
        deploy_dir: str

        entrypoint = self.require_entrypoint()
        if self.deploy_dir is not None:
            deploy_dir = self.deploy_dir
        elif entrypoint is not None and isfile(entrypoint):
            deploy_dir = dirname(entrypoint)
        else:
            # TODO: This branch might be an error case. Need to investigate.
            deploy_dir = entrypoint

        for k, v in self.buffer.items():
            rel_path = relpath(k, deploy_dir)
            manifestPath = Path(rel_path).as_posix()
            new_buffer[manifestPath] = v
        return new_buffer

    def get_relative_entrypoint(self) -> str:
        entrypoint = self.require_entrypoint()
        return basename(entrypoint)

    def get_flattened_primary_html(self):
        if self.primary_html is None:
            raise RSConnectException("A valid primary_html must be provided.")
        return relpath(self.primary_html, dirname(self.primary_html))

    def get_flattened_copy(self):
        new_manifest = deepcopy(self)
        new_manifest.data["files"] = self.get_manifest_files()
        new_manifest.buffer = self.get_manifest_files_from_buffer()
        new_manifest.entrypoint = self.get_relative_entrypoint()
        if self.primary_html:
            new_manifest.primary_html = self.get_flattened_primary_html()
        return new_manifest


class Bundle:
    def __init__(self) -> None:
        self.file_paths: set[str] = set()
        self.buffer: dict[str, str] = {}

    def add_file(self, filepath: str) -> None:
        self.file_paths.add(filepath)

    def discard_file(self, filepath: str) -> None:
        self.file_paths.discard(filepath)

    def to_file(self, deploy_dir: str) -> typing.IO[bytes]:
        bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")
        with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
            for fp in self.file_paths:
                if Path(fp).name in self.buffer:
                    continue
                rel_path = Path(fp).relative_to(deploy_dir)
                logger.log(VERBOSE, "Adding file: %s", fp)
                bundle.add(fp, arcname=rel_path)
            for k, v in self.buffer.items():
                buf = io.BytesIO(to_bytes(v))
                file_info = tarfile.TarInfo(k)
                file_info.size = len(buf.getvalue())
                logger.log(VERBOSE, "Adding file: %s", k)
                bundle.addfile(file_info, buf)
        bundle_file.seek(0)
        return bundle_file

    def add_to_buffer(self, key: str, value: str):
        self.buffer[key] = value
        return self

    def discard_from_buffer(self, key: str):
        if key in self.buffer:
            del self.buffer[key]
        return self


# noinspection SpellCheckingInspection
def make_source_manifest(
    app_mode: AppMode,
    environment: Optional[Environment] = None,
    entrypoint: Optional[str] = None,
    quarto_inspection: Optional[QuartoInspectResult] = None,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> ManifestData:
    manifest: ManifestData = cast(ManifestData, {"version": 1})

    # When adding locale, add it early so it is ordered immediately after
    # version.
    if environment:
        manifest["locale"] = environment.locale

    manifest["metadata"] = {
        "appmode": app_mode.name(),
    }

    if entrypoint:
        manifest["metadata"]["entrypoint"] = entrypoint

    if quarto_inspection:
        manifest["quarto"] = {
            "version": quarto_inspection.get("quarto", {}).get("version", "99.9.9"),
            "engines": quarto_inspection.get("engines", []),
        }

        files_data = quarto_inspection.get("files", {})
        files_input_data = files_data.get("input", [])
        if len(files_input_data) > 1:
            manifest["metadata"]["content_category"] = "site"

    if environment:
        package_manager = environment.package_manager
        manifest["python"] = {
            "version": environment.python,
            "package_manager": {
                "name": package_manager,
                "version": getattr(environment, package_manager),
                "package_file": environment.filename,
            },
        }

    if image or env_management_py is not None or env_management_r is not None:
        manifest["environment"] = {}
        if image:
            manifest["environment"]["image"] = image
        if env_management_py is not None or env_management_r is not None:
            manifest["environment"]["environment_management"] = {}
            if env_management_py is not None:
                manifest["environment"]["environment_management"]["python"] = env_management_py
            if env_management_r is not None:
                manifest["environment"]["environment_management"]["r"] = env_management_r

    manifest["files"] = {}

    return manifest


def manifest_add_file(manifest: ManifestData, rel_path: str, base_dir: str) -> None:
    """Add the specified file to the manifest files section

    The file must be specified as a pathname relative to the notebook directory.
    """
    path = join(base_dir, rel_path) if os.path.isdir(base_dir) else rel_path
    if "files" not in manifest:
        manifest["files"] = {}
    manifestPath = Path(rel_path).as_posix()
    manifest["files"][manifestPath] = {"checksum": file_checksum(path)}


def manifest_add_buffer(manifest: ManifestData, filename: str, buf: str | bytes) -> None:
    """Add the specified in-memory buffer to the manifest files section"""
    manifest["files"][filename] = {"checksum": buffer_checksum(buf)}


def make_hasher():
    try:
        return hashlib.md5()
    except Exception:
        # md5 is not available in FIPS mode, see if the usedforsecurity option is available
        # (it was added in python 3.9). We set usedforsecurity=False since we are only
        # using this for a file upload integrity check.
        return hashlib.md5(usedforsecurity=False)


def file_checksum(path: str | Path) -> str:
    """Calculate the md5 hex digest of the specified file"""
    with open(path, "rb") as f:
        m = make_hasher()
        chunk_size = 64 * 1024

        chunk = f.read(chunk_size)
        while chunk:
            m.update(chunk)
            chunk = f.read(chunk_size)
        return m.hexdigest()


def buffer_checksum(buf: str | bytes) -> str:
    """Calculate the md5 hex digest of a buffer (str or bytes)"""
    m = make_hasher()
    m.update(to_bytes(buf))
    return m.hexdigest()


def to_bytes(s: str | bytes) -> bytes:
    if isinstance(s, bytes):
        return s
    elif isinstance(s, str):
        return s.encode("utf-8")
    logger.warning("can't encode to bytes: %s" % type(s).__name__)
    return s


def bundle_add_file(bundle: tarfile.TarFile, rel_path: str, base_dir: str) -> None:
    """Add the specified file to the tarball.

    The file path is relative to the notebook directory.
    """
    path = join(base_dir, rel_path) if os.path.isdir(base_dir) else rel_path
    logger.log(VERBOSE, "Adding file: %s", path)
    bundle.add(path, arcname=rel_path)


def bundle_add_buffer(bundle: tarfile.TarFile, filename: str, contents: str | bytes) -> None:
    """Add an in-memory buffer to the tarball.

    `contents` may be a string or bytes object
    """
    logger.log(VERBOSE, "Adding file: %s", filename)
    buf = io.BytesIO(to_bytes(contents))
    file_info = tarfile.TarInfo(filename)
    file_info.size = len(buf.getvalue())
    bundle.addfile(file_info, buf)


def write_manifest(
    relative_dir: str,
    nb_name: str,
    environment: Environment,
    output_dir: str,
    hide_all_input: bool = False,
    hide_tagged_input: bool = False,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> tuple[list[str], list[str]]:
    """Create a manifest for source publishing the specified notebook.

    The manifest will be written to `manifest.json` in the output directory..
    A requirements.txt file will be created if one does not exist.

    Returns the list of filenames written.
    """
    manifest_filename = "manifest.json"
    manifest = make_source_manifest(
        AppModes.JUPYTER_NOTEBOOK, environment, nb_name, None, image, env_management_py, env_management_r
    )
    if hide_all_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_all_input": hide_all_input})
    if hide_tagged_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_tagged_input": hide_tagged_input})
    manifest_file = join(output_dir, manifest_filename)
    created: list[str] = []
    skipped: list[str] = []

    manifest_relative_path = join(relative_dir, manifest_filename)
    if exists(manifest_file):
        skipped.append(manifest_relative_path)
    else:
        with open(manifest_file, "w") as f:
            f.write(json.dumps(manifest, indent=2))
            created.append(manifest_relative_path)
            logger.debug("wrote manifest file: %s", manifest_file)

    environment_filename = environment.filename
    environment_file = join(output_dir, environment_filename)
    environment_relative_path = join(relative_dir, environment_filename)
    if environment.source == "file":
        skipped.append(environment_relative_path)
    else:
        with open(environment_file, "w") as f:
            f.write(environment.contents)
            created.append(environment_relative_path)
            logger.debug("wrote environment file: %s", environment_file)

    return created, skipped


def list_files(
    base_dir: str,
    include_sub_dirs: bool,
    walk: Callable[[str], Iterator[tuple[str, list[str], list[str]]]] = os.walk,
) -> list[str]:
    """List the files in the directory at path.

    If include_sub_dirs is True, recursively list
    files in subdirectories.

    Returns an iterable of file paths relative to base_dir.
    """
    skip_dirs = [".ipynb_checkpoints", ".git"]

    def iter_files():
        for root, sub_dirs, files in walk(base_dir):
            if include_sub_dirs:
                for skip in skip_dirs:
                    if skip in sub_dirs:
                        sub_dirs.remove(skip)
            else:
                # tell walk not to traverse any subdirectories
                sub_dirs[:] = []

            for filename in files:
                yield relpath(join(root, filename), base_dir)

    return list(iter_files())


def make_notebook_source_bundle(
    file: str,
    environment: Environment,
    extra_files: Sequence[str],
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> IO[bytes]:
    """Create a bundle containing the specified notebook and python environment.

    Returns a file-like object containing the bundle tarball.
    """
    if extra_files is None:
        extra_files = []
    base_dir = dirname(file)
    nb_name = basename(file)

    manifest = make_source_manifest(
        AppModes.JUPYTER_NOTEBOOK, environment, nb_name, None, image, env_management_py, env_management_r
    )
    if hide_all_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_all_input": hide_all_input})
    if hide_tagged_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_tagged_input": hide_tagged_input})
    manifest_add_file(manifest, nb_name, base_dir)
    manifest_add_buffer(manifest, environment.filename, environment.contents)

    if extra_files:
        skip = [nb_name, environment.filename, "manifest.json"]
        extra_files = sorted(list(set(extra_files) - set(skip)))

    for rel_path in extra_files:
        manifest_add_file(manifest, rel_path, base_dir)

    logger.debug("manifest: %r", manifest)

    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")
    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        # add the manifest first in case we want to partially untar the bundle for inspection
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))
        bundle_add_buffer(bundle, environment.filename, environment.contents)
        bundle_add_file(bundle, nb_name, base_dir)

        for rel_path in extra_files:
            bundle_add_file(bundle, rel_path, base_dir)

    bundle_file.seek(0)
    return bundle_file


def make_quarto_source_bundle(
    file_or_directory: str,
    inspect: QuartoInspectResult,
    app_mode: AppMode,
    environment: Optional[Environment],
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.IO[bytes]:
    """
    Create a bundle containing the specified Quarto content and (optional)
    python environment.

    Returns a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_quarto_manifest(
        file_or_directory,
        inspect,
        app_mode,
        environment,
        extra_files,
        excludes,
        image,
        env_management_py,
        env_management_r,
    )
    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = dirname(file_or_directory)

    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))
        if environment:
            bundle_add_buffer(bundle, environment.filename, environment.contents)

        for rel_path in relevant_files:
            bundle_add_file(bundle, rel_path, base_dir)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def make_html_manifest(
    filename: str,
) -> ManifestData:
    # noinspection SpellCheckingInspection
    manifest: ManifestData = {
        "version": 1,
        "metadata": {
            "appmode": "static",
            "primary_html": filename,
        },
        "files": {},
    }
    return manifest


def make_notebook_html_bundle(
    filename: str,
    python: str,
    hide_all_input: bool,
    hide_tagged_input: bool,
    check_output: Callable[..., bytes] = subprocess.check_output,
) -> typing.IO[bytes]:
    # noinspection SpellCheckingInspection
    cmd = [
        python,
        "-m",
        "nbconvert",
        "--execute",
        "--stdout",
        "--log-level=ERROR",
        "--to=html",
        filename,
    ]
    if hide_all_input and hide_tagged_input or hide_all_input:
        cmd.append("--no-input")
    elif hide_tagged_input:
        version = check_output([python, "--version"]).decode("utf-8")
        if version >= "Python 3":
            cmd.append("--TagRemovePreprocessor.remove_input_tags=hide_input")
        else:
            cmd.append("--TagRemovePreprocessor.remove_input_tags=['hide_input']")
    try:
        output = check_output(cmd)
    except subprocess.CalledProcessError:
        raise

    nb_name = basename(filename)
    filename = splitext(nb_name)[0] + ".html"

    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")
    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, filename, output)

        # manifest
        manifest = make_html_manifest(filename)
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))

    # rewind file pointer
    bundle_file.seek(0)
    return bundle_file


def keep_manifest_specified_file(relative_path: str, ignore_path_set: set[Path] = directories_to_ignore) -> bool:
    """
    A helper to see if the relative path given, which is assumed to have come
    from a manifest.json file, should be kept or ignored.

    :param relative_path: the relative path name to check.
    :return: True, if the path should kept or False, if it should be ignored.
    """
    p = Path(relative_path)
    for parent in p.parents:
        if parent in ignore_path_set:
            return False
    if p in ignore_path_set:
        return False
    return True


def _default_title_from_manifest(the_manifest: ManifestData, manifest_file: str | Path) -> str:
    """
    Produce a default content title from the contents of a manifest.
    """
    filename = None

    metadata = the_manifest.get("metadata")
    if metadata:
        # noinspection SpellCheckingInspection
        filename = metadata.get("entrypoint") or metadata.get("primary_rmd") or metadata.get("primary_html")
        # If the manifest is for an API, revert to using the parent directory.
        if filename and _module_pattern.match(filename):
            filename = None
    return _default_title(filename or dirname(manifest_file))


def read_manifest_app_mode(file: str | Path) -> AppMode:
    source_manifest, _ = read_manifest_file(file)
    # noinspection SpellCheckingInspection
    app_mode = AppModes.get_by_name(source_manifest["metadata"]["appmode"])
    return app_mode


def default_title_from_manifest(file: str | Path) -> str:
    source_manifest, _ = read_manifest_file(file)
    title = _default_title_from_manifest(source_manifest, file)
    return title


def read_manifest_file(manifest_path: str | Path) -> tuple[ManifestData, str]:
    """
    Read a manifest's content from its file.  The content is provided as both a
    raw string and a parsed dictionary.

    :param manifest_path: the path to the file to read.
    :return: the parsed manifest data and the raw file content as a string.
    """
    with open(manifest_path, "rb") as f:
        raw_manifest = f.read().decode("utf-8")
        manifest = json.loads(raw_manifest)

    return manifest, raw_manifest


def make_manifest_bundle(manifest_path: str | Path) -> typing.IO[bytes]:
    """Create a bundle, given a manifest.

    :return: a file-like object containing the bundle tarball.
    """
    manifest, raw_manifest = read_manifest_file(manifest_path)

    base_dir = dirname(manifest_path)
    files = list(filter(keep_manifest_specified_file, manifest.get("files", {}).keys()))

    if "manifest.json" in files:
        # this will be created
        files.remove("manifest.json")

    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")
    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        # add the manifest first in case we want to partially untar the bundle for inspection
        bundle_add_buffer(bundle, "manifest.json", raw_manifest)

        for rel_path in files:
            bundle_add_file(bundle, rel_path, base_dir)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def create_glob_set(directory: str | Path, excludes: Sequence[str]) -> GlobSet:
    """
    Takes a list of glob strings and produces a GlobSet for path matching.

    **Note:** we don't use Python's glob support because it takes way too
    long to run when large file trees are involved in conjunction with the
    '**' pattern.

    :param directory: the directory the globs are relative to.
    :param excludes: the list of globs to expand.
    :return: a GlobSet ready for path matching.
    """
    work: list[str] = []
    if excludes:
        for pattern in excludes:
            file_pattern = join(directory, pattern)
            # Special handling, if they gave us just a dir then "do the right thing".
            if isdir(file_pattern):
                file_pattern = join(file_pattern, "**/*")
            work.append(file_pattern)

    return GlobSet(work)


def is_environment_dir(directory: str | Path):
    """Detect whether `directory` is a virtualenv"""

    # A virtualenv will have Python at ./bin/python
    python_path = join(directory, "bin", "python")
    # But on Windows, it's at Scripts\Python.exe
    win_path = join(directory, "Scripts", "Python.exe")
    return exists(python_path) or exists(win_path)


def list_environment_dirs(directory: str | Path):
    """Returns a list of subdirectories in `directory` that appear to contain virtual environments."""
    envs: list[str] = []

    for name in os.listdir(directory):
        path = join(directory, name)
        if is_environment_dir(path):
            envs.append(name)
    return envs


def make_api_manifest(
    directory: str,
    entry_point: str,
    app_mode: AppMode,
    environment: Environment,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> tuple[ManifestData, list[str]]:
    """
    Makes a manifest for an API.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the manifest and a list of the files involved.
    """
    if is_environment_dir(directory):
        excludes = list(excludes or []) + ["bin/", "lib/", "Lib/", "Scripts/", "Include/"]

    extra_files = extra_files or []
    skip = [environment.filename, "manifest.json"]
    extra_files = sorted(list(set(extra_files) - set(skip)))

    # Don't include these top-level files.
    excludes = list(excludes) if excludes else []
    excludes.append("manifest.json")
    excludes.append(environment.filename)
    excludes.extend(list_environment_dirs(directory))

    relevant_files = create_file_list(directory, extra_files, excludes)
    manifest = make_source_manifest(
        app_mode, environment, entry_point, None, image, env_management_py, env_management_r
    )

    manifest_add_buffer(manifest, environment.filename, environment.contents)

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, directory)

    return manifest, relevant_files


def create_html_manifest(
    path: str,
    entrypoint: Optional[str],
    extra_files: Sequence[str],
    excludes: Sequence[str],
) -> Manifest:
    """
    Creates and writes a manifest.json file for the given path.

    :param path: the file, or the directory containing the files to deploy.
    :param entrypoint: the main entry point for the API.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one. Previous default = None.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the manifest data structure.
    """
    if not path:
        raise RSConnectException("A valid path must be provided.")
    extra_files = list(extra_files) if extra_files else []
    entrypoint_candidates = infer_entrypoint_candidates(path=abspath(path), mimetype="text/html")

    deploy_dir = guess_deploy_dir(path, entrypoint)
    if len(entrypoint_candidates) <= 0:
        if entrypoint is None:
            raise RSConnectException("No valid entrypoint found.")
        entrypoint = abs_entrypoint(path, entrypoint)
    elif len(entrypoint_candidates) == 1:
        if entrypoint:
            entrypoint = abs_entrypoint(path, entrypoint)
        else:
            entrypoint = entrypoint_candidates[0]
    else:  # len(entrypoint_candidates) > 1:
        if entrypoint is None:
            raise RSConnectException("No valid entrypoint found.")
        entrypoint = abs_entrypoint(path, entrypoint)

    extra_files = validate_extra_files(deploy_dir, extra_files, use_abspath=True)
    excludes = list(excludes) if excludes else []
    excludes.extend(["manifest.json"])
    excludes.extend(list_environment_dirs(deploy_dir))

    manifest = Manifest(
        app_mode=AppModes.STATIC,
        entrypoint=entrypoint,
        primary_html=entrypoint,
    )
    manifest.deploy_dir = deploy_dir

    file_list = create_file_list(path, extra_files, excludes, use_abspath=True)
    for abs_path in file_list:
        manifest.add_file(abs_path)

    return manifest


def make_tensorflow_manifest(
    directory: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
) -> ManifestData:
    """
    Creates and writes a manifest.json file for the given path.

    :param directory the directory containing the TensorFlow model.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: the manifest data structure.
    """
    if not directory:
        raise RSConnectException("A valid directory must be provided.")
    extra_files = list(extra_files) if extra_files else []

    extra_files = validate_extra_files(directory, extra_files, use_abspath=True)
    excludes = list(excludes) if excludes else []
    excludes.extend(["manifest.json"])
    excludes.extend(list_environment_dirs(directory))

    manifest = make_source_manifest(
        app_mode=AppModes.TENSORFLOW,
        image=image,
    )

    file_list = create_file_list(directory, extra_files, excludes)
    for rel_path in file_list:
        manifest_add_file(manifest, rel_path, directory)
    return manifest


def make_html_bundle(
    path: str,
    entrypoint: Optional[str],
    extra_files: Sequence[str],
    excludes: Sequence[str],
) -> typing.IO[bytes]:
    """
    Create an html bundle, given a path and/or entrypoint.

    The bundle contains a manifest.json file created for the given notebook entrypoint file.

    :param path: the file, or the directory containing the files to deploy.
    :param entrypoint: the main entry point.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: a file-like object containing the bundle tarball.
    """

    manifest = create_html_manifest(
        path=path,
        entrypoint=entrypoint,
        extra_files=extra_files,
        excludes=excludes,
    )

    if manifest.data.get("files") is None:
        raise RSConnectException("No valid files were found for the manifest.")
    if manifest.deploy_dir is None:
        raise RSConnectException("deploy_dir was not set for the manifest.")

    bundle = Bundle()
    for f in manifest.data["files"]:
        if f in manifest.buffer:
            continue
        bundle.add_file(f)
    for k, v in manifest.get_manifest_files_from_buffer().items():
        bundle.add_to_buffer(k, v)

    manifest_flattened_copy_data = manifest.get_flattened_copy().data
    bundle.add_to_buffer("manifest.json", json.dumps(manifest_flattened_copy_data, indent=2))

    return bundle.to_file(manifest.deploy_dir)


def make_tensorflow_bundle(
    directory: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
) -> typing.IO[bytes]:
    """
    Create an html bundle, given a path and/or entrypoint.

    The bundle contains a manifest.json file created for the given notebook entrypoint file.

    :param directory: the directory containing the TensorFlow model.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: a file-like object containing the bundle tarball.
    """

    manifest = make_tensorflow_manifest(
        directory=directory,
        extra_files=extra_files,
        excludes=excludes,
        image=image,
    )

    if not manifest.get("files"):
        raise RSConnectException("No valid files were found for the manifest.")

    bundle = Bundle()
    for f in manifest["files"]:
        bundle.add_file(join(directory, f))

    bundle.add_to_buffer("manifest.json", json.dumps(manifest, indent=2))

    return bundle.to_file(directory)


def create_file_list(
    path: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    use_abspath: bool = False,
) -> list[str]:
    """
    Builds a full list of files under the given path that should be included
    in a manifest or bundle.  Extra files and excludes are relative to the given
    directory and work as you'd expect.

    :param path: a file, or a directory to walk for files.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the list of relevant files, relative to the given directory.
    """
    extra_files = extra_files or []
    excludes = excludes if excludes else []
    glob_set = create_glob_set(path, excludes)
    exclude_paths = {Path(p) for p in excludes}
    file_set: set[str] = set(extra_files)

    if isfile(path):
        path_to_add = abspath(path) if use_abspath else path
        file_set.add(path_to_add)
        return sorted(file_set)

    for cur_dir, _, files in os.walk(path):
        if Path(cur_dir) in exclude_paths:
            continue
        if any(parent in exclude_paths for parent in Path(cur_dir).parents):
            continue
        for file in files:
            cur_path = os.path.join(cur_dir, file)
            rel_path = relpath(cur_path, path)

            if Path(cur_path) in exclude_paths:
                continue
            if keep_manifest_specified_file(rel_path, exclude_paths | directories_to_ignore) and (
                rel_path in extra_files or not glob_set.matches(cur_path)
            ):
                path_to_add = abspath(cur_path) if use_abspath else rel_path
                file_set.add(path_to_add)

    return sorted(file_set)


def infer_entrypoint(path: str, mimetype: str) -> str | None:
    candidates = infer_entrypoint_candidates(path, mimetype)
    return candidates.pop() if len(candidates) == 1 else None


def infer_entrypoint_candidates(path: str, mimetype: str) -> list[str]:
    if not path:
        return []
    if isfile(path):
        return [path]
    if not isdir(path):
        return []

    default_mimetype_entrypoints: defaultdict[str, str] = defaultdict(str)
    default_mimetype_entrypoints["text/html"] = "index.html"

    mimetype_filelist: defaultdict[str | None, list[str]] = defaultdict(list)

    for file in os.listdir(path):
        abs_path = os.path.join(path, file)
        if not isfile(abs_path):
            continue
        file_type = guess_type(file)[0]
        mimetype_filelist[file_type].append(abs_path)
        if file in default_mimetype_entrypoints[mimetype]:
            return [abs_path]
    return mimetype_filelist[mimetype] or []


def guess_deploy_dir(path: str | Path, entrypoint: Optional[str]) -> str:
    if path and not exists(path):
        raise RSConnectException(f"Path {path} does not exist.")
    if entrypoint and not exists(entrypoint):
        raise RSConnectException(f"Entrypoint {entrypoint} does not exist.")
    abs_path = abspath(path)
    abs_entrypoint = abspath(entrypoint) if entrypoint else None
    if not path and not entrypoint:
        raise RSConnectException("No path or entrypoint provided.")
    deploy_dir: str
    if path and isfile(path):
        if not entrypoint:
            deploy_dir = dirname(abs_path)
        elif isfile(entrypoint):
            if abs_path == abs_entrypoint:
                deploy_dir = dirname(abs_path)
            else:
                raise RSConnectException("Path and entrypoint need to match if they are both files.")
        elif isdir(entrypoint):
            raise RSConnectException("Entrypoint cannot be a directory while the path is a file.")
        else:
            raise RSConnectException("Entrypoint cannot be a special file.")

    elif path and isdir(path):
        if not entrypoint or not abs_entrypoint:
            deploy_dir = abs_path
        # elif entrypoint and isdir(entrypoint):
        #     raise RSConnectException("Path and entrypoint cannot both be directories.")
        else:
            if isdir(entrypoint):
                raise RSConnectException("Path and entrypoint cannot both be directories.")
            guess_entry_file = os.path.join(abs_path, basename(entrypoint))
            if isfile(guess_entry_file):
                deploy_dir = dirname(guess_entry_file)
            elif isfile(entrypoint):
                deploy_dir = dirname(abs_entrypoint)
            else:
                raise RSConnectException("Can't find entrypoint.")
    elif not path and entrypoint:
        raise RSConnectException("A path needs to be provided.")
    else:
        deploy_dir = abs_path
    return deploy_dir


def abs_entrypoint(path: str | Path, entrypoint: str) -> str | None:
    if isfile(entrypoint):
        return abspath(entrypoint)
    guess_entry_file = os.path.join(abspath(path), basename(entrypoint))
    if isfile(guess_entry_file):
        return guess_entry_file
    return None


def make_voila_bundle(
    path: str,
    entrypoint: Optional[str],
    extra_files: Sequence[str],
    excludes: Sequence[str],
    force_generate: bool,
    environment: Environment,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
    multi_notebook: bool = False,
) -> typing.IO[bytes]:
    """
    Create an voila bundle, given a path and/or entrypoint.

    The bundle contains a manifest.json file created for the given notebook entrypoint file.
    If the related environment file (requirements.txt) doesn't
    exist (or force_generate is set to True), the environment file will also be written.

    :param path: the file, or the directory containing the files to deploy.
    :param entrypoint: the main entry point.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param force_generate: bool indicating whether to force generate manifest and related environment files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: a file-like object containing the bundle tarball.
    """

    manifest = create_voila_manifest(
        path=path,
        entrypoint=entrypoint,
        extra_files=extra_files,
        excludes=excludes,
        force_generate=force_generate,
        environment=environment,
        image=image,
        env_management_py=env_management_py,
        env_management_r=env_management_r,
        multi_notebook=multi_notebook,
    )

    if manifest.data.get("files") is None:
        raise RSConnectException("No valid files were found for the manifest.")
    if manifest.deploy_dir is None:
        raise RSConnectException("deploy_dir was not set for the manifest.")

    bundle = Bundle()
    for f in manifest.data["files"]:
        if f in manifest.buffer:
            continue
        bundle.add_file(f)
    for k, v in manifest.get_manifest_files_from_buffer().items():
        bundle.add_to_buffer(k, v)

    manifest_flattened_copy_data = manifest.get_flattened_copy().data
    if multi_notebook and "metadata" in manifest_flattened_copy_data:
        manifest_flattened_copy_data["metadata"]["entrypoint"] = ""
    bundle.add_to_buffer("manifest.json", json.dumps(manifest_flattened_copy_data, indent=2))

    return bundle.to_file(manifest.deploy_dir)


def make_api_bundle(
    directory: str,
    entry_point: str,
    app_mode: AppMode,
    environment: Environment,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> typing.IO[bytes]:
    """
    Create an API bundle, given a directory path and a manifest.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_api_manifest(
        directory,
        entry_point,
        app_mode,
        environment,
        extra_files,
        excludes,
        image,
        env_management_py,
        env_management_r,
    )
    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")

    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))
        bundle_add_buffer(bundle, environment.filename, environment.contents)

        for rel_path in relevant_files:
            bundle_add_file(bundle, rel_path, directory)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def _create_quarto_file_list(
    directory: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
) -> list[str]:
    """
    Builds a full list of files under the given directory that should be included
    in a manifest or bundle.  Extra files and excludes are relative to the given
    directory and work as you'd expect.

    :param directory: the directory to walk for files.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the list of relevant files, relative to the given directory.
    """
    # Don't let these top-level files be added via the extra files list.
    extra_files = extra_files or []
    skip = ["manifest.json"]
    extra_files = sorted(list(set(extra_files) - set(skip)))

    # Don't include these top-level files.
    excludes = list(excludes) if excludes else []
    excludes.append("manifest.json")
    excludes.extend(list_environment_dirs(directory))

    file_list = create_file_list(directory, extra_files, excludes)
    return file_list


def make_quarto_manifest(
    file_or_directory: str,
    quarto_inspection: QuartoInspectResult,
    app_mode: AppMode,
    environment: Optional[Environment],
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> tuple[ManifestData, list[str]]:
    """
    Makes a manifest for a Quarto project.

    :param file_or_directory: The Quarto document or the directory containing the Quarto project.
    :param quarto_inspection: The parsed JSON from a 'quarto inspect' against the project.
    :param app_mode: The application mode to assume.
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the manifest and a list of the files involved.
    """
    if environment:
        extra_files = list(extra_files or [])

    base_dir = file_or_directory
    if isdir(file_or_directory):
        # Directory as a Quarto project.
        excludes = list(excludes or []) + [".quarto"]

        project_config = quarto_inspection.get("config", {}).get("project", {})
        output_dir = cast(Union[str, None], project_config.get("output-dir", None))
        if output_dir:
            excludes = excludes + [output_dir]

        files_data = quarto_inspection.get("files", {})
        files_input_data = files_data.get("input", [])
        # files.input is a list of absolute paths to input (rendered)
        # files. Automatically ignore the most common derived files for
        # those inputs.
        #
        # These files are ignored even when the project has an output
        # directory, as Quarto may create these files while a render is
        # in-flight.
        for each in files_input_data:
            t, _ = splitext(os.path.relpath(each, file_or_directory))
            excludes = excludes + [t + ".html", t + "_files/**/*"]

        # relevant files don't need to include requirements.txt file because it is
        # always added to the manifest (as a buffer) from the environment contents
        if environment:
            excludes.append(environment.filename)

        relevant_files = _create_quarto_file_list(base_dir, extra_files, excludes)
    else:
        # Standalone Quarto document
        base_dir = dirname(file_or_directory)
        file_name = basename(file_or_directory)
        relevant_files = [file_name] + list(extra_files or [])

    manifest = make_source_manifest(
        app_mode,
        environment,
        None,
        quarto_inspection,
        image,
        env_management_py,
        env_management_r,
    )

    if environment:
        manifest_add_buffer(manifest, environment.filename, environment.contents)

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, base_dir)

    return manifest, relevant_files


def _default_title(file_name: str | Path) -> str:
    """
    Produce a default content title from the given file path.  The result is
    guaranteed to be between 3 and 1024 characters long, as required by Posit
    Connect.

    :param file_name: the name from which the title will be derived.
    :return: the derived title.
    """
    # Make sure we have enough of a path to derive text from.
    file_name = abspath(file_name)
    # noinspection PyTypeChecker
    return basename(file_name).rsplit(".", 1)[0][:1024].rjust(3, "0")


def validate_file_is_notebook(file_name: str | Path) -> None:
    """
    Validate that the given file is a Jupyter Notebook. If it isn't, an exception is
    thrown.  A file must exist and have the '.ipynb' extension.

    :param file_name: the name of the file to validate.
    """
    file_suffix = splitext(file_name)[1].lower()
    if file_suffix != ".ipynb" or not exists(file_name):
        raise RSConnectException("A Jupyter notebook (.ipynb) file is required here.")


def validate_extra_files(
    directory: str | Path,
    extra_files: Sequence[str] | None,
    use_abspath: bool = False,
) -> list[str]:
    """
    If the user specified a list of extra files, validate that they all exist and are
    beneath the given directory and, if so, return a list of them made relative to that
    directory.

    :param directory: the directory that the extra files must be relative to.
    :param extra_files: the list of extra files to qualify and validate.
    :return: the extra files qualified by the directory.
    """
    result: list[str] = []
    if extra_files:
        for extra in extra_files:
            extra_file = relpath(extra, directory)
            # It's an error if we have to leave the given dir to get to the extra
            # file.
            if extra_file.startswith("../"):
                raise RSConnectException("%s must be under %s." % (extra_file, directory))
            if not exists(join(directory, extra_file)):
                raise RSConnectException("Could not find file %s under %s" % (extra, directory))
            extra_file = abspath(join(directory, extra_file)) if use_abspath else extra_file
            result.append(extra_file)
    return result


def validate_manifest_file(file_or_directory: str) -> str:
    """
    Validates that the name given represents either an existing manifest.json file or
    a directory that contains one.  If not, an exception is raised.

    :param file_or_directory: the name of the manifest file or directory that contains it.
    :return: the real path to the manifest file.
    """
    if isdir(file_or_directory):
        file_or_directory = join(file_or_directory, "manifest.json")
    if basename(file_or_directory) != "manifest.json" or not exists(file_or_directory):
        raise RSConnectException("A manifest.json file or a directory containing one is required here.")
    return file_or_directory


re_app_prefix = re.compile(r"^app[-_].+\.py$")
re_app_suffix = re.compile(r".+[-_]app\.py$")


def get_default_entrypoint(directory: str | Path) -> str:
    candidates = ["app", "application", "main", "api"]
    files = set(os.listdir(directory))

    for candidate in candidates:
        filename = candidate + ".py"
        if filename in files:
            return candidate

    # if only one python source file, use it
    python_files = list(filter(lambda s: s.endswith(".py"), files))
    if len(python_files) == 1:
        return python_files[0][:-3]

    # try app-*.py, app_*.py, *-app.py, *_app.py
    app_files = list(filter(lambda s: re_app_prefix.match(s) or re_app_suffix.match(s), python_files))
    if len(app_files) == 1:
        # In these cases, the app should be in the "app" attribute
        return app_files[0][:-3]

    raise RSConnectException(f"Could not determine default entrypoint file in directory '{directory}'")


def validate_entry_point(entry_point: str | None, directory: str) -> str:
    """
    Validates the entry point specified by the user, expanding as necessary.  If the
    user specifies nothing, a module of "app" is assumed.  If the user specifies a
    module only, at runtime the following object names will be tried in order: `app`,
    `application`, `create_app`, and `make_app`.

    :param entry_point: the entry point as specified by the user.
    :return: An entry point, in the form of "module" or "module:app".
    """
    if not entry_point:
        entry_point = get_default_entrypoint(directory)

    parts = entry_point.split(":")

    if len(parts) > 2:
        raise RSConnectException('Entry point is not in "module:object" format.')

    return entry_point


def _warn_on_ignored_entrypoint(entrypoint: Optional[str]) -> None:
    if entrypoint:
        click.secho(
            "    Warning: entrypoint will not be used or considered for multi-notebook mode.",
            fg="yellow",
        )


def _warn_on_ignored_manifest(directory: str) -> None:
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    """
    if exists(join(directory, "manifest.json")):
        click.secho(
            "    Warning: the existing manifest.json file will not be used or considered.",
            fg="yellow",
        )


def _warn_if_no_requirements_file(directory: str) -> None:
    """
    Checks for the existence of a file called requirements.txt in the given directory.
    If it's not there, a warning will be printed.

    :param directory: the directory to check in.
    """
    if not exists(join(directory, "requirements.txt")):
        click.secho(
            "    Warning: Capturing the environment using 'pip freeze'.\n"
            "             Consider creating a requirements.txt file instead.",
            fg="yellow",
        )


def _warn_if_environment_directory(directory: str | Path) -> None:
    """
    Issue a warning if the deployment directory is itself a virtualenv (yikes!).

    :param directory: the directory to check in.
    """
    if is_environment_dir(directory):
        click.secho(
            "    Warning: The deployment directory appears to be a python virtual environment.\n"
            "             Python libraries and binaries will be excluded from the deployment.",
            fg="yellow",
        )


def _warn_on_ignored_requirements(directory: str, requirements_file_name: str) -> None:
    """
    Checks for the existence of a file called manifest.json in the given directory.
    If it's there, a warning noting that it will be ignored will be printed.

    :param directory: the directory to check in.
    :param requirements_file_name: the name of the requirements file.
    """
    if exists(join(directory, requirements_file_name)):
        click.secho(
            "    Warning: the existing %s file will not be used or considered." % requirements_file_name,
            fg="yellow",
        )


def fake_module_file_from_directory(directory: str) -> str:
    """
    Takes a directory and invents a properly named file that though possibly fake,
    can be used for other name/title derivation.

    :param directory: the directory to start with.
    :return: the directory plus the (potentially) fake module file.
    """
    app_name = abspath(directory)
    app_name = dirname(app_name) if app_name.endswith(os.path.sep) else basename(app_name)
    return join(directory, app_name + ".py")


def which_python(python: Optional[str] = None) -> str:
    """Determines which Python executable to use.

    If the :param python: is provided, then validation is performed to check if the path is an executable file. If
    None, the invoking system Python executable location is returned.

    :param python: (Optional) path to a python executable.
    :return: :param python: or `sys.executable`.
    """
    if python is None:
        return sys.executable
    if not exists(python):
        raise RSConnectException(f"The path '{python}' does not exist. Expected a Python executable.")
    if isdir(python):
        raise RSConnectException(f"The path '{python}' is a directory. Expected a Python executable.")
    if not os.access(python, os.X_OK):
        raise RSConnectException(f"The path '{python}' is not executable. Expected a Python executable")
    return python


def inspect_environment(
    python: str,
    directory: str,
    force_generate: bool = False,
    check_output: Callable[..., bytes] = subprocess.check_output,
) -> Environment:
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    flags: list[str] = []
    if force_generate:
        flags.append("f")

    args = [python, "-m", "rsconnect.environment"]
    if flags:
        args.append("-" + "".join(flags))
    args.append(directory)

    try:
        environment_json = check_output(args, text=True)
    except Exception as e:
        raise RSConnectException("Error inspecting environment (subprocess failed)") from e

    try:
        environment_data = json.loads(environment_json)
    except json.JSONDecodeError as e:
        raise RSConnectException("Error parsing environment JSON") from e

    try:
        return MakeEnvironment(**environment_data)
    except TypeError as e:
        system_error_message = environment_data.get("error")
        if system_error_message:
            raise RSConnectException(f"Error creating environment: {system_error_message}") from e
        raise RSConnectException("Error constructing environment object") from e


def get_python_env_info(
    file_name: str,
    python: str | None,
    force_generate: bool = False,
    override_python_version: str | None = None,
) -> tuple[str, Environment]:
    """
    Gathers the python and environment information relating to the specified file
    with an eye to deploy it.

    :param file_name: the primary file being deployed.
    :param python: the optional name of a Python executable.
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :return: information about the version of Python in use plus some environmental
    stuff.
    """
    python = which_python(python)
    logger.debug("Python: %s" % python)
    environment = inspect_environment(python, dirname(file_name), force_generate=force_generate)
    if environment.error:
        raise RSConnectException(environment.error)
    logger.debug("Python: %s" % python)
    logger.debug("Environment: %s" % pformat(environment._asdict()))

    if override_python_version:
        environment = environment._replace(python=override_python_version)

    return python, environment


def create_notebook_manifest_and_environment_file(
    entry_point_file: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: Sequence[str],
    force: bool,
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> None:
    """
    Creates and writes a manifest.json file for the given notebook entry point file.
    If the related environment file (requirements.txt, environment.yml, etc.) doesn't
    exist (or force is set to True), the environment file will also be written.

    :param entry_point_file: the entry point file (Jupyter notebook, etc.) to build
    the manifest for.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one. Previous default = None.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param force: if True, forces the environment file to be written. even if it
    already exists. Previous default = True.
    :param hide_all_input: if True, will hide all input cells when rendering output.  Previous default = False.
    :param hide_tagged_input: If True, will hide input code cells with the 'hide_input' tag
    when rendering output.   Previous default = False.
    :param image: an optional docker image for off-host execution. Previous default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return:
    """
    if (
        not write_notebook_manifest_json(
            entry_point_file,
            environment,
            app_mode,
            extra_files,
            hide_all_input,
            hide_tagged_input,
            image,
            env_management_py,
            env_management_r,
        )
        or force
    ):
        write_environment_file(environment, dirname(entry_point_file))


def write_notebook_manifest_json(
    entry_point_file: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: Sequence[str],
    hide_all_input: Optional[bool],
    hide_tagged_input: Optional[bool],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> bool:
    """
    Creates and writes a manifest.json file for the given entry point file.  If
    the application mode is not provided, an attempt will be made to resolve one
    based on the extension portion of the entry point file.

    :param entry_point_file: the entry point file (Jupyter notebook, etc.) to build
    the manifest for.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one. Previous default = None.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param hide_all_input: if True, will hide all input cells when rendering output. Previous default = False.
    :param hide_tagged_input: If True, will hide input code cells with the 'hide_input' tag
    when rendering output.  Previous default = False.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: whether or not the environment file (requirements.txt, environment.yml,
    etc.) that goes along with the manifest exists.
    """
    extra_files = validate_extra_files(dirname(entry_point_file), extra_files)
    directory = dirname(entry_point_file)
    file_name = basename(entry_point_file)
    manifest_path = join(directory, "manifest.json")

    if app_mode is None:
        _, extension = splitext(file_name)
        app_mode = AppModes.get_by_extension(extension, True)
        if app_mode == AppModes.UNKNOWN:
            raise RSConnectException('Could not determine the app mode from "%s"; please specify one.' % extension)

    manifest_data = make_source_manifest(
        app_mode, environment, file_name, None, image, env_management_py, env_management_r
    )
    if hide_all_input or hide_tagged_input:
        if "jupyter" not in manifest_data:
            manifest_data["jupyter"] = {}
        if hide_all_input:
            manifest_data["jupyter"]["hide_all_input"] = True
        if hide_tagged_input:
            manifest_data["jupyter"]["hide_tagged_input"] = True

    manifest_add_file(manifest_data, file_name, directory)
    manifest_add_buffer(manifest_data, environment.filename, environment.contents)

    for rel_path in extra_files:
        manifest_add_file(manifest_data, rel_path, directory)

    write_manifest_json(manifest_path, manifest_data)

    return exists(join(directory, environment.filename))


MULTI_NOTEBOOK_EXC_MSG = """
Unable to infer entrypoint.
Multi-notebook deployments need to be specified with the following:
1) A directory as the path
2) Set multi_notebook=True,
    i.e. include --multi-notebook (or -m) in the CLI command.
"""


def create_voila_manifest(
    path: str,
    entrypoint: Optional[str],
    environment: Environment,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    force_generate: bool = True,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
    multi_notebook: bool = False,
) -> Manifest:
    """
    Creates and writes a manifest.json file for the given path.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one. Previous default = None.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param force_generate: bool indicating whether to force generate manifest and related environment files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: the manifest data structure.
    """
    if not path:
        raise RSConnectException("A valid path must be provided.")
    extra_files = list(extra_files) if extra_files else []
    entrypoint_candidates = infer_entrypoint_candidates(path=abspath(path), mimetype="text/ipynb")

    deploy_dir = guess_deploy_dir(path, entrypoint)
    if not multi_notebook:
        if len(entrypoint_candidates) <= 0:
            if entrypoint is None:
                raise RSConnectException(MULTI_NOTEBOOK_EXC_MSG)
            entrypoint = abs_entrypoint(path, entrypoint)
        elif len(entrypoint_candidates) == 1:
            if entrypoint:
                entrypoint = abs_entrypoint(path, entrypoint)
            else:
                entrypoint = entrypoint_candidates[0]
        else:  # len(entrypoint_candidates) > 1:
            if entrypoint is None:
                raise RSConnectException(MULTI_NOTEBOOK_EXC_MSG)
            entrypoint = abs_entrypoint(path, entrypoint)

    if multi_notebook:
        if path and not isdir(path):
            raise RSConnectException(MULTI_NOTEBOOK_EXC_MSG)
        _warn_on_ignored_entrypoint(entrypoint)
        deploy_dir = entrypoint = abspath(path)
    extra_files = validate_extra_files(deploy_dir, extra_files, use_abspath=True)
    excludes = list(excludes) if excludes else []
    excludes.extend([environment.filename, "manifest.json"])
    excludes.extend(list_environment_dirs(deploy_dir))

    voila_json_path = join(deploy_dir, "voila.json")
    if isfile(voila_json_path):
        extra_files.append(voila_json_path)

    manifest = Manifest(
        app_mode=AppModes.JUPYTER_VOILA,
        environment=environment,
        entrypoint=entrypoint,
        image=image,
        env_management_py=env_management_py,
        env_management_r=env_management_r,
    )
    manifest.deploy_dir = deploy_dir
    if entrypoint and isfile(entrypoint):
        validate_file_is_notebook(entrypoint)
        manifest.entrypoint = entrypoint

    manifest.add_to_buffer(join(deploy_dir, environment.filename), environment.contents)

    file_list = create_file_list(path, extra_files, excludes, use_abspath=True)
    for abs_path in file_list:
        manifest.add_file(abs_path)
    return manifest


def write_voila_manifest_json(
    path: str,
    entrypoint: Optional[str],
    environment: Environment,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    force_generate: bool = True,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
    multi_notebook: bool = False,
) -> bool:
    """
    Creates and writes a manifest.json file for the given path.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume.  If this is None, the extension
    portion of the entry point file name will be used to derive one. Previous default = None.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param force_generate: bool indicating whether to force generate manifest and related environment files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: whether the manifest was written.
    """
    manifest = create_voila_manifest(
        path=path,
        entrypoint=entrypoint,
        environment=environment,
        extra_files=extra_files,
        excludes=excludes,
        force_generate=force_generate,
        image=image,
        env_management_py=env_management_py,
        env_management_r=env_management_r,
        multi_notebook=multi_notebook,
    )

    if manifest.entrypoint is None:
        raise RSConnectException("Voila manifest requires an entrypoint.")

    deploy_dir = dirname(manifest.entrypoint) if isfile(manifest.entrypoint) else manifest.entrypoint
    manifest_flattened_copy_data = manifest.get_flattened_copy().data
    if multi_notebook and "metadata" in manifest_flattened_copy_data:
        manifest_flattened_copy_data["metadata"]["entrypoint"] = ""
    manifest_path = join(deploy_dir, "manifest.json")
    write_manifest_json(manifest_path, manifest_flattened_copy_data)
    return exists(manifest_path)


def create_api_manifest_and_environment_file(
    directory: str,
    entry_point: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    force: bool,
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> None:
    """
    Creates and writes a manifest.json file for the given Python API entry point.  If
    the related environment file (requirements.txt, environment.yml, etc.) doesn't
    exist (or force is set to True), the environment file will also be written.

    :param directory: the root directory of the Python API.
    :param entry_point: the module/executable object for the WSGi framework.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume. Previous default = AppModes.PYTHON_API.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files. Previous default = None.
    :param force: if True, forces the environment file to be written. even if it
    already exists. Previous default = True.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return:
    """
    if (
        not write_api_manifest_json(
            directory,
            entry_point,
            environment,
            app_mode,
            extra_files,
            excludes,
            image,
            env_management_py,
            env_management_r,
        )
        or force
    ):
        write_environment_file(environment, directory)


def write_api_manifest_json(
    directory: str,
    entry_point: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> bool:
    """
    Creates and writes a manifest.json file for the given entry point file.  If
    the application mode is not provided, an attempt will be made to resolve one
    based on the extension portion of the entry point file.

    :param directory: the root directory of the Python API.
    :param entry_point: the module/executable object for the WSGi framework.
    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param app_mode: the application mode to assume. Previous default = AppModes.PYTHON_API.
    :param extra_files: any extra files that should be included in the manifest. Previous default = None.
    :param excludes: a sequence of glob patterns that will exclude matched files. Previous default = None.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :return: whether or not the environment file (requirements.txt, environment.yml,
    etc.) that goes along with the manifest exists.
    """
    extra_files = validate_extra_files(directory, extra_files)
    manifest, _ = make_api_manifest(
        directory, entry_point, app_mode, environment, extra_files, excludes, image, env_management_py, env_management_r
    )
    manifest_path = join(directory, "manifest.json")

    write_manifest_json(manifest_path, manifest)

    return exists(join(directory, environment.filename))


def write_environment_file(
    environment: Environment,
    directory: str,
) -> None:
    """
    Writes the environment file (requirements.txt, environment.yml, etc.) to the
    specified directory.

    :param environment: the Python environment to start with.  This should be what's
    returned by the inspect_environment() function.
    :param directory: the directory where the file should be written.
    """
    environment_file_path = join(directory, environment.filename)
    with open(environment_file_path, "w") as f:
        f.write(environment.contents)


def describe_manifest(
    file_name: str,
) -> tuple[str | None, str | None]:
    """
    Determine the entry point and/or primary file from the given manifest file.
    If no entry point is recorded in the manifest, then None will be returned for
    that.  The same is true for the primary document.  None will be returned for
    both if the file doesn't exist or doesn't look like a manifest file.

    :param file_name: the name of the manifest file to read.
    :return: the entry point and primary document from the manifest.
    """
    if basename(file_name) == "manifest.json" and exists(file_name):
        manifest, _ = read_manifest_file(file_name)
        metadata = manifest.get("metadata")
        if metadata:
            # noinspection SpellCheckingInspection
            return (
                metadata.get("entrypoint"),
                metadata.get("primary_rmd") or metadata.get("primary_html"),
            )
    return None, None


def write_quarto_manifest_json(
    file_or_directory: str,
    inspect: QuartoInspectResult,
    app_mode: AppMode,
    environment: Optional[Environment],
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
    env_management_py: Optional[bool] = None,
    env_management_r: Optional[bool] = None,
) -> None:
    """
    Creates and writes a manifest.json file for the given Quarto project.

    :param file_or_directory: The Quarto document or the directory containing the Quarto project.
    :param inspect: The parsed JSON from a 'quarto inspect' against the project.
    :param app_mode: The application mode to assume (such as AppModes.STATIC_QUARTO)
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :param env_management_py: False prevents Connect from managing the Python environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    :param env_management_r: False prevents Connect from managing the R environment for this bundle.
        The server administrator is responsible for installing packages in the runtime environment. Default = None.
    """

    manifest, _ = make_quarto_manifest(
        file_or_directory,
        inspect,
        app_mode,
        environment,
        extra_files,
        excludes,
        image,
    )

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = dirname(file_or_directory)
    manifest_path = join(base_dir, "manifest.json")
    write_manifest_json(manifest_path, manifest)


def write_tensorflow_manifest_json(
    directory: str,
    extra_files: Sequence[str],
    excludes: Sequence[str],
    image: Optional[str] = None,
) -> None:
    """
    Creates and writes a manifest.json file for the given TensorFlow content.

    :param directory: The directory containing the TensorFlow model.
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    """

    manifest = make_tensorflow_manifest(
        directory,
        extra_files,
        excludes,
        image,
    )
    manifest_path = join(directory, "manifest.json")
    write_manifest_json(manifest_path, manifest)


def write_manifest_json(manifest_path: str | Path, manifest: ManifestData) -> None:
    """
    Write the manifest data as JSON to the named manifest.json with a trailing newline.
    """
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def create_python_environment(
    directory: str,
    force_generate: bool = False,
    python: Optional[str] = None,
    override_python_version: Optional[str] = None,
) -> Environment:
    module_file = fake_module_file_from_directory(directory)

    # click.secho('    Deploying %s to server "%s"' % (directory, connect_server.url))

    _warn_on_ignored_manifest(directory)
    _warn_if_no_requirements_file(directory)
    _warn_if_environment_directory(directory)

    # with cli_feedback("Inspecting Python environment"):
    _, environment = get_python_env_info(module_file, python, force_generate, override_python_version)

    if force_generate:
        _warn_on_ignored_requirements(directory, environment.filename)

    return environment
