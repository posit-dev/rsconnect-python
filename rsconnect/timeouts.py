import os
import textwrap

from typing import Union

from rsconnect.exception import RSConnectException

_CONNECT_REQUEST_TIMEOUT_KEY: str = "CONNECT_REQUEST_TIMEOUT"
_CONNECT_REQUEST_TIMEOUT_DEFAULT_VALUE: str = "300"

_CONNECT_TASK_TIMEOUT_KEY: str = "CONNECT_TASK_TIMEOUT"
_CONNECT_TASK_TIMEOUT_DEFAULT_VALUE: str = "86400"


def get_request_timeout() -> int:
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
            f"'CONNECT_REQUEST_TIMEOUT' is set to '{timeout}'. The value must be a non-negative integer."
        )

    if timeout < 0:
        raise RSConnectException(
            f"'CONNECT_REQUEST_TIMEOUT' is set to '{timeout}'. The value must be a non-negative integer."
        )

    return timeout


def get_task_timeout() -> int:
    """Gets the timeout from the CONNECT_TASK_TIMEOUT env variable.

    The timeout value is intended to be interpreted in seconds. A value of 60 is equal to sixty seconds, or one minute.

    If CONNECT_TASK_TIMEOUT is unset, a default value of 86,400 (1 day) is used.

    If CONNECT_TASK_TIMEOUT is set to a value less or equal to 0, an `RSConnectException` is raised.

    The primary intent for this method is for usage with the `api` module. Specifically, for setting the timeout
    parameter in the method `wait_for_task`.

    :raises: `RSConnectException` if CONNECT_TASK_TIMEOUT is not a positive integer.
    :return: the timeout value
    """
    timeout: Union[int, str] = os.environ.get(_CONNECT_TASK_TIMEOUT_KEY, _CONNECT_TASK_TIMEOUT_DEFAULT_VALUE)

    try:
        timeout = int(timeout)
    except ValueError:
        raise RSConnectException(f"'CONNECT_TASK_TIMEOUT' is set to '{timeout}'. The value must be a positive integer.")

    if timeout <= 0:
        raise RSConnectException(f"'CONNECT_TASK_TIMEOUT' is set to '{timeout}'. The value must be a positive integer.")

    return timeout


def get_task_timeout_help_message(timeout=get_task_timeout()) -> str:
    """Gets a human friendly help message for adjusting the task timeout value."""

    return f"The task timed out after {timeout} seconds." + textwrap.dedent(
        f"""

        You may try increasing the task timeout value using the {_CONNECT_TASK_TIMEOUT_KEY} environment variable. The default value is {_CONNECT_TASK_TIMEOUT_DEFAULT_VALUE} seconds. The current value is {get_task_timeout()} seconds.

        Example:

            CONNECT_TASK_TIMEOUT={_CONNECT_TASK_TIMEOUT_DEFAULT_VALUE} rsconnect deploy api --server <your-server> --api-key <your-api-key> ./
        """  # noqa: E501
    )
