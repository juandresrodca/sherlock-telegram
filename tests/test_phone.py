"""The opt-in MTProto module — mostly a test that its guardrails hold."""

from __future__ import annotations

import pytest

from sherlock_telegram.modules import phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+1 415 555 0123", "+14155550123"),
        ("+44-20-7946-0958", "+442079460958"),
        ("(598) 99 123 456", "+59899123456"),
        ("+59899123456", "+59899123456"),
    ],
)
def test_normalise_to_e164(raw, expected):
    assert phone.normalise(raw) == expected


@pytest.mark.parametrize("raw", ["not-a-number", "+", "12", "+0123", ""])
def test_invalid_numbers_are_rejected(raw):
    with pytest.raises(ValueError):
        phone.normalise(raw)


async def test_bulk_enumeration_is_refused():
    """The cap is the design, not a configuration default.

    There is no flag that raises it: the check runs before credentials are
    even read, so no amount of setup turns this into a bulk enumerator.
    """
    too_many = [f"+1415555{i:04d}" for i in range(phone.MAX_NUMBERS_PER_RUN + 1)]
    with pytest.raises(phone.TooManyNumbers, match="bulk enumeration"):
        await phone.lookup(too_many)


def test_the_cap_is_small():
    assert phone.MAX_NUMBERS_PER_RUN <= 10


def test_missing_credentials_explain_how_to_get_them(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    with pytest.raises(phone.MTProtoUnavailable, match="my.telegram.org"):
        phone.credentials()


def test_credentials_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    assert phone.credentials() == (12345, "deadbeef")


def test_non_numeric_api_id_is_reported_clearly(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "not-an-int")
    monkeypatch.setenv("TELEGRAM_API_HASH", "deadbeef")
    with pytest.raises(phone.MTProtoUnavailable, match="integer"):
        phone.credentials()
