"""Command-line interface.

argparse rather than click/typer, on purpose: the runtime dependency list is
``httpx`` + ``rich``, so ``pipx install sherlock-telegram`` resolves in seconds
and there is nothing to break on an air-gapped analyst box.

Subcommands
-----------
``scan``       full recon on one or more handles
``permute``    generate and check likely alternate handles
``channel``    deep-dive a public channel's feed and forward graph
``phone``      MTProto phone lookup (opt-in, capped, needs credentials)
``surfaces``   list the manifest
``selftest``   verify manifest entries against known-good/known-absent handles
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path

# Rich parses square brackets as style tags, so any interpolated exception text
# must be escaped first. Without this the hint 'pip install
# "sherlock-telegram[mtproto]"' prints with the extra silently eaten.
from rich.markup import escape as _esc

from . import __version__
from .core.engine import ScanOptions, check_surface, run_scan
from .core.http import Fetcher
from .core.manifest import ManifestError, Surface, filter_surfaces, load_surfaces
from .core.models import Investigation, Status, Subject
from .modules import channel as channel_mod
from .modules import fragment as fragment_mod
from .modules import permutations as perm_mod
from .modules import phone as phone_mod
from .modules import tme as tme_mod
from .report import console as console_report
from .report.exporters import EXPORTERS

EPILOG = """\
examples:
  slt scan durov                       full recon on a single handle
  slt scan durov --all --html out.html include negatives, write an HTML report
  slt scan durov --only telegram       skip cross-platform handle reuse checks
  slt permute johndoe --limit 40       hunt for alternate accounts
  slt channel durov --json feed.json   channel cadence + forward graph
  slt surfaces --category telegram     inspect the manifest
  slt selftest                         verify manifest entries still work

