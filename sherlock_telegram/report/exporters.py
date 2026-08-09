"""File exporters: JSON, CSV, Markdown, HTML.

All four take the same ``list[Investigation]`` so a single-handle scan and a
permutation sweep serialise identically — a downstream tool never needs to know
which subcommand produced the file.
"""

from __future__ import annotations

import csv
import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..core.models import Investigation, Status

# CSV is the flat, spreadsheet-friendly view; nested attributes get one column.
_CSV_COLUMNS = [
    "subject",
    "surface",
    "category",
    "status",
    "confidence",
    "entity_type",
    "title",
    "url",
    "http_status",
    "elapsed_ms",
    "attributes",
    "error",
]


def _payload(investigations: Sequence[Investigation]) -> dict[str, Any]:
    return {
        "tool": "sherlock-telegram",
        "version": investigations[0].tool_version if investigations else "0.1.0",
        "investigations": [inv.to_dict() for inv in investigations],
    }


def to_json(investigations: Sequence[Investigation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_payload(investigations), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def to_csv(investigations: Sequence[Investigation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is required on Windows or csv emits blank rows.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for investigation in investigations:
            for finding in investigation.findings:
                writer.writerow(
                    {
                        "subject": investigation.subject.value,
                        "surface": finding.surface,
                        "category": finding.category,
                        "status": finding.status.value,
                        "confidence": finding.confidence.value,
                        "entity_type": finding.entity_type.value,
                        "title": finding.title or "",
                        "url": finding.url,
                        "http_status": finding.http_status or "",
                        "elapsed_ms": finding.elapsed_ms or "",
                        "attributes": json.dumps(finding.attributes, ensure_ascii=False)
                        if finding.attributes
                        else "",
                        "error": finding.error or "",
                    }
                )
    return path


def _md_attributes(attrs: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in attrs.items():
        if value in (None, "", []):
            continue
        if isinstance(value, list):
            rendered = ", ".join(
                str(v.get("channel") or v.get("handle") or v) if isinstance(v, dict) else str(v)
                for v in value[:10]
            )
        else:
            rendered = f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else str(value)
        lines.append(f"  - **{key.replace('_', ' ')}**: {rendered}")
    return lines


def to_markdown(investigations: Sequence[Investigation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = ["# Sherlock Telegram report", ""]

    for investigation in investigations:
        subject = investigation.subject
        out.append(f"## `{subject.value}` ({subject.kind})")
        out.append("")
        out.append(f"- Scanned: {investigation.started_at} → {investigation.finished_at}")
        out.append(f"- Surfaces checked: {len(investigation.findings)}")
        out.append(f"- Positive hits: {len(investigation.hits)}")
        primary = investigation.primary
        if primary:
            out.append(f"- Entity type: **{primary.entity_type.value}**")
        out.append("")

        hits = investigation.hits
        if hits:
            out.append("### Hits")
            out.append("")
            for finding in hits:
                title = f" — {finding.title}" if finding.title else ""
                out.append(f"- **{finding.surface}**{title} — <{finding.url}>")
                if finding.description:
                    out.append(f"  - {finding.description}")
                out.extend(_md_attributes(finding.attributes))
            out.append("")

        inconclusive = [
            f for f in investigation.findings if f.status in (Status.UNKNOWN, Status.ERROR)
        ]
        if inconclusive:
            out.append("### Inconclusive")
            out.append("")
            out.append("> These surfaces did not answer. They are **not** negative results.")
            out.append("")
            for finding in inconclusive:
                out.append(f"- {finding.surface}: {finding.error or 'no conclusion'}")
            out.append("")

        negatives = [f for f in investigation.findings if f.status is Status.NOT_FOUND]
        if negatives:
            out.append(
                f"### Not found ({len(negatives)})\n\n"
                + ", ".join(f.surface for f in negatives)
                + "\n"
            )

    path.write_text("\n".join(out), encoding="utf-8")
    return path


_HTML_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Sherlock Telegram — {title}</title>
<style>
  :root {{ color-scheme: light dark; --bg:#fff; --fg:#111; --muted:#666; --line:#e3e3e3;
           --ok:#0a7f3f; --warn:#a86b00; --bad:#999; --card:#fafafa; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --fg:#e6e6e6; --muted:#9aa0a6; --line:#252932;
             --ok:#4ade80; --warn:#fbbf24; --bad:#5b616e; --card:#161922; }}
  }}
  body {{ background:var(--bg); color:var(--fg); font:15px/1.55 -apple-system,BlinkMacSystemFont,
          "Segoe UI",Roboto,sans-serif; margin:0; padding:2.5rem 1.5rem; }}
  main {{ max-width:60rem; margin:0 auto; }}
  h1 {{ font-size:1.4rem; margin:0 0 .3rem; }}
  h2 {{ font-size:1.15rem; margin:2.5rem 0 .6rem; border-bottom:1px solid var(--line); padding-bottom:.4rem; }}
  .sub {{ color:var(--muted); font-size:.85rem; margin-bottom:2rem; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:1rem 1.2rem; margin:.8rem 0; }}
  .card h3 {{ margin:0 0 .4rem; font-size:1rem; }}
  dl {{ display:grid; grid-template-columns:max-content 1fr; gap:.15rem .9rem; margin:.6rem 0 0; font-size:.88rem; }}
  dt {{ color:var(--muted); }} dd {{ margin:0; }}
  .tbl-wrap {{ overflow-x:auto; }}
  table {{ border-collapse:collapse; width:100%; font-size:.88rem; }}
  th,td {{ text-align:left; padding:.4rem .7rem; border-bottom:1px solid var(--line); white-space:nowrap; }}
  td.u {{ white-space:normal; word-break:break-all; }}
  .found {{ color:var(--ok); font-weight:600; }}
  .unknown {{ color:var(--warn); }}
  .miss {{ color:var(--bad); }}
  a {{ color:inherit; }}
  footer {{ margin-top:3rem; color:var(--muted); font-size:.8rem; }}
</style>
<main>
<h1>Sherlock Telegram report</h1>
<div class="sub">{subtitle}</div>
{body}
<footer>Generated by sherlock-telegram. Findings reflect public data at scan time and may be stale.
Inconclusive rows are unanswered surfaces, not negative results.</footer>
</main>
"""

_STATUS_CLASS = {
    Status.FOUND: ("found", "found"),
    Status.NOT_FOUND: ("miss", "not found"),
    Status.UNKNOWN: ("unknown", "inconclusive"),
    Status.ERROR: ("unknown", "error"),
    Status.SKIPPED: ("miss", "skipped"),
}


def to_html(investigations: Sequence[Investigation], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    esc = html.escape
    parts: list[str] = []

    for investigation in investigations:
        parts.append(f"<h2>@{esc(investigation.subject.value)}</h2>")

        for finding in investigation.hits:
            parts.append('<div class="card">')
            heading = esc(finding.title or finding.surface)
            parts.append(f"<h3>{esc(finding.surface)} — {heading}</h3>")
            if finding.description:
                parts.append(f"<div class='sub'>{esc(finding.description)}</div>")
            if finding.url:
                parts.append(f"<div><a href='{esc(finding.url)}'>{esc(finding.url)}</a></div>")
            if finding.attributes:
                rows = []
                for key, value in finding.attributes.items():
                    if value in (None, "", []):
                        continue
                    if isinstance(value, list):
                        value = ", ".join(
                            str(v.get("channel") or v.get("handle") or v)
                            if isinstance(v, dict)
                            else str(v)
                            for v in value[:12]
                        )
                    rows.append(
                        f"<dt>{esc(key.replace('_', ' '))}</dt><dd>{esc(str(value))}</dd>"
                    )
                if rows:
                    parts.append("<dl>" + "".join(rows) + "</dl>")
            parts.append("</div>")

        parts.append('<div class="tbl-wrap"><table>')
        parts.append("<tr><th>Status</th><th>Surface</th><th>Category</th><th>URL / note</th></tr>")
        for finding in investigation.findings:
            css, label = _STATUS_CLASS[finding.status]
            detail = finding.url or finding.error or ""
            cell = (
                f"<a href='{esc(finding.url)}'>{esc(finding.url)}</a>"
                if finding.url
                else esc(detail)
            )
            parts.append(
                f"<tr><td class='{css}'>{label}</td><td>{esc(finding.surface)}</td>"
                f"<td>{esc(finding.category)}</td><td class='u'>{cell}</td></tr>"
            )
        parts.append("</table></div>")

    subjects = ", ".join(inv.subject.value for inv in investigations[:5])
    if len(investigations) > 5:
        subjects += f" (+{len(investigations) - 5} more)"
    subtitle = f"{len(investigations)} subject(s): {esc(subjects)}"

    path.write_text(
        _HTML_TEMPLATE.format(
            title=esc(investigations[0].subject.value if investigations else "report"),
            subtitle=subtitle,
            body="\n".join(parts),
        ),
        encoding="utf-8",
    )
    return path


EXPORTERS = {
    "json": to_json,
    "csv": to_csv,
    "md": to_markdown,
    "html": to_html,
}
