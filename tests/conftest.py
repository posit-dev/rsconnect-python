import sys

import pytest


@pytest.fixture(autouse=True)
def no_system_keyring(monkeypatch: pytest.MonkeyPatch):
    """Make the system keyring unavailable to every test.

    `keyring` is installed in the test environment (twine depends on it), so
    without this the credential paths would read and write the machine's real
    keychain. Tests that exercise keyring storage replace `sys.modules["keyring"]`
    with a mock of their own, or patch the helpers in `rsconnect.oauth`.
    """
    monkeypatch.setitem(sys.modules, "keyring", None)
