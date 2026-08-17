import sys

import pytest


@pytest.fixture(autouse=True)
def no_system_keyring():
    """Make the system keyring unavailable to every test.

    `keyring` is installed in the test environment (twine depends on it), so
    without this the credential paths would read and write the machine's real
    keychain. Tests that exercise keyring storage replace `sys.modules["keyring"]`
    with a mock of their own, or patch the helpers in `rsconnect.oauth`.

    sys.modules is restored by hand rather than through the `monkeypatch`
    fixture: an autouse fixture requesting `monkeypatch` hoists the shared
    instance ahead of every test-level fixture, so its undo (including any
    `monkeypatch.chdir`) would run after those fixtures' cleanup. That order
    deletes a still-current working directory on Windows, which fails.
    """
    absent = object()
    previous = sys.modules.get("keyring", absent)
    sys.modules["keyring"] = None  # type: ignore[assignment]
    try:
        yield
    finally:
        # The sentinel default distinguishes the fixture's own None marker from
        # a key some test deleted outright, which is left as that test's doing.
        if sys.modules.get("keyring", absent) is None:
            if previous is absent:
                del sys.modules["keyring"]
            else:
                sys.modules["keyring"] = previous  # type: ignore[assignment]
