import requests
import time
import sys
from datetime import timedelta

from rsconnect.json_web_token import (
    JWTEncoder,
    TokenGenerator,
    read_secret_key,
    validate_hs256_secret_key,
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    INITIAL_ADMIN_SCOPE,
    INITIAL_ADMIN_EXP,
)

SERVER = "http://localhost:3939"
INITIAL_ADMIN_ENDPOINT = SERVER + "/__api__/v1/experimental/installation/initial_admin"
JWT_KEYPATH = "/Users/zverham/Development/rstudio/connect/jwt/secret.key"


SUCCESS = "\u2713"
FAILURE = "FAILED"


def preamble(text):
    print(text + "... ", end="")


def success():
    print(SUCCESS)


def failure(reason):
    print(FAILURE + ": " + reason)
    sys.exit(1)


def authorization_header(token):
    return {"Authorization": "Bearer " + token}


def generate_jwt_secured_header():
    secret_key = read_secret_key(JWT_KEYPATH)
    validate_hs256_secret_key(secret_key)

    token_generator = TokenGenerator(secret_key)

    initial_admin_token = token_generator.initial_admin()

    return authorization_header(initial_admin_token)


def create_jwt_encoder(issuer, audience):
    secret_key = read_secret_key(JWT_KEYPATH)
    validate_hs256_secret_key(secret_key)

    return JWTEncoder(issuer, audience, secret_key)


def assert_status_code(response, expected):
    if response.status_code != expected:
        failure("unexpected response status: " + str(response.status_code))


def initial_admin_no_header():
    preamble("Unable to access endpoint without a header present")

    response = requests.post(INITIAL_ADMIN_ENDPOINT)

    assert_status_code(response, 401)

    success()


def initial_admin_no_jwt_header():
    preamble("Unable to access endpoint without a JWT in the auth header")

    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(""))

    assert_status_code(response, 401)

    success()


def initial_admin_invalid_jwt_header():
    preamble("Unable to access endpoint with a bearer token that isn't a JWT")

    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header("invalid"))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_issuer():
    preamble("Unable to access endpoint with an incorrectly scoped JWT (invalid issuer)")

    encoder = create_jwt_encoder("invalid", DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": INITIAL_ADMIN_SCOPE}, INITIAL_ADMIN_EXP)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_audience():
    preamble("Unable to access endpoint with an incorrectly scoped JWT (invalid audience)")

    encoder = create_jwt_encoder(DEFAULT_ISSUER, "invalid")
    token = encoder.new_token({"scope": INITIAL_ADMIN_SCOPE}, INITIAL_ADMIN_EXP)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_scope():
    preamble("Unable to access endpoint with an incorrectly scopet JWT (invalid scope)")

    encoder = create_jwt_encoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": INITIAL_ADMIN_SCOPE}, INITIAL_ADMIN_EXP)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_no_scope():
    preamble("Unable to access endpoint with an incorrectly scoped JWT (no scope provided)")

    encoder = create_jwt_encoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"invalid": "invalid"}, INITIAL_ADMIN_EXP)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_different_secret():
    preamble("Unable to access endpoint with a JWT signed with an unexpected secret")

    encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, "invalid_secret")
    token = encoder.new_token({"scope": INITIAL_ADMIN_SCOPE}, INITIAL_ADMIN_EXP)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_expired():
    preamble("Unable to access endpoint with an incorrectly scoped JWT (expired)")

    encoder = create_jwt_encoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": INITIAL_ADMIN_SCOPE}, timedelta(seconds=1))
    time.sleep(5)
    response = requests.post(INITIAL_ADMIN_ENDPOINT, authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_endpoint_happy_path():
    preamble("Verifying initial admin endpoint happy path")

    response = requests.post(INITIAL_ADMIN_ENDPOINT, headers=generate_jwt_secured_header())

    assert_status_code(response, 200)

    json_data = response.json()
    if "api_key" not in json_data:
        failure("api_key key not in json response")

    if json_data["api_key"] is None or json_data["api_key"] == "":
        failure("api_key value not in json response")

    success()


def initial_admin_subsequent_calls():
    preamble("Subsequent call should fail gracefully")

    response = requests.post(INITIAL_ADMIN_ENDPOINT, headers=generate_jwt_secured_header())

    assert_status_code(response, 400)

    success()


def other_endpoint_does_not_accept_jwts():
    preamble("Only the initial admin endpoint will authorize using jwts")

    response = requests.post(SERVER + "/__api__/me", headers=generate_jwt_secured_header())

    assert_status_code(response, 401)

    success()


test_functions = [
    initial_admin_no_header,
    initial_admin_no_jwt_header,
    initial_admin_invalid_jwt_header,
    initial_admin_incorrect_jwt_invalid_issuer,
    initial_admin_incorrect_jwt_invalid_audience,
    initial_admin_incorrect_jwt_invalid_scope,
    initial_admin_incorrect_jwt_expired,
    initial_admin_no_scope,
    initial_admin_different_secret,
    initial_admin_endpoint_happy_path,
    initial_admin_subsequent_calls,
    other_endpoint_does_not_accept_jwts,
]


def run_testbed():

    print("RUNNING TESTBED")
    print("---------------")

    for test_function in test_functions:
        test_function()

    print()
    print("Done.")


if __name__ == "__main__":
    run_testbed()
