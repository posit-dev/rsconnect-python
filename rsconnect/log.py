"""
Logging wrapper and shared instance
"""
import json
import logging

import click
import six

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

class LogOutputFormat(object):
    TEXT = "text"
    JSON = "json"
    DEFAULT = TEXT
    _all = [
        TEXT,
        JSON
    ]


class JsonLogFormatter(logging.Formatter):
    """
    https://stackoverflow.com/a/70223539
    Formatter that outputs JSON strings after parsing the LogRecord.

    @param dict fmt_dict: Key: logging format attribute pairs.
    @param str datefmt: Key: strftime format string
    """
    def __init__(self, fmt_dict = None, datefmt = _DATE_FORMAT):
        self.fmt_dict = fmt_dict if fmt_dict is not None else {
            "timestamp": "asctime",
            "level": "levelname",
            "message": "message"
        }
        self.datefmt = datefmt

    def usesTime(self):
        """
        Overwritten to look for the attribute in the format dict values instead of the fmt string.
        """
        return "asctime" in self.fmt_dict.values()

    def formatMessage(self, record):
        """
        Overwritten to return a dictionary of the relevant LogRecord attributes instead of a string.
        KeyError is raised if an unknown attribute is provided in the fmt_dict.
        """
        return {fmt_key: record.__dict__[fmt_val] for fmt_key, fmt_val in self.fmt_dict.items()}

    def format(self, record):
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


class RSLogger(logging.LoggerAdapter):
    def __init__(self):
        super(RSLogger, self).__init__(logging.getLogger("rsconnect"), {})
        self._in_feedback = False
        self._have_feedback_output = False
        self._log_format = LogOutputFormat.DEFAULT

    def addHandler(self, handler):
        self.logger.addHandler(handler)

    def set_in_feedback(self, value):
        self._in_feedback = value
        self._have_feedback_output = False

    def set_log_output_format(self, value):
        self._log_format = value
        if self._log_format == LogOutputFormat.JSON:
            for h in self.logger.handlers:
                h.setFormatter(JsonLogFormatter())
        else:
            for h in self.logger.handlers:
                h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s %(message)s", datefmt=_DATE_FORMAT))

    def process(self, msg, kwargs):
        msg, kwargs = super(RSLogger, self).process(msg, kwargs)
        if self._in_feedback and self.is_debugging():
            if not self._have_feedback_output:
                six.print_()
                self._have_feedback_output = True
            msg = click.style(" %s" % msg, fg="green")
        return msg, kwargs

    def is_debugging(self):
        return self.isEnabledFor(logging.DEBUG)

    def setLevel(self, level):
        """
        Set the specified level on the underlying logger.

        **Note:** This is present in newer Python versions but since it's missing
        from 2.7, we replicate it here.
        """
        self.logger.setLevel(level)

logger = RSLogger()
logger.addHandler(logging.StreamHandler())
logger.set_log_output_format(LogOutputFormat.DEFAULT)
