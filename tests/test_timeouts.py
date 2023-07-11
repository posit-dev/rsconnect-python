import os

from unittest import TestCase
from unittest.mock import patch

from rsconnect.exception import RSConnectException
from rsconnect.timeouts import get_request_timeout, get_task_timeout, get_task_timeout_help_message


class GetRequestTimeoutTestCase(TestCase):
    def test_get_default_timeout(self):
        timeout = get_request_timeout()
        self.assertEqual(300, timeout)

    def test_get_valid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "24"}):
            timeout = get_request_timeout()
            self.assertEqual(24, timeout)

    def test_get_zero_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "0"}):
            timeout = get_request_timeout()
            self.assertEqual(0, timeout)

    def test_get_invalid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "foobar"}):
            with self.assertRaises(RSConnectException):
                get_request_timeout()

    def test_get_negative_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_REQUEST_TIMEOUT": "-24"}):
            with self.assertRaises(RSConnectException):
                get_request_timeout()

class GetTaskTimeoutTestCase(TestCase):
    def test_get_default_timeout(self):
        timeout = get_task_timeout()
        self.assertEqual(24 * 60 * 60, timeout)

    def test_get_valid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_TASK_TIMEOUT": "24"}):
            timeout = get_task_timeout()
            self.assertEqual(24, timeout)

    def test_get_zero_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_TASK_TIMEOUT": "0"}):
            with self.assertRaises(RSConnectException):
                get_task_timeout()

    def test_get_invalid_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_TASK_TIMEOUT": "foobar"}):
            with self.assertRaises(RSConnectException):
                get_task_timeout()

    def test_get_negative_timeout_from_environment(self):
        with patch.dict(os.environ, {"CONNECT_TASK_TIMEOUT": "-24"}):
            with self.assertRaises(RSConnectException):
                get_task_timeout()

class GetTaskTimeoutHelpMessageTestCase(TestCase):
    def test_get_task_timeout_help_message(self):
        res = get_task_timeout_help_message(1)
        self.assertTrue("The task timed out after 1 seconds." in res)
        self.assertTrue("You may try increasing the task timeout value using the CONNECT_TASK_TIMEOUT environment variable." in res)  # noqa: E501
        self.assertTrue("The default value is 86400 seconds." in res)
        self.assertTrue("The current value is 86400 seconds." in res)
