"""Handle permutation generation."""

from __future__ import annotations

import pytest

from sherlock_telegram.modules import permutations as perm


@pytest.mark.parametrize("handle", ["alice", "alice_bob", "Alice99", "a" * 32])
def test_valid_handles_accepted(handle):
    assert perm.is_valid_handle(handle)


@pytest.mark.parametrize(
    "handle",
    [
        "abcd",          # too short (Telegram requires 5)
        "a" * 33,        # too long
        "9alice",        # must start with a letter
        "alice_",        # cannot end with an underscore
        "alice__bob",    # no consecutive underscores
        "alice-bob",     # hyphen is not allowed
        "",
    ],
)
def test_invalid_handles_rejected(handle):
    assert not perm.is_valid_handle(handle)


def test_every_candidate_is_a_legal_telegram_handle():
    """No request should ever be spent on a handle that cannot exist."""
    for candidate in perm.generate("johndoe", typos=True, limit=None):
        assert perm.is_valid_handle(candidate), candidate


def test_base_handle_is_never_returned():
    assert "johndoe" not in perm.generate("johndoe", limit=None)


def test_results_are_deduplicated():
    candidates = perm.generate("john_doe", typos=True, limit=None)
    lowered = [c.lower() for c in candidates]
    assert len(lowered) == len(set(lowered))


def test_limit_truncates_the_long_shots_not_a_random_slice():
    """Ordering is by likelihood, so a prefix of the full list is the top N."""
    full = perm.generate("johndoe", limit=None)
    assert perm.generate("johndoe", limit=5) == full[:5]


def test_separator_variants_are_generated():
    candidates = perm.generate("john_doe", limit=None)
    assert "johndoe" in candidates


def test_leetspeak_can_be_disabled():
    with_leet = perm.generate("alice", leet=True, limit=None)
    without = perm.generate("alice", leet=False, limit=None)
    assert len(without) < len(with_leet)
    assert "al1ce" in with_leet
    assert "al1ce" not in without


def test_leetspeak_never_produces_a_digit_leading_handle():
    """'alice' -> '4lice' is a natural substitution but an illegal handle;
    the validity filter must drop it rather than spend a request on it."""
    assert "4lice" not in perm.generate("alice", leet=True, limit=None)


def test_typos_are_opt_in():
    assert len(perm.generate("alice", typos=True, limit=None)) > len(
        perm.generate("alice", typos=False, limit=None)
    )


def test_leading_at_is_tolerated():
    assert perm.generate("@alice", limit=3) == perm.generate("alice", limit=3)


def test_empty_input_yields_nothing():
    assert perm.generate("") == []
    assert perm.generate("   @  ".strip().lstrip("@")) == []
