from unittest import TestCase
from datetime import timedelta

from rsconnect.json_web_token import is_jwt_compatible_python_version

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey

from rsconnect.json_web_token import JWTEncoder

from tests.utils import (
    generate_test_ed25519_keypair,
    JWTDecoder,
    convert_ed25519_private_key_to_bytes,
    has_jwt_structure,
)


class TestJwtUtils(TestCase):
    def setUp(self):
        if not is_jwt_compatible_python_version():
            self.skipTest("JWTs not supported in Python < 3.6")

    def test_generate_test_keypair(self):
        """
        Verify our test keypair generator produces reasonable results
        """

        private_key, public_key = generate_test_ed25519_keypair()

        self.assertTrue(isinstance(private_key, Ed25519PrivateKey))
        self.assertTrue(isinstance(public_key, Ed25519PublicKey))

    def test_convert_ed25519_private_key_to_bytes(self):
        private_key, _ = generate_test_ed25519_keypair()
        result = convert_ed25519_private_key_to_bytes(private_key)
        self.assertTrue(isinstance(result, bytes))

    def test_convert_ed25519_private_key_to_bytes_with_password(self):
        """
        Should be able to encrypt the bytes with a password
        """
        private_key, _ = generate_test_ed25519_keypair()
        result = convert_ed25519_private_key_to_bytes(private_key, password="a_password")
        self.assertTrue(isinstance(result, bytes))

    def test_jwt_decoder(self):
        private_key, public_key = generate_test_ed25519_keypair()
        encoder = JWTEncoder("issuer", "audience", private_key)

        token = encoder.new_token({}, timedelta(minutes=5))
        self.assertTrue(isinstance(token, str))

        decoder = JWTDecoder("audience", public_key)

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
