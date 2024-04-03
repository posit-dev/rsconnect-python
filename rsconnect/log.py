"""
Logging wrapper and shared instance
"""

from __future__ import annotations

import json
import logging
import sys
from functools import partial, wraps
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Protocol, TypeVar

if sys.version_info >= (3, 10):
    from typing import Concatenate, ParamSpec
else:
    from typing_extensions import Concatenate, ParamSpec


if TYPE_CHECKING:
    from collections.abc import MutableMapping

import click

T = TypeVar("T")
P = ParamSpec("P")


_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

VERBOSE = int((logging.INFO + logging.DEBUG) / 2)
logging.addLevelName(VERBOSE, "VERBOSE")


class LogOutputFormat(object):
    TEXT = "text"
    JSON = "json"
    DEFAULT = TEXT
    _all = [TEXT, JSON]
    All = Literal["text", "json"]


class JsonLogFormatter(logging.Formatter):
    """
    https://stackoverflow.com/a/70223539
    Formatter that outputs JSON strings after parsing the LogRecord.

    @param dict fmt_dict: Key: logging format attribute pairs.
    @param str datefmt: Key: strftime format string
    """

    def __init__(self, fmt_dict: Optional[dict[str, str]] = None, datefmt: str = _DATE_FORMAT):
        self.fmt_dict = (
            fmt_dict if fmt_dict is not None else {"timestamp": "asctime", "level": "levelname", "message": "message"}
        )
        self.datefmt = datefmt

    def usesTime(self):
        """
        Overwritten to look for the attribute in the format dict values instead of the fmt string.
        """
        return "asctime" in self.fmt_dict.values()

    def formatMessage(self, record: logging.LogRecord):  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        Overwritten to return a dictionary of the relevant LogRecord attributes instead of a string.
        KeyError is raised if an unknown attribute is provided in the fmt_dict.
        """
        return {fmt_key: record.__dict__[fmt_val] for fmt_key, fmt_val in self.fmt_dict.items()}

    def format(self, record: logging.LogRecord):
        """
        Mostly the same as the parent's class method, the difference being that a dict is manipulated and dumped as JSON
        instead of a string.
        """
        record.message = record.getMessage()

        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        message_dict = self.formatMessage(record)

        if record.exc_info:
            # Cache the traceback text to avoid converting it multiple times
            # (it's constant anyway)
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        if record.exc_text:
            message_dict["exc_info"] = record.exc_text

        if record.stack_info:
            message_dict["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(message_dict, default=str)


# This is a workaround for LoggerAdapter not being generic in Python<=3.10.
# See also:
# https://github.com/python/typeshed/issues/7855#issuecomment-1128857842
if sys.version_info >= (3, 11):
    _LoggerAdapter = logging.LoggerAdapter[logging.Logger]
else:
    _LoggerAdapter = logging.LoggerAdapter


class RSLogger(_LoggerAdapter):
    def __init__(self):
        super(RSLogger, self).__init__(logging.getLogger("rsconnect"), {})
        self._in_feedback = False
        self._have_feedback_output = False
        self._log_format = LogOutputFormat.DEFAULT

    def addHandler(self, handler: logging.Handler):
        self.logger.addHandler(handler)

    def set_in_feedback(self, value: bool):
        self._in_feedback = value
        self._have_feedback_output = False

    def set_log_output_format(self, value: LogOutputFormat.All):
        self._log_format = value
        if self._log_format == LogOutputFormat.JSON:
            for h in self.logger.handlers:
                h.setFormatter(JsonLogFormatter())
        else:
            for h in self.logger.handlers:
                h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s %(message)s", datefmt=_DATE_FORMAT))

    def process(self, msg: str, kwargs: MutableMapping[str, Any]):
        msg, kwargs = super(RSLogger, self).process(msg, kwargs)
        if self._in_feedback and self.is_debugging():
            if not self._have_feedback_output:
                print()
                self._have_feedback_output = True
            msg = click.style(" %s" % msg, fg="green")
        return msg, kwargs

    def is_debugging(self):
        return self.isEnabledFor(logging.DEBUG)

    def setLevel(self, level: int | str):
        """
        Set the specified level on the underlying logger.

        **Note:** This is present in newer Python versions but since it's missing
        from 2.7, we replicate it here.
        """
        self.logger.setLevel(level)


logger = RSLogger()
logger.addHandler(logging.StreamHandler())
logger.set_log_output_format(LogOutputFormat.DEFAULT)


class ConsoleFormatter(logging.Formatter):

    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    msg_format = "%(message)s"
    reset = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: green + msg_format + reset,
        logging.INFO: reset + msg_format + reset,
        logging.WARNING: yellow + msg_format + reset,
        logging.ERROR: red + msg_format + reset,
        logging.CRITICAL: red + msg_format + reset,
    }

    def format(self, record: logging.LogRecord):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


console_logger = logging.getLogger("console")
console_logger.setLevel(logging.DEBUG)

# create console handler
console_handler = logging.StreamHandler()
console_handler.terminator = ""
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(ConsoleFormatter())
console_logger.addHandler(console_handler)


def logged(logger: logging.Logger, label: str):
    def decorator(f: Callable[P, T]) -> Callable[P, T]:
        @wraps(f)
        def wrapper(*args: P.args, **kw: P.kwargs):
            logger.info(label)
            result = None
            try:
                result = f(*args, **kw)
            except Exception as exc:
                logger.error(" \t[ERROR]: {}\n".format(str(exc)))
                raise
            logger.debug(" \t[OK]\n")
            return result

        return wrapper

    return decorator


class HasLoggerMethod(Protocol):
    logger: logging.Logger | None


HasLoggerMethodT = TypeVar("HasLoggerMethodT", bound=HasLoggerMethod)


def cls_logged(label: str):  # uses logger provided by a class' self.logger
    def decorator(
        method: Callable[Concatenate[HasLoggerMethodT, P], T],
    ) -> Callable[Concatenate[HasLoggerMethodT, P], T]:

        @wraps(method)
        def wrapper(self: HasLoggerMethodT, *args: P.args, **kw: P.kwargs):
            logger = self.logger
            if logger:
                logger.info(label)
            result = None
            try:
                result = method(self, *args, **kw)
            except Exception as exc:
                msg = " \t[ERROR]: {}\n"
                if logger:
                    logger.error(msg.format(str(exc)))
                else:
                    print(msg)
                raise
            if logger:
                logger.debug(" \t[OK]\n")
            return result

        return wrapper

    return decorator


console_logged = partial(logged, console_logger)


# generic logger
connect_logger = logging.getLogger("connect_logger")
connect_logger.setLevel(logging.DEBUG)
connect_handler = logging.StreamHandler()
connect_handler.terminator = "\n"
connect_handler.setLevel(logging.DEBUG)
connect_handler.setFormatter(ConsoleFormatter())
connect_logger.addHandler(connect_handler)
