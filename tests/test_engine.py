"""Scan orchestration, failure isolation and result normalisation."""

from __future__ import annotations

import httpx
import pytest

from sherlock_telegram.core.engine import check_surface, run_scan
from sherlock_telegram.core.manifest import load_surfaces
from sherlock_telegram.core.models import (
    Confidence,
    EntityType,
    Finding,
    Investigation,
    Status,
    Subject,
)

from .conftest import FakeFetcher, make_response

GITHUB = next(s for s in load_surfaces() if s.name == "GitHub")
KEYBASE = next(s for s in load_surfaces() if s.name == "Keybase")


async def test_hit_is_recorded_with_extracted_attributes():
    body = '<meta property="og:title" content="Alice - Overview">'
    fetcher = FakeFetcher({"github.com": make_response(body, 200)})
    finding = await check_surface(fetcher, GITHUB, "alice")
    assert finding.status is Status.FOUND
    assert finding.title == "Alice - Overview"
    assert finding.url == "https://github.com/alice"


async def test_miss_is_recorded():
    fetcher = FakeFetcher({"github.com": make_response("", 404)})
    finding = await check_surface(fetcher, GITHUB, "alice")
    assert finding.status is Status.NOT_FOUND


async def test_a_network_failure_is_unknown_never_a_negative():
    """A surface that never answered has not told us the handle is free."""
    fetcher = FakeFetcher({"github.com": httpx.ConnectTimeout("timed out")})
    finding = await check_surface(fetcher, GITHUB, "alice")
    assert finding.status is Status.UNKNOWN
    assert finding.status is not Status.NOT_FOUND
    assert finding.confidence is Confidence.LOW
    assert "ConnectTimeout" in finding.error


async def test_impossible_handles_are_skipped_without_a_request():
    """Keybase caps handles at 16 chars, so a longer one cannot exist there."""
    fetcher = FakeFetcher({})
    finding = await check_surface(fetcher, KEYBASE, "a_very_long_telegram_handle")
    assert finding.status is Status.SKIPPED
    assert fetcher.requested == []


async def test_one_broken_module_cannot_kill_the_scan():
    async def exploding(_fetcher):
        raise RuntimeError("boom")

    async def healthy(_fetcher):
        return [
            Finding(
                surface="ok", category="telegram", url="https://ok", status=Status.FOUND
            )
        ]

    investigation = await run_scan(
        Subject("alice"), [], extra_tasks=[exploding, healthy]
    )
    statuses = {f.surface: f.status for f in investigation.findings}
    assert statuses["ok"] is Status.FOUND
    assert Status.ERROR in statuses.values()


async def test_entity_type_is_promoted_from_the_authoritative_tme_result():
    """Directory sites know a handle exists but not what it is."""

    async def tme_task(_fetcher):
        return [
            Finding(
                surface="t.me",
                category="telegram",
                url="https://t.me/x",
                status=Status.FOUND,
                entity_type=EntityType.CHANNEL,
            )
        ]

    async def directory(_fetcher):
        return [
            Finding(surface="Dir", category="telegram", url="https://d", status=Status.FOUND)
        ]

    investigation = await run_scan(Subject("x"), [], extra_tasks=[tme_task, directory])
    directory_finding = next(f for f in investigation.findings if f.surface == "Dir")
    assert directory_finding.entity_type is EntityType.CHANNEL


async def test_tme_sorts_first_and_hits_before_misses():
    async def make(surface, status):
        async def task(_fetcher):
            return [Finding(surface=surface, category="c", url="", status=status)]

        return task

    tasks = [
        await make("zzz", Status.NOT_FOUND),
        await make("aaa", Status.FOUND),
        await make("t.me", Status.FOUND),
    ]
    investigation = await run_scan(Subject("x"), [], extra_tasks=tasks)
    assert [f.surface for f in investigation.findings] == ["t.me", "aaa", "zzz"]


def test_investigation_serialises_with_a_summary():
    investigation = Investigation(subject=Subject("alice"))
    investigation.add(
        Finding(
            surface="t.me",
            category="telegram",
            url="https://t.me/alice",
            status=Status.FOUND,
            entity_type=EntityType.USER,
        )
    )
    investigation.add(
        Finding(surface="GitHub", category="cross-platform", url="", status=Status.NOT_FOUND)
    )

    data = investigation.to_dict()
    assert data["summary"] == {"checked": 2, "found": 1, "entity_type": "user"}
    # Enums must serialise as plain strings for JSON consumers.
    assert data["findings"][0]["status"] == "found"
    assert isinstance(data["findings"][0]["entity_type"], str)


def test_status_is_positive_only_for_found():
    assert Status.FOUND.is_positive
    assert not any(
        s.is_positive for s in (Status.NOT_FOUND, Status.UNKNOWN, Status.ERROR, Status.SKIPPED)
    )


@pytest.mark.parametrize("status", [Status.UNKNOWN, Status.ERROR])
def test_inconclusive_results_are_not_counted_as_hits(status):
    investigation = Investigation(subject=Subject("alice"))
    investigation.add(Finding(surface="X", category="c", url="", status=status))
    assert investigation.hits == []
