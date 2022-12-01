"""
Manifest generation and bundling utilities
"""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import re
from pprint import pformat
from collections import defaultdict
from mimetypes import guess_type
import click


try:
    import typing
except ImportError:
    typing = None

from os.path import basename, dirname, exists, isdir, join, relpath, splitext, isfile, abspath

from .log import logger
from .models import AppMode, AppModes, GlobSet
from .environment import Environment, MakeEnvironment
from .exception import RSConnectException

_module_pattern = re.compile(r"^[A-Za-z0-9_]+:[A-Za-z0-9_]+$")

# From https://github.com/rstudio/rsconnect/blob/485e05a26041ab8183a220da7a506c9d3a41f1ff/R/bundle.R#L85-L88
# noinspection SpellCheckingInspection
directories_to_ignore = [
    ".Rproj.user/",
    ".env/",
    ".git/",
    ".svn/",
    ".venv/",
    "__pycache__/",
    "env/",
    "packrat/",
    "renv/",
    "rsconnect-python/",
    "rsconnect/",
    "venv/",
]


# noinspection SpellCheckingInspection
def make_source_manifest(
    app_mode: AppMode,
    environment: Environment,
    entrypoint: str,
    quarto_inspection: typing.Dict[str, typing.Any],
    image: str = None,
) -> typing.Dict[str, typing.Any]:

    manifest = {
        "version": 1,
    }  # type: typing.Dict[str, typing.Any]

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
        project_config = quarto_inspection.get("config", {}).get("project", {})
        render_targets = project_config.get("render", [])
        if len(render_targets):
            manifest["metadata"]["primary_rmd"] = render_targets[0]
        project_type = project_config.get("type", None)
        if project_type or len(render_targets) > 1:
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

    if image:
        manifest["environment"] = {
            "image": image,
        }

    manifest["files"] = {}

    return manifest


def manifest_add_file(manifest, rel_path, base_dir):
    """Add the specified file to the manifest files section

    The file must be specified as a pathname relative to the notebook directory.
    """
    path = join(base_dir, rel_path) if os.path.isdir(base_dir) else rel_path
    if "files" not in manifest:
        manifest["files"] = {}
    manifest["files"][rel_path] = {"checksum": file_checksum(path)}


def manifest_add_buffer(manifest, filename, buf):
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


def file_checksum(path):
    """Calculate the md5 hex digest of the specified file"""
    with open(path, "rb") as f:
        m = make_hasher()
        chunk_size = 64 * 1024

        chunk = f.read(chunk_size)
        while chunk:
            m.update(chunk)
            chunk = f.read(chunk_size)
        return m.hexdigest()


def buffer_checksum(buf):
    """Calculate the md5 hex digest of a buffer (str or bytes)"""
    m = make_hasher()
    m.update(to_bytes(buf))
    return m.hexdigest()


def to_bytes(s):
    if isinstance(s, bytes):
        return s
    elif hasattr(s, "encode"):
        return s.encode("utf-8")
    logger.warning("can't encode to bytes: %s" % type(s).__name__)
    return s


def bundle_add_file(bundle, rel_path, base_dir):
    """Add the specified file to the tarball.

    The file path is relative to the notebook directory.
    """
    path = join(base_dir, rel_path) if os.path.isdir(base_dir) else rel_path
    logger.debug("adding file: %s", rel_path)
    bundle.add(path, arcname=rel_path)


def bundle_add_buffer(bundle, filename, contents):
    """Add an in-memory buffer to the tarball.

    `contents` may be a string or bytes object
    """
    logger.debug("adding file: %s", filename)
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
    image: str = None,
) -> typing.Tuple[list, list]:
    """Create a manifest for source publishing the specified notebook.

    The manifest will be written to `manifest.json` in the output directory..
    A requirements.txt file will be created if one does not exist.

    Returns the list of filenames written.
    """
    manifest_filename = "manifest.json"
    manifest = make_source_manifest(AppModes.JUPYTER_NOTEBOOK, environment, nb_name, None, image)
    if hide_all_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_all_input": hide_all_input})
    if hide_tagged_input:
        if "jupyter" not in manifest:
            manifest["jupyter"] = {}
        manifest["jupyter"].update({"hide_tagged_input": hide_tagged_input})
    manifest_file = join(output_dir, manifest_filename)
    created = []
    skipped = []

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


