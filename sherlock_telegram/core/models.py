"""Data model for everything the scanner produces.

The whole tool funnels into :class:`Investigation`, which is what the reporters
render and what ``--json`` serialises. Keeping one flat, boring schema means a
downstream consumer can diff two scans without knowing which module produced
which finding.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Status(str, enum.Enum):
    """Outcome of a single check.

    ``UNKNOWN`` is deliberately distinct from ``NOT_FOUND``: a surface that
    rate-limited us has *not* told us the handle is free, and conflating the two
    is how OSINT tools end up asserting things they never observed.
    """

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"
    ERROR = "error"
    SKIPPED = "skipped"

    @property
    def is_positive(self) -> bool:
        return self is Status.FOUND


class EntityType(str, enum.Enum):
    """What a claimed t.me handle actually resolves to."""

    USER = "user"
    BOT = "bot"
    CHANNEL = "channel"
    GROUP = "group"
    GIFT = "gift"
    UNKNOWN = "unknown"


class Confidence(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Finding:
    """One surface's answer about one subject."""

    surface: str
    category: str
    url: str
    status: Status
    confidence: Confidence = Confidence.MEDIUM
    entity_type: EntityType = EntityType.UNKNOWN
    title: str | None = None
    description: str | None = None
    # Free-form, surface-specific extras (subscriber counts, avatar hash, ...).
    attributes: dict[str, Any] = field(default_factory=dict)
    http_status: int | None = None
    elapsed_ms: int | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["status"] = self.status.value
        data["confidence"] = self.confidence.value
        data["entity_type"] = self.entity_type.value
        return data


@dataclass
class Subject:
    """The thing being investigated."""

    value: str
    kind: str = "username"  # username | phone | channel

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass
class Investigation:
    """Complete result set for one subject."""

    subject: Subject
    findings: list[Finding] = field(default_factory=list)
    started_at: str = field(default_factory=_utcnow)
    finished_at: str | None = None
    tool_version: str = "0.1.0"

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def hits(self) -> list[Finding]:
        return [f for f in self.findings if f.status.is_positive]

    @property
    def primary(self) -> Finding | None:
        """The authoritative t.me finding, if we got one."""
        for finding in self.findings:
            if finding.surface == "t.me" and finding.status is Status.FOUND:
                return finding
        return None

    def by_category(self) -> dict[str, list[Finding]]:
        grouped: dict[str, list[Finding]] = {}
        for finding in self.findings:
            grouped.setdefault(finding.category, []).append(finding)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": {"value": self.subject.value, "kind": self.subject.kind},
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "tool_version": self.tool_version,
            "summary": {
                "checked": len(self.findings),
                "found": len(self.hits),
                "entity_type": (self.primary.entity_type.value if self.primary else "unknown"),
            },
            "findings": [f.to_dict() for f in self.findings],
        }
