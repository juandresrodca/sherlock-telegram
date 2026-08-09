# Sherlock Telegram

**Sherlock's methodology, aimed at Telegram.** Give it a handle and it tells you what that handle *is* — person, bot, channel or group — what it looks like from the outside, where else the name appears, and which neighbouring handles are worth pulling next.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Passive by default](https://img.shields.io/badge/collection-passive%20by%20default-brightgreen)](ETHICS.md)
[![No bulk enumeration](https://img.shields.io/badge/bulk%20phone%20enumeration-refused-critical)](ETHICS.md#what-this-tool-will-not-do)
[![Manifest-driven](https://img.shields.io/badge/surfaces-manifest--driven-blue)](CONTRIBUTING.md#adding-a-surface)

> Most "Telegram OSINT" tools are a `requests.get("https://t.me/" + name)` and a status-code check. That check is **always wrong**: `t.me` returns HTTP 200 for every handle on earth, claimed or not. This tool starts from the markup that actually discriminates, and refuses to report a conclusion it did not observe.

---

## Try it in 30 seconds

```bash
pipx install sherlock-telegram
slt scan durov
```

```
╭─ @durov ──────────────────────────────────────────────╮
│ Pavel Durov  (channel)                                 │
│ Founder of Telegram.                                   │
│      Subscribers  11,288,217                           │
│       Posts/day   0.63                                 │
│  Median gap (h)   31.4                                 │
│        Fragment   Taken                                │
│       Avatar ID   4f2a91c07be3d158                     │
│  Related Channels @tginfoen, @telegram, @toncoin       │
╰────────────────────────────────────────────────────────╯

Surface checks
 [+] t.me           telegram    Pavel Durov  (https://t.me/durov)
 [+] Fragment       telegram    @durov is assigned
 [+] Channel feed   telegram    20 recent posts sampled; 7 related handles
 [+] GitHub         cross-plat  https://github.com/durov
 [?] VK             cross-plat  interstitial served to datacenter IP

found 4  not-found 9  inconclusive 1  skipped 0
```

Nothing to configure, no API key, no account. Everything above is public data that Telegram serves to any browser.

---

## Why the naive check is wrong

This is the single fact the whole project is built around:

| Handle | HTTP status | `tgme_page_title` present? | Reality |
|---|---|---|---|
| `durov` | **200** | yes | claimed |
| `zzq9x7v2knotreal4421` | **200** | no | free |

A status-code check reports *both* as found. Sherlock's `errorType: "message"` strategy — look for a sentinel in the body, not at the response line — is the correct tool, and it is what `t.me` demands. Every detection rule here is declared explicitly in a manifest so you can audit it, and `slt selftest` re-verifies each rule against a handle known to exist and one known not to.

---

## What it actually tells you

### 1. Entity classification, not just existence

A claimed handle is a person, a bot, a channel or a group, and the difference decides your next move. The `t.me` page discriminates all four, and the tool reads all four:

| Signal | Means |
|---|---|
| `N subscribers` | channel |
| `N members, M online` | group |
| action button says *Start Bot* | bot |
| action button says *Send Message* | user |

### 2. Ownership history via Fragment

[Fragment](https://fragment.com) is Telegram's official username marketplace and the most under-used Telegram OSINT source there is. Its badge answers what `t.me` cannot:

- **Taken** — assigned to a live account, and an independent corroboration of the `t.me` hit.
- **On auction / For sale** — currently *unassigned and purchasable*. Flagged as an impersonation risk, because whoever buys it inherits the name.
- **Sold** — changed hands on-chain, and the TON transaction is public and pivotable.
- **Unavailable** — Fragment simply does not list it. Reported as **inconclusive**, never as absent.

### 3. Channel behaviour and the forward graph

`t.me/s/<channel>` is Telegram's own server-rendered mirror of a public channel. From the last ~20 posts the tool derives posting cadence, median gap, active UTC hours and busiest weekday — plus the part that matters most, **outbound references**: forwarded-from attributions and inline `t.me` links.

One channel is a data point. Its forward graph is a network. Feed `related_channels` back into the next scan and you map an ecosystem instead of an account.

### 4. Alternate handles

When a primary handle is taken, banned or burned, the replacement is rarely unrelated — it is the same name with a suffix, a separator swap, or a leetspeak substitution. `slt permute` generates candidates **ordered by real-world likelihood**, so `--limit` truncates the long-shots rather than a random slice.

```bash
slt permute johndoe --limit 40
```

### 5. Handle reuse off-platform

The Sherlock crossover: the same string checked against GitHub, GitLab, Keybase, Hacker News, PyPI, npm and more. Keybase is the highest-value pivot in that list, since its profiles self-attest links to other platforms.

---

## Commands

| Command | What it does |
|---|---|
| `slt scan <handle>` | Full recon: `t.me` + Fragment + feed + cross-platform |
| `slt permute <handle>` | Generate and check likely alternate handles |
| `slt channel <handle>` | Deep-dive a public channel's cadence and forward graph |
| `slt phone <number>` | MTProto phone lookup — opt-in, capped, needs credentials |
| `slt surfaces` | List and audit the manifest |
| `slt selftest` | Verify every manifest rule still behaves as declared |

```bash
slt scan durov --all --html report.html   # include negatives, write HTML
slt scan durov --only telegram            # skip cross-platform checks
slt scan a b c --json out.json            # several handles, one report
slt channel durov --md feed.md            # cadence + forward graph
slt permute johndoe --typos --dry-run     # print candidates, check nothing
slt surfaces --category telegram          # audit the detection rules
```

Reports export to **JSON, CSV, Markdown and HTML** — same schema whichever subcommand produced them, so a scan and a permutation sweep are diffable against each other.

### Exit codes

`0` at least one hit · `1` nothing found · `2` bad input or manifest error · `130` interrupted.

---

## `found` / `not_found` / `unknown` are three different things

A surface that rate-limited you has **not** told you the handle is free. Collapsing "no answer" into "no" is how OSINT tools end up asserting things they never observed, so the tool keeps `UNKNOWN` strictly separate from `NOT_FOUND` everywhere: in the model, in the terminal summary, in every export, and in the HTML report's "inconclusive" rows.

Each surface also carries a declared **confidence** (`high` / `medium` / `low`), because a Keybase API answer and a scraped VK interstitial do not deserve equal weight in your notes.

---

## Install

```bash
pipx install sherlock-telegram          # recommended
pip install sherlock-telegram           # or plain pip
pip install "sherlock-telegram[mtproto]"  # adds the optional phone module
```

From source:

```bash
git clone https://github.com/juandresrodca/sherlock-telegram
cd sherlock-telegram
pip install -e ".[dev]"
pytest
```

Runtime dependencies are **`httpx` and `rich`** — nothing else. The CLI is argparse, the parsers are stdlib `re`. That keeps `pipx install` instant and leaves nothing to break on an air-gapped analyst box.

---

## Scope, and one deliberate omission

Everything above is **passive**: public pages, no account, no authentication, nothing that touches the target.

`slt phone` is the exception — the only way to ask Telegram whether a number has an account is MTProto's `contacts.importContacts`, which needs your own credentials and a login. It is quarantined behind an optional dependency, explicit credentials and a typed confirmation, and it **hard-caps at 10 numbers per run** with no file input, no batch mode and no resume state.

That cap is the design, not a missing feature. Looking up the numbers already tied to one investigation is research. Feeding a list through it to discover which strangers have Telegram is bulk enumeration of people who never opted in — so this tool does not do it, and `--yes` will not make it.

Read **[ETHICS.md](ETHICS.md)** before you scan anyone but yourself.

---

## Adding a surface

Adding a site is a JSON edit, not a code change — that is Sherlock's best idea and it is kept intact. Append to [`sherlock_telegram/resources/surfaces.json`](sherlock_telegram/resources/surfaces.json):

```jsonc
{
  "name": "Example",
  "category": "cross-platform",
  "url": "https://example.com/{}",
  "errorType": "message",          // status_code | message | response_url | regex
  "errorMsg": ["User not found"],
  "confidence": "high",
  "usernameClaimed": "someone_real",     // slt selftest asserts FOUND
  "usernameUnclaimed": "zzq9x7v2knotreal4421"  // ...and NOT_FOUND
}
```

Then prove it works:

```bash
slt selftest --site Example
```

A surface that reports FOUND for a handle nobody registered is worse than a broken one — it quietly poisons every report. `selftest` is what stops that, and CI runs it. Full field reference in **[CONTRIBUTING.md](CONTRIBUTING.md)**.

---

## Prior art

- **[Sherlock](https://github.com/sherlock-project/sherlock)** — the manifest-driven, `errorType`-based methodology this project ports to Telegram.
- **[whatsapp-scrapping-tool](https://github.com/eduair94/whatsapp-scrapping-tool)** — the messenger-recon project that prompted this one. Its bulk-verification model is intentionally *not* reproduced; see the omission above.

## License

MIT — see [LICENSE](LICENSE).