def list_files(base_dir, include_sub_dirs, walk=os.walk):
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
    extra_files: typing.List[str],
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: str = None,
) -> typing.IO[bytes]:
    """Create a bundle containing the specified notebook and python environment.

    Returns a file-like object containing the bundle tarball.
    """
    if extra_files is None:
        extra_files = []
    base_dir = dirname(file)
    nb_name = basename(file)

    manifest = make_source_manifest(AppModes.JUPYTER_NOTEBOOK, environment, nb_name, None, image)
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
    inspect: typing.Dict[str, typing.Any],
    app_mode: AppMode,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> typing.IO[bytes]:
    """
    Create a bundle containing the specified Quarto content and (optional)
    python environment.

    Returns a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_quarto_manifest(
        file_or_directory, inspect, app_mode, environment, extra_files, excludes, image
    )
    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")

    base_dir = file_or_directory
    if not isdir(file_or_directory):
        base_dir = basename(file_or_directory)

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
    image: str = None,
) -> typing.Dict[str, typing.Any]:
    # noinspection SpellCheckingInspection
    manifest = {
        "version": 1,
        "metadata": {
            "appmode": "static",
            "primary_html": filename,
        },
    }
    if image:
        manifest["environment"] = {
            "image": image,
        }
    return manifest


def make_notebook_html_bundle(
    filename: str,
    python: str,
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: str = None,
    check_output: typing.Callable = subprocess.check_output,
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
        manifest = make_html_manifest(filename, image)
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest))

    # rewind file pointer
    bundle_file.seek(0)
    return bundle_file


def keep_manifest_specified_file(relative_path):
    """
    A helper to see if the relative path given, which is assumed to have come
    from a manifest.json file, should be kept or ignored.

    :param relative_path: the relative path name to check.
    :return: True, if the path should kept or False, if it should be ignored.
    """
    for ignore_me in directories_to_ignore:
        if relative_path.startswith(ignore_me):
            return False
    return True


def _default_title_from_manifest(the_manifest, manifest_file):
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


def read_manifest_app_mode(file):
    source_manifest, _ = read_manifest_file(file)
    # noinspection SpellCheckingInspection
    app_mode = AppModes.get_by_name(source_manifest["metadata"]["appmode"])
    return app_mode


def default_title_from_manifest(file):
    source_manifest, _ = read_manifest_file(file)
    title = _default_title_from_manifest(source_manifest, file)
    return title


def read_manifest_file(manifest_path):
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


def make_manifest_bundle(manifest_path):
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


def create_glob_set(directory, excludes):
    """
    Takes a list of glob strings and produces a GlobSet for path matching.

    **Note:** we don't use Python's glob support because it takes way too
    long to run when large file trees are involved in conjunction with the
    '**' pattern.

    :param directory: the directory the globs are relative to.
    :param excludes: the list of globs to expand.
    :return: a GlobSet ready for path matching.
    """
    work = []
    if excludes:
        for pattern in excludes:
            file_pattern = join(directory, pattern)
            # Special handling, if they gave us just a dir then "do the right thing".
            if isdir(file_pattern):
                file_pattern = join(file_pattern, "**/*")
            work.append(file_pattern)

    return GlobSet(work)


def is_environment_dir(directory):
    python_path = join(directory, "bin", "python")
    return exists(python_path)


def list_environment_dirs(directory):
    # type: (...) -> typing.List[str]
    """Returns a list of subdirectories in `directory` that appear to contain virtual environments."""
    envs = []

    for name in os.listdir(directory):
        path = join(directory, name)
        if is_environment_dir(path):
            envs.append(name)
    return envs


def _create_api_file_list(
    directory,  # type: str
    requirements_file_name,  # type: str
    extra_files=None,  # type: typing.Optional[typing.List[str]]
    excludes=None,  # type: typing.Optional[typing.List[str]]
):
    # type: (...) -> typing.List[str]
    """
    Builds a full list of files under the given directory that should be included
    in a manifest or bundle.  Extra files and excludes are relative to the given
    directory and work as you'd expect.

    :param directory: the directory to walk for files.
    :param requirements_file_name: the name of the requirements file for the current
    Python environment.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the list of relevant files, relative to the given directory.
    """
    # Don't let these top-level files be added via the extra files list.
    extra_files = extra_files or []
    skip = [requirements_file_name, "manifest.json"]
    extra_files = sorted(list(set(extra_files) - set(skip)))

    # Don't include these top-level files.
    excludes = list(excludes) if excludes else []
    excludes.append("manifest.json")
    excludes.append(requirements_file_name)
    excludes.extend(list_environment_dirs(directory))
    glob_set = create_glob_set(directory, excludes)

    file_list = []

    for subdir, dirs, files in os.walk(directory):
        for file in files:
            abs_path = os.path.join(subdir, file)
            rel_path = os.path.relpath(abs_path, directory)

            if keep_manifest_specified_file(rel_path) and (rel_path in extra_files or not glob_set.matches(abs_path)):
                file_list.append(rel_path)
                # Don't add extra files more than once.
                if rel_path in extra_files:
                    extra_files.remove(rel_path)

    for rel_path in extra_files:
        file_list.append(rel_path)

    return sorted(file_list)


def make_api_manifest(
    directory: str,
    entry_point: str,
    app_mode: AppMode,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:
    """
    Makes a manifest for an API.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: the manifest and a list of the files involved.
    """
    if is_environment_dir(directory):
        excludes = list(excludes or []) + ["bin/", "lib/"]

    relevant_files = _create_api_file_list(directory, environment.filename, extra_files, excludes)
    manifest = make_source_manifest(app_mode, environment, entry_point, None, image)

    manifest_add_buffer(manifest, environment.filename, environment.contents)

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, directory)

    return manifest, relevant_files


def make_html_bundle_content(
    path: str,
    entrypoint: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:

    """
    Makes a manifest for static html deployment.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: the manifest and a list of the files involved.
    """
    extra_files = list(extra_files) if extra_files else []
    entrypoint = entrypoint or infer_entrypoint(path=path, mimetype="text/html")

    if path.startswith(os.curdir):
        path = relpath(path)
    if entrypoint.startswith(os.curdir):
        entrypoint = relpath(entrypoint)
    extra_files = [relpath(f) if isfile(f) and f.startswith(os.curdir) else f for f in extra_files]

    if is_environment_dir(path):
        excludes = list(excludes or []) + ["bin/", "lib/"]

    extra_files = extra_files or []
    skip = ["manifest.json"]
    extra_files = sorted(list(set(extra_files) - set(skip)))

    # Don't include these top-level files.
    excludes = list(excludes) if excludes else []
    excludes.append("manifest.json")
    if not isfile(path):
        excludes.extend(list_environment_dirs(path))
    glob_set = create_glob_set(path, excludes)

    file_list = []

    for rel_path in extra_files:
        file_list.append(rel_path)

    if isfile(path):
        file_list.append(path)
    else:
        for subdir, dirs, files in os.walk(path):
            for file in files:
                abs_path = os.path.join(subdir, file)
                rel_path = os.path.relpath(abs_path, path)

                if keep_manifest_specified_file(rel_path) and (
                    rel_path in extra_files or not glob_set.matches(abs_path)
                ):
                    file_list.append(rel_path)
                    # Don't add extra files more than once.
                    if rel_path in extra_files:
                        extra_files.remove(rel_path)

    relevant_files = sorted(file_list)
    manifest = make_html_manifest(entrypoint, image)

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, path)

    return manifest, relevant_files


def infer_entrypoint(path, mimetype):
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        raise ValueError("Entrypoint is not a valid file type or directory.")

    default_mimetype_entrypoints = {"text/html": "index.html"}
    if mimetype not in default_mimetype_entrypoints:
        raise ValueError("Not supported mimetype inference.")

    mimetype_filelist = defaultdict(list)

    for file in os.listdir(path):
        rel_path = os.path.join(path, file)
        if not os.path.isfile(rel_path):
            continue
        mimetype_filelist[guess_type(file)[0]].append(rel_path)
        if file in default_mimetype_entrypoints[mimetype]:
            return file
    return mimetype_filelist[mimetype].pop() if len(mimetype_filelist[mimetype]) == 1 else None


def make_html_bundle(
    path: str,
    entry_point: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> typing.IO[bytes]:
    """
    Create an html bundle, given a path and a manifest.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_html_bundle_content(path, entry_point, extra_files, excludes, image)
    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")

    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))

        for rel_path in relevant_files:
            bundle_add_file(bundle, rel_path, path)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def make_api_bundle(
    directory: str,
    entry_point: str,
    app_mode: AppMode,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
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
    :return: a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_api_manifest(
        directory, entry_point, app_mode, environment, extra_files, excludes, image
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
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.List[str]:
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
    glob_set = create_glob_set(directory, excludes)

    file_list = []

    for subdir, dirs, files in os.walk(directory):
        for file in files:
            abs_path = os.path.join(subdir, file)
            rel_path = os.path.relpath(abs_path, directory)

            if keep_manifest_specified_file(rel_path) and (rel_path in extra_files or not glob_set.matches(abs_path)):
                file_list.append(rel_path)
                # Don't add extra files more than once.
                if rel_path in extra_files:
                    extra_files.remove(rel_path)

    for rel_path in extra_files:
        file_list.append(rel_path)

    return sorted(file_list)


def make_quarto_manifest(
    file_or_directory: str,
    quarto_inspection: typing.Dict[str, typing.Any],
    app_mode: AppMode,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:
    """
    Makes a manifest for a Quarto project.

    :param file_or_directory: The Quarto document or the directory containing the Quarto project.
    :param quarto_inspection: The parsed JSON from a 'quarto inspect' against the project.
    :param app_mode: The application mode to assume.
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    :return: the manifest and a list of the files involved.
    """
    if environment:
        extra_files = list(extra_files or []) + [environment.filename]

    base_dir = file_or_directory
    if isdir(file_or_directory):
        # Directory as a Quarto project.
        excludes = list(excludes or []) + [".quarto"]

        project_config = quarto_inspection.get("config", {}).get("project", {})
        output_dir = project_config.get("output-dir", None)
        if output_dir:
            excludes = excludes + [output_dir]
        else:
            render_targets = project_config.get("render", [])
            for target in render_targets:
                t, _ = splitext(target)
                # TODO: Single-file inspect would give inspect.formats.html.pandoc.output-file
                # For foo.qmd, we would get an output-file=foo.html, but foo_files is not available.
                excludes = excludes + [t + ".html", t + "_files"]

        relevant_files = _create_quarto_file_list(base_dir, extra_files, excludes)
    else:
        # Standalone Quarto document
        base_dir = dirname(file_or_directory)
        relevant_files = [file_or_directory] + extra_files

    manifest = make_source_manifest(
        app_mode,
        environment,
        None,
        quarto_inspection,
        image,
    )

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, base_dir)

    return manifest, relevant_files


def _validate_title(title):
    """
    If the user specified a title, validate that it meets Connect's length requirements.
    If the validation fails, an exception is raised.  Otherwise,

    :param title: the title to validate.
    """
    if title:
        if not (3 <= len(title) <= 1024):
            raise RSConnectException("A title must be between 3-1024 characters long.")


def _default_title(file_name):
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


def validate_file_is_notebook(file_name):
    """
    Validate that the given file is a Jupyter Notebook. If it isn't, an exception is
    thrown.  A file must exist and have the '.ipynb' extension.

    :param file_name: the name of the file to validate.
    """
    file_suffix = splitext(file_name)[1].lower()
    if file_suffix != ".ipynb" or not exists(file_name):
        raise RSConnectException("A Jupyter notebook (.ipynb) file is required here.")


def validate_extra_files(directory, extra_files):
    """
    If the user specified a list of extra files, validate that they all exist and are
    beneath the given directory and, if so, return a list of them made relative to that
    directory.

    :param directory: the directory that the extra files must be relative to.
    :param extra_files: the list of extra files to qualify and validate.
    :return: the extra files qualified by the directory.
    """
    result = []
    if extra_files:
        for extra in extra_files:
            extra_file = relpath(extra, directory)
            # It's an error if we have to leave the given dir to get to the extra
            # file.
            if extra_file.startswith("../"):
                raise RSConnectException("%s must be under %s." % (extra_file, directory))
            if not exists(join(directory, extra_file)):
                raise RSConnectException("Could not find file %s under %s" % (extra, directory))
            result.append(extra_file)
    return result


def validate_manifest_file(file_or_directory):
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


def get_default_entrypoint(directory):
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

    logger.warning("Can't determine entrypoint; defaulting to 'app'")
    return "app"


def validate_entry_point(entry_point, directory):
    """
    Validates the entry point specified by the user, expanding as necessary.  If the
    user specifies nothing, a module of "app" is assumed.  If the user specifies a
    module only, the object is assumed to be the same name as the module.

    :param entry_point: the entry point as specified by the user.
    :return: the fully expanded and validated entry point and the module file name..
    """
    if not entry_point:
        entry_point = get_default_entrypoint(directory)

    parts = entry_point.split(":")

    if len(parts) > 2:
        raise RSConnectException('Entry point is not in "module:object" format.')

    return entry_point


def _warn_on_ignored_manifest(directory):
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


def _warn_if_no_requirements_file(directory):
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


def _warn_if_environment_directory(directory):
    """
    Issue a warning if the deployment directory is itself a virtualenv (yikes!).

    :param directory: the directory to check in.
    """
    if is_environment_dir(directory):
        click.secho(
            "    Warning: The deployment directory appears to be a python virtual environment.\n"
            "             Excluding the 'bin' and 'lib' directories.",
            fg="yellow",
        )


def _warn_on_ignored_requirements(directory, requirements_file_name):
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


def fake_module_file_from_directory(directory: str):
    """
    Takes a directory and invents a properly named file that though possibly fake,
    can be used for other name/title derivation.

    :param directory: the directory to start with.
    :return: the directory plus the (potentially) fake module file.
    """
    app_name = abspath(directory)
    app_name = dirname(app_name) if app_name.endswith(os.path.sep) else basename(app_name)
    return join(directory, app_name + ".py")


def are_apis_supported_on_server(connect_details):
    """
    Returns whether or not the Connect server has Python itself enabled and its license allows
    for API usage.  This controls whether APIs may be deployed..

    :param connect_details: details about a Connect server as returned by gather_server_details()
    :return: boolean True if the Connect server supports Python APIs or not or False if not.
    :error: The Posit Connect server does not allow for Python APIs.
    """
    return connect_details["python"]["api_enabled"]


def which_python(python, env=os.environ):
    """Determine which python binary should be used.

    In priority order:
    * --python specified on the command line
    * RETICULATE_PYTHON defined in the environment
    * the python binary running this script
    """
    if python:
        if not (exists(python) and os.access(python, os.X_OK)):
            raise RSConnectException('The file, "%s", does not exist or is not executable.' % python)
        return python

    if "RETICULATE_PYTHON" in env:
        return os.path.expanduser(env["RETICULATE_PYTHON"])

    return sys.executable


def inspect_environment(
    python,  # type: str
    directory,  # type: str
    conda_mode=False,  # type: bool
    force_generate=False,  # type: bool
    check_output=subprocess.check_output,  # type: typing.Callable
):
    # type: (...) -> Environment
    """Run the environment inspector using the specified python binary.

    Returns a dictionary of information about the environment,
    or containing an "error" field if an error occurred.
    """
    flags = []
    if conda_mode:
        flags.append("c")
    if force_generate:
        flags.append("f")
    args = [python, "-m", "rsconnect.environment"]
    if len(flags) > 0:
        args.append("-" + "".join(flags))
    args.append(directory)
    try:
        environment_json = check_output(args, universal_newlines=True)
    except subprocess.CalledProcessError as e:
        raise RSConnectException("Error inspecting environment: %s" % e.output)
    return MakeEnvironment(**json.loads(environment_json))  # type: ignore


def get_python_env_info(file_name, python, conda_mode=False, force_generate=False):
    """
    Gathers the python and environment information relating to the specified file
    with an eye to deploy it.

    :param file_name: the primary file being deployed.
    :param python: the optional name of a Python executable.
    :param conda_mode: inspect the environment assuming Conda
    :param force_generate: force generating "requirements.txt" or "environment.yml",
    even if it already exists.
    :return: information about the version of Python in use plus some environmental
    stuff.
    """
    python = which_python(python)
    logger.debug("Python: %s" % python)
    environment = inspect_environment(python, dirname(file_name), conda_mode=conda_mode, force_generate=force_generate)
    if environment.error:
        raise RSConnectException(environment.error)
    logger.debug("Python: %s" % python)
    logger.debug("Environment: %s" % pformat(environment._asdict()))

    return python, environment


def create_notebook_manifest_and_environment_file(
    entry_point_file: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: typing.List[str],
    force: bool,
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: str = None,
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
    :return:
    """
    if (
        not write_notebook_manifest_json(
            entry_point_file, environment, app_mode, extra_files, hide_all_input, hide_tagged_input, image
        )
        or force
    ):
        write_environment_file(environment, dirname(entry_point_file))


def write_notebook_manifest_json(
    entry_point_file: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: typing.List[str],
    hide_all_input: bool,
    hide_tagged_input: bool,
    image: str = None,
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

    manifest_data = make_source_manifest(app_mode, environment, file_name, None, image)
    if hide_all_input or hide_tagged_input:
        if "jupyter" not in manifest_data:
            manifest_data["jupyter"] = dict()
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


def create_api_manifest_and_environment_file(
    directory: str,
    entry_point: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    force: bool,
    image: str = None,
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
    :return:
    """
    if (
        not write_api_manifest_json(directory, entry_point, environment, app_mode, extra_files, excludes, image)
        or force
    ):
        write_environment_file(environment, directory)


def write_api_manifest_json(
    directory: str,
    entry_point: str,
    environment: Environment,
    app_mode: AppMode,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
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
    :return: whether or not the environment file (requirements.txt, environment.yml,
    etc.) that goes along with the manifest exists.
    """
    extra_files = validate_extra_files(directory, extra_files)
    manifest, _ = make_api_manifest(directory, entry_point, app_mode, environment, extra_files, excludes, image)
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
) -> typing.Tuple[str, str]:
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
    directory: str,
    inspect: typing.Any,
    app_mode: AppMode,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
    image: str = None,
) -> None:
    """
    Creates and writes a manifest.json file for the given Quarto project.

    :param directory: The directory containing the Quarto project.
    :param inspect: The parsed JSON from a 'quarto inspect' against the project.
    :param app_mode: The application mode to assume (such as AppModes.STATIC_QUARTO)
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :param image: the optional docker image to be specified for off-host execution. Default = None.
    """

    extra_files = validate_extra_files(directory, extra_files)
    manifest, _ = make_quarto_manifest(directory, inspect, app_mode, environment, extra_files, excludes, image)
    manifest_path = join(directory, "manifest.json")

    write_manifest_json(manifest_path, manifest)


def write_manifest_json(manifest_path, manifest):
    """
    Write the manifest data as JSON to the named manifest.json with a trailing newline.
    """
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def create_python_environment(
    directory: str = None,
    force_generate: bool = False,
    python: str = None,
    conda: bool = False,
):
    module_file = fake_module_file_from_directory(directory)

    # click.secho('    Deploying %s to server "%s"' % (directory, connect_server.url))

    _warn_on_ignored_manifest(directory)
    _warn_if_no_requirements_file(directory)
    _warn_if_environment_directory(directory)

    # with cli_feedback("Inspecting Python environment"):
    _, environment = get_python_env_info(module_file, python, conda, force_generate)

    if force_generate:
        _warn_on_ignored_requirements(directory, environment.filename)

    return environment
