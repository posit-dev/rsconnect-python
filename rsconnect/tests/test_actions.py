import os
import sys
from unittest import TestCase

from rsconnect import api

from rsconnect.actions import _default_title, _default_title_from_manifest, which_python, _to_server_check_list, \
    _verify_server, check_server_capabilities, are_apis_supported_on_server, is_conda_supported_on_server, \
    _make_deployment_name, _validate_title, validate_entry_point
from rsconnect.api import RSConnectException, RSConnectServer
from rsconnect.tests.test_data_util import get_api_path


class TestActions(TestCase):
    @staticmethod
    def optional_target(default):
        return os.environ.get('CONNECT_DEPLOY_TARGET', default)

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
        no_api_support = {'python': {'api_enabled': False}}
        api_support = {'python': {'api_enabled': True}}

        with self.assertRaises(api.RSConnectException) as context:
            check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: no_api_support)
        self.assertEqual(str(context.exception), 'The RStudio Connect does not allow for Python APIs.')

        check_server_capabilities(None, (are_apis_supported_on_server,), lambda x: api_support)

        no_conda = api_support
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

    def test_validate_title(self):
        with self.assertRaises(RSConnectException):
            _validate_title('12')

        with self.assertRaises(RSConnectException):
            _validate_title('1' * 1025)

        _validate_title('123')
        _validate_title('1' * 1024)

    def test_validate_entry_point(self):
        directory = self.optional_target(get_api_path('flask'))

        self.assertEqual(validate_entry_point(directory, None)[0], 'app:app')
        self.assertEqual(validate_entry_point(directory, 'app')[0], 'app:app')

        with self.assertRaises(RSConnectException):
            validate_entry_point(directory, 'x:y:z')

        with self.assertRaises(RSConnectException):
            validate_entry_point(directory, 'bob:app')

        with self.assertRaises(RSConnectException):
            validate_entry_point(directory, 'app:bogus_app')

    def test_make_deployment_name(self):
        self.assertEqual(_make_deployment_name('title'), 'title')
        self.assertEqual(_make_deployment_name('Title'), 'title')
        self.assertEqual(_make_deployment_name('My Title'), 'my_title')
        self.assertEqual(_make_deployment_name('My  Title'), 'my_title')
        self.assertEqual(_make_deployment_name('My _ Title'), 'my_title')
        self.assertEqual(_make_deployment_name('My-Title'), 'my-title')
        # noinspection SpellCheckingInspection
        self.assertEqual(_make_deployment_name(u'M\ry\n \tT\u2103itle'), 'my_title')
        self.assertEqual(_make_deployment_name(u'\r\n\t\u2103'), '___')
        self.assertEqual(_make_deployment_name(u'\r\n\tR\u2103'), '__r')

    def test_default_title(self):
        self.assertEqual(_default_title('testing.txt'), 'testing')
        self.assertEqual(_default_title('this.is.a.test.ext'), 'this.is.a.test')
        self.assertEqual(_default_title('1.ext'), '001')
        self.assertEqual(_default_title('%s.ext' % ('n' * 2048)), 'n' * 1024)

    def test_default_title_from_manifest(self):
        self.assertEqual(_default_title_from_manifest({}, 'dir/to/manifest.json'), '0to')
        # noinspection SpellCheckingInspection
        m = {'metadata': {'entrypoint': 'point'}}
        self.assertEqual(_default_title_from_manifest(m, 'dir/to/manifest.json'), 'point')
        m = {'metadata': {'primary_rmd': 'file.Rmd'}}
        self.assertEqual(_default_title_from_manifest(m, 'dir/to/manifest.json'), 'file')
        m = {'metadata': {'primary_html': 'page.html'}}
        self.assertEqual(_default_title_from_manifest(m, 'dir/to/manifest.json'), 'page')
        m = {'metadata': {'primary_wat?': 'my-cool-thing.wat'}}
        self.assertEqual(_default_title_from_manifest(m, 'dir/to/manifest.json'), '0to')
        # noinspection SpellCheckingInspection
        m = {'metadata': {'entrypoint': 'module:object'}}
        self.assertEqual(_default_title_from_manifest(m, 'dir/to/manifest.json'), '0to')
