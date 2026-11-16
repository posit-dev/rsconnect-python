from __future__ import annotations


class RSConnectException(Exception):
    def __init__(self, message: str, cause: Exception | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.status = status


class DeploymentFailedException(RSConnectException):
    pass


class ConnectCloudAccountNotFoundError(RSConnectException):
    """A completed account lookup did not find the requested Cloud account."""
