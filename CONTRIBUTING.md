# Contributing

The most useful contribution is usually **a new surface**, and that is a JSON edit.

```bash
git clone https://github.com/juandresrodca/sherlock-telegram
cd sherlock-telegram
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest && ruff check .
```

The test suite is fixture-driven and runs fully offline in about a second. No test may make a network call.

---

## Adding a surface

Append an entry to [`sherlock_telegram/resources/surfaces.json`](sherlock_telegram/resources/surfaces.json), then prove it works:

```bash
slt selftest --site "Your Surface"
```

### The one rule

**A surface must be able to tell a hit from a miss, from a datacenter IP, without an account.**

If it cannot, it does not go in as enabled. Ship it with `"enabled": false` and a `note` explaining exactly what goes wrong — that is genuinely useful, because it stops the next person rediscovering the same dead end. Several entries in the manifest are exactly this.

A surface that reports `found` for a handle nobody registered is worse than no surface at all: it quietly poisons every report that includes it. `selftest` exists to catch that, and it is why `usernameUnclaimed` is required.

### Field reference

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Unique display name |
| `category` | yes | `telegram`, `telegram-directory`, or `cross-platform` |
| `url` | yes | Public URL template; must contain `{}` |
| `errorType` | yes | `status_code`, `message`, `response_url`, or `regex` |
| `urlProbe` | | Fetch this instead of `url` — use an API endpoint when one exists |
| `errorMsg` | if `message` | String(s) present **only** when the handle is absent |
| `errorCode` | | Status codes meaning absent (default `[404]`) |
| `errorUrl` | if `response_url` | Redirect target meaning absent |
| `regexFound` | if `regex` | Pattern present **only** when the handle exists |
| `usernameRegex` | | Site's own handle rules; non-matching handles are skipped, not requested |
| `extract` | | `{"key": "regex with one capture group"}` — `title` and `description` are promoted |
| `confidence` | | `high`, `medium`, `low` (default `medium`) |
| `tags` | | Free-form, filterable with `--tag` |
| `enabled` | | `false` keeps a documented-but-unusable surface out of default scans |
| `note` | | **Required when disabled.** Why it cannot answer |
| `usernameClaimed` | yes if enabled | A handle that exists — `selftest` asserts `FOUND` |
| `usernameUnclaimed` | yes if enabled | A handle that does not — `selftest` asserts `NOT_FOUND` |

### Choosing an `errorType`

Check the status code for a real handle and a fake one **before** you pick:

- Different status codes → `status_code`. Simplest, prefer it.
- Both 200, different body → `message` (sentinel on the miss) or `regex` (marker on the hit). Prefer `regex` when the miss page is a bot challenge or an app shell, since "the sentinel is absent" is weak evidence there.
- Miss redirects somewhere canonical → `response_url`.

Prefer a JSON API over HTML whenever the site has one. `GitLab`, `Keybase`, `npm` and `Gravatar` all do, and their entries are stable because of it.

Use `zzq9x7v2knot44` as the unclaimed handle unless the site's rules forbid it. It is 14 characters, so it fits Keybase's 16-character cap while remaining a legal Telegram handle.

---

## Changing a parser

The hand-written modules in `sherlock_telegram/modules/` exist for surfaces a manifest entry cannot express. If you touch one:

1. **Add a fixture.** Save the real page to `tests/fixtures/` and assert against it. Parsers must be pure functions of HTML — `parse_profile`, `parse`, `parse_feed` all take a string and return a `Finding`, with I/O confined to the thin `check()` wrapper. That is what keeps the suite offline.
2. **Cover the negative case.** The most valuable test in this repo asserts that a *free* handle is `NOT_FOUND` despite HTTP 200.
3. **Never turn silence into a denial.** If a surface did not answer, return `Status.UNKNOWN`. `NOT_FOUND` is a claim, and you need evidence for it.

## Style

Ruff enforces the rest (`ruff check .`). Runtime dependencies are `httpx` and `rich`; adding a third needs a good argument, because a fast `pipx install` is a feature.

Comments should explain **why**, not restate the code — particularly the non-obvious bits, like why `subscribers` is matched before `members`, or why the channel feed splits on the post wrapper rather than the looser prefix.

## Pull requests

Say what you verified and how. For a new surface, paste your `slt selftest --site "..."` output. CI runs `pytest`, `ruff`, and a `selftest` against the live enabled surfaces — that last job is allowed to fail on a network hiccup, but a consistent failure means a surface has rotted and needs disabling.

By contributing you agree your work is MIT-licensed, and that it is consistent with [ETHICS.md](ETHICS.md). Features whose primary purpose is bulk collection of people who did not opt in will be declined.
