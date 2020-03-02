import ctypes
import glob
import hashlib
import io
import json
import logging
import os
import subprocess
import tarfile
import tempfile

from os.path import basename, dirname, exists, isdir, join, relpath, splitext

from rsconnect.models import AppModes

log = logging.getLogger('rsconnect')
# From https://github.com/rstudio/rsconnect/blob/485e05a26041ab8183a220da7a506c9d3a41f1ff/R/bundle.R#L85-L88
# noinspection SpellCheckingInspection
directories_to_ignore = ['rsconnect-python/', 'packrat/', '.svn/', '.git/', '.Rproj.user/']


# Special hidden check for Windows systems.
def has_hidden_attribute(filepath):
    try:
        attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
        assert attrs != -1
        result = bool(attrs & 2)
    except (AttributeError, AssertionError):
        result = False
    return result


def is_hidden(filepath):
    name = os.path.basename(os.path.abspath(filepath))
    return name.startswith('.') or has_hidden_attribute(filepath)


# noinspection SpellCheckingInspection
def make_source_manifest(entrypoint, environment, app_mode):
    package_manager = environment['package_manager']

    # noinspection SpellCheckingInspection
    manifest = {
        "version": 1,
        "metadata": {
            "appmode": app_mode.name(),
            "entrypoint": entrypoint
        },
        "locale": environment['locale'],
        "python": {
            "version": environment['python'],
            "package_manager": {
                "name": package_manager,
                "version": environment[package_manager],
                "package_file": environment['filename']
            }
        },
        "files": {}
    }
    return manifest


def manifest_add_file(manifest, rel_path, base_dir):
    """Add the specified file to the manifest files section

    The file must be specified as a pathname relative to the notebook directory.
    """
    path = join(base_dir, rel_path)

    manifest['files'][rel_path] = {
        'checksum': file_checksum(path)
    }


def manifest_add_buffer(manifest, filename, buf):
    """Add the specified in-memory buffer to the manifest files section"""
    manifest['files'][filename] = {
        'checksum': buffer_checksum(buf)
    }


def file_checksum(path):
    """Calculate the md5 hex digest of the specified file"""
    with open(path, 'rb') as f:
        m = hashlib.md5()
        chunk_size = 64 * 1024

        chunk = f.read(chunk_size)
        while chunk:
            m.update(chunk)
            chunk = f.read(chunk_size)
        return m.hexdigest()


def buffer_checksum(buf):
    """Calculate the md5 hex digest of a buffer (str or bytes)"""
    m = hashlib.md5()
    m.update(to_bytes(buf))
    return m.hexdigest()


def to_bytes(s):
    if hasattr(s, 'encode'):
        return s.encode('utf-8')
    return s


def bundle_add_file(bundle, rel_path, base_dir):
    """Add the specified file to the tarball.

    The file path is relative to the notebook directory.
    """
    path = join(base_dir, rel_path)
    bundle.add(path, arcname=rel_path)
    log.debug('added file: %s', path)


def bundle_add_buffer(bundle, filename, contents):
    """Add an in-memory buffer to the tarball.

    `contents` may be a string or bytes object
    """
    buf = io.BytesIO(to_bytes(contents))
    file_info = tarfile.TarInfo(filename)
    file_info.size = len(buf.getvalue())
    bundle.addfile(file_info, buf)
    log.debug('added buffer: %s', filename)


def write_manifest(relative_dir, nb_name, environment, output_dir):
    """Create a manifest for source publishing the specified notebook.

    The manifest will be written to `manifest.json` in the output directory..
    A requirements.txt file will be created if one does not exist.

    Returns the list of filenames written.
    """
    manifest_filename = 'manifest.json'
    manifest = make_source_manifest(nb_name, environment, AppModes.JUPYTER_NOTEBOOK)
    manifest_file = join(output_dir, manifest_filename)
    created = []
    skipped = []

    manifest_relative_path = join(relative_dir, manifest_filename)
    if exists(manifest_file):
        skipped.append(manifest_relative_path)
    else:
        with open(manifest_file, 'w') as f:
            f.write(json.dumps(manifest, indent=2))
            created.append(manifest_relative_path)
            log.debug('wrote manifest file: %s', manifest_file)

    environment_filename = environment['filename']
    environment_file = join(output_dir, environment_filename)
    environment_relative_path = join(relative_dir, environment_filename)
    if exists(environment_file):
        skipped.append(environment_relative_path)
    else:
        with open(environment_file, 'w') as f:
            f.write(environment['contents'])
            created.append(environment_relative_path)
            log.debug('wrote environment file: %s', environment_file)

    return created, skipped


def list_files(base_dir, include_sub_dirs, walk=os.walk):
    """List the files in the directory at path.

    If include_sub_dirs is True, recursively list
    files in subdirectories.

    Returns an iterable of file paths relative to base_dir.
    """
    skip_dirs = ['.ipynb_checkpoints', '.git']

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


def make_notebook_source_bundle(file, environment, extra_files=None):
    """Create a bundle containing the specified notebook and python environment.

    Returns a file-like object containing the bundle tarball.
    """
    if extra_files is None:
        extra_files = []
    base_dir = dirname(file)
    nb_name = basename(file)

    manifest = make_source_manifest(nb_name, environment, AppModes.JUPYTER_NOTEBOOK)
    manifest_add_file(manifest, nb_name, base_dir)
    manifest_add_buffer(manifest, environment['filename'], environment['contents'])

    if extra_files:
        skip = [nb_name, environment['filename'], 'manifest.json']
        extra_files = sorted(list(set(extra_files) - set(skip)))

    for rel_path in extra_files:
        manifest_add_file(manifest, rel_path, base_dir)

    log.debug('manifest: %r', manifest)

    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')
    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:

        # add the manifest first in case we want to partially untar the bundle for inspection
        bundle_add_buffer(bundle, 'manifest.json', json.dumps(manifest, indent=2))
        bundle_add_buffer(bundle, environment['filename'], environment['contents'])
        bundle_add_file(bundle, nb_name, base_dir)

        for rel_path in extra_files:
            bundle_add_file(bundle, rel_path, base_dir)

    bundle_file.seek(0)
    return bundle_file


