"""Backfill empty GitHub Release bodies from docs/CHANGELOG.md.

The GitHub Releases for this project have empty bodies; the real history
lives in docs/CHANGELOG.md (Keep a Changelog format). This one-time script
parses that file and populates each matching Release so great-docs can
generate its Changelog page from Releases.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Dict

VERSION_HEADER = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+(?:[a-z]+\d+)?)\](?: - \S+)?\s*$")
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


def build_backfill_plan(
    entries: Dict[str, str],
    existing_tags: set[str],
    release_has_body: Dict[str, bool],
) -> list[tuple[str, str]]:
    """Return (tag, body) edits for releases that exist and are empty."""
    plan: list[tuple[str, str]] = []
    for version, body in entries.items():
        if version not in existing_tags:
            continue
        if release_has_body.get(version, False):
            continue
        plan.append((version, body))
    return plan


def _gh_releases() -> Dict[str, bool]:
    """Map existing release tag -> whether its body is non-empty."""
    out = subprocess.run(
        ["gh", "release", "list", "--limit", "500", "--json", "tagName,name"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    result: Dict[str, bool] = {}
    for rel in json.loads(out):
        tag = rel["tagName"]
        try:
            body = subprocess.run(
                ["gh", "release", "view", tag, "--json", "body", "-q", ".body"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as err:
            print(f"warning: could not read release {tag}: {err}", file=sys.stderr)
            result[tag] = True
            continue
        result[tag] = bool(body)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("changelog", nargs="?", default="docs/CHANGELOG.md")
    parser.add_argument("--apply", action="store_true", help="Actually edit releases")
    args = parser.parse_args(argv)

    with open(args.changelog, encoding="utf-8") as handle:
        entries = parse_changelog(handle.read())

    body_by_tag = _gh_releases()
    existing = set(body_by_tag)
    plan = build_backfill_plan(entries, existing, body_by_tag)

    for tag, body in plan:
        print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {tag} ({len(body)} chars)")
        if args.apply:
            subprocess.run(
                ["gh", "release", "edit", tag, "--notes-file", "-"],
                input=body,
                text=True,
                check=True,
            )
    print(f"{len(plan)} release(s) {'updated' if args.apply else 'would be updated'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
