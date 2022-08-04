from unittest import TestCase
import pytest

from datetime import datetime, timedelta, timezone
import re
import os

from rsconnect.json_web_token import (
    SECRET_ENV_VAR,
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    load_secret,
    TokenGenerator,
    JWTEncoder,
    JWTDecoder,
)


def has_jwt_structure(token):
    return re.search("^[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+\\.[a-zA-Z0-9-_]+$", token) is not None


# timestamps are recorded in the number of seconds since the epoch
def are_unix_timestamps_approx_equal(a, b):
    # assume +/- 1 second is approximately equal, since we cant precisely know
    # when the token generator gets the current timestamp
    return abs(a - b) <= 1


class TestJwtEncoder(TestCase):
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


class TestTokenGenerator(TestCase):
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


class TestLoadSecret(TestCase):
    def test_load_secret_env_variable(self):

        secret = "123abcenvsecret"

        os.environ[SECRET_ENV_VAR] = secret

        self.assertEqual(load_secret(), secret)
        self.assertEqual(load_secret(None), secret)
        self.assertEqual(load_secret("/some/path.secret"), secret)

        # this secret key exists and contains '123abcsecret' - overridden by env variable
        self.assertEqual(load_secret("tests/testdata/secret.key"), secret)

        # Cleanup
        os.environ.pop(SECRET_ENV_VAR)

    def test_load_secret_none(self):

        with pytest.raises(RuntimeError):
            load_secret(None)

        with pytest.raises(RuntimeError):
            load_secret()

    def test_load_secret_file(self):

        with pytest.raises(FileNotFoundError):
            load_secret("/some/path.secret")

        # todo: this limits from which directory the tests can be run...
        self.assertEqual(load_secret("tests/testdata/secret.key"), "123abcsecret")
