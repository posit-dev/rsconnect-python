import tempfile
from unittest import TestCase
import pytest
import jwt

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from datetime import datetime, timedelta, timezone
import re
import os
from rsconnect.exception import RSConnectException


from rsconnect.json_web_token import (
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    load_ed25519_private_key,
    read_ed25519_private_key,
    load_ed25519_private_key_from_bytes,
    is_jwt_compatible_python_version,
    TokenGenerator,
    JWTEncoder,
)


class JWTDecoder:
    """
    Used to decode / verify JWTs in testing
    """

    def __init__(self, audience: str, secret):
        self.audience = audience
        self.secret = secret

    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["EdDSA"])


def generate_test_ed25519_keypair():
    """
    TO BE USED JUST FOR UNIT TESTS!!!

    These 'cryptography' routines have not been verified for
    production use - we just want 'valid' encoded / formatted keypairs
    for unit testing (without having to save keypairs in the commit history,
    which could probably technically be ok but still feels bad).
    """

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    return (private_key, public_key)


def convert_ed25519_private_key_to_bytes(private_key: Ed25519PrivateKey) -> bytes:
    """
    Mimics the approach used by ssh-keygen, which will only output ed25519 keys in OpenSSH format
    """

    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )


def has_jwt_structure(token):
    """
    Verify that token is a well-formatted JWT string
    """

    if token is None:
        return False

    return re.search("^[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+$", token) is not None


def are_unix_timestamps_approx_equal(a, b):
    """
    Assume that +/- 1 second is approximately equal, since we can't precisely
    know when the token generator gets the current timestamp.

    Timestamps are recorded as the number of seconds since the epoch
    """
    return abs(a - b) <= 1


