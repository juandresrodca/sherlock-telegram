"""CLI argument handling and input normalisation."""

from __future__ import annotations

import pytest

from sherlock_telegram.cli import _normalise_handle, build_parser, main


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("durov", "durov"),
        ("@durov", "durov"),
        ("https://t.me/durov", "durov"),
        ("http://t.me/durov", "durov"),
        ("t.me/durov", "durov"),
        ("telegram.me/durov", "durov"),
        ("https://t.me/durov/519", "durov"),
        ("https://t.me/durov?start=1", "durov"),
        ("  @durov  ", "durov"),
    ],
)
def test_handle_normalisation(raw, expected):
    assert _normalise_handle(raw) == expected


def test_scan_parses_multiple_handles_and_output_flags():
    args = build_parser().parse_args(
        ["scan", "alice", "bob", "--json", "o.json", "--all", "--only", "telegram"]
    )
    assert args.handles == ["alice", "bob"]
    assert args.json == "o.json"
    assert args.all is True
    assert args.only == ["telegram"]


def test_network_defaults_are_polite():
    args = build_parser().parse_args(["scan", "alice"])
    assert args.rate <= 10
    assert args.concurrency <= 16
    assert args.retries >= 1


def test_permute_flags():
    args = build_parser().parse_args(["permute", "alice", "--limit", "5", "--typos", "--dry-run"])
    assert (args.limit, args.typos, args.dry_run) == (5, True, True)


def test_subcommand_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_surfaces_command_runs(capsys):
    assert main(["surfaces", "--no-color"]) == 0
    assert "GitHub" in capsys.readouterr().out


def test_surfaces_command_filters_by_category(capsys):
    assert main(["surfaces", "--category", "telegram-directory", "--no-color"]) == 0
    out = capsys.readouterr().out
    assert "TGStat" in out
    assert "GitHub" not in out


def test_bad_manifest_exits_with_code_two(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["surfaces", "--manifest", str(bad)]) == 2
    assert "error" in capsys.readouterr().err


def test_permute_dry_run_makes_no_requests(capsys):
    assert main(["permute", "johndoe", "--limit", "4", "--dry-run", "--no-color"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 4
    assert "johndoe" not in lines


def test_scan_rejects_a_malformed_handle_without_scanning(capsys):
    # "ab" cannot be a Telegram handle, so the scan short-circuits before any
    # network call is made — which is also what keeps this test offline.
    assert main(["scan", "ab", "--no-color", "--quiet"]) == 2
    assert "skipping" in capsys.readouterr().out


def test_phone_refuses_bulk_input(capsys):
    numbers = [f"+1415555{i:04d}" for i in range(20)]
    assert main(["phone", *numbers, "--yes", "--no-color"]) == 2
    assert "Refusing" in capsys.readouterr().out


def test_error_text_containing_brackets_survives_rich_markup(capsys, monkeypatch):
    """Regression: rich parses [...] as a style tag.

    The install hint 'pip install "sherlock-telegram[mtproto]"' printed as
    '...sherlock-telegram"' — rich ate the extra, leaving a command that
    silently installs the wrong thing.
    """
    import sherlock_telegram.modules.phone as phone_mod

    def boom(*_args, **_kwargs):
        raise phone_mod.MTProtoUnavailable(
            'Telethon is not installed. Run: pip install "sherlock-telegram[mtproto]"'
        )

    monkeypatch.setattr(phone_mod, "_require_telethon", boom)
    assert main(["phone", "+14155550123", "--yes", "--no-color"]) == 2
    assert "[mtproto]" in capsys.readouterr().out
