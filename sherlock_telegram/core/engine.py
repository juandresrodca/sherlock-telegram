"""Scan orchestration: run every enabled module/surface against a subject."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .http import Fetcher
from .manifest import Surface
from .models import Confidence, EntityType, Finding, Investigation, Status, Subject

ProgressHook = Callable[[Finding], None]


@dataclass
class ScanOptions:
    concurrency: int = 12
    timeout: float = 15.0
    retries: int = 2
    rate: float = 8.0
    proxy: str | None = None
    verify_tls: bool = True


async def check_surface(fetcher: Fetcher, surface: Surface, username: str) -> Finding:
    """Run one manifest surface. Never raises — failures become findings."""
    target = surface.target(username)

    if not surface.accepts(username):
        return Finding(
            surface=surface.name,
            category=surface.category,
            url=target,
            status=Status.SKIPPED,
            confidence=surface.confidence,
            error="username does not match this site's allowed format",
        )

    try:
        resp = await fetcher.get(surface.probe(username))
    except Exception as exc:  # noqa: BLE001 - a dead surface must not kill the scan
        return Finding(
            surface=surface.name,
            category=surface.category,
            url=target,
            status=Status.UNKNOWN,
            confidence=Confidence.LOW,
            error=f"{type(exc).__name__}: {exc}",
        )

    status = surface.evaluate(resp)
    attributes = surface.extract_attributes(resp) if status is Status.FOUND else {}

    return Finding(
        surface=surface.name,
        category=surface.category,
        url=target,
        status=status,
        confidence=surface.confidence,
        title=attributes.pop("title", None),
        description=attributes.pop("description", None),
        attributes=attributes,
        http_status=resp.status_code,
        elapsed_ms=resp.elapsed_ms,
    )


async def run_scan(
    subject: Subject,
    surfaces: Sequence[Surface],
    *,
    options: ScanOptions | None = None,
    extra_tasks: Sequence[Callable[[Fetcher], Awaitable[list[Finding]]]] | None = None,
    on_result: ProgressHook | None = None,
) -> Investigation:
    """Scan ``subject`` across ``surfaces`` plus any bespoke module tasks.

    ``extra_tasks`` are the hand-written modules (t.me, Fragment, channel
    feed) that produce richer output than a manifest entry can express. They
    receive the shared fetcher so they inherit the same rate limit.
    """
    options = options or ScanOptions()
    investigation = Investigation(subject=subject)

    async with Fetcher(
        concurrency=options.concurrency,
        timeout=options.timeout,
        retries=options.retries,
        rate=options.rate,
        proxy=options.proxy,
        verify=options.verify_tls,
    ) as fetcher:

        async def _surface_job(surface: Surface) -> list[Finding]:
            return [await check_surface(fetcher, surface, subject.value)]

        async def _module_job(
            fn: Callable[[Fetcher], Awaitable[list[Finding]]],
        ) -> list[Finding]:
            try:
                return await fn(fetcher)
            except Exception as exc:  # noqa: BLE001
                return [
                    Finding(
                        surface=getattr(fn, "surface_name", "module"),
                        category="module",
                        url="",
                        status=Status.ERROR,
                        confidence=Confidence.LOW,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                ]

        jobs: list[Awaitable[list[Finding]]] = [_surface_job(s) for s in surfaces]
        jobs += [_module_job(fn) for fn in (extra_tasks or [])]

        for coro in asyncio.as_completed(jobs):
            for finding in await coro:
                investigation.add(finding)
                if on_result:
                    on_result(finding)

    investigation.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _promote_entity_type(investigation)
    investigation.findings.sort(key=_sort_key)
    return investigation


def _promote_entity_type(investigation: Investigation) -> None:
    """Let the authoritative t.me answer label findings that could not tell.

    Directory sites know a handle exists but rarely know whether it is a bot or
    a channel; t.me always does. Copying the type across makes the report read
    as one conclusion instead of a pile of disagreeing rows.
    """
    primary = investigation.primary
    if primary is None or primary.entity_type is EntityType.UNKNOWN:
        return
    for finding in investigation.findings:
        if finding.status is Status.FOUND and finding.entity_type is EntityType.UNKNOWN:
            finding.entity_type = primary.entity_type


_STATUS_ORDER = {
    Status.FOUND: 0,
    Status.UNKNOWN: 1,
    Status.ERROR: 2,
    Status.NOT_FOUND: 3,
    Status.SKIPPED: 4,
}


def _sort_key(finding: Finding) -> tuple:
    # t.me is the headline result and always sorts first.
    return (
        0 if finding.surface == "t.me" else 1,
        _STATUS_ORDER.get(finding.status, 9),
        finding.category,
        finding.surface.lower(),
    )
