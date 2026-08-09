"""Fragment.com — Telegram's official username marketplace.

Fragment is the single most under-used Telegram OSINT source. It answers a
question ``t.me`` cannot: *what is the ownership history of this handle?*

Its status badge has three CSS states, and each means something different for
an investigation:

``tm-status-taken`` ("Taken")
    Assigned to a live Telegram account. Independent corroboration of a t.me
    hit — and a useful tell when t.me is unreachable from your network.

``tm-status-avail`` ("On auction" / "For sale")
    Currently *unassigned* and purchasable. A handle in this state is a
    known impersonation risk: anyone can buy it and inherit the name.

``tm-status-unavail``
    Two very different meanings behind one class, so the label text matters —
    "Sold" means it changed hands on-chain (the TON transaction is public and
    pivotable), while "Unavailable" merely means Fragment does not list it and
    tells you nothing at all.

That last distinction is why this module reads the label and not just the
class: collapsing "Sold" into "Unavailable" would throw away the only
blockchain pivot the tool has.
"""

from __future__ import annotations

import re

from ..core.http import Fetcher
from ..core.models import Confidence, Finding, Status

FRAGMENT_URL = "https://fragment.com/username/{}"

_STATUS_RE = re.compile(r'tm-status-([a-z]+)"[^>]*>\s*([^<]*?)\s*<')
_PRICE_RE = re.compile(r'tm-value[^>]*>\s*([\d,\. ]{1,20})\s*<')
_OWNER_RE = re.compile(r'href="(https://tonviewer\.com/[^"]+|/username/[^"]+/owner[^"]*)"')


def parse(html: str, handle: str) -> Finding:
    """Map a Fragment page to a finding. Pure — no I/O."""
    url = FRAGMENT_URL.format(handle)
    match = _STATUS_RE.search(html)

    if not match:
        return Finding(
            surface="Fragment",
            category="telegram",
            url=url,
            status=Status.UNKNOWN,
            confidence=Confidence.LOW,
            error="no status badge found (page layout may have changed)",
        )

    css_state, label = match.group(1).lower(), match.group(2).strip()
    attrs = {"fragment_status": label or css_state}

    price = _PRICE_RE.search(html)
    if price and css_state == "avail":
        attrs["auction_price_ton"] = price.group(1).strip()

    if css_state == "taken":
        return Finding(
            surface="Fragment",
            category="telegram",
            url=url,
            status=Status.FOUND,
            confidence=Confidence.HIGH,
            title=f"@{handle} is assigned",
            description="Handle is bound to a live Telegram account.",
            attributes=attrs,
        )

    if css_state == "avail":
        return Finding(
            surface="Fragment",
            category="telegram",
            url=url,
            status=Status.NOT_FOUND,
            confidence=Confidence.HIGH,
            title=f"@{handle} is for sale",
            description=(
                "Unassigned and purchasable on Fragment — impersonation risk, "
                "since any buyer inherits this name."
            ),
            attributes=attrs,
        )

    if "sold" in label.lower():
        owner = _OWNER_RE.search(html)
        if owner:
            attrs["owner_link"] = owner.group(1)
        return Finding(
            surface="Fragment",
            category="telegram",
            url=url,
            status=Status.FOUND,
            confidence=Confidence.MEDIUM,
            title=f"@{handle} was sold on Fragment",
            description="Ownership transferred on-chain; the TON record is public.",
            attributes=attrs,
        )

    # "Unavailable": Fragment simply does not list it. Not evidence either way.
    return Finding(
        surface="Fragment",
        category="telegram",
        url=url,
        status=Status.UNKNOWN,
        confidence=Confidence.LOW,
        description="Not listed on Fragment — no conclusion about the handle.",
        attributes=attrs,
    )


async def check(fetcher: Fetcher, handle: str) -> list[Finding]:
    url = FRAGMENT_URL.format(handle)
    resp = await fetcher.get(url)
    if not resp.ok:
        return [
            Finding(
                surface="Fragment",
                category="telegram",
                url=url,
                status=Status.UNKNOWN,
                confidence=Confidence.LOW,
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )
        ]
    finding = parse(resp.text, handle)
    finding.http_status = resp.status_code
    finding.elapsed_ms = resp.elapsed_ms
    return [finding]
