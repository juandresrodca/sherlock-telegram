"""Manifest-driven surface definitions.

This is the Sherlock idea, kept intact: *adding a site should be a JSON edit,
not a code change*. ``resources/surfaces.json`` is the data file; this module
loads, validates and evaluates it.

Detection strategies (``errorType``) mirror Sherlock's vocabulary so anyone who
has written a Sherlock manifest entry already knows this format:

``status_code``
    Absent handles return a distinct HTTP code (usually 404).
``message``
    The page always returns 200; a sentinel string appears only when the handle
    is absent. This is what ``t.me`` needs.
``response_url``
    Absent handles redirect somewhere canonical (a login wall, a home page).
``regex``
    A positive pattern that only renders for a real profile.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .http import Response
from .models import Confidence, Status

RESOURCE_PATH = Path(__file__).resolve().parent.parent / "resources" / "surfaces.json"

_VALID_ERROR_TYPES = {"status_code", "message", "response_url", "regex"}


class ManifestError(ValueError):
    """The manifest is malformed. Raised at load time, never mid-scan."""


@dataclass
class Surface:
    """One checkable site."""

    name: str
    category: str
    url: str
    error_type: str
    error_msgs: list[str] = field(default_factory=list)
    error_codes: list[int] = field(default_factory=lambda: [404])
    error_url: str | None = None
    regex_found: str | None = None
    url_probe: str | None = None
    username_regex: str | None = None
    extract: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    enabled: bool = True
    note: str | None = None
    # Known-good / known-absent handles, used by ``slt selftest``.
    username_claimed: str | None = None
    username_unclaimed: str | None = None

    def target(self, username: str) -> str:
        """User-facing URL for this handle."""
        return self.url.replace("{}", username)

    def probe(self, username: str) -> str:
        """URL we actually request (may differ, e.g. an API endpoint)."""
        template = self.url_probe or self.url
        return template.replace("{}", username)

    def accepts(self, username: str) -> bool:
        """False when the handle cannot exist here (site-specific charset rules)."""
        if not self.username_regex:
            return True
        return re.fullmatch(self.username_regex, username) is not None

    def evaluate(self, resp: Response) -> Status:
        """Apply this surface's detection strategy to a response."""
        if self.error_type == "status_code":
            if resp.status_code in self.error_codes:
                return Status.NOT_FOUND
            if resp.ok:
                return Status.FOUND
            return Status.UNKNOWN

        if self.error_type == "message":
            # A non-2xx body is not a trustworthy place to look for the sentinel.
            if not resp.ok and resp.status_code in self.error_codes:
                return Status.NOT_FOUND
            if not resp.ok:
                return Status.UNKNOWN
            if any(msg in resp.text for msg in self.error_msgs):
                return Status.NOT_FOUND
            return Status.FOUND

        if self.error_type == "response_url":
            if resp.status_code in self.error_codes:
                return Status.NOT_FOUND
            if self.error_url and resp.url.rstrip("/") == self.error_url.rstrip("/"):
                return Status.NOT_FOUND
            return Status.FOUND if resp.ok else Status.UNKNOWN

        if self.error_type == "regex":
            if resp.status_code in self.error_codes:
                return Status.NOT_FOUND
            if not self.regex_found:
                return Status.UNKNOWN
            found = re.search(self.regex_found, resp.text, re.I | re.S) is not None
            return Status.FOUND if found else Status.NOT_FOUND

        return Status.UNKNOWN

    def extract_attributes(self, resp: Response) -> dict[str, str]:
        """Pull the manifest's declared capture groups out of the body."""
        out: dict[str, str] = {}
        for key, pattern in self.extract.items():
            match = re.search(pattern, resp.text, re.I | re.S)
            if match and match.groups():
                out[key] = match.group(1).strip()
        return out


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _build(raw: dict[str, Any]) -> Surface:
    try:
        name = raw["name"]
        category = raw["category"]
        url = raw["url"]
        error_type = raw["errorType"]
    except KeyError as exc:  # pragma: no cover - guarded by tests
        raise ManifestError(f"surface {raw!r} is missing required key {exc}") from exc

    if error_type not in _VALID_ERROR_TYPES:
        raise ManifestError(
            f"surface {name!r} has unknown errorType {error_type!r}; "
            f"expected one of {sorted(_VALID_ERROR_TYPES)}"
        )
    if "{}" not in url:
        raise ManifestError(f"surface {name!r} url must contain the '{{}}' placeholder")
    if error_type == "message" and not raw.get("errorMsg"):
        raise ManifestError(f"surface {name!r} uses errorType 'message' but defines no errorMsg")
    if error_type == "regex" and not raw.get("regexFound"):
        raise ManifestError(f"surface {name!r} uses errorType 'regex' but defines no regexFound")
    if error_type == "response_url" and not raw.get("errorUrl"):
        raise ManifestError(f"surface {name!r} uses errorType 'response_url' but defines no errorUrl")

    for pattern in list(raw.get("extract", {}).values()) + _as_list(raw.get("regexFound")):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ManifestError(f"surface {name!r} has an invalid regex {pattern!r}: {exc}") from exc

    return Surface(
        name=name,
        category=category,
        url=url,
        error_type=error_type,
        error_msgs=_as_list(raw.get("errorMsg")),
        error_codes=[int(c) for c in raw.get("errorCode", [404])],
        error_url=raw.get("errorUrl"),
        regex_found=raw.get("regexFound"),
        url_probe=raw.get("urlProbe"),
        username_regex=raw.get("usernameRegex"),
        extract=raw.get("extract", {}),
        tags=raw.get("tags", []),
        confidence=Confidence(raw.get("confidence", "medium")),
        enabled=raw.get("enabled", True),
        note=raw.get("note"),
        username_claimed=raw.get("usernameClaimed"),
        username_unclaimed=raw.get("usernameUnclaimed"),
    )


def load_surfaces(path: Path | None = None) -> list[Surface]:
    """Load and validate the surface manifest."""
    path = path or RESOURCE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest not found at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest at {path} is not valid JSON: {exc}") from exc

    entries = raw.get("surfaces") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ManifestError("manifest must be a list, or an object with a 'surfaces' list")

    surfaces = [_build(entry) for entry in entries]

    seen = set()
    for surface in surfaces:
        if surface.name in seen:
            raise ManifestError(f"duplicate surface name {surface.name!r}")
        seen.add(surface.name)
    return surfaces


def filter_surfaces(
    surfaces: Sequence[Surface],
    *,
    categories: Sequence[str] | None = None,
    names: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    include_disabled: bool = False,
) -> list[Surface]:
    """Narrow the surface list. All filters are case-insensitive and ANDed."""
    lower = str.lower
    cats = {lower(c) for c in categories} if categories else None
    wanted = {lower(n) for n in names} if names else None
    tagset = {lower(t) for t in tags} if tags else None

    out = []
    for surface in surfaces:
        if not surface.enabled and not include_disabled:
            continue
        if cats and lower(surface.category) not in cats:
            continue
        if wanted and lower(surface.name) not in wanted:
            continue
        if tagset and not tagset & {lower(t) for t in surface.tags}:
            continue
        out.append(surface)
    return out
