"""
Json Web Token (JWT) utilities
"""

import os

import jwt
from datetime import datetime, timedelta, timezone

DEFAULT_ISSUER = "rsconnect-python"
DEFAULT_AUDIENCE = "rsconnect"

SECRET_ENV_VAR = "RSCONNECT_JWT_SECRET"


# Load the secret to be used for signing JWTs
def load_secret(secret_path=None):

    # Prioritize environment variable (if it exists)
    env_secret = os.getenv(SECRET_ENV_VAR)
    if env_secret is not None:
        return env_secret

    # Default read from filepath

    # Can't read a file if we didn't provide one
    if secret_path is None:
        raise RuntimeError()

    # If file does not exist, we have no secret!
    if not os.path.exists(secret_path):
        raise FileNotFoundError()

    with open(secret_path, "r") as f:
        return f.read()


class JWTEncoder:
    def __init__(self, issuer: str, audience: str, secret: str):
        self.issuer = issuer
        self.audience = audience
        self.secret = secret

    def generate_standard_claims(self, current_datetime: datetime, exp: timedelta):

        return {
            "exp": int((current_datetime + exp).timestamp()),
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(current_datetime.timestamp()),
        }

    def new_token(self, custom_claims: dict, exp: timedelta):

        standard_claims = self.generate_standard_claims(datetime.now(tz=timezone.utc), exp)

        claims = {}
        for c in [standard_claims, custom_claims]:
            claims.update(c)

        return jwt.encode(claims, self.secret, algorithm="HS256")


# Used in unit tests
class JWTDecoder:
    def __init__(self, audience: str, secret: str):
        self.audience = audience
        self.secret = secret

    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["HS256"])


# Uses a generic encoder to create JWTs with specific custom scopes / expiration times
class TokenGenerator:
    def __init__(self, secret: str):
        self.encoder = JWTEncoder(DEFAULT_ISSUER, DEFAULT_AUDIENCE, secret)

    def initial_admin(self):
        custom_claims = {"endpoint": "/__api__/v1/experimental/installation/initial-admin", "method": "GET"}  # todo

        exp = timedelta(minutes=15)

        return self.encoder.new_token(custom_claims, exp)
