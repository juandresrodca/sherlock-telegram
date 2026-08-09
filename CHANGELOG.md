# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semantic](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-09

Initial release.

### Added

- **`t.me` probe** with entity classification (user / bot / channel / group),
  driven by the `tgme_page_title` block rather than the status code — `t.me`
  answers HTTP 200 for every handle, claimed or not.
- **Fragment marketplace module** distinguishing `Taken`, `On auction`, `Sold`
  and `Unavailable`, including the TON ownership pivot for sold handles.
- **Channel feed analysis** via `t.me/s/<channel>`: posting cadence, median
  gap, active UTC hours, busiest weekday, plus the forwarded-from and mention
  graph for pivoting between channels.
- **Permutation engine** for alternate handles — separator, suffix, prefix,
  leetspeak and optional typo variants, ordered by likelihood and filtered
  against Telegram's handle rules.
- **Manifest-driven surfaces** (`resources/surfaces.json`) with Sherlock's four
  detection strategies (`status_code`, `message`, `response_url`, `regex`),
  validated at load time.
- **`slt selftest`** — verifies every enabled surface against a handle known to
  exist and one known not to, so a rule that reports false positives fails
  loudly instead of poisoning reports.
- **Opt-in MTProto phone lookup**, capped at 10 numbers per run, with no file
  input, batch mode or resume state. See [ETHICS.md](ETHICS.md).
- Exporters for JSON, CSV, Markdown and HTML, all sharing one schema.
- 125 offline, fixture-driven tests.

### Notes on the shipped manifest

Enabled and verified: GitHub, GitLab, Keybase, PyPI, npm, Gravatar, Steam, VK.

Shipped disabled, each with a documented reason: Hacker News and Reddit (block
datacenter IPs), Medium (Cloudflare 403 for every handle), YouTube (EU consent
redirect), Twitch (JS-rendered not-found state reported a hit for an
unregistered handle during selftest), Lyzem (hit and miss pages are
structurally identical), TGStat and Telemetr (403 / auth required).

A surface that cannot honestly distinguish a hit from a miss is recorded rather
than deleted, so the same dead end is not rediscovered.

[Unreleased]: https://github.com/juandresrodca/sherlock-telegram/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/juandresrodca/sherlock-telegram/releases/tag/v0.1.0
