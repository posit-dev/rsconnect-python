import sys
from unittest import TestCase

from rsconnect.actions import default_title, default_title_from_manifest, which_python, _to_server_check_list,\
    _verify_server
from rsconnect.api import RSConnectException, RSConnectServer


class TestActions(TestCase):
    def test_which_python(self):
        with self.assertRaises(RSConnectException):
            which_python('fake.file')

        with self.assertRaises(RSConnectException):
            which_python(__file__)

        self.assertEqual(which_python(sys.executable), sys.executable)
        self.assertEqual(which_python(None), sys.executable)
        self.assertEqual(which_python(None, {'RETICULATE_PYTHON': 'fake-python'}), 'fake-python')

    def test_verify_server(self):
        with self.assertRaises(RSConnectException):
            _verify_server(RSConnectServer('fake-url', None))

    def test_to_server_check_list(self):
        l = _to_server_check_list('no-scheme')

        self.assertEqual(l, ['https://no-scheme', 'http://no-scheme'])

        l = _to_server_check_list('//no-scheme')

        self.assertEqual(l, ['https://no-scheme', 'http://no-scheme'])

        l = _to_server_check_list('scheme://no-scheme')

        self.assertEqual(l, ['scheme://no-scheme'])

    def test_default_title(self):
        self.assertEqual(default_title('testing.txt'), 'testing')
        self.assertEqual(default_title('this.is.a.test.ext'), 'this.is.a.test')
        self.assertEqual(default_title('1.ext'), '001')
        self.assertEqual(default_title('%s.ext' % ('n' * 2048)), 'n' * 1024)

    def test_default_title_from_manifest(self):
        self.assertEqual(default_title_from_manifest({}), 'manifest')
        m = {'metadata': {'entrypoint': 'point'}}
        self.assertEqual(default_title_from_manifest(m), 'point')
        m = {'metadata': {'primary_rmd': 'file.Rmd'}}
        self.assertEqual(default_title_from_manifest(m), 'file')
        m = {'metadata': {'primary_html': 'page.html'}}
        self.assertEqual(default_title_from_manifest(m), 'page')
        m = {'metadata': {'primary_wat?': 'my-cool-thing.wat'}}
        self.assertEqual(default_title_from_manifest(m), 'manifest')
