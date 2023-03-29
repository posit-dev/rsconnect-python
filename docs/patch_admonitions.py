#!/usr/bin/env python3

#
# Reads from STDIN. Writes to STDOUT. Messages to STDERR.
#
# Rewrites GitHub admonitions into mkdocs admonitions.
#
# This is because the README.md needs to use GitHub admonitions, while mkdocs
# wants its separate style when rendering. Only warnings and notes are
# supported by both flavors of admonitions.
#
# Input:
#
# > **Warning**
# > This is the warning text.
#
# > **Note**
# > This is the note text.
#
# Output:
# !!! warning
#     This is the warning text.
#
# !!! note
#     This is the note text.

import sys

def rewrite(gh_admonition, mkdocs_admonition, lines):
    for i in range(len(lines)):
        line = lines[i]
        # The GitHub admonition starts with something like:
        #     > **Note**
        # and continues until the current blockquote ends.
        # The start of the GitHub admonition MUST be on its own line.
        if gh_admonition == line.rstrip():
            lines[i] = f"!!! { mkdocs_admonition }\n"
            for j in range(i+1, len(lines)):
                if lines[j].startswith("> "):
                    text = lines[j][2:]
                    lines[j] = f"    { text }"
                else:
                    # Left the blockquote; stop rewriting.
                    break
    return lines

lines = sys.stdin.readlines()

lines = rewrite("> **Note**", "note", lines)
lines = rewrite("> **Warning**", "warning", lines)

sys.stdout.writelines(lines)
