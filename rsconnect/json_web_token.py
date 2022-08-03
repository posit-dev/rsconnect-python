"""
Json Web Token (JWT) utilities
"""

import jwt
from datetime import datetime, timedelta, timezone


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


class JWTDecoder:
    def __init__(self, audience: str, secret: str):
        self.audience = audience
        self.secret = secret


    def decode_token(self, token: str):
        return jwt.decode(token, self.secret, audience=self.audience, algorithms=["HS256"])

