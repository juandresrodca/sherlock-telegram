"""Fragment marketplace parsing — and the not-found/unknown distinction."""

from __future__ import annotations

from sherlock_telegram.core.models import Status
from sherlock_telegram.modules import fragment

from .conftest import load


def test_taken_handle_is_a_hit():
    finding = fragment.parse(load("fragment_taken.html"), "durov")
    assert finding.status is Status.FOUND
    assert finding.attributes["fragment_status"].lower() == "taken"


def test_auctioned_handle_is_unassigned_and_flags_impersonation_risk():
    finding = fragment.parse(load("fragment_auction.html"), "board")
    assert finding.status is Status.NOT_FOUND
    assert "auction" in finding.attributes["fragment_status"].lower()
    assert finding.attributes.get("auction_price_ton")
    assert "impersonation" in (finding.description or "")


def test_unlisted_handle_is_unknown_not_absent():
    """Fragment not listing a handle is silence, not a denial.

    Reporting this as NOT_FOUND would let a scan assert the handle is free
    when Fragment never said so — exactly the conflation the tool is built to
    avoid.
    """
    finding = fragment.parse(load("fragment_unavail.html"), "zzq9x7v2knot44")
    assert finding.status is Status.UNKNOWN
    assert finding.status is not Status.NOT_FOUND


def test_sold_handle_is_a_hit_and_keeps_the_label():
    html = '<div class="tm-status-unavail">Sold</div>'
    finding = fragment.parse(html, "notcoin")
    assert finding.status is Status.FOUND
    assert finding.attributes["fragment_status"] == "Sold"
    assert "on-chain" in (finding.description or "")


def test_missing_badge_is_unknown_with_an_explanation():
    finding = fragment.parse("<html><body>nothing here</body></html>", "whoever")
    assert finding.status is Status.UNKNOWN
    assert finding.error
