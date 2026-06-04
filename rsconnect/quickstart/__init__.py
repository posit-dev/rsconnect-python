"""``rsconnect quickstart`` package.

Public API:

- :func:`run_quickstart` — scaffold a new project.

Internal pieces (``TemplateSpec``, ``_REGISTRY``, etc.) live in
:mod:`rsconnect.quickstart.quickstart` and are not re-exported here.
Tests that need them (registry-extensibility) import the inner module
directly. The CLI alias vocabulary lives on :class:`rsconnect.models.AppModes`
(see :meth:`rsconnect.models.AppModes.cli_aliases`).
"""

from .quickstart import run_quickstart

__all__ = ["run_quickstart"]
