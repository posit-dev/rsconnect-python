from __future__ import annotations

from typing import Optional


class RSConnectException(Exception):
    def __init__(self, message: str, cause: Optional[Exception] = None):
        super(RSConnectException, self).__init__(message)
        self.message = message
        self.cause = cause


class DeploymentFailedException(RSConnectException):
    pass
