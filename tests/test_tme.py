"""The t.me parser — the tool's authoritative signal."""

from __future__ import annotations

import pytest

from sherlock_telegram.core.models import EntityType, Status
from sherlock_telegram.modules import tme

from .conftest import load


def test_free_handle_is_not_found_despite_http_200():
    """The whole project exists because of this case.

    t.me answers HTTP 200 for a handle nobody has registered. Any tool that
    checks the status code reports it as a hit. The absence of the
    ``tgme_page_title`` block is what actually discriminates.
    """
    finding = tme.parse_profile(load("tme_free.html"), "zzq9x7v2knot44")
    assert finding.status is Status.NOT_FOUND
    assert "tgme_page_title" not in load("tme_free.html")


def test_channel_is_classified_with_subscriber_count():
    finding = tme.parse_profile(load("tme_channel.html"), "durov")
    assert finding.status is Status.FOUND
    assert finding.entity_type is EntityType.CHANNEL
    assert finding.title and "Durov" in finding.title
    assert finding.attributes["subscribers"] > 1_000_000


def test_bot_is_classified_from_its_action_button():
    finding = tme.parse_profile(load("tme_bot.html"), "BotFather")
    assert finding.status is Status.FOUND
    assert finding.entity_type is EntityType.BOT
    assert "start bot" in finding.attributes["action"].lower()


def test_user_is_classified():
    finding = tme.parse_profile(load("tme_user.html"), "nikolai")
    assert finding.status is Status.FOUND
    assert finding.entity_type is EntityType.USER
    # A user page carries no audience counter.
    assert "subscribers" not in finding.attributes
    assert "members" not in finding.attributes


def test_group_is_classified_with_member_and_online_counts():
    finding = tme.parse_profile(load("tme_group.html"), "python")
    assert finding.status is Status.FOUND
    assert finding.entity_type is EntityType.GROUP
    assert finding.attributes["members"] > 1000
    assert finding.attributes["online"] > 0


def test_avatar_id_is_stable_and_derived_from_the_url():
    html = load("tme_channel.html")
    first = tme.parse_profile(html, "durov").attributes["avatar_id"]
    second = tme.parse_profile(html, "durov").attributes["avatar_id"]
    assert first == second
    assert len(first) == 16


def test_nbsp_separated_counts_are_parsed():
    """Telegram separates thousands with U+00A0, not commas."""
    assert tme._parse_count("11 288 217") == 11288217
    assert tme._parse_count("97 957") == 97957
    assert tme._parse_count("") is None


@pytest.mark.parametrize(
    ("extra", "action", "handle", "expected"),
    [
        ("1 234 subscribers", "View in Telegram", "somechan", EntityType.CHANNEL),
        ("500 members, 12 online", "View in Telegram", "somegroup", EntityType.GROUP),
        ("@helper", "Start Bot", "helper", EntityType.BOT),
        ("@alice", "Send Message", "alice", EntityType.USER),
        # A bot that does not advertise itself with a "Start Bot" button is
        # still identifiable from the conventional handle suffix.
        ("@quietbot", "Send Message", "quietbot", EntityType.BOT),
    ],
)
def test_classify_matrix(extra, action, handle, expected):
    entity_type, _ = tme.classify(extra, action, handle)
    assert entity_type is expected


def test_subscribers_wins_over_members_when_both_words_appear():
    """A channel with a discussion group can surface both nouns."""
    entity_type, attrs = tme.classify("9 000 subscribers, 12 members", "View in Telegram", "c")
    assert entity_type is EntityType.CHANNEL
    assert attrs["subscribers"] == 9000


@pytest.mark.parametrize("handle", ["durov", "Bot_Father9", "abcde"])
def test_username_regex_accepts_valid_handles(handle):
    assert tme.USERNAME_RE.match(handle)


def test_four_character_handles_are_accepted_because_they_resolve():
    """Self-service registration needs 5 characters, but Fragment auctions
    4-character names — @abcd is a live channel. Rejecting it here would be a
    false negative on exactly the handles most worth investigating."""
    assert tme.USERNAME_RE.match("abcd")


@pytest.mark.parametrize("handle", ["abc", "9leading", "has-dash", "a" * 33])
def test_username_regex_rejects_invalid_handles(handle):
    assert not tme.USERNAME_RE.match(handle)
