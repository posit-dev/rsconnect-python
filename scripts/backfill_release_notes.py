"""Backfill empty GitHub Release bodies from docs/CHANGELOG.md.

The GitHub Releases for this project have empty bodies; the real history
lives in docs/CHANGELOG.md (Keep a Changelog format). This one-time script
parses that file and populates each matching Release so great-docs can
generate its Changelog page from Releases.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Dict

VERSION_HEADER = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+(?:[a-z]+\d+)?)\](?: - \S+)?\s*$"
)
LINK_REF = re.compile(r"^\[[^\]]+\]:\s+https?://")


def parse_changelog(text: str) -> Dict[str, str]:
    """Split a Keep-a-Changelog document into {version: body}.

    Skips the 'Unreleased' section and trailing link-reference
    definitions. Body is the markdown between a version header and the
    next '## ' header, with surrounding blank lines stripped.
    """
    entries: Dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is not None:
            entries[current] = "\n".join(buffer).strip()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            match = VERSION_HEADER.match(line)
            current = match.group("version") if match else None
            buffer = []
            continue
        if LINK_REF.match(line):
            continue
        if current is not None:
            buffer.append(line)

    flush()
    return entries
