import os
from typing import Union

from rsconnect.exception import RSConnectException

_CONNECT_REQUEST_TIMEOUT_KEY = "CONNECT_REQUEST_TIMEOUT"
_CONNECT_REQUEST_TIMEOUT_DEFAULT_VALUE = "300"


def get_timeout() -> int:
    """Gets the timeout from the CONNECT_REQUEST_TIMEOUT env variable.

    The timeout value is intended to be interpreted in seconds. A value of 60 is equal to sixty seconds, or one minute.

    If CONNECT_REQUEST_TIMEOUT is unset, a default value of 300 is used.

    If CONNECT_REQUEST_TIMEOUT is set to a value less than 0, an `RSConnectException` is raised.

    A CONNECT_REQUEST_TIMEOUT set to 0 is logically equivalent to no timeout.

    The primary intent for this method is for usage with the `http` module. Specifically, for setting the timeout
    parameter with an `http.client.HTTPConnection` or `http.client.HTTPSConnection`.

    :raises: `RSConnectException` if CONNECT_REQUEST_TIMEOUT is not a natural number.
    :return: the timeout value
    """
    timeout: Union[int, str] = os.environ.get(_CONNECT_REQUEST_TIMEOUT_KEY, _CONNECT_REQUEST_TIMEOUT_DEFAULT_VALUE)

    try:
        timeout = int(timeout)
    except ValueError:
        raise RSConnectException(
            f"'CONNECT_REQUEST_TIMEOUT' is set to '{timeout}'. The value must be a natural number."
        )

    if timeout < 0:
        raise RSConnectException(
            f"'CONNECT_REQUEST_TIMEOUT' is set to '{timeout}'. The value must be a natural number."
        )

    return timeout
