from unittest import TestCase
import pytest

from datetime import datetime, timedelta, timezone
import re
import os
from rsconnect.exception import RSConnectException


from rsconnect.json_web_token import (
    SECRET_ENV_VAR,
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


def has_jwt_structure(token):
    if token is None:
        return False

    return re.search("^[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+$", token) is not None


# timestamps are recorded in the number of seconds since the epoch
def are_unix_timestamps_approx_equal(a, b):
    # assume +/- 1 second is approximately equal, since we cant precisely know
    # when the token generator gets the current timestamp
    return abs(a - b) <= 1


class TestJsonWebToken(TestCase):
    def setUp(self):
        if not is_jwt_compatible_python_version():
            self.skipTest("JWTs not supported in Python < 3.6")

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

        # env variable lets us load an environment variable regardless of the key path
        os.environ[SECRET_ENV_VAR] = SECRET
        env_token_generator = safe_instantiate_token_generator(None)
        self.assertIsNotNone(env_token_generator)
        os.environ.pop(SECRET_ENV_VAR)

    def test_jwt_encoder_constructor(self):
        encoder = JWTEncoder("issuer", "audience", "secret")

        self.assertEqual(encoder.issuer, "issuer")
        self.assertEqual(encoder.audience, "audience")
        self.assertEqual(encoder.secret, "secret")

    def test_generate_standard_claims(self):
        encoder = JWTEncoder("issuer", "audience", "secret")

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
        encoder = JWTEncoder("issuer", "audience", "secret")
        decoder = JWTDecoder("audience", "secret")

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
        encoder = JWTEncoder("issuer", "audience", "secret")
        decoder = JWTDecoder("audience", "secret")

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
        generator = TokenGenerator("secret")

        # Assert that the encoder is instantiated properly
        self.assertEqual(generator.encoder.issuer, DEFAULT_ISSUER)
        self.assertEqual(generator.encoder.audience, DEFAULT_AUDIENCE)
        self.assertEqual(generator.encoder.secret, "secret")

    def test_token_generator_initial_admin(self):
        generator = TokenGenerator("secret")
        initial_admin_token = generator.initial_admin()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, "secret")
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

    def test_load_secret_env_variable(self):

        os.environ[SECRET_ENV_VAR] = SECRET

        self.assertEqual(load_secret(), SECRET)
        self.assertEqual(load_secret(None), SECRET)
        self.assertEqual(load_secret("/some/path.secret"), SECRET)

        # this secret key exists and contains '123abcsecret' - overridden by env variable
        self.assertEqual(load_secret("tests/testdata/secret.key"), SECRET)

        # Cleanup
        os.environ.pop(SECRET_ENV_VAR)

    def test_load_secret_none(self):

        with pytest.raises(RSConnectException):
            load_secret(None)

        with pytest.raises(RSConnectException):
            load_secret()

    def test_load_secret_file(self):

        with pytest.raises(RSConnectException):
            load_secret("/some/path.secret")

        # todo: this limits from which directory the tests can be run...
        self.assertEqual(load_secret("tests/testdata/secret.key"), SECRET)