Only public data is collected unless you explicitly run `slt phone`.
See ETHICS.md before scanning anyone but yourself.
"""


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def _add_network_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("network")
    group.add_argument("--concurrency", type=int, default=12, help="parallel requests (default: 12)")
    group.add_argument("--timeout", type=float, default=15.0, help="per-request timeout seconds")
    group.add_argument("--retries", type=int, default=2, help="retries on timeout/429/5xx")
    group.add_argument(
        "--rate", type=float, default=8.0, help="global requests per second (default: 8)"
    )
    group.add_argument("--proxy", help="proxy URL, e.g. socks5://127.0.0.1:9050")
    group.add_argument(
        "--insecure", action="store_true", help="skip TLS verification (debugging only)"
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("output")
    group.add_argument("--json", metavar="PATH", help="write JSON report")
    group.add_argument("--csv", metavar="PATH", help="write CSV report")
    group.add_argument("--md", metavar="PATH", help="write Markdown report")
    group.add_argument("--html", metavar="PATH", help="write HTML report")
    group.add_argument("-a", "--all", action="store_true", help="show negative results too")
    group.add_argument("-v", "--verbose", action="store_true", help="stream every check")
    group.add_argument("-q", "--quiet", action="store_true", help="suppress the live stream")
    group.add_argument("--no-color", action="store_true", help="disable ANSI colour")


def _add_surface_filters(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("surface selection")
    group.add_argument("--manifest", metavar="PATH", help="use a custom surfaces.json")
    group.add_argument(
        "--only",
        metavar="CATEGORY",
        action="append",
        help="restrict to a category (telegram, telegram-directory, cross-platform)",
    )
    group.add_argument("--site", metavar="NAME", action="append", help="restrict to a named surface")
    group.add_argument("--tag", metavar="TAG", action="append", help="restrict by tag")
    group.add_argument(
        "--include-disabled",
        action="store_true",
        help="also run surfaces disabled by default (blocked or unreliable ones)",
    )
    group.add_argument(
        "--no-cross-platform",
        action="store_true",
        help="Telegram surfaces only; skip handle-reuse checks on other sites",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slt",
        description="Sherlock Telegram — OSINT reconnaissance for Telegram identities.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"sherlock-telegram {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="full recon on one or more handles")
    scan.add_argument("handles", nargs="+", help="Telegram handle(s), with or without @")
    _add_surface_filters(scan)
    _add_network_args(scan)
    _add_output_args(scan)

    permute = sub.add_parser("permute", help="generate and check likely alternate handles")
    permute.add_argument("handle", help="base handle to mutate")
    permute.add_argument("--limit", type=int, default=60, help="max candidates (default: 60)")
    permute.add_argument("--typos", action="store_true", help="also try doubled/dropped characters")
    permute.add_argument("--no-leet", action="store_true", help="skip leetspeak substitutions")
    permute.add_argument(
        "--dry-run", action="store_true", help="print candidates without checking them"
    )
    _add_network_args(permute)
    _add_output_args(permute)

    chan = sub.add_parser("channel", help="deep-dive a public channel feed")
    chan.add_argument("handle", help="public channel handle")
    _add_network_args(chan)
    _add_output_args(chan)

    phone = sub.add_parser(
        "phone",
        help="MTProto phone lookup (opt-in; needs API credentials)",
        description=(
            f"Resolve up to {phone_mod.MAX_NUMBERS_PER_RUN} phone numbers to Telegram accounts. "
            "This is the one authenticated module: it uses your own API credentials and "
            "temporarily adds each number as a contact. There is no bulk mode by design."
        ),
    )
    phone.add_argument("numbers", nargs="+", help="phone number(s) in E.164, e.g. +14155550123")
    phone.add_argument("--api-id", help="Telegram API ID (or set TELEGRAM_API_ID)")
    phone.add_argument("--api-hash", help="Telegram API hash (or set TELEGRAM_API_HASH)")
    phone.add_argument("--session", default="sherlock-telegram", help="Telethon session name")
    phone.add_argument(
        "--yes", action="store_true", help="skip the interactive confirmation prompt"
    )
    _add_output_args(phone)

    surfaces = sub.add_parser("surfaces", help="list manifest surfaces")
    surfaces.add_argument("--manifest", metavar="PATH", help="use a custom surfaces.json")
    surfaces.add_argument("--category", help="filter by category")
    surfaces.add_argument("--no-color", action="store_true")

    selftest = sub.add_parser(
        "selftest", help="verify manifest entries against known handles"
    )
    selftest.add_argument("--manifest", metavar="PATH", help="use a custom surfaces.json")
    selftest.add_argument("--site", action="append", help="test only this surface")
    selftest.add_argument("--include-disabled", action="store_true")
    selftest.add_argument(
        "--strict",
        action="store_true",
        help="also fail when a surface does not answer (blocked/rate-limited), "
        "not just when it answers wrongly",
    )
    selftest.add_argument("--no-color", action="store_true")
    _add_network_args(selftest)

    return parser


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _normalise_handle(raw: str) -> str:
    """Accept ``@name``, a bare name, or any ``t.me/...`` URL form."""
    handle = raw.strip().lstrip("@")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "telegram.me/"):
        if handle.lower().startswith(prefix):
            handle = handle[len(prefix) :]
    handle = handle.split("/")[0].split("?")[0]
    return handle


def _scan_options(args: argparse.Namespace) -> ScanOptions:
    return ScanOptions(
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
        rate=args.rate,
        proxy=args.proxy,
        verify_tls=not args.insecure,
    )


def _select_surfaces(args: argparse.Namespace) -> list[Surface]:
    manifest_path = Path(args.manifest) if getattr(args, "manifest", None) else None
    surfaces = load_surfaces(manifest_path)
    categories = list(args.only) if getattr(args, "only", None) else None
    if getattr(args, "no_cross_platform", False):
        categories = [c for c in (categories or []) if c != "cross-platform"] or [
            "telegram",
            "telegram-directory",
        ]
    return filter_surfaces(
        surfaces,
        categories=categories,
        names=getattr(args, "site", None),
        tags=getattr(args, "tag", None),
        include_disabled=getattr(args, "include_disabled", False),
    )


def _write_reports(args: argparse.Namespace, investigations: Sequence[Investigation], console) -> None:
    for fmt, exporter in EXPORTERS.items():
        target = getattr(args, fmt, None)
        if target:
            path = exporter(investigations, Path(target))
            console.print(f"[dim]wrote {fmt} ->[/dim] {path}")


def _telegram_tasks(handle: str, *, include_feed: bool = True):
    """The hand-written modules that run alongside manifest surfaces."""
    tasks = [
        partial(tme_mod.check, handle=handle),
        partial(fragment_mod.check, handle=handle),
    ]
    if include_feed:
        tasks.append(partial(channel_mod.check, handle=handle))
    for task, name in zip(tasks, ("t.me", "Fragment", "Channel feed")):
        task.surface_name = name  # surfaced in the engine's error path
    return tasks


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


async def cmd_scan(args: argparse.Namespace) -> int:
    console = console_report.make_console(args.no_color)
    surfaces = _select_surfaces(args)
    options = _scan_options(args)
    investigations: list[Investigation] = []

    for raw in args.handles:
        handle = _normalise_handle(raw)
        if not tme_mod.USERNAME_RE.match(handle):
            console.print(
                f"[yellow]skipping[/yellow] {_esc(repr(raw))}: not a valid Telegram handle "
                "(5-32 chars, letters/digits/underscore, must start with a letter)"
            )
            continue

        console.print(f"[bold]Scanning[/bold] @{handle} across {len(surfaces) + 3} surfaces...")
        hook = (
            None
            if args.quiet
            else partial(console_report.print_progress_line, console, verbose=args.verbose)
        )
        investigation = await run_scan(
            Subject(handle, "username"),
            surfaces,
            options=options,
            extra_tasks=_telegram_tasks(handle),
            on_result=hook,
        )
        console_report.render(console, investigation, show_all=args.all)
        investigations.append(investigation)

    if not investigations:
        return 2
    _write_reports(args, investigations, console)
    return 0 if any(inv.hits for inv in investigations) else 1


async def cmd_permute(args: argparse.Namespace) -> int:
    console = console_report.make_console(args.no_color)
    base = _normalise_handle(args.handle)
    candidates = perm_mod.generate(
        base, leet=not args.no_leet, typos=args.typos, limit=args.limit
    )

    if not candidates:
        console.print("[yellow]No valid permutations generated.[/yellow]")
        return 1

    if args.dry_run:
        for candidate in candidates:
            console.print(candidate)
        return 0

    console.print(
        f"[bold]Checking[/bold] {len(candidates)} permutations of @{base} "
        "(t.me only, to stay polite)..."
    )
    options = _scan_options(args)
    investigations: list[Investigation] = []

    # t.me alone here: a permutation sweep multiplied by every cross-platform
    # surface would be a lot of traffic aimed at sites that did not ask for it.
    for candidate in candidates:
        investigation = await run_scan(
            Subject(candidate, "username"),
            [],
            options=options,
            extra_tasks=_telegram_tasks(candidate, include_feed=False),
        )
        investigations.append(investigation)
        if not args.quiet:
            primary = investigation.primary
            if primary:
                console.print(f"[bold green][+][/bold green] @{candidate} — {primary.title or ''}")
            elif args.verbose:
                console.print(f"[dim][-] @{candidate}[/dim]")

    console_report.render_permutation_summary(console, investigations, base)
    _write_reports(args, investigations, console)
    return 0 if any(inv.hits for inv in investigations) else 1


async def cmd_channel(args: argparse.Namespace) -> int:
    console = console_report.make_console(args.no_color)
    handle = _normalise_handle(args.handle)
    console.print(f"[bold]Analysing[/bold] channel @{handle}...")

    investigation = await run_scan(
        Subject(handle, "channel"),
        [],
        options=_scan_options(args),
        extra_tasks=_telegram_tasks(handle),
    )
    console_report.render(console, investigation, show_all=args.all)
    _write_reports(args, [investigation], console)
    return 0 if investigation.hits else 1


async def cmd_phone(args: argparse.Namespace) -> int:
    console = console_report.make_console(args.no_color)
    numbers = args.numbers

    if len(numbers) > phone_mod.MAX_NUMBERS_PER_RUN:
        console.print(
            f"[red]Refusing:[/red] at most {phone_mod.MAX_NUMBERS_PER_RUN} numbers per run. "
            "This module investigates a subject; it is not a bulk enumerator."
        )
        return 2

    if not args.yes:
        console.print(
            "[yellow]This module authenticates as you[/yellow] and temporarily adds each "
            "number to your contacts (then removes it). Only run it on numbers you have a "
            "lawful basis to investigate."
        )
        try:
            if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
                console.print("Aborted.")
                return 130
        except (EOFError, KeyboardInterrupt):
            console.print("\nAborted.")
            return 130

    try:
        findings = await phone_mod.lookup(
            numbers, api_id=args.api_id, api_hash=args.api_hash, session=args.session
        )
    except (phone_mod.MTProtoUnavailable, phone_mod.TooManyNumbers, ValueError) as exc:
        console.print(f"[red]error:[/red] {_esc(str(exc))}")
        return 2

    investigations = []
    for number, finding in zip(numbers, findings):
        investigation = Investigation(subject=Subject(number, "phone"))
        investigation.add(finding)
        investigation.finished_at = investigation.started_at
        console_report.render(console, investigation, show_all=args.all)
        investigations.append(investigation)

    _write_reports(args, investigations, console)
    return 0 if any(inv.hits for inv in investigations) else 1


def cmd_surfaces(args: argparse.Namespace) -> int:
    from rich.table import Table

    console = console_report.make_console(args.no_color)
    surfaces = load_surfaces(Path(args.manifest) if args.manifest else None)
    if args.category:
        surfaces = [s for s in surfaces if s.category.lower() == args.category.lower()]

    table = Table(title=f"{len(surfaces)} surfaces", title_justify="left", box=None)
    table.add_column("Surface", style="bold")
    table.add_column("Category", style="dim")
    table.add_column("Detection")
    table.add_column("Conf.")
    table.add_column("On", justify="center")
    table.add_column("Note", overflow="fold", style="dim")

    for surface in surfaces:
        table.add_row(
            surface.name,
            surface.category,
            surface.error_type,
            surface.confidence.value,
            "[green]yes[/green]" if surface.enabled else "[dim]no[/dim]",
            surface.note or "",
        )
    console.print()
    console.print(table)
    console.print()
    return 0


async def cmd_selftest(args: argparse.Namespace) -> int:
    """Check each surface against a handle known to exist and one known not to.

    This is the manifest's regression test, and it applies the project's own
    central distinction to itself: a **wrong answer** and **no answer** are not
    the same event.

    * A surface that says NOT_FOUND for a handle that exists, or FOUND for one
      that does not, has a broken rule. That is a real defect — it silently
      poisons every report — and it fails the run.
    * A surface that returns UNKNOWN was rate-limited, blocked or unreachable.
      It never made a claim, so it cannot have made a false one. Treating that
      as a manifest failure would be exactly the ``unknown``-means-``no``
      conflation this tool exists to avoid, and in CI it turns every
      third-party hiccup into a red build.

    Pass ``--strict`` to fail on inconclusive results too, which is what you
    want when verifying a new surface locally.
    """
    console = console_report.make_console(args.no_color)
    surfaces = filter_surfaces(
        load_surfaces(Path(args.manifest) if args.manifest else None),
        names=args.site,
        include_disabled=args.include_disabled,
    )
    options = _scan_options(args)
    failures = 0
    inconclusive = 0

    async with Fetcher(
        concurrency=options.concurrency,
        timeout=options.timeout,
        retries=options.retries,
        rate=options.rate,
        proxy=options.proxy,
        verify=options.verify_tls,
    ) as fetcher:
        for surface in surfaces:
            checks = []
            if surface.username_claimed:
                checks.append((surface.username_claimed, Status.FOUND))
            if surface.username_unclaimed:
                checks.append((surface.username_unclaimed, Status.NOT_FOUND))
            if not checks:
                console.print(f"[dim][ ][/dim] {surface.name:<24} no test handles defined")
                continue

            wrong: list[str] = []
            silent: list[str] = []
            for handle, expected in checks:
                finding = await check_surface(fetcher, surface, handle)
                if finding.status is expected:
                    continue
                detail = f"{handle} -> {finding.status.value} (expected {expected.value})" + (
                    f" ({_esc(finding.error)})" if finding.error else ""
                )
                # UNKNOWN/ERROR/SKIPPED are non-answers, not wrong answers.
                if finding.status in (Status.UNKNOWN, Status.ERROR, Status.SKIPPED):
                    silent.append(detail)
                else:
                    wrong.append(detail)

            if wrong and surface.enabled:
                failures += 1
                console.print(f"[red][!][/red] {surface.name:<24} " + "; ".join(wrong))
            elif wrong:
                # A disabled surface is *documented* as unable to answer, so a
                # wrong answer here confirms the note rather than breaking CI.
                console.print(
                    f"[yellow][~][/yellow] {surface.name:<24} disabled, as expected: "
                    + "; ".join(wrong)
                )
            elif silent:
                inconclusive += 1
                console.print(
                    f"[yellow][?][/yellow] {surface.name:<24} no answer: " + "; ".join(silent)
                )
            else:
                console.print(f"[green][+][/green] {surface.name:<24} ok")

    console.print()
    if failures:
        console.print(f"[red]{failures} enabled surface(s) returned a wrong answer.[/red]")
        return 1
    if inconclusive:
        console.print(
            f"[yellow]{inconclusive} surface(s) did not answer[/yellow] "
            "(blocked or rate-limited, not a manifest defect). "
            "Repeated failures for the same surface mean it should be disabled."
        )
        if args.strict:
            console.print("[red]--strict: treating inconclusive as failure.[/red]")
            return 1
    console.print("[green]No surface contradicted its declared behaviour.[/green]")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "surfaces":
        handler = cmd_surfaces
        try:
            return handler(args)
        except ManifestError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    coroutines = {
        "scan": cmd_scan,
        "permute": cmd_permute,
        "channel": cmd_channel,
        "phone": cmd_phone,
        "selftest": cmd_selftest,
    }
    try:
        return asyncio.run(coroutines[args.command](args))
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
