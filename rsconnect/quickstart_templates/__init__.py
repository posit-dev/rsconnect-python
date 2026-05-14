"""
Template data for :mod:`rsconnect.quickstart`.

This package hosts the on-disk template files for every supported app mode.
It is deliberately a package (not a single module) so each mode can live in
its own subdirectory and the registry stays "drop in a directory to add a
mode" per SPEC_QUICKSTART.md §4.1. The package is internal to
``rsconnect.quickstart``; callers should not import from it directly.

See ``rsconnect/quickstart.py`` for the public entrypoint and the evolution
marker that defines the registry contract.
"""

# TODO(EVO-270): Ship the per-mode template files under this package.
#                Scope: quickstart
#                Why: The storage format is locked: stdlib ``str.format``
#                     substitution on plain text files discovered at runtime
#                     via :func:`importlib.resources.files`, laid out as
#                     ``rsconnect/quickstart_templates/<mode>/<file>`` so
#                     they survive wheel install. What remains is the
#                     per-mode content (streamlit, shiny, fastapi, api/flask,
#                     notebook, voila, quarto-static, quarto-shiny) referenced
#                     by each :class:`rsconnect.quickstart.FileSpec`.
#                Done: Every per-mode evolution in ``rsconnect/quickstart.py``
#                      (``Register the <mode> template ...``) has its
#                      ``source_files`` tuple populated and a matching file
#                      laid down under this package; the ATDD tests in
#                      ``tests/test_quickstart.py`` that assert on generated
#                      file contents pass.
#                Non-Goals: Do not introduce a template engine - stdlib
#                           ``str.format`` is the chosen format. Do not add
#                           build steps; do not mix R or Node templates in
#                           (v1 is Python-only per §16).
#                Caveat: :func:`importlib.resources.files` is Python 3.9+;
#                        ``rsconnect-python`` advertises ``requires-python
#                        >= 3.8``. When this marker lands, either use the
#                        ``importlib_resources`` backport on 3.8 or coordinate
#                        a floor bump first.
