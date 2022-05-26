"""
Manifest generation and bundling utilities
"""

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile

try:
    import typing
except ImportError:
    typing = None

from os.path import basename, dirname, exists, isdir, join, relpath, splitext, isfile

from .log import logger
from .models import AppMode, AppModes, GlobSet
from .environment import Environment
from collections import defaultdict
from mimetypes import guess_type

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
    image: str,
    environment: Environment,
    entrypoint: str,
    quarto_inspection: typing.Dict[str, typing.Any],
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
    manifest = make_source_manifest(AppModes.JUPYTER_NOTEBOOK, image, environment, nb_name, None)
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
    hide_all_input: bool = False,
    hide_tagged_input: bool = False,
    image: str = None,
) -> typing.IO[bytes]:
    """Create a bundle containing the specified notebook and python environment.

    Returns a file-like object containing the bundle tarball.
    """
    if extra_files is None:
        extra_files = []
    base_dir = dirname(file)
    nb_name = basename(file)

    manifest = make_source_manifest(AppModes.JUPYTER_NOTEBOOK, image, environment, nb_name, None)
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


#
def make_quarto_source_bundle(
    directory: str,
    inspect: typing.Dict[str, typing.Any],
    app_mode: AppMode,
    image: str,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.IO[bytes]:
    """
    Create a bundle containing the specified Quarto content and (optional)
    python environment.

    Returns a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_quarto_manifest(
        directory, inspect, app_mode, image, environment, extra_files, excludes
    )
    bundle_file = tempfile.TemporaryFile(prefix="rsc_bundle")

    with tarfile.open(mode="w:gz", fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, "manifest.json", json.dumps(manifest, indent=2))
        if environment:
            bundle_add_buffer(bundle, environment.filename, environment.contents)

        for rel_path in relevant_files:
            bundle_add_file(bundle, rel_path, directory)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def make_html_manifest(
    filename: str,
    image: str,
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
    hide_all_input: bool = False,
    hide_tagged_input: bool = False,
    image: str = False,
    check_output: typing.Callable = subprocess.check_output,  # used to default to subprocess.check_output
) -> typing.IO[bytes]:
    # noinspection SpellCheckingInspection
    if check_output is None:
        check_output = subprocess.check_output

    cmd = [
        python,
        "-m",
        "jupyter",
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
    image: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:
    """
    Makes a manifest for an API.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param image: an optional docker image for off-host execution.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the manifest and a list of the files involved.
    """
    if is_environment_dir(directory):
        excludes = list(excludes or []) + ["bin/", "lib/"]

    relevant_files = _create_api_file_list(directory, environment.filename, extra_files, excludes)
    manifest = make_source_manifest(app_mode, image, environment, entry_point, None)

    manifest_add_buffer(manifest, environment.filename, environment.contents)

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, directory)

    return manifest, relevant_files


def make_html_bundle_content(
    path: str,
    entrypoint: str,
    image: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:
    """
    Makes a manifest for static html deployment.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: the manifest and a list of the files involved.
    """
    entrypoint = entrypoint or infer_entrypoint(path, "text/html")

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
    image: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.IO[bytes]:
    """
    Create an html bundle, given a path and a manifest.

    :param path: the file, or the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param image: an optional docker image for off-host execution.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_html_bundle_content(path, entry_point, image, extra_files, excludes)
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
    image: str,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.IO[bytes]:
    """
    Create an API bundle, given a directory path and a manifest.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param image: an optional docker image for off-host execution.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: a file-like object containing the bundle tarball.
    """
    manifest, relevant_files = make_api_manifest(
        directory, entry_point, app_mode, environment, image, extra_files, excludes
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
    directory: str,
    quarto_inspection: typing.Dict[str, typing.Any],
    app_mode: AppMode,
    image: str,
    environment: Environment,
    extra_files: typing.List[str],
    excludes: typing.List[str],
) -> typing.Tuple[typing.Dict[str, typing.Any], typing.List[str]]:
    """
    Makes a manifest for a Quarto project.

    :param directory: The directory containing the Quarto project.
    :param quarto_inspection: The parsed JSON from a 'quarto inspect' against the project.
    :param app_mode: The application mode to assume.
    :param image: an optional docker image for off-host execution.
    :param environment: The (optional) Python environment to use.
    :param extra_files: Any extra files to include in the manifest.
    :param excludes: A sequence of glob patterns to exclude when enumerating files to bundle.
    :return: the manifest and a list of the files involved.
    """
    if environment:
        extra_files = list(extra_files or []) + [environment.filename]

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

    relevant_files = _create_quarto_file_list(directory, extra_files, excludes)
    manifest = make_source_manifest(
        app_mode,
        image,
        environment,
        None,
        quarto_inspection,
    )

    for rel_path in relevant_files:
        manifest_add_file(manifest, rel_path, directory)

    return manifest, relevant_files
