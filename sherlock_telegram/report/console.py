"""Rich terminal rendering.

The layout puts the identity card first and the surface table second, because
an investigator reads *what is this account* before *where else does the name
appear*. Negative results are collapsed to a count by default — a wall of
grey "not found" rows buries the two lines that matter.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..core.models import EntityType, Finding, Investigation, Status

STATUS_STYLE = {
    Status.FOUND: ("[+]", "bold green"),
    Status.NOT_FOUND: ("[-]", "dim"),
    Status.UNKNOWN: ("[?]", "yellow"),
    Status.ERROR: ("[!]", "red"),
    Status.SKIPPED: ("[ ]", "dim cyan"),
}

ENTITY_ICON = {
    EntityType.USER: "person",
    EntityType.BOT: "bot",
    EntityType.CHANNEL: "channel",
    EntityType.GROUP: "group",
    EntityType.GIFT: "gift",
    EntityType.UNKNOWN: "unknown",
}

# Attributes worth promoting into the identity card, in display order.
_CARD_FIELDS = (
    ("subscribers", "Subscribers"),
    ("members", "Members"),
    ("online", "Online now"),
    ("posts_per_day", "Posts/day"),
    ("median_gap_hours", "Median gap (h)"),
    ("last_sampled_post", "Latest post"),
    ("fragment_status", "Fragment"),
    ("auction_price_ton", "Auction (TON)"),
    ("avatar_id", "Avatar ID"),
    ("last_seen", "Last seen"),
    ("telegram_id", "Telegram ID"),
)


def _fmt(value: Any) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def make_console(no_color: bool = False) -> Console:
    return Console(no_color=no_color, highlight=False, soft_wrap=False)


def print_progress_line(console: Console, finding: Finding, verbose: bool) -> None:
    """Stream one result as it lands. Quiet unless it is a hit or a problem."""
    if not verbose and finding.status in (Status.NOT_FOUND, Status.SKIPPED):
        return
    marker, style = STATUS_STYLE[finding.status]
    line = Text.assemble(
        (marker, style),
        " ",
        (f"{finding.surface:<24}", "bold" if finding.status.is_positive else ""),
        (finding.url or finding.error or "", "cyan" if finding.status.is_positive else "dim"),
    )
    console.print(line)


def _identity_card(investigation: Investigation) -> Panel:
    """Merged view of everything we learned about the subject itself."""
    merged: dict[str, Any] = {}
    title = None
    description = None
    entity = EntityType.UNKNOWN

    for finding in investigation.findings:
        if finding.status is not Status.FOUND or finding.category != "telegram":
            continue
        merged.update({k: v for k, v in finding.attributes.items() if v not in (None, "", [])})
        if finding.surface == "t.me":
            title = finding.title or title
            description = finding.description or description
            entity = finding.entity_type
    for finding in investigation.findings:
        if finding.category == "phone" and finding.status is Status.FOUND:
            merged.update(finding.attributes)
            title = title or finding.title
            entity = finding.entity_type

    if not merged:
        return Panel(
            Text("No Telegram presence found for this subject.", style="yellow"),
            title=f"@{investigation.subject.value}",
            border_style="yellow",
        )

    header = Text()
    header.append(title or f"@{investigation.subject.value}", style="bold white")
    header.append(f"  ({ENTITY_ICON[entity]})", style="magenta")
    body = [header]
    if description:
        body.append(Text(description, style="italic"))

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    for key, label in _CARD_FIELDS:
        if key in merged:
            table.add_row(label, _fmt(merged[key]))

    for key in ("forwarded_from", "related_channels"):
        if key in merged:
            items = merged[key][:8]
            rendered = ", ".join(
                f"@{i.get('channel') or i.get('handle')}" for i in items if isinstance(i, dict)
            )
            table.add_row(key.replace("_", " ").title(), rendered)

    body.append(table)
    return Panel(
        Group(*body),
        title=f"@{investigation.subject.value}",
        border_style="green",
    )


def _surface_table(investigation: Investigation, show_all: bool) -> Table:
    table = Table(
        title="Surface checks",
        title_justify="left",
        header_style="bold",
        expand=False,
        box=None,
        pad_edge=False,
    )
    table.add_column("", width=3)
    table.add_column("Surface", style="bold")
    table.add_column("Category", style="dim")
    table.add_column("Detail", overflow="fold")

    for finding in investigation.findings:
        if not show_all and finding.status in (Status.NOT_FOUND, Status.SKIPPED):
            continue
        marker, style = STATUS_STYLE[finding.status]
        detail = finding.url if finding.status.is_positive else (finding.error or "")
        if finding.status.is_positive and finding.title:
            detail = f"{finding.title}  ({finding.url})"
        table.add_row(
            Text(marker, style=style),
            finding.surface,
            finding.category,
            Text(detail, style="cyan" if finding.status.is_positive else "dim"),
        )
    return table


def _summary(investigation: Investigation) -> Text:
    counts = dict.fromkeys(Status, 0)
    for finding in investigation.findings:
        counts[finding.status] += 1
    return Text.assemble(
        ("found ", "dim"),
        (str(counts[Status.FOUND]), "bold green"),
        ("  not-found ", "dim"),
        (str(counts[Status.NOT_FOUND]), "bold"),
        ("  inconclusive ", "dim"),
        (str(counts[Status.UNKNOWN] + counts[Status.ERROR]), "bold yellow"),
        ("  skipped ", "dim"),
        (str(counts[Status.SKIPPED]), "bold"),
    )


def render(console: Console, investigation: Investigation, *, show_all: bool = False) -> None:
    console.print()
    console.print(_identity_card(investigation))
    console.print()
    console.print(_surface_table(investigation, show_all))
    console.print()
    console.print(_summary(investigation))
    if not show_all:
        console.print(Text("re-run with --all to list negative results", style="dim"))


def render_permutation_summary(
    console: Console, results: Iterable[Investigation], base: str
) -> None:
    """Compact table for ``slt permute`` — one row per candidate handle."""
    table = Table(title=f"Handle permutations of @{base}", title_justify="left", box=None)
    table.add_column("", width=3)
    table.add_column("Handle", style="bold")
    table.add_column("Type", style="magenta")
    table.add_column("Name", overflow="fold")
    table.add_column("Audience", justify="right")

    hits = 0
    for investigation in results:
        primary = investigation.primary
        if primary is None:
            continue
        hits += 1
        attrs = primary.attributes
        audience = attrs.get("subscribers") or attrs.get("members")
        table.add_row(
            Text("[+]", style="bold green"),
            f"@{investigation.subject.value}",
            ENTITY_ICON[primary.entity_type],
            primary.title or "",
            _fmt(audience) if audience else "",
        )

    console.print()
    if hits:
        console.print(table)
    else:
        console.print(Text("No permutations resolved to a live handle.", style="yellow"))
    console.print()
