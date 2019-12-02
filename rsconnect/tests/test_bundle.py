
import json
import sys
import tarfile

from unittest import TestCase
from os.path import dirname, exists, join

from rsconnect.environment import detect_environment
from rsconnect.bundle import list_files, make_notebook_html_bundle, make_notebook_source_bundle


class TestBundle(TestCase):
    def get_dir(self, name):
        py_version = 'py%d' % sys.version_info[0]
        path = join(dirname(__file__), 'testdata', py_version, name)
        self.assertTrue(exists(path))
        return path

    def python_version(self):
        return u'.'.join(map(str, sys.version_info[:3]))

    def test_source_bundle1(self):
        self.maxDiff = 5000
        dir = self.get_dir('pip1')
        nb_path = join(dir, 'dummy.ipynb')

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = detect_environment(dir)
        with make_notebook_source_bundle(nb_path, environment) as bundle, \
            tarfile.open(mode='r:gz', fileobj=bundle) as tar:

            names = sorted(tar.getnames())
            self.assertEqual(names, [
                'dummy.ipynb',
                'manifest.json',
                'requirements.txt',
            ])

            reqs = tar.extractfile('requirements.txt').read()
            self.assertEqual(reqs, b'numpy\npandas\nmatplotlib\n')

            manifest = json.loads(tar.extractfile('manifest.json').read().decode('utf-8'))

            # don't check locale value, just require it be present
            del manifest['locale']
            del manifest['python']['package_manager']['version']

            if sys.version_info[0] == 2:
                ipynb_hash = u"38aa30662bc16e91e6804cf21d7722f7"
            else:
                ipynb_hash = u"36873800b48ca5ab54760d60ba06703a"

            self.assertEqual(manifest, {
                u"version": 1,
                u"metadata": {
                    u"appmode": u"jupyter-static",
                    u"entrypoint": u"dummy.ipynb"
                },
                u"python": {
                    u"version": self.python_version(),
                    u"package_manager": {
                        u"name": u"pip",
                        u"package_file": u"requirements.txt"
                    }
                },
                u"files": {
                    u"dummy.ipynb": {
                        u"checksum": ipynb_hash,
                    },
                    u"requirements.txt": {
                        u"checksum": u"5f2a5e862fe7afe3def4a57bb5cfb214"
                    }
                }
            })

    def test_source_bundle2(self):
        self.maxDiff = 5000
        dir = self.get_dir('pip2')
        nb_path = join(dir, 'dummy.ipynb')

        # Note that here we are introspecting the environment from within
        # the test environment. Don't do this in the production code, which
        # runs in the notebook server. We need the introspection to run in
        # the kernel environment and not the notebook server environment.
        environment = detect_environment(dir)

        with make_notebook_source_bundle(nb_path, environment, extra_files=['data.csv']) as bundle, \
            tarfile.open(mode='r:gz', fileobj=bundle) as tar:

            names = sorted(tar.getnames())
            self.assertEqual(names, [
                'data.csv',
                'dummy.ipynb',
                'manifest.json',
                'requirements.txt',
            ])

            reqs = tar.extractfile('requirements.txt').read()

            # these are the dependencies declared in our setup.py
            self.assertIn(b'six', reqs)

            manifest = json.loads(tar.extractfile('manifest.json').read().decode('utf-8'))

            # don't check requirements.txt since we don't know the checksum
            del manifest['files']['requirements.txt']

            # also don't check locale value, just require it be present
            del manifest['locale']
            del manifest['python']['package_manager']['version']

            if sys.version_info[0] == 2:
                ipynb_hash = u"38aa30662bc16e91e6804cf21d7722f7"
            else:
                ipynb_hash = u"36873800b48ca5ab54760d60ba06703a"

            self.assertEqual(manifest, {
                u"version": 1,
                u"metadata": {
                    u"appmode": u"jupyter-static",
                    u"entrypoint": u"dummy.ipynb"
                },
                u"python": {
                    u"version": self.python_version(),
                    u"package_manager": {
                        u"name": u"pip",
                        u"package_file": u"requirements.txt"
                    }
                },
                u"files": {
                    u"dummy.ipynb": {
                        u"checksum": ipynb_hash,
                    },
                    u"data.csv": {
                        u"checksum": u"f2bd77cc2752b3efbb732b761d2aa3c3"
                    }
                }
            })

    def test_list_files(self):
        paths = [
            'notebook.ipynb',
            'somedata.csv',
            'subdir/subfile',
            'subdir2/subfile2',
            '.ipynb_checkpoints/notebook.ipynb',
            '.git/config',
        ]

        def walk(base_dir):
            dirnames = []
            filenames = []

            for path in paths:
                if '/' in path:
                    dirname, filename = path.split('/', 1)
                    dirnames.append(dirname)
                else:
                    filenames.append(path)

            yield (base_dir, dirnames, filenames)

            for subdir in dirnames:
                for path in paths:
                    if path.startswith(subdir + '/'):
                        yield (base_dir + '/' + subdir, [], [path.split('/', 1)[1]])

        files = list_files('/', True, walk=walk)
        self.assertEqual(files, paths[:4])

        files = list_files('/', False, walk=walk)
        self.assertEqual(files, paths[:2])

    def test_html_bundle1(self):
        self.do_test_html_bundle(self.get_dir('pip1'))

    def test_html_bundle2(self):
        self.do_test_html_bundle(self.get_dir('pip2'))

    def do_test_html_bundle(self, dir):
        self.maxDiff = 5000
        nb_path = join(dir, 'dummy.ipynb')

        bundle = make_notebook_html_bundle(nb_path, sys.executable)

        tar = tarfile.open(mode='r:gz', fileobj=bundle)

        try:
            names = sorted(tar.getnames())
            self.assertEqual(names, [
                'dummy.html',
                'manifest.json',
            ])

            manifest = json.loads(tar.extractfile('manifest.json').read().decode('utf-8'))

            self.assertEqual(manifest, {
                u"version": 1,
                u"metadata": {
                    u"appmode": u"static",
                    u"primary_html": u"dummy.html"
                },
            })
        finally:
            tar.close()
            bundle.close()
