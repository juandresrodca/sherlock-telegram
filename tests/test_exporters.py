"""Export formats."""

from __future__ import annotations

import csv
import json

from sherlock_telegram.core.models import (
    EntityType,
    Finding,
    Investigation,
    Status,
    Subject,
)
from sherlock_telegram.report import exporters


def _investigation() -> Investigation:
    inv = Investigation(subject=Subject("alice"))
    inv.add(
        Finding(
            surface="t.me",
            category="telegram",
            url="https://t.me/alice",
            status=Status.FOUND,
            entity_type=EntityType.CHANNEL,
            title="Alice & Co",
            description="A channel",
            attributes={"subscribers": 1234, "related_channels": [{"handle": "bob"}]},
        )
    )
    inv.add(
        Finding(
            surface="Reddit",
            category="cross-platform",
            url="https://reddit.com/u/alice",
            status=Status.UNKNOWN,
            error="HTTP 403",
        )
    )
    inv.add(Finding(surface="GitHub", category="cross-platform", url="", status=Status.NOT_FOUND))
    inv.finished_at = inv.started_at
    return inv


def test_json_export_round_trips(tmp_path):
    path = exporters.to_json([_investigation()], tmp_path / "out.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    inv = data["investigations"][0]
    assert inv["subject"]["value"] == "alice"
    assert inv["summary"] == {"checked": 3, "found": 1, "entity_type": "channel"}
    assert inv["findings"][0]["attributes"]["subscribers"] == 1234


def test_csv_export_has_one_row_per_finding(tmp_path):
    path = exporters.to_csv([_investigation()], tmp_path / "out.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    assert rows[0]["subject"] == "alice"
    assert {r["status"] for r in rows} == {"found", "unknown", "not_found"}
    # Nested attributes survive as embedded JSON.
    assert json.loads(rows[0]["attributes"])["subscribers"] == 1234


def test_csv_has_no_blank_interleaved_rows(tmp_path):
    """Regression guard for the classic Windows csv newline bug."""
    path = exporters.to_csv([_investigation()], tmp_path / "out.csv")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "" not in lines


def test_markdown_separates_inconclusive_from_negative(tmp_path):
    path = exporters.to_markdown([_investigation()], tmp_path / "out.md")
    text = path.read_text(encoding="utf-8")
    assert "### Hits" in text
    assert "### Inconclusive" in text
    assert "not** negative results" in text
    assert "### Not found (1)" in text


def test_html_escapes_untrusted_content(tmp_path):
    """Titles come from remote pages and must never reach the DOM raw."""
    inv = Investigation(subject=Subject("alice"))
    inv.add(
        Finding(
            surface="t.me",
            category="telegram",
            url="https://t.me/alice",
            status=Status.FOUND,
            title="<script>alert(1)</script>",
        )
    )
    inv.finished_at = inv.started_at
    path = exporters.to_html([inv], tmp_path / "out.html")
    text = path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;" in text


def test_html_marks_inconclusive_rows_distinctly(tmp_path):
    path = exporters.to_html([_investigation()], tmp_path / "out.html")
    text = path.read_text(encoding="utf-8")
    assert "inconclusive" in text
    assert "not found" in text


def test_exporters_create_missing_directories(tmp_path):
    target = tmp_path / "deep" / "nested" / "out.json"
    assert exporters.to_json([_investigation()], target).exists()


def test_all_formats_accept_multiple_investigations(tmp_path):
    two = [_investigation(), _investigation()]
    for fmt, exporter in exporters.EXPORTERS.items():
        assert exporter(two, tmp_path / f"multi.{fmt}").exists()
