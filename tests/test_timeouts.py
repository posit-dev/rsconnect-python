import os

from unittest import TestCase
from unittest.mock import patch

from rsconnect.exception import RSConnectException
from rsconnect.timeouts import get_timeout


class GetTimeoutTestCase(TestCase):
    def test_get_default_timeout(self):
        timeout = get_timeout()
        self.assertEqual(300, timeout)

    def test_get_valid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "24"}):
            timeout = get_timeout()
            self.assertEqual(24, timeout)

    def test_get_zero_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "0"}):
            timeout = get_timeout()
            self.assertEqual(0, timeout)

    def test_get_invalid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "foobar"}):
            with self.assertRaises(RSConnectException):
                get_timeout()

    def test_get_negative_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "-24"}):
            with self.assertRaises(RSConnectException):
                get_timeout()
