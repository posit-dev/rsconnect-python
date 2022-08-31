from unittest import TestCase
from datetime import timedelta

from rsconnect.json_web_token import is_jwt_compatible_python_version

from rsconnect.json_web_token import JWTEncoder

from tests.utils import (
    JWTDecoder,
    has_jwt_structure,
)


class TestJwtUtils(TestCase):
    def setUp(self):
        if not is_jwt_compatible_python_version():
            self.skipTest("JWTs not supported in Python < 3.6")

    def test_jwt_decoder(self):

        secret = b"12345678912345678912345678912345"

        encoder = JWTEncoder("issuer", "audience", secret)

        token = encoder.new_token({}, timedelta(minutes=5))
        self.assertTrue(isinstance(token, str))

        decoder = JWTDecoder("audience", secret)

        result = decoder.decode_token(token)
        self.assertTrue(isinstance(result, dict))

        self.assertEqual(result["iss"], "issuer")
        self.assertEqual(result["aud"], "audience")

    def test_has_jwt_structure(self):
        """
        Verify that our jwt structure verification helper works as expected
        """

        true_examples = [
            "aA1-_.aA1-_.aA1-_",
        ]

        for true_example in true_examples:
            self.assertTrue(has_jwt_structure(true_example))

        false_examples = [
            None,
            "",
            "aA1-_",
            "aA1-_.aA1-_.",
            "aA1-_.aA1-_.aA1-_.",
            ".aA1-_.aA1-_.aA1-_",
        ]

        for false_example in false_examples:
            self.assertFalse(has_jwt_structure(false_example))
