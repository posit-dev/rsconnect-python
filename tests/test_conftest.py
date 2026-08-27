import contextlib
import sys
import types
from typing import Generator, Iterator

import pytest

from tests.conftest import _no_system_keyring


def _drain(gen: Iterator[None]) -> None:
    try:
        next(gen)
    except StopIteration:
        pass


@pytest.fixture
def reinstate_marker() -> Iterator[None]:
    # Reinstates the autouse fixture's marker even when the test fails, so a
    # failure here cannot leak a stand-in module into later tests' teardowns.
    # As a test-level fixture it unwinds before the autouse fixture does.
    try:
        yield
    finally:
        sys.modules["keyring"] = None  # type: ignore[assignment]


@pytest.fixture
def fixture_gen(reinstate_marker: None) -> Iterator["Generator[None, None, None]"]:
    # closing() finalizes a generator a failed assertion left suspended, so
    # its teardown runs before reinstate_marker restores the marker rather
    # than at garbage collection, after.
    gen = _no_system_keyring()
    with contextlib.closing(gen):
        yield gen


def test_teardown_restores_the_previous_module(fixture_gen: "Generator[None, None, None]") -> None:
    stand_in = types.ModuleType("keyring")
    sys.modules["keyring"] = stand_in
    next(fixture_gen)
    assert sys.modules["keyring"] is None
    _drain(fixture_gen)
    assert sys.modules["keyring"] is stand_in


def test_teardown_removes_the_marker_when_nothing_was_stored(fixture_gen: "Generator[None, None, None]") -> None:
    del sys.modules["keyring"]
    next(fixture_gen)
    assert sys.modules["keyring"] is None
    _drain(fixture_gen)
    assert "keyring" not in sys.modules


def test_teardown_leaves_a_deleted_key_deleted(fixture_gen: "Generator[None, None, None]") -> None:
    next(fixture_gen)
    del sys.modules["keyring"]
    _drain(fixture_gen)
    assert "keyring" not in sys.modules
