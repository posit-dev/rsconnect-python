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
API_KEY_ENDPOINT = "/__api__/me"


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


def api_key_authorization_header(token):
    return {"Authorization": "Key " + token}


def jwt_authorization_header(token):
    return {"Authorization": "Connect-Bootstrap " + token}


def generate_jwt_secured_header(keypath):
    secret_key = read_secret_key(keypath)
    validate_hs256_secret_key(secret_key)

    token_generator = TokenGenerator(secret_key)

    initial_admin_token = token_generator.bootstrap()
    return jwt_authorization_header(initial_admin_token)


def create_jwt_encoder(keypath, issuer, audience):
    secret_key = read_secret_key(keypath)
    validate_hs256_secret_key(secret_key)

    return JWTEncoder(issuer, audience, secret_key)


def assert_status_code(response, expected):
    if response.status_code != expected:
        failure("unexpected response status: " + str(response.status_code))


def no_header(step, env):
    preamble(step, "Unable to access endpoint without a header present")

    response = requests.post(env["bootstrap_endpoint"])

    assert_status_code(response, 401)

    success()


def no_jwt_header(step, env):
    preamble(step, "Unable to access endpoint without a JWT in the auth header")

    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(""))

    assert_status_code(response, 401)

    success()


def invalid_jwt_header(step, env):
    preamble(step, "Unable to access endpoint with a bearer token that isn't a JWT")

    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header("invalid"))

    assert_status_code(response, 401)

    success()


def incorrect_jwt_invalid_issuer(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (invalid issuer)")

    encoder = create_jwt_encoder(env["keypath"], "invalid", DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def incorrect_jwt_invalid_audience(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (invalid audience)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, "invalid")
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def incorrect_jwt_invalid_scope(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (invalid scope)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def no_scope(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (no scope provided)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"invalid": "invalid"}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def different_secret(step, env):
    preamble(step, "Unable to access endpoint with a JWT signed with an unexpected secret")

    encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, "invalid_secret")
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, BOOTSTRAP_EXP)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def incorrect_jwt_expired(step, env):
    preamble(step, "Unable to access endpoint with an incorrectly scoped JWT (expired)")

    encoder = create_jwt_encoder(env["keypath"], DEFAULT_ISSUER, DEFAULT_AUDIENCE)
    token = encoder.new_token({"scope": BOOTSTRAP_SCOPE}, timedelta(seconds=1))
    time.sleep(5)
    response = requests.post(env["bootstrap_endpoint"], jwt_authorization_header(token))

    assert_status_code(response, 401)

    success()


def verify_api_key_endpoint_invalid(step, env):
    preamble(step, "Unable to access api key endpoint with invalid api key (prereq)")

    response = requests.get(env["api_key_endpoint"], headers=api_key_authorization_header("invalid"))
    assert_status_code(response, 401)

    empty_string_response = requests.get(env["api_key_endpoint"], headers=api_key_authorization_header(""))
    assert_status_code(empty_string_response, 401)

    success()


def verify_api_key_endpoint_empty(step, env):
    preamble(step, "Unable to access api key endpoint with no api key (prereq)")

    response = requests.get(env["api_key_endpoint"])
    assert_status_code(response, 401)

    success()


def endpoint_happy_path(step, env):
    preamble(step, "Verifying initial admin endpoint happy path")

    response = requests.post(env["bootstrap_endpoint"], headers=generate_jwt_secured_header(env["keypath"]))

    assert_status_code(response, 200)

    json_data = response.json()
    if "api_key" not in json_data:
        failure("api_key key not in json response")

    api_key = json_data["api_key"]
    if api_key is None or api_key == "":
        failure("api_key value not in json response")

    # verify that we can get into the api key endpoint with the returned key

    api_key = json_data["api_key"]

    api_response = requests.get(env["api_key_endpoint"], headers=api_key_authorization_header(api_key))
    assert_status_code(api_response, 200)
    api_json = api_response.json()

    # verify that the response is reasonable from an api_key secured endpoint

    if "username" not in api_json:
        failure("No username returned from /me")

    if len(api_json["username"]) == 0:
        failure("Empty username returned from /me")

    if "user_role" not in api_json:
        failure("No user_role returned from /me")

    if api_json["user_role"] != "administrator":
        failure("Invalid user_role returned from /me: {}".format(api_json["user_role"]))

    # bootstrap endpoint should not respond to api key
    bootstrap_api_response = requests.post(env["bootstrap_endpoint"], headers=jwt_authorization_header(api_key))
    assert_status_code(bootstrap_api_response, 401)

    success()


def endpoint_subsequent_calls(step, env):
    preamble(step, "Subsequent call should fail gracefully")

    response = requests.post(env["bootstrap_endpoint"], headers=generate_jwt_secured_header(env["keypath"]))

    assert_status_code(response, 403)

    success()


def other_endpoint_does_not_accept_jwts(step, env):
    preamble(step, "Only the initial admin endpoint will authorize using jwts")

    response = requests.get(env["api_key_endpoint"], headers=generate_jwt_secured_header(env["keypath"]))

    assert_status_code(response, 401)

    invalid_jwt_response = requests.get(env["api_key_endpoint"], headers={"Authorization": "Bearer invalid"})

    assert_status_code(invalid_jwt_response, 401)

    success()


test_functions = [
    no_header,
    no_jwt_header,
    invalid_jwt_header,
    incorrect_jwt_invalid_issuer,
    incorrect_jwt_invalid_audience,
    incorrect_jwt_invalid_scope,
    incorrect_jwt_expired,
    no_scope,
    different_secret,
    # verify the behavior of a "normal" api key endpoint before running the full endpoint excercise
    verify_api_key_endpoint_invalid,
    verify_api_key_endpoint_empty,
    endpoint_happy_path,
    endpoint_subsequent_calls,
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
    json_env["api_key_endpoint"] = json_env["server"] + API_KEY_ENDPOINT

    print("RUNNING TESTBED")
    print("---------------")

    for i in range(len(test_functions)):
        test_functions[i](i, json_env)

    print()
    print("Done.")


if __name__ == "__main__":
    run_testbed()