def make_html_manifest(filename):
    # noinspection SpellCheckingInspection
    return {
        "version": 1,
        "metadata": {
            "appmode": "static",
            "primary_html": filename,
        },
    }


def make_notebook_html_bundle(filename, python, check_output=subprocess.check_output):
    # noinspection SpellCheckingInspection
    cmd = [
        python, '-m', 'jupyter',
        'nbconvert', '--execute', '--stdout',
        '--log-level', 'ERROR', filename
    ]
    try:
        output = check_output(cmd)
    except subprocess.CalledProcessError:
        raise

    nb_name = basename(filename)
    filename = splitext(nb_name)[0] + '.html'

    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')

    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, filename, output)

        # manifest
        manifest = make_html_manifest(filename)
        bundle_add_buffer(bundle, 'manifest.json', json.dumps(manifest))

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
    with open(manifest_path, 'rb') as f:
        raw_manifest = f.read().decode('utf-8')
        manifest = json.loads(raw_manifest)

    return manifest, raw_manifest


def make_manifest_bundle(manifest_path):
    """Create a bundle, given a manifest.

    :return: a file-like object containing the bundle tarball.
    """
    manifest, raw_manifest = read_manifest_file(manifest_path)

    base_dir = dirname(manifest_path)
    files = list(filter(keep_manifest_specified_file, manifest.get('files', {}).keys()))

    if 'manifest.json' in files:
        # this will be created
        files.remove('manifest.json')

    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')
    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:
        # add the manifest first in case we want to partially untar the bundle for inspection
        bundle_add_buffer(bundle, 'manifest.json', raw_manifest)

        for rel_path in files:
            bundle_add_file(bundle, rel_path, base_dir)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file


def _get_hidden_files(directory):
    """
    Look in a directory for hidden files.  The result will be a sequence of
    those files.  If a hidden directory is found, then **all** files under
    that directory are also considered hidden and returned in the result.

    :param directory: the directory to search.
    :return: the list of hidden files in that directory.
    """
    result = []
    for name in os.listdir(directory):
        path = join(directory, name)
        if is_hidden(path):
            if isdir(path):
                for subdir, dirs, files in os.walk(path):
                    for file in files:
                        result.append(join(subdir, file))
            else:
                result.append(path)
    return result


def expand_globs(directory, excludes):
    """
    Takes a list of glob strings, joins each one in turn to the specified directory
    and produce a list of matching files.  The list returned is sorted and will not
    contain duplicates.

    :param directory: the directory the globs are relative to.
    :param excludes: the list of globs to expand.
    :return: a sorted list of unique file names.
    """
    work = []
    if excludes:
        for pattern in excludes:
            file_pattern = join(directory, pattern)
            # Special handling, if they gave us just a dir then "do the right thing".
            if isdir(file_pattern):
                file_pattern = join(file_pattern, '/**/*')
            files = glob.glob(file_pattern, recursive=True)
            hidden = []
            # Since glob doesn't see hidden files, look for any hidden files/dirs under
            # an excluded directory.
            for file in files:
                if isdir(file):
                    hidden.extend(_get_hidden_files(file))
            work.extend(files)
            work.extend(hidden)

    # Remove unnecessary duplicates.
    return sorted(list(set(work)))


def make_api_bundle(directory, entry_point, app_mode, environment, extra_files=None, excludes=None):
    """
    Create an API bundle, given a directory path and a manifest.

    :param directory: the directory containing the files to deploy.
    :param entry_point: the main entry point for the API.
    :param app_mode: the app mode to use.
    :param environment: the Python environment information.
    :param extra_files: a sequence of any extra files to include in the bundle.
    :param excludes: a sequence of glob patterns that will exclude matched files.
    :return: a file-like object containing the bundle tarball.
    """
    if extra_files is None:
        extra_files = []

    manifest = make_source_manifest(entry_point, environment, app_mode)
    bundle_file = tempfile.TemporaryFile(prefix='rsc_bundle')
    excludes = expand_globs(directory, excludes)

    manifest_add_buffer(manifest, environment['filename'], environment['contents'])

    if extra_files:
        skip = [environment['filename'], 'manifest.json']
        extra_files = sorted(list(set(extra_files) - set(skip)))

    for rel_path in extra_files:
        manifest_add_file(manifest, rel_path, directory)

    with tarfile.open(mode='w:gz', fileobj=bundle_file) as bundle:
        bundle_add_buffer(bundle, 'manifest.json', json.dumps(manifest, indent=2))
        bundle_add_buffer(bundle, environment['filename'], environment['contents'])

        for subdir, dirs, files in os.walk(directory):
            for file in files:
                abs_path = os.path.join(subdir, file)
                rel_path = os.path.relpath(abs_path, directory)

                if keep_manifest_specified_file(rel_path) and \
                        (rel_path in extra_files or abs_path not in excludes) and \
                        rel_path != environment['filename']:
                    bundle.add(abs_path, arcname=rel_path)
                    # Don't add extra files more than once.
                    if rel_path in extra_files:
                        extra_files.remove(rel_path)

        for rel_path in extra_files:
            bundle_add_file(bundle, rel_path, directory)

    # rewind file pointer
    bundle_file.seek(0)

    return bundle_file
