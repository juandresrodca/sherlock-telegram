"""Handle permutation engine — finding the accounts next door.

Sherlock has ``{?}`` for trying separator variants. This generalises that into
the pattern investigators actually see: when someone's primary handle is taken,
banned, or burned, the replacement is rarely unrelated. It is the same name
with a suffix, a separator swap, a doubled letter, or a leetspeak substitution.

Generation is **ordered by likelihood, not by rule** — separator and suffix
variants come before leetspeak, because that is the order real alts appear in.
That ordering is what makes ``--limit`` useful: truncating the list drops the
long-shots first.

Everything here is pure string work. Nothing is checked until the caller feeds
the output to the scanner, and Telegram's own handle rules are applied at the
end so the scanner never wastes a request on a handle that cannot exist.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

# Telegram: 5-32 chars, [A-Za-z0-9_], must start with a letter, cannot end with
# an underscore, and no two underscores in a row.
_VALID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]$|^[A-Za-z][A-Za-z0-9]{3,31}$")
_DOUBLE_US_RE = re.compile(r"__")

DEFAULT_SUFFIXES: Sequence[str] = (
    "1", "2", "01", "07", "77", "99", "123", "2024", "2025", "2026",
    "_", "x", "xx", "z", "official", "real", "the", "its", "im",
    "bot", "news", "chat", "group", "channel", "backup", "alt", "new", "old", "vip", "pro", "hq",
)

DEFAULT_PREFIXES: Sequence[str] = ("the", "real", "official", "its", "im", "mr", "its_", "real_")

_LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7", "b": "8", "g": "9"}


def is_valid_handle(handle: str) -> bool:
    """Enforce Telegram's public-username rules."""
    if not 5 <= len(handle) <= 32:
        return False
    if _DOUBLE_US_RE.search(handle):
        return False
    return _VALID_RE.match(handle) is not None


def _separator_variants(base: str) -> list[str]:
    """Swap between ``snake_case``, ``flatcase`` and split-word forms."""
    out = [base.replace("_", ""), base.replace("_", "_")]
    # camelCase / PascalCase -> snake_case, and the reverse.
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", base).lower()
    out.append(snake)
    if "_" in base:
        parts = [p for p in base.split("_") if p]
        out.append("".join(p.capitalize() for p in parts))
        out.append(parts[0] if parts else base)
    return out


def _leet_variants(base: str) -> list[str]:
    """One substitution at a time — full leetspeak explodes and rarely hits."""
    out = []
    lowered = base.lower()
    for char, replacement in _LEET.items():
        if char in lowered:
            out.append(lowered.replace(char, replacement, 1))
            if lowered.count(char) > 1:
                out.append(lowered.replace(char, replacement))
    return out


def _typo_variants(base: str) -> list[str]:
    """Doubled and dropped characters — cheap, and how squatters register."""
    out = []
    for i, char in enumerate(base):
        if char.isalpha():
            out.append(base[:i] + char + base[i:])
    for i in range(len(base)):
        candidate = base[:i] + base[i + 1 :]
        if len(candidate) >= 5:
            out.append(candidate)
    return out


def generate(
    base: str,
    *,
    suffixes: Iterable[str] | None = None,
    prefixes: Iterable[str] | None = None,
    leet: bool = True,
    typos: bool = False,
    limit: int | None = 60,
) -> list[str]:
    """Return likely alternate handles for ``base``, most-plausible first.

    The base handle itself is always excluded — the caller has already checked
    it. ``typos`` is off by default because transposition variants generate a
    lot of noise for a low hit rate; turn it on when hunting impersonators
    rather than alts.
    """
    base = base.strip().lstrip("@")
    if not base:
        return []

    suffix_list = list(suffixes) if suffixes is not None else list(DEFAULT_SUFFIXES)
    prefix_list = list(prefixes) if prefixes is not None else list(DEFAULT_PREFIXES)

    # Ordered by empirical likelihood; dedup below preserves this priority.
    candidates: list[str] = []
    candidates += _separator_variants(base)
    for suffix in suffix_list:
        candidates.append(f"{base}{suffix}")
        candidates.append(f"{base}_{suffix}")
    for prefix in prefix_list:
        candidates.append(f"{prefix}{base}")
        candidates.append(f"{prefix}_{base}")
    if leet:
        candidates += _leet_variants(base)
    if typos:
        candidates += _typo_variants(base)

    seen = {base.lower()}
    out: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen or not is_valid_handle(candidate):
            continue
        seen.add(key)
        out.append(candidate)
        if limit is not None and len(out) >= limit:
            break
    return out