class TestJsonWebToken(TestCase):
    def setUp(self):
        if not is_jwt_compatible_python_version():
            self.skipTest("JWTs not supported in Python < 3.6")

        private_key, public_key = generate_test_ed25519_keypair()

        self.private_key = private_key
        self.public_key = public_key

    def test_generate_test_keypair(self):
        """
        Verify our test keypair generator produces reasonable results
        """

        private_key, public_key = generate_test_ed25519_keypair()

        self.assertTrue(isinstance(private_key, Ed25519PrivateKey))
        self.assertTrue(isinstance(public_key, Ed25519PublicKey))

    # verify that our has_jwt_structure helper works as expected
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

    def test_are_unix_timestamps_approx_equal(self):
        """
        Verify that our unix timestamp verification helper works as expected
        """

        self.assertTrue(are_unix_timestamps_approx_equal(1, 1))
        self.assertTrue(are_unix_timestamps_approx_equal(1, 0))
        self.assertTrue(are_unix_timestamps_approx_equal(0, 1))
        self.assertFalse(are_unix_timestamps_approx_equal(0, 2))
        self.assertFalse(are_unix_timestamps_approx_equal(2, 0))

    def test_is_jwt_compatible_python_version(self):
        """
        With setUp() skipping invalid versions, this test should always return True
        regardless of the particular python env we're running the tests in
        """
        self.assertTrue(is_jwt_compatible_python_version())

    def test_jwt_encoder_constructor(self):
        encoder = JWTEncoder("issuer", "audience", self.private_key)

        self.assertEqual(encoder.issuer, "issuer")
        self.assertEqual(encoder.audience, "audience")
        self.assertEqual(encoder.secret, self.private_key)

    def test_generate_standard_claims(self):
        encoder = JWTEncoder("issuer", "audience", self.private_key)

        current_datetime = datetime(2022, 1, 1, 1, 1, 1)
        exp = timedelta(hours=5)

        standard_claims = encoder.generate_standard_claims(current_datetime, exp)

        # verify we have all the expected standard claims
        self.assertEqual(standard_claims.keys(), set(["exp", "iss", "aud", "iat"]))

        self.assertEqual(standard_claims["exp"], int((current_datetime + exp).timestamp()))
        self.assertEqual(datetime.fromtimestamp(standard_claims["exp"]), datetime(2022, 1, 1, 6, 1, 1))

        self.assertEqual(standard_claims["iss"], "issuer")
        self.assertEqual(standard_claims["aud"], "audience")

        self.assertEqual(standard_claims["iat"], int(current_datetime.timestamp()))
        self.assertEqual(datetime.fromtimestamp(standard_claims["iat"]), current_datetime)

    def test_new_token_empty_custom_claims(self):
        encoder = JWTEncoder("issuer", "audience", self.private_key)
        decoder = JWTDecoder("audience", self.public_key)

        exp = timedelta(hours=5)
        current_datetime = datetime.now(tz=timezone.utc)
        expected_exp = int((current_datetime + exp).timestamp())
        expected_iat = int(current_datetime.timestamp())

        # empty custom claims
        new_token = encoder.new_token({}, exp)
        self.assertTrue(has_jwt_structure(new_token))

        payload = decoder.decode_token(new_token)

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat"]))

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], "issuer")
        self.assertEqual(payload["aud"], "audience")
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))

    def test_new_token_populated_custom_claims(self):
        encoder = JWTEncoder("issuer", "audience", self.private_key)
        decoder = JWTDecoder("audience", self.public_key)

        exp = timedelta(hours=5)
        current_datetime = datetime.now(tz=timezone.utc)
        expected_exp = int((current_datetime + exp).timestamp())
        expected_iat = int(current_datetime.timestamp())

        # populated custom claims
        custom_claims = {"endpoint": "http://something.test.com", "method": "POST"}
        new_token = encoder.new_token(custom_claims, exp)
        self.assertTrue(has_jwt_structure(new_token))

        payload = decoder.decode_token(new_token)

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "endpoint", "method"]))

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], "issuer")
        self.assertEqual(payload["aud"], "audience")
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))
        self.assertEqual(payload["endpoint"], "http://something.test.com")
        self.assertEqual(payload["method"], "POST")

    def test_token_generator_constructor(self):
        generator = TokenGenerator(self.private_key)

        # Assert that the encoder is instantiated properly
        self.assertEqual(generator.encoder.issuer, DEFAULT_ISSUER)
        self.assertEqual(generator.encoder.audience, DEFAULT_AUDIENCE)
        self.assertEqual(generator.encoder.secret, self.private_key)

    def test_token_generator_initial_admin(self):
        generator = TokenGenerator(self.private_key)
        initial_admin_token = generator.initial_admin()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, self.public_key)
        payload = decoder.decode_token(initial_admin_token)

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "endpoint", "method"]))

        exp = timedelta(minutes=15)
        current_datetime = datetime.now(tz=timezone.utc)
        expected_exp = int((current_datetime + exp).timestamp())
        expected_iat = int(current_datetime.timestamp())

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], DEFAULT_ISSUER)
        self.assertEqual(payload["aud"], DEFAULT_AUDIENCE)
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))
        self.assertEqual(payload["endpoint"], "/__api__/v1/experimental/installation/initial-admin")
        self.assertEqual(payload["method"], "GET")

    def test_private_key_serialization(self):
        """
        Validate private key serialization routines
        """

        private_key_bytes = convert_ed25519_private_key_to_bytes(self.private_key)
        private_key_copy = load_ed25519_private_key_from_bytes(private_key_bytes, None)
        private_key_copy_bytes = convert_ed25519_private_key_to_bytes(private_key_copy)

        self.assertTrue(private_key_bytes, private_key_copy_bytes)

    def test_load_ed25519_private_key(self):

        # Invalid Path
        with pytest.raises(RSConnectException):
            load_ed25519_private_key("/some/path.secret", None)

        # Invalid secret type
        with pytest.raises(RSConnectException):
            load_ed25519_private_key("tests/testdata/jwt/secret.key", None)

        # Empty secret fyle
        with pytest.raises(RSConnectException):
            load_ed25519_private_key("tests/testdata/jwt/empty_secret.key", None)

        private_key_bytes = convert_ed25519_private_key_to_bytes(self.private_key)

        # A 'valid' secret key should load w/ no problems
        with tempfile.TemporaryDirectory() as td:
            private_keyfile = os.path.join(td, "test_ed25519")
            with open(private_keyfile, "wb") as f:
                f.write(private_key_bytes)

            # first, test the private key load subroutine methods piecewise

            bytes = read_ed25519_private_key(private_keyfile)

            # validate that the bytes from the file are read correctly
            self.assertEqual(bytes, private_key_bytes)

            # read the key's byte representation into a cryptography.Ed25519PrivateKey
            from_bytes = load_ed25519_private_key_from_bytes(bytes, None)

            # convert the read key back to its byte representation
            read_key_bytes = convert_ed25519_private_key_to_bytes(from_bytes)

            # validate that the byte representation is what we expected
            self.assertEqual(read_key_bytes, private_key_bytes)

            # put it all together, running the same process with a single consolidated function

            read_private_key = load_ed25519_private_key(private_keyfile, None)
            self.assertEqual(convert_ed25519_private_key_to_bytes(read_private_key), private_key_bytes)

        # Confirm that cleanup worked
        self.assertFalse(os.path.exists(private_keyfile))
