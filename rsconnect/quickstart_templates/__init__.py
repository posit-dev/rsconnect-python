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

# TODO(EVO-270): Decide template storage format and ship the v1 templates.
#                Scope: quickstart
#                Why: SPEC §17.5 leaves the choice open (plain copy with
#                     string substitution, Jinja2, Tempita, ...). v1 needs one
#                     concrete choice plus the eight supported-mode templates
#                     (streamlit, shiny, fastapi, api/flask, notebook, voila,
#                     quarto-static, quarto-shiny). Templates must be
#                     discoverable at runtime (either as ``package_data`` or
#                     via ``importlib.resources``) so they survive wheel
#                     install.
#                Done: Every per-mode evolution in ``rsconnect/quickstart.py``
#                      (``Register the <mode> template ...``) has its
#                      template files materialized here; the ATDD tests in
#                      ``tests/test_quickstart.py`` that assert on generated
#                      file contents pass.
#                Non-Goals: Do not introduce a template engine when plain
#                           string substitution suffices; do not add build
#                           steps; do not mix R or Node templates in (v1 is
#                           Python-only per §16).
