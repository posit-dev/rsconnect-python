import os
import ssl
import sys

from os.path import abspath, dirname

import httpretty.core


HERE = dirname(abspath(__file__))
sys.path.insert(0, HERE)

# tests/test_main_content.py expects the content build store to live in
# "rsconnect-build-test". rsconnect.metadata binds CONNECT_CONTENT_BUILD_DIR as a
# default argument value at import time, so this must be set before any test
# module imports rsconnect. (Previously injected by the Makefile's TEST_ENV.)
os.environ.setdefault("CONNECT_CONTENT_BUILD_DIR", "rsconnect-build-test")

# httpretty (1.1.4, released 2021) mocks TLS with
# `ssl.SSLContext.wrap_socket = functools.partial(fake_wrap_socket, ...)`.
# Python 3.14 made partial objects descriptors, so that class attribute now binds
# the SSLContext as the first positional argument and httpretty mistakes it for
# the socket. Drop the extra argument. The isinstance check makes this a no-op on
# Python 3.13 and earlier, and also once httpretty ships the fix in
# gabrielfalcao/HTTPretty#488. Tracked by #833, which proposes replacing
# httpretty with mocket so this shim can go away.
_httpretty_fake_wrap_socket = httpretty.core.fake_wrap_socket


def _fake_wrap_socket(orig_wrap_socket_fn, *args, **kw):
    if args and isinstance(args[0], ssl.SSLContext):
        args = args[1:]
    return _httpretty_fake_wrap_socket(orig_wrap_socket_fn, *args, **kw)


httpretty.core.fake_wrap_socket = _fake_wrap_socket
