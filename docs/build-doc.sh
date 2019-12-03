#!/bin/sh

set -ex

TITLE='rsconnect-python User Guide'

pandoc -f markdown-implicit_figures \
    --self-contained \
    -o "dist/rsconnect_python-${VERSION}.html" \
    -H docs/style.css \
    -T "${TITLE}" \
    -M "title:${TITLE}" \
    README.md

pandoc -f markdown-implicit_figures \
    -o "dist/rsconnect_python-${VERSION}.pdf" \
    -T "${TITLE}" \
    -M "title:${TITLE}" \
    README.md
