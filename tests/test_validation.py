from unittest import TestCase
import pytest
import os

from rsconnect.exception import RSConnectException
from rsconnect.json_web_token import SECRET_ENV_VAR


from rsconnect.validation import validate_jwt_options


class TestValidateJwtOptions(TestCase):
    def test_validate_jwt_options(self):

        # Have to specify a token type to generate

        with pytest.raises(RSConnectException):
            validate_jwt_options(None, None)

        with pytest.raises(RSConnectException):
            validate_jwt_options(None, "something")

        # If no secret path is specified, need an env variable set

        with pytest.raises(RSConnectException):
            validate_jwt_options("something", None)

        # If a secret path is specified, the file needs to exist
        with pytest.raises(RSConnectException):
            validate_jwt_options("something", "something")

        # Success
        validate_jwt_options("something", "tests/testdata/secret.key")

        # Env variable lets us ignore the provided filepath entirely

        os.environ[SECRET_ENV_VAR] = "asecret"

        validate_jwt_options("something", None)
        validate_jwt_options("something", "something")
        validate_jwt_options("something", "tests/testdata/secret.key")
