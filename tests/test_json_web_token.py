from unittest import TestCase
import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from datetime import datetime, timedelta, timezone
import re
from rsconnect.exception import RSConnectException


from rsconnect.json_web_token import (
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    is_valid_secret_key,
    is_jwt_compatible_python_version,
    load_secret,
    TokenGenerator,
    JWTEncoder,
    JWTDecoder,
    safe_instantiate_token_generator,
)

SECRET = "12345678912345678912345678912345"


def generate_test_keypair():
    """
    TO BE USED JUST FOR UNIT TESTS!!!
    These 'cryptography' routines have not been verified for
    testing in production - we just want 'valid' PEM-formatted keys for testing
    """

    private_key = Ed25519PrivateKey.generate()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # todo - what should the keys be decoded as?
    return (private_key_pem.decode("utf-8"), public_key_pem.decode("utf-8"))


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

        private_key, public_key = generate_test_keypair()
        self.private_key = private_key
        self.public_key = public_key

    def test_generate_test_keyparir(self):

        # todo
        self.assertTrue(True)

    # verify that our has_jwt_structure helper works as expected
    def test_has_jwt_structure(self):

        true_examples = [
            "aA1-_.aA1-_.aA1-_",
        ]

        for true_example in true_examples:
            self.assertTrue(has_jwt_structure(true_example))

        false_examples = [
            None,
            "",
            "aA1-_",
            "aA1-_.aA1-_." "aA1-_.aA1-_.aA1-_.",
            ".aA1-_.aA1-_.aA1-_",
        ]

        for false_example in false_examples:
            self.assertFalse(has_jwt_structure(false_example))

    def test_are_unix_timestamps_approx_equal(self):

        self.assertTrue(are_unix_timestamps_approx_equal(1, 1))
        self.assertTrue(are_unix_timestamps_approx_equal(1, 0))
        self.assertTrue(are_unix_timestamps_approx_equal(0, 1))
        self.assertFalse(are_unix_timestamps_approx_equal(0, 2))
        self.assertFalse(are_unix_timestamps_approx_equal(2, 0))

    def test_is_valid_secret_key(self):

        true_examples = [SECRET]

        for true_example in true_examples:
            self.assertTrue(is_valid_secret_key(true_example))

        false_examples = [
            "12345",
            "",
            None,
            123,
        ]

        for false_example in false_examples:
            self.assertFalse(is_valid_secret_key(false_example))

    def test_is_jwt_compatible_python_version(self):
        """
        With setUp() skipping invalid versions, this test should always return True
        regardless of the particular python env we're running the tests in
        """
        self.assertTrue(is_jwt_compatible_python_version())

    def test_safe_instantiate_token_generator(self):
        with pytest.raises(RSConnectException):
            safe_instantiate_token_generator(None)

        with pytest.raises(RSConnectException):
            safe_instantiate_token_generator("invalid")

        with pytest.raises(RSConnectException):
            safe_instantiate_token_generator("tests/testdata/empty_secret.key")

        with pytest.raises(RSConnectException):
            safe_instantiate_token_generator("tests/testdata/short_secret.key")

        token_generator = safe_instantiate_token_generator("tests/testdata/secret.key")
        self.assertIsNotNone(token_generator)

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

    def test_load_secret_file(self):

        with pytest.raises(RSConnectException):
            load_secret("/some/path.secret")

        # todo: this limits from which directory the tests can be run...
        self.assertEqual(load_secret("tests/testdata/secret.key"), SECRET)
