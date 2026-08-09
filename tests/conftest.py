from __future__ import annotations

from pathlib import Path

import pytest

from sherlock_telegram.core.http import Response

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def make_response(text: str = "", status_code: int = 200, url: str = "https://example.com/x") -> Response:
    return Response(url=url, status_code=status_code, text=text, elapsed_ms=1)


class FakeFetcher:
    """Stands in for :class:`Fetcher`, returning canned responses by URL.

    ``routes`` maps a URL substring to either a Response or an Exception to
    raise, so tests can exercise the engine's failure paths without a network.
    """

    def __init__(self, routes: dict, default: object = None) -> None:
        self.routes = routes
        self.default = default if default is not None else make_response("", 404)
        self.requested: list = []

    async def get(self, url: str, *, headers: dict | None = None) -> Response:
        self.requested.append(url)
        for needle, outcome in self.routes.items():
            if needle in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        if isinstance(self.default, Exception):
            raise self.default
        return self.default
