import sys
from unittest import TestCase

from rsconnect import api

from rsconnect.actions import default_title, default_title_from_manifest, which_python, _to_server_check_list, \
    _verify_server, check_server_capabilities, is_version_1_8_2_or_higher, is_conda_supported_on_server
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
        a_list = _to_server_check_list('no-scheme')

        self.assertEqual(a_list, ['https://no-scheme', 'http://no-scheme'])

        a_list = _to_server_check_list('//no-scheme')

        self.assertEqual(a_list, ['https://no-scheme', 'http://no-scheme'])

        a_list = _to_server_check_list('scheme://no-scheme')

        self.assertEqual(a_list, ['scheme://no-scheme'])

    def test_check_server_capabilities(self):
        old_connect = {'connect': '1.8.0-42'}
        new_connect = {'connect': '1.8.1-1'}

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (is_version_1_8_2_or_higher,), lambda x: old_connect)
        self.assertEqual(str(context.exception), 'The RStudio Connect server must be at least v1.8.2.')

        check_server_capabilities(None, (is_version_1_8_2_or_higher,), lambda x: new_connect)

        no_conda = new_connect
        conda_not_supported = {'conda': {'supported': False}}
        conda_supported = {'conda': {'supported': True}}

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: no_conda)
        self.assertEqual(str(context.exception),
                         'Conda is not supported on the target server.  Try deploying without requesting Conda.')

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: conda_not_supported)
        self.assertEqual(str(context.exception),
                         'Conda is not supported on the target server.  Try deploying without requesting Conda.')

        check_server_capabilities(None, (is_conda_supported_on_server,), lambda x: conda_supported)

        # noinspection PyUnusedLocal
        def fake_cap(details):
            return False

        # noinspection PyUnusedLocal
        def fake_cap_with_doc(details):
            """A docstring."""
            return False

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (fake_cap,), lambda x: None)
        self.assertEqual(str(context.exception), 'The server does not satisfy the fake_cap capability check.')

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (fake_cap_with_doc,), lambda x: None)
        self.assertEqual(str(context.exception), 'The server does not satisfy the fake_cap_with_doc capability check.')

    def test_default_title(self):
        self.assertEqual(default_title('testing.txt'), 'testing')
        self.assertEqual(default_title('this.is.a.test.ext'), 'this.is.a.test')
        self.assertEqual(default_title('1.ext'), '001')
        self.assertEqual(default_title('%s.ext' % ('n' * 2048)), 'n' * 1024)

    def test_default_title_from_manifest(self):
        self.assertEqual(default_title_from_manifest({}), 'manifest')
        # noinspection SpellCheckingInspection
        m = {'metadata': {'entrypoint': 'point'}}
        self.assertEqual(default_title_from_manifest(m), 'point')
        m = {'metadata': {'primary_rmd': 'file.Rmd'}}
        self.assertEqual(default_title_from_manifest(m), 'file')
        m = {'metadata': {'primary_html': 'page.html'}}
        self.assertEqual(default_title_from_manifest(m), 'page')
        m = {'metadata': {'primary_wat?': 'my-cool-thing.wat'}}
        self.assertEqual(default_title_from_manifest(m), 'manifest')
