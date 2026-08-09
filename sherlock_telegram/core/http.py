"""Shared async HTTP client.

Every network call in the tool goes through :class:`Fetcher` so that timeouts,
retries, concurrency and the global rate limit are enforced in exactly one
place. Surfaces are third-party sites we do not own — being a polite client is
a correctness requirement, not a nicety.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

import httpx

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Surfaces render server-side for crawlers; asking for HTML keeps us on the
# lightweight path and avoids the JS app shells.
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Response:
    """Minimal, picklable view of an HTTP response."""

    url: str
    status_code: int
    text: str
    elapsed_ms: int

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class RateLimiter:
    """Token-bucket-ish limiter: at most ``rate`` requests per second, globally."""

    def __init__(self, rate: float) -> None:
        self._min_interval = 1.0 / rate if rate > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_slot = 0.0

    async def acquire(self) -> None:
        if self._min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + self._min_interval
        if wait > 0:
            await asyncio.sleep(wait)


class Fetcher:
    """Concurrency-capped, rate-limited, retrying HTTP GET."""

    def __init__(
        self,
        *,
        concurrency: int = 12,
        timeout: float = 15.0,
        retries: int = 2,
        rate: float = 8.0,
        proxy: str | None = None,
        verify: bool = True,
    ) -> None:
        self.retries = retries
        self._sem = asyncio.Semaphore(concurrency)
        self._limiter = RateLimiter(rate)
        self._client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy,
            verify=verify,
        )

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, headers: dict | None = None) -> Response:
        """GET ``url``, retrying transient failures with jittered backoff.

        Raises the last exception if every attempt fails; callers turn that into
        a ``Status.UNKNOWN`` finding rather than a false negative.
        """
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            async with self._sem:
                await self._limiter.acquire()
                start = time.monotonic()
                try:
                    resp = await self._client.get(url, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_exc = exc
                else:
                    elapsed = int((time.monotonic() - start) * 1000)
                    # 429/5xx are worth another go; everything else is an answer.
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                        last_exc = httpx.HTTPStatusError(
                            f"HTTP {resp.status_code}", request=resp.request, response=resp
                        )
                    else:
                        return Response(
                            url=str(resp.url),
                            status_code=resp.status_code,
                            text=resp.text,
                            elapsed_ms=elapsed,
                        )
            if attempt < self.retries:
                await asyncio.sleep((2**attempt) * 0.5 + random.uniform(0, 0.3))

        assert last_exc is not None
        raise last_exc
