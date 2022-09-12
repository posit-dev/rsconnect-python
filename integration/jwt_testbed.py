import requests
import time
import sys
import json
from datetime import timedelta

from rsconnect.json_web_token import (
    JWTEncoder,
    TokenGenerator,
    read_secret_key,
    validate_hs256_secret_key,
    DEFAULT_ISSUER,
    DEFAULT_AUDIENCE,
    BOOTSTRAP_SCOPE,
    BOOTSTRAP_EXP,
)

BOOTSTRAP_ENDPOINT = "/__api__/v1/experimental/bootstrap"

ENV_FILENAME = "env.json"

SUCCESS = "\u2713"
FAILURE = "FAILED"


def read_env():
    with open("integration/env.json", "r") as f:
        return json.loads(f.read())


def preamble(step, text):
    print("[{}] {}... ".format(step, text), end="")


def success():
    print(SUCCESS)


def failure(reason):
    print(FAILURE + ": {}".format(reason))
    sys.exit(1)


def authorization_header(token):
    return {"Authorization": "Bearer " + token}


def generate_jwt_secured_header(keypath):
    secret_key = read_secret_key(keypath)
    validate_hs256_secret_key(secret_key)

    token_generator = TokenGenerator(secret_key)

    initial_admin_token = token_generator.bootstrap()
    return authorization_header(initial_admin_token)


def create_jwt_encoder(keypath, issuer, audience):
    secret_key = read_secret_key(keypath)
    validate_hs256_secret_key(secret_key)

    return JWTEncoder(issuer, audience, secret_key)


def assert_status_code(response, expected):
    if response.status_code != expected:
        failure("unexpected response status: " + str(response.status_code))


def initial_admin_no_header(step, env):
    preamble(step, "Unable to access endpoint without a header present")

    response = requests.post(env["bootstrap_endpoint"])

    assert_status_code(response, 401)

    success()


def initial_admin_no_jwt_header(step, env):
    preamble(step, "Unable to access endpoint without a JWT in the auth header")

    response = requests.post(env["bootstrap_endpoint"], authorization_header(""))

    assert_status_code(response, 401)

    success()


def initial_admin_invalid_jwt_header(step, env):
    preamble(step, "Unable to access endpoint with a bearer token that isn't a JWT")

    response = requests.post(env["bootstrap_endpoint"], authorization_header("invalid"))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_issuer(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (invalid issuer)")

    encoder = create_jwt_encoder(env["keypath"], "invalid", DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_audience(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (invalid audience)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, "invalid")
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_invalid_scope(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scopet JWT (invalid scope)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_no_scope(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (no scope provided)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"invalid": "invalid"}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_different_secret(step, env):
    preamble(step, "Unable to access endpoint with a JWT signed with an unexpected secret")

    encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, "invalid_secret")
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_incorrect_jwt_expired(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (expired)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, timedelta(seconds=1))
    time.sleep(5)
    response = requests.post(env["bootstrap_endpoint"], authorization_header(token))

    assert_status_code(response, 401)

    success()


def initial_admin_endpoint_happy_path(step, env):
    preamble(step, "Verifying initial admin endpoint happy path")

    response = requests.post(env["bootstrap_endpoint"], headers=generate_jwt_secured_header(env["keypath"]))

    assert_status_code(response, 200)

    json_data = response.json()
    if "api_key" not in json_data:
        failure("api_key key not in json response")

    if json_data["api_key"] is None or json_data["api_key"] == "":
        failure("api_key value not in json response")

    success()


def initial_admin_subsequent_calls(step, env):
    preamble(step, "Subsequent call should fail gracefully")

    response = requests.post(env["bootstrap_endpoint"], headers=generate_jwt_secured_header(env["keypath"]))

    assert_status_code(response, 400)

    success()


def other_endpoint_does_not_accept_jwts(step, env):
    preamble(step, "Only the initial admin endpoint will authorize using jwts")

    response = requests.post(env["server"] + "/__api__/me", headers=generate_jwt_secured_header(env["keypath"]))

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

    print("VERIFYING ENV FILE")
    print("------------------")

    json_env = read_env()
    if "server" not in json_env:
        print("ERROR: server not configured in env file")
        sys.exit(1)
    if "keypath" not in json_env:
        print("ERROR keypath not configured in env file")
        sys.exit(1)

    json_env["bootstrap_endpoint"] = json_env["server"] + BOOTSTRAP_ENDPOINT

    print("RUNNING TESTBED")
    print("---------------")

    for i in range(len(test_functions)):
        test_functions[i](i, json_env)

    print()
    print("Done.")


if __name__ == "__main__":
    run_testbed()
