"""``rsconnect quickstart`` package.

Public API:

- :func:`run_quickstart` — scaffold a new project.
- :data:`SUPPORTED_APP_TYPES` — supported quickstart type vocabulary.

Internal pieces (``TemplateSpec``, ``_REGISTRY``, etc.) live in
:mod:`rsconnect.quickstart.quickstart` and are not re-exported here.
Tests that need them (registry-extensibility) import the inner module
directly.
"""

from .quickstart import SUPPORTED_APP_TYPES, run_quickstart

__all__ = ["SUPPORTED_APP_TYPES", "run_quickstart"]
