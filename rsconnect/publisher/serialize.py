"""TOML (de)serialization for ``.posit/publish`` files.

Reading uses the stdlib ``tomllib`` (3.11+) or the ``toml`` backport. Writing
uses ``tomli_w``, whose default output already matches Publisher's format:
multiline 4-space-indented arrays, quoted ``$schema`` key, and tables emitted
after top-level scalars. We only add the leading comment/header block and prune
empty values (which ``tomli_w`` cannot serialize).
"""

from __future__ import annotations

import os
import typing

import tomli_w

TOMLDecodeError: typing.Type[Exception]
try:
    import tomllib

    TOMLDecodeError = tomllib.TOMLDecodeError
except ImportError:
    # Python < 3.11 has no stdlib tomllib; fall back to the ``toml`` backport.
    import toml as tomllib  # type: ignore[no-redef]

    TOMLDecodeError = tomllib.TomlDecodeError


def load(path: str) -> typing.Dict[str, typing.Any]:
    """Parse the TOML file at ``path`` into a dict."""
    with open(path, encoding="utf-8") as f:
        return tomllib.loads(f.read())


def _prune(value: typing.Any) -> typing.Any:
    """Recursively drop ``None`` and empty-string values (and now-empty tables).

    Lists and falsy-but-meaningful scalars (``False``, ``0``) are preserved.
    ``tomli_w`` raises on ``None``, and Publisher omits empty strings, so this
    mirrors its ``omitempty``/``stripEmpty`` behavior.
    """
    if isinstance(value, dict):
        out: typing.Dict[str, typing.Any] = {}
        for key, val in value.items():
            pruned = _prune(val)
            if pruned is None:
                continue
            out[key] = pruned
        return out or None
    if isinstance(value, str):
        return value if value != "" else None
    return value


def dumps(data: typing.Mapping[str, typing.Any], header_lines: typing.Sequence[str] = ()) -> str:
    """Serialize ``data`` to a TOML string, prefixed with ``header_lines``.

    Each header line is written verbatim (callers include the leading ``#``).
    """
    pruned = _prune(dict(data)) or {}
    body = tomli_w.dumps(pruned)
    prefix = "".join(line + "\n" for line in header_lines)
    text = prefix + body
    if not text.endswith("\n"):
        text += "\n"
    return text


def write(path: str, content: str) -> None:
    """Write ``content`` to ``path``, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
