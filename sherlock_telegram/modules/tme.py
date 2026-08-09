"""The ``t.me`` probe — the authoritative signal.

``https://t.me/<handle>`` always answers **HTTP 200**, whether the handle is
claimed or not. Status-code detection is therefore useless here, which is
exactly the trap a naive port of Sherlock falls into. The real discriminator is
the ``tgme_page_title`` block, which Telegram only renders for a handle that
resolves:

===================  =========================  ====================
Handle               ``tgme_page_title``        ``tgme_page_extra``
===================  =========================  ====================
free                 absent                     absent
user                 display name               ``@handle``
bot                  bot name                   ``@handle`` (+ Start Bot)
channel              channel name               ``N subscribers``
group                group name                 ``N members, M online``
===================  =========================  ====================

Parsed with regex rather than a DOM library on purpose: the markup is a small,
stable, server-rendered fragment, and it keeps the dependency footprint to
``httpx`` + ``rich`` so ``pipx install`` stays instant.
"""

from __future__ import annotations

import hashlib
import re

from ..core.http import Fetcher
from ..core.models import Confidence, EntityType, Finding, Status

TME_URL = "https://t.me/{}"

# Telegram requires [A-Za-z0-9_] starting with a letter. Self-service
# registration has a 5-character floor, but shorter handles demonstrably exist
# and resolve — Fragment auctions 4-character names, so @abcd is a live
# channel. The scanner therefore accepts 4-32 rather than 5-32: rejecting a
# handle that resolves would be a false negative, and the floor is only
# meaningful when *generating* candidates (see modules.permutations).
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")

_TITLE_RE = re.compile(
    r'<div class="tgme_page_title"[^>]*>\s*(?:<span[^>]*>)?(.*?)(?:</span>)?\s*</div>',
    re.S,
)
_DESC_RE = re.compile(r'<div class="tgme_page_description"[^>]*>(.*?)</div>', re.S)
_EXTRA_RE = re.compile(r'<div class="tgme_page_extra">(.*?)</div>', re.S)
_ACTION_RE = re.compile(r'<div class="tgme_page_action">.*?<a[^>]*>(.*?)</a>', re.S)
_PHOTO_RE = re.compile(r'<img class="tgme_page_photo_image"[^>]*src="([^"]+)"')
_OG_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')

_SUBSCRIBERS_RE = re.compile(r"([\d\s ,.]+)\s+subscribers?", re.I)
_MEMBERS_RE = re.compile(r"([\d\s ,.]+)\s+members?", re.I)
_ONLINE_RE = re.compile(r"([\d\s ,.]+)\s+online", re.I)


def _clean(html: str) -> str:
    """Strip tags and unescape the handful of entities Telegram emits."""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
        ("&nbsp;", " "),
    ):
        text = text.replace(entity, char)
    return text.strip()


def _parse_count(raw: str) -> int | None:
    """``"11 288 217"`` -> ``11288217``. Telegram uses NBSP as a separator."""
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def classify(extra: str, action: str, handle: str) -> tuple[EntityType, dict]:
    """Decide what a resolved handle is, and pull the counts that come with it.

    Order matters: ``subscribers`` is checked before ``members`` because a
    channel's discussion group can surface both words on adjacent pages, and
    the action button ("Start Bot") is the only unambiguous bot tell — plenty
    of real bots do not end their handle in "bot".
    """
    attrs: dict = {}
    extra = extra.strip()
    action = action.strip().lower()

    subs = _SUBSCRIBERS_RE.search(extra)
    if subs:
        attrs["subscribers"] = _parse_count(subs.group(1))
        return EntityType.CHANNEL, attrs

    members = _MEMBERS_RE.search(extra)
    if members:
        attrs["members"] = _parse_count(members.group(1))
        online = _ONLINE_RE.search(extra)
        if online:
            attrs["online"] = _parse_count(online.group(1))
        return EntityType.GROUP, attrs

    if "start bot" in action:
        return EntityType.BOT, attrs
    if "send message" in action or "view in telegram" in action:
        if handle.lower().endswith("bot"):
            return EntityType.BOT, attrs
        return EntityType.USER, attrs

    return EntityType.USER if not handle.lower().endswith("bot") else EntityType.BOT, attrs


def parse_profile(html: str, handle: str) -> Finding:
    """Turn a ``t.me`` page into a :class:`Finding`. Pure — no I/O, easy to test."""
    url = TME_URL.format(handle)
    title_match = _TITLE_RE.search(html)

    if not title_match:
        # No title block == Telegram does not resolve this handle. The og:title
        # falls back to "Telegram: Contact @handle", which is the tell.
        return Finding(
            surface="t.me",
            category="telegram",
            url=url,
            status=Status.NOT_FOUND,
            confidence=Confidence.HIGH,
            attributes={"handle": handle},
        )

    title = _clean(title_match.group(1))
    desc_match = _DESC_RE.search(html)
    description = _clean(desc_match.group(1)) if desc_match else None
    extra = _clean(_EXTRA_RE.search(html).group(1)) if _EXTRA_RE.search(html) else ""
    action_match = _ACTION_RE.search(html)
    action = _clean(action_match.group(1)) if action_match else ""

    entity_type, attrs = classify(extra, action, handle)
    attrs["handle"] = handle
    if action:
        attrs["action"] = action

    photo = _PHOTO_RE.search(html)
    if photo:
        avatar = photo.group(1)
        attrs["avatar_url"] = avatar
        # Telegram avatar URLs embed a content-addressed path, so hashing the
        # URL gives a stable pivot for "same picture on another account"
        # without downloading a single image.
        attrs["avatar_id"] = hashlib.sha256(avatar.encode()).hexdigest()[:16]

    og = _OG_TITLE_RE.search(html)
    if og and og.group(1) and not og.group(1).startswith("Telegram: Contact"):
        attrs["og_title"] = og.group(1)

    return Finding(
        surface="t.me",
        category="telegram",
        url=url,
        status=Status.FOUND,
        confidence=Confidence.HIGH,
        entity_type=entity_type,
        title=title or None,
        description=description or None,
        attributes=attrs,
    )


async def check(fetcher: Fetcher, handle: str) -> list[Finding]:
    """Fetch and parse the public t.me page for ``handle``."""
    url = TME_URL.format(handle)
    resp = await fetcher.get(url)

    if not resp.ok:
        return [
            Finding(
                surface="t.me",
                category="telegram",
                url=url,
                status=Status.UNKNOWN,
                confidence=Confidence.LOW,
                http_status=resp.status_code,
                error=f"unexpected HTTP {resp.status_code} from t.me",
            )
        ]

    finding = parse_profile(resp.text, handle)
    finding.http_status = resp.status_code
    finding.elapsed_ms = resp.elapsed_ms
    return [finding]
