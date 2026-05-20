"""
Template data for :mod:`rsconnect.quickstart.quickstart`.

This package hosts the on-disk template files for every supported app mode.
It is deliberately a package (not a single module) so each mode can live in
its own subdirectory and the registry stays "drop in a directory to add a
mode". The package is internal to ``rsconnect.quickstart``; callers should
not import from it directly.

Template bodies are loaded at scaffold time via :func:`pkgutil.get_data`
and substituted with :class:`string.Template`, which uses ``$identifier``
syntax. The ``$``-syntax sidesteps the literal-brace concern that JSON
templates (``notebook.ipynb.tmpl``) and TOML inline tables would raise
under :meth:`str.format`. A literal ``$`` in any template must be escaped
as ``$$``.
"""
