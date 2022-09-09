import tempfile
from unittest import TestCase
import pytest
import jwt

from datetime import datetime, timedelta, timezone
import os
from rsconnect.exception import RSConnectException

from rsconnect.http_support import HTTPResponse

from rsconnect.json_web_token import (
    INITIAL_ADMIN_EXP,
    INITIAL_ADMIN_SCOPE,
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    read_secret_key,
    produce_initial_admin_output,
    is_jwt_compatible_python_version,
    parse_client_response,
    TokenGenerator,
    JWTEncoder,
    validate_hs256_secret_key,
)

from tests.utils import (
    JWTDecoder,
    has_jwt_structure,
)


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

        # decoded copy of the base64-encoded key in testdata/jwt/secret.key
        self.secret_key = b"12345678901234567890123456789012345"
        self.secret_key_b64 = b"MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU="

    def assert_initial_admin_jwt_is_valid(self, payload, current_datetime):
        """
        Helper to verify state of decoded initial admin jwt
        """
        expected_exp = int((current_datetime + INITIAL_ADMIN_EXP).timestamp())
        expected_iat = int(current_datetime.timestamp())

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "scope"]))

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], DEFAULT_ISSUER)
        self.assertEqual(payload["aud"], DEFAULT_AUDIENCE)
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))
        self.assertEqual(payload["scope"], INITIAL_ADMIN_SCOPE)

    def test_are_unix_timestamps_approx_equal(self):
        """
        Verify that our unix timestamp verification helper works as expected
        """

        self.assertTrue(are_unix_timestamps_approx_equal(1, 1))
        self.assertTrue(are_unix_timestamps_approx_equal(1, 0))
        self.assertTrue(are_unix_timestamps_approx_equal(0, 1))
        self.assertFalse(are_unix_timestamps_approx_equal(0, 2))
        self.assertFalse(are_unix_timestamps_approx_equal(2, 0))

    def test_parse_client_response(self):

        status, response = parse_client_response({"api_key": "apikey123"})
        self.assertEqual(status, 200)
        self.assertEqual(response, {"api_key": "apikey123"})

        status, response = parse_client_response({})
        self.assertEqual(status, 200)
        self.assertEqual(response, {})

        status, response = parse_client_response({"something": "else"})
        self.assertEqual(status, 200)
        self.assertEqual(response, {"something": "else"})

        # test if json_data is none
        not_found_response = HTTPResponse("http://uri")
        not_found_response.status = 404
        status, response = parse_client_response(not_found_response)
        self.assertEqual(status, 404)
        self.assertEqual(response, None)

        # test if json_data is empty
        unauthorized_response = HTTPResponse("http://uri")
        unauthorized_response.status = 401
        unauthorized_response.json_data = {}
        status, response = parse_client_response(unauthorized_response)
        self.assertEqual(status, 401)
        self.assertEqual(response, {})

        # test if json data is something else
        other_response = HTTPResponse("http://uri")
        other_response.status = 500
        other_response.json_data = {"test": "something"}
        status, response = parse_client_response(other_response)
        self.assertEqual(status, 500)
        self.assertEqual(response, {"test": "something"})

    def test_is_jwt_compatible_python_version(self):
        """
        With setUp() skipping invalid versions, this test should always return True
        regardless of the particular python env we're running the tests in
        """
        self.assertTrue(is_jwt_compatible_python_version())

    def test_jwt_encoder_constructor(self):
        encoder = JWTEncoder("issuer", "audience", self.secret_key)

        self.assertEqual(encoder.issuer, "issuer")
        self.assertEqual(encoder.audience, "audience")
        self.assertEqual(encoder.secret, self.secret_key)

    def test_produce_initial_admin_output(self):

        api_key = "apikey123"

        # if we get a 200 response without a valid API key, something is messed up

        with pytest.raises(RSConnectException):
            produce_initial_admin_output(200, None)

        with pytest.raises(RSConnectException):
            produce_initial_admin_output(200, {})

        with pytest.raises(RSConnectException):
            produce_initial_admin_output(200, {"api_key": ""})

        with pytest.raises(RSConnectException):
            produce_initial_admin_output(200, {"something": "else"})

        # if we get a non-200 response with an API key, something is messed up

        with pytest.raises(RSConnectException):
            produce_initial_admin_output(400, {"api_key": api_key})

        expected_successful_result = {
            "status": 200,
            "api_key": api_key,
            "message": "Success.",
        }
        self.assertEqual(produce_initial_admin_output(200, {"api_key": api_key}), expected_successful_result)

        expected_client_error_result = {
            "status": 400,
            "api_key": "",
            "message": "Unable to provision initial admin. Please check status of Connect database.",
        }
        self.assertEqual(produce_initial_admin_output(400, None), expected_client_error_result)
        self.assertEqual(produce_initial_admin_output(400, {}), expected_client_error_result)
        self.assertEqual(produce_initial_admin_output(400, {"api_key": ""}), expected_client_error_result)
        self.assertEqual(produce_initial_admin_output(400, {"something": "else"}), expected_client_error_result)

        expected_unauthorized_error_result = {"status": 401, "api_key": "", "message": "JWT authorization failed."}
        self.assertEqual(produce_initial_admin_output(401, None), expected_unauthorized_error_result)
        self.assertEqual(produce_initial_admin_output(401, {}), expected_unauthorized_error_result)
        self.assertEqual(produce_initial_admin_output(401, {"api_key": ""}), expected_unauthorized_error_result)
        self.assertEqual(produce_initial_admin_output(401, {"something": "else"}), expected_unauthorized_error_result)

        expected_not_found_error_result = {
            "status": 404,
            "api_key": "",
            "message": (
                "Unable to find provisioning endpoint. "
                "Please check the 'rsconnect --server' parameter and your Connect configuration."
            ),
        }
        self.assertEqual(produce_initial_admin_output(404, None), expected_not_found_error_result)
        self.assertEqual(produce_initial_admin_output(404, {}), expected_not_found_error_result)
        self.assertEqual(produce_initial_admin_output(404, {"api_key": ""}), expected_not_found_error_result)
        self.assertEqual(produce_initial_admin_output(404, {"something": "else"}), expected_not_found_error_result)

        expected_other_error_result = {
            "status": 500,
            "api_key": "",
            "message": "Unexpected response status.",
        }
        self.assertEqual(produce_initial_admin_output(500, None), expected_other_error_result)
        self.assertEqual(produce_initial_admin_output(500, {}), expected_other_error_result)
        self.assertEqual(produce_initial_admin_output(500, {"api_key": ""}), expected_other_error_result)
        self.assertEqual(produce_initial_admin_output(500, {"something": "else"}), expected_other_error_result)

    def test_generate_standard_claims(self):
        """
        Test production of common claims that will be consistent across all JWTs
        """

        encoder = JWTEncoder("issuer", "audience", self.secret_key)

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

    def test_generate_standard_claims_invalid_exp(self):
        """
        The exp timedelta needs to be nonnegative
        """

        encoder = JWTEncoder("issuer", "audience", self.secret_key)

        current_datetime = datetime(2022, 1, 1, 1, 1, 1)
        exp = timedelta(seconds=-1)

        with pytest.raises(RSConnectException):
            encoder.generate_standard_claims(current_datetime, exp)

    def test_new_token_empty_custom_claims(self):
        encoder = JWTEncoder("issuer", "audience", self.secret_key)
        decoder = JWTDecoder("audience", self.secret_key)

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
        encoder = JWTEncoder("issuer", "audience", self.secret_key)
        decoder = JWTDecoder("audience", self.secret_key)

        exp = timedelta(hours=5)
        current_datetime = datetime.now(tz=timezone.utc)
        expected_exp = int((current_datetime + exp).timestamp())
        expected_iat = int(current_datetime.timestamp())

        # populated custom claims
        custom_claims = {"scope": "initial_admin"}
        new_token = encoder.new_token(custom_claims, exp)
        self.assertTrue(has_jwt_structure(new_token))

        payload = decoder.decode_token(new_token)

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "scope"]))

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], "issuer")
        self.assertEqual(payload["aud"], "audience")
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))
        self.assertEqual(payload["scope"], "initial_admin")

    def test_token_generator_constructor(self):
        generator = TokenGenerator(self.secret_key)

        # Assert that the encoder is instantiated properly
        self.assertEqual(generator.encoder.issuer, DEFAULT_ISSUER)
        self.assertEqual(generator.encoder.audience, DEFAULT_AUDIENCE)
        self.assertEqual(generator.encoder.secret, self.secret_key)

    def test_token_generator_initial_admin(self):
        generator = TokenGenerator(self.secret_key)
        initial_admin_token = generator.initial_admin()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, self.secret_key)
        payload = decoder.decode_token(initial_admin_token)

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "scope"]))

        current_datetime = datetime.now(tz=timezone.utc)
        self.assert_initial_admin_jwt_is_valid(payload, current_datetime)

    def test_token_generator_invalid_public_key(self):
        """
        If our public key doesn't match the private key, we should not be able to validate the token
        """
        generator = TokenGenerator(self.secret_key)

        decoder = JWTDecoder(DEFAULT_AUDIENCE, "someRandomValue")

        initial_admin_token = generator.initial_admin()

        with pytest.raises(jwt.InvalidSignatureError):
            decoder.decode_token(initial_admin_token)

    def test_read_secret_key(self):

        valid = read_secret_key("tests/testdata/jwt/secret.key")
        self.assertEqual(valid, self.secret_key)

        with pytest.raises(RSConnectException):
            read_secret_key("invalid/path.key")

    def test_validate_hs256_secret_key(self):

        with pytest.raises(RSConnectException):
            validate_hs256_secret_key(b"")

        with pytest.raises(RSConnectException):
            validate_hs256_secret_key(b"tooshort")

        # success
        validate_hs256_secret_key(self.secret_key)

        # very long key is also fine
        validate_hs256_secret_key(b"12345678901234567890123456789012345678901234567890")

    def test_token_workflow(self):

        # Gold standard - we can generate, sign, and verify the token with this keypair

        generator = TokenGenerator(self.secret_key)
        initial_admin_token = generator.initial_admin()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, self.secret_key)
        payload = decoder.decode_token(initial_admin_token)

        current_datetime = datetime.now(tz=timezone.utc)
        self.assert_initial_admin_jwt_is_valid(payload, current_datetime)

        # BEGIN ACTUAL TEST

        # Write the byte representation of the private key into a file
        with tempfile.TemporaryDirectory() as td:
            secret_keyfile = os.path.join(td, "secret_key")
            with open(secret_keyfile, "wb") as f:
                f.write(self.secret_key_b64)

            loaded_private_key = read_secret_key(secret_keyfile)

            test_generator = TokenGenerator(loaded_private_key)
            test_initial_admin_token = test_generator.initial_admin()
            test_payload = decoder.decode_token(test_initial_admin_token)

            test_datetime = datetime.now(tz=timezone.utc)
            self.assert_initial_admin_jwt_is_valid(test_payload, test_datetime)
