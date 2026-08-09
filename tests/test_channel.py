"""Channel feed statistics and the forward/mention graph."""

from __future__ import annotations

from sherlock_telegram.core.models import EntityType, Status
from sherlock_telegram.modules import channel

from .conftest import load


def test_feed_is_parsed_into_posts_and_cadence():
    finding = channel.parse_feed(load("channel_feed.html"), "durov")
    assert finding.status is Status.FOUND
    assert finding.entity_type is EntityType.CHANNEL

    attrs = finding.attributes
    # The /s/ preview ships 20 posts; every one must survive the split.
    assert attrs["sampled_posts"] == 20
    assert attrs["posts_per_day"] > 0
    assert attrs["median_gap_hours"] > 0
    assert len(attrs["active_hours_utc"]) == 3
    assert attrs["first_sampled_post"] <= attrs["last_sampled_post"]


def test_post_wrapper_split_keeps_each_post_intact():
    """Regression: splitting on the loose `tgme_widget_message` prefix also
    matched inner `_user`/`_bubble` divs, shredding posts so their <time>
    elements were stranded and cadence silently came back empty."""
    html = load("channel_feed.html")
    blocks = channel._POST_SPLIT_RE.split(html)[1:]
    with_id = [b for b in blocks if channel._POST_ID_RE.search(b)]
    assert len(with_id) == 20
    assert all(channel._TIME_RE.search(b) for b in with_id)


def test_channel_counters_are_captured():
    attrs = channel.parse_feed(load("channel_feed.html"), "durov").attributes
    assert "counter_subscribers" in attrs


def test_related_channels_exclude_self_and_telegram_chrome():
    attrs = channel.parse_feed(load("channel_feed.html"), "durov").attributes
    handles = {item["handle"].lower() for item in attrs.get("related_channels", [])}
    assert "durov" not in handles
    assert not handles & {"s", "share", "joinchat", "iv"}


def test_page_without_a_feed_is_not_found():
    finding = channel.parse_feed("<html><body>nope</body></html>", "whoever")
    assert finding.status is Status.NOT_FOUND


def test_cadence_needs_at_least_two_timestamps():
    assert channel._cadence([]) == {}
