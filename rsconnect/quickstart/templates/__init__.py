"""
Template data for :mod:`rsconnect.quickstart.quickstart`.

This package hosts the on-disk template files for every supported app mode.
It is deliberately a package (not a single module) so each mode can live in
its own subdirectory and the registry stays "drop in a directory to add a
mode". The package is internal to ``rsconnect.quickstart``; callers should
not import from it directly.

Template bodies are loaded at scaffold time via :func:`pkgutil.get_data`
and run through ``str.replace("{name}", name)`` for the single supported
substitution token. ``str.format`` is deliberately avoided so templates
carrying literal braces (e.g. ``notebook.ipynb`` JSON) pass through
unchanged.
"""
