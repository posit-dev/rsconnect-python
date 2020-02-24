import sys
from os.path import join, dirname, exists


def get_dir(name):
    py_version = 'py%d' % sys.version_info[0]
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), 'testdata', py_version, name)
    if not exists(path):
        raise AssertionError('%s does not exist' % path)
    return path


def get_manifest_path(name, parent='R'):
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), 'testdata', parent, name, 'manifest.json')
    if not exists(path):
        raise AssertionError('%s does not exist' % path)
    return path


def get_api_path(name, parent='api'):
    # noinspection SpellCheckingInspection
    path = join(dirname(__file__), 'testdata', parent, name)
    if not exists(path):
        raise AssertionError('%s does not exist' % path)
    return path
