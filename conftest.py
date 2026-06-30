import os
import sys

from os.path import abspath, dirname


HERE = dirname(abspath(__file__))
sys.path.insert(0, HERE)

# tests/test_main_content.py expects the content build store to live in
# "rsconnect-build-test". rsconnect.metadata binds CONNECT_CONTENT_BUILD_DIR as a
# default argument value at import time, so this must be set before any test
# module imports rsconnect. (Previously injected by the Makefile's TEST_ENV.)
os.environ.setdefault("CONNECT_CONTENT_BUILD_DIR", "rsconnect-build-test")
