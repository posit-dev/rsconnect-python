from scripts.backfill_release_notes import parse_changelog

SAMPLE = """# Changelog

Some preamble.

## Unreleased

- unreleased thing

## [1.29.0] - 2026-04-29

- Added `rsconnect deploy nodejs` command.

### Added

- `rsconnect content get-lockfile` command.

## [1.28.2] - 2025-12-05

### Fixed

- Corrected Changelog.

[Unreleased]: https://github.com/posit-dev/rsconnect-python/compare/1.5.0...HEAD
[1.5.0]: https://github.com/posit-dev/rsconnect-python/releases/tag/1.5.0
"""


def test_parse_changelog_extracts_versions_only():
    entries = parse_changelog(SAMPLE)
    assert set(entries) == {"1.29.0", "1.28.2"}


def test_parse_changelog_excludes_unreleased_and_link_refs():
    entries = parse_changelog(SAMPLE)
    assert "unreleased thing" not in "".join(entries.values())
    assert "compare/1.5.0" not in "".join(entries.values())


def test_parse_changelog_keeps_body_and_subsections():
    entries = parse_changelog(SAMPLE)
    assert "deploy nodejs" in entries["1.29.0"]
    assert "### Added" in entries["1.29.0"]
    assert "get-lockfile" in entries["1.29.0"]
    assert entries["1.28.2"].startswith("### Fixed")


def test_parse_changelog_strips_surrounding_blank_lines():
    entries = parse_changelog(SAMPLE)
    assert not entries["1.29.0"].startswith("\n")
    assert not entries["1.29.0"].endswith("\n")
