import tempfile
from unittest import TestCase
from unittest.mock import patch
import pytest
import jwt

from datetime import datetime, timedelta, timezone
import os
from rsconnect.exception import RSConnectException


from rsconnect.json_web_token import (
    INITIAL_ADMIN_EXP,
    INITIAL_ADMIN_ENDPOINT,
    INITIAL_ADMIN_METHOD,
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    load_ed25519_private_key,
    produce_initial_admin_output,
    read_ed25519_private_key,
    load_ed25519_private_key_from_bytes,
    is_jwt_compatible_python_version,
    load_private_key_password,
    TokenGenerator,
    JWTEncoder,
)

from tests.utils import (
    JWTDecoder,
    generate_test_ed25519_keypair,
    convert_ed25519_private_key_to_bytes,
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

        private_key, public_key = generate_test_ed25519_keypair()

        self.private_key = private_key
        self.public_key = public_key

    def assert_initial_admin_jwt_is_valid(self, payload, current_datetime):
        """
        Helper to verify state of decoded initial admin jwt
        """
        expected_exp = int((current_datetime + INITIAL_ADMIN_EXP).timestamp())
        expected_iat = int(current_datetime.timestamp())

        self.assertEqual(payload.keys(), set(["exp", "iss", "aud", "iat", "endpoint", "method"]))

        self.assertTrue(are_unix_timestamps_approx_equal(payload["exp"], expected_exp))
        self.assertEqual(payload["iss"], DEFAULT_ISSUER)
        self.assertEqual(payload["aud"], DEFAULT_AUDIENCE)
        self.assertTrue(are_unix_timestamps_approx_equal(payload["iat"], expected_iat))
        self.assertEqual(payload["endpoint"], INITIAL_ADMIN_ENDPOINT)
        self.assertEqual(payload["method"], INITIAL_ADMIN_METHOD)

    def test_are_unix_timestamps_approx_equal(self):
        """
        Verify that our unix timestamp verification helper works as expected
        """

        self.assertTrue(are_unix_timestamps_approx_equal(1, 1))
        self.assertTrue(are_unix_timestamps_approx_equal(1, 0))
        self.assertTrue(are_unix_timestamps_approx_equal(0, 1))
        self.assertFalse(are_unix_timestamps_approx_equal(0, 2))
        self.assertFalse(are_unix_timestamps_approx_equal(2, 0))

    def test_private_key_password_loader(self):
        """
        Verify password loading behavior
        """

        mock_env_password = "env password123!"
        mock_cli_password = "cli password123!"

        # no environment variable
        with patch("rsconnect.json_web_token._load_private_key_password_env") as fn_env, patch(
            "rsconnect.json_web_token._load_private_key_password_interactive"
        ) as fn_interactive:

            fn_env.return_value = None
            fn_interactive.return_value = mock_cli_password

            self.assertEqual(load_private_key_password(False), None)
            self.assertEqual(load_private_key_password(True), mock_cli_password.encode())

        # populated environment variable
        with patch("rsconnect.json_web_token._load_private_key_password_env") as fn_env, patch(
            "rsconnect.json_web_token._load_private_key_password_interactive"
        ) as fn_interactive:

            fn_env.return_value = mock_env_password
            fn_interactive.return_value = mock_cli_password

            self.assertEqual(load_private_key_password(False), mock_env_password.encode())
            self.assertEqual(load_private_key_password(True), mock_env_password.encode())

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

    def test_generate_standard_claims_invalid_exp(self):
        """
        The exp timedelta needs to be nonnegative
        """

        encoder = JWTEncoder("issuer", "audience", self.private_key)

        current_datetime = datetime(2022, 1, 1, 1, 1, 1)
        exp = timedelta(seconds=-1)

        with pytest.raises(RSConnectException):
            encoder.generate_standard_claims(current_datetime, exp)

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

        current_datetime = datetime.now(tz=timezone.utc)
        self.assert_initial_admin_jwt_is_valid(payload, current_datetime)

    def test_token_generator_invalid_public_key(self):
        """
        If our public key doesn't match the private key, we should not be able to validate the token
        """
        generator = TokenGenerator(self.private_key)

        # generate another keypair, use its public key in the decoder
        _, another_public_key = generate_test_ed25519_keypair()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, another_public_key)

        initial_admin_token = generator.initial_admin()

        with pytest.raises(jwt.InvalidSignatureError):
            decoder.decode_token(initial_admin_token)

    def test_token_workflow(self):

        # Gold standard - we can generate, sign, and verify the token with this keypair

        generator = TokenGenerator(self.private_key)
        initial_admin_token = generator.initial_admin()

        decoder = JWTDecoder(DEFAULT_AUDIENCE, self.public_key)
        payload = decoder.decode_token(initial_admin_token)

        current_datetime = datetime.now(tz=timezone.utc)
        self.assert_initial_admin_jwt_is_valid(payload, current_datetime)

        # BEGIN ACTUAL TEST

        # Write the byte representation of the private key into a file
        with tempfile.TemporaryDirectory() as td:
            private_keyfile = os.path.join(td, "test_ed25519")
            with open(private_keyfile, "wb") as f:
                f.write(convert_ed25519_private_key_to_bytes(self.private_key))

            loaded_private_key = load_ed25519_private_key(private_keyfile, None)

            test_generator = TokenGenerator(loaded_private_key)
            test_initial_admin_token = test_generator.initial_admin()
            test_payload = decoder.decode_token(test_initial_admin_token)

            test_datetime = datetime.now(tz=timezone.utc)
            self.assert_initial_admin_jwt_is_valid(test_payload, test_datetime)

    def test_load_ed25519_private_key(self):

        # NoneType Path
        with pytest.raises(RSConnectException):
            load_ed25519_private_key(None, None)

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

            # Confirm that we generated a private key object from the read bytes
            self.assertTrue(from_bytes is not None)
        # Confirm that cleanup worked
        self.assertFalse(os.path.exists(private_keyfile))
