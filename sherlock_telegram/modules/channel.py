"""Public channel feed analysis via ``https://t.me/s/<channel>``.

The ``/s/`` preview is Telegram's own server-rendered mirror of a public
channel — no account, no API key, no MTProto. It hands over the last ~20 posts
with timestamps, view counts and, crucially, **outbound references**:
forwarded-from attributions and inline ``t.me`` links.

Those references are the interesting part. A single channel is a data point; a
channel's forward graph is a network. Chasing the ``related_channels`` output
of one scan into the next is how you map an ecosystem rather than an account.

Everything derived here is arithmetic on public post metadata — posting cadence,
active hours, the busiest weekday. No message content is stored beyond a short
preview, because the goal is to characterise an account's behaviour, not to
mirror what it said.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime
from typing import Any

from ..core.http import Fetcher
from ..core.models import Confidence, EntityType, Finding, Status

CHANNEL_URL = "https://t.me/s/{}"

# Split on the per-post *wrapper* only. Matching the looser
# `tgme_widget_message[ _"]` also matches the inner `_user` / `_bubble` /
# `_footer` divs, which shreds each post into fragments and strands the
# <time> element in a block with no data-post attribute.
_POST_SPLIT_RE = re.compile(r'<div class="tgme_widget_message_wrap[ "]')
_POST_ID_RE = re.compile(r'data-post="([^"]+)"')
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_VIEWS_RE = re.compile(r'tgme_widget_message_views">([^<]*)<')
_TEXT_RE = re.compile(r'tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_FWD_RE = re.compile(r'tgme_widget_message_forwarded_from_name"[^>]*href="https://t\.me/([^/"?]+)')
_TME_LINK_RE = re.compile(r'href="https://t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})(?:/\d+)?[/"?]')
_COUNTER_RE = re.compile(
    r'tgme_channel_info_counter">.*?counter_value">([^<]*)<.*?counter_type">([^<]*)<', re.S
)

# Handles that appear on every channel page as chrome, not as references.
_LINK_NOISE = {"s", "share", "telegram", "joinchat", "addstickers", "proxy", "iv"}


def _strip_tags(html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cadence(timestamps: list[datetime]) -> dict[str, Any]:
    """Posting rhythm from the sampled window.

    ``median_gap_hours`` beats a mean here: one long holiday gap would drag an
    average into meaninglessness, while the median still describes the normal
    day.
    """
    if len(timestamps) < 2:
        return {}
    ordered = sorted(timestamps)
    gaps = [
        (b - a).total_seconds() / 3600.0
        for a, b in zip(ordered, ordered[1:])
        if (b - a).total_seconds() > 0
    ]
    span_days = max((ordered[-1] - ordered[0]).total_seconds() / 86400.0, 1e-9)

    out: dict[str, Any] = {
        "sampled_posts": len(ordered),
        "first_sampled_post": ordered[0].isoformat(),
        "last_sampled_post": ordered[-1].isoformat(),
        "posts_per_day": round(len(ordered) / span_days, 2),
        "active_hours_utc": [h for h, _ in Counter(t.hour for t in ordered).most_common(3)],
        "busiest_weekday": ordered[0].strftime("%A")
        if len(ordered) < 3
        else Counter(t.strftime("%A") for t in ordered).most_common(1)[0][0],
    }
    if gaps:
        out["median_gap_hours"] = round(statistics.median(gaps), 2)
    return out


def parse_feed(html: str, handle: str) -> Finding:
    """Parse a ``/s/`` channel page into a finding. Pure — no I/O."""
    url = CHANNEL_URL.format(handle)

    if "tgme_widget_message_wrap" not in html and "tgme_channel_info" not in html:
        return Finding(
            surface="Channel feed",
            category="telegram",
            url=url,
            status=Status.NOT_FOUND,
            confidence=Confidence.MEDIUM,
            description="No public post feed — not a channel, or previews are disabled.",
        )

    attrs: dict[str, Any] = {}
    for value, ctype in _COUNTER_RE.findall(html):
        attrs[f"counter_{_strip_tags(ctype).lower()}"] = _strip_tags(value)

    timestamps: list[datetime] = []
    forwards: Counter = Counter()
    views: list[str] = []
    latest_preview: str | None = None

    for block in _POST_SPLIT_RE.split(html)[1:]:
        post_id = _POST_ID_RE.search(block)
        if not post_id:
            continue

        time_match = _TIME_RE.search(block)
        if time_match:
            parsed = _parse_dt(time_match.group(1))
            if parsed:
                timestamps.append(parsed)

        view_match = _VIEWS_RE.search(block)
        if view_match:
            views.append(view_match.group(1).strip())

        fwd = _FWD_RE.search(block)
        if fwd:
            forwards[fwd.group(1)] += 1

        text_match = _TEXT_RE.search(block)
        if text_match and latest_preview is None:
            preview = _strip_tags(text_match.group(1))
            if preview:
                latest_preview = preview[:200]

    if timestamps:
        attrs.update(_cadence(timestamps))
    if views:
        attrs["recent_views"] = views[:5]
    if latest_preview:
        attrs["latest_post_preview"] = latest_preview

    # Outbound references, minus the page's own handle and Telegram's chrome.
    mentioned = Counter(
        h for h in _TME_LINK_RE.findall(html) if h.lower() not in _LINK_NOISE and h.lower() != handle.lower()
    )
    if forwards:
        attrs["forwarded_from"] = [
            {"channel": name, "count": count} for name, count in forwards.most_common(10)
        ]
    if mentioned:
        attrs["related_channels"] = [
            {"handle": name, "mentions": count} for name, count in mentioned.most_common(15)
        ]

    latest_id = _POST_ID_RE.search(html)
    if latest_id:
        attrs["latest_post"] = latest_id.group(1)

    return Finding(
        surface="Channel feed",
        category="telegram",
        url=url,
        status=Status.FOUND,
        confidence=Confidence.HIGH,
        entity_type=EntityType.CHANNEL,
        title=f"Public feed for @{handle}",
        description=(
            f"{attrs.get('sampled_posts', 0)} recent posts sampled; "
            f"{len(mentioned)} related handles referenced."
        ),
        attributes=attrs,
    )


async def check(fetcher: Fetcher, handle: str) -> list[Finding]:
    url = CHANNEL_URL.format(handle)
    resp = await fetcher.get(url)
    if not resp.ok:
        return [
            Finding(
                surface="Channel feed",
                category="telegram",
                url=url,
                status=Status.UNKNOWN,
                confidence=Confidence.LOW,
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )
        ]
    finding = parse_feed(resp.text, handle)
    finding.http_status = resp.status_code
    finding.elapsed_ms = resp.elapsed_ms
    return [finding]
