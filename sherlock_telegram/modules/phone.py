"""Phone-number lookup via MTProto (optional, opt-in, rate-capped).

Telegram exposes no public web endpoint for "does this number have an account".
The only way to ask is MTProto's ``contacts.importContacts``, which needs your
own API credentials and a logged-in session. That makes this the one module
here that is *authenticated* rather than passive, so it is quarantined behind
an extra dependency (``pip install "sherlock-telegram[mtproto]"``), explicit
credentials, and a typed confirmation.

**Deliberately single-subject.** The reference WhatsApp tooling this project
draws from is built for bulk — 100k numbers, resumable batches. That capability
is not reproduced here, and the omission is the design, not a gap:

* ``MAX_NUMBERS_PER_RUN`` is a hard cap of 10, enforced in code.
* There is no file input, no batch mode, and no resume state.
* Every probe adds a contact and then deletes it; the contact list is restored.

Looking up the numbers already tied to one investigation is research. Feeding a
list through it to find out which strangers have Telegram is bulk enumeration
of people who never opted in, and it also gets the account banned. If you need
that, this is the wrong tool.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from typing import Any

from ..core.models import Confidence, EntityType, Finding, Status

MAX_NUMBERS_PER_RUN = 10

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


class MTProtoUnavailable(RuntimeError):
    """Telethon is not installed, or credentials are missing."""


class TooManyNumbers(ValueError):
    """Caller exceeded :data:`MAX_NUMBERS_PER_RUN`."""


def normalise(number: str) -> str:
    """Coerce to E.164. Raises ``ValueError`` if it cannot be made valid."""
    cleaned = re.sub(r"[\s\-().]", "", number.strip())
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned.lstrip("0")
    if not E164_RE.match(cleaned):
        raise ValueError(f"{number!r} is not a valid E.164 phone number (expected e.g. +14155550123)")
    return cleaned


def credentials(
    api_id: str | None = None, api_hash: str | None = None
) -> tuple:
    """Resolve API credentials from arguments or environment."""
    api_id = api_id or os.environ.get("TELEGRAM_API_ID")
    api_hash = api_hash or os.environ.get("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise MTProtoUnavailable(
            "Missing credentials. Create an app at https://my.telegram.org/apps, then set "
            "TELEGRAM_API_ID and TELEGRAM_API_HASH (or pass --api-id/--api-hash)."
        )
    try:
        return int(api_id), api_hash
    except ValueError as exc:
        raise MTProtoUnavailable(f"TELEGRAM_API_ID must be an integer, got {api_id!r}") from exc


def _require_telethon():
    try:
        from telethon import TelegramClient, functions, types  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise MTProtoUnavailable(
            'Telethon is not installed. Run: pip install "sherlock-telegram[mtproto]"'
        ) from exc
    return TelegramClient, functions, types


def _user_attributes(user: Any) -> dict[str, Any]:
    """Extract the public-profile fields MTProto returns for a resolved user."""
    attrs: dict[str, Any] = {"telegram_id": getattr(user, "id", None)}
    for field in ("username", "first_name", "last_name", "phone"):
        value = getattr(user, field, None)
        if value:
            attrs[field] = value
    for flag in ("bot", "verified", "premium", "scam", "fake", "restricted"):
        if getattr(user, flag, False):
            attrs[flag] = True

    status = getattr(user, "status", None)
    if status is not None:
        # Telethon models last-seen as a class name; the granularity Telegram
        # gives depends on the target's privacy settings.
        attrs["last_seen"] = type(status).__name__.replace("UserStatus", "")
        was_online = getattr(status, "was_online", None)
        if was_online is not None:
            attrs["last_seen_at"] = was_online.isoformat()
    return attrs


async def lookup(
    numbers: Sequence[str],
    *,
    api_id: str | None = None,
    api_hash: str | None = None,
    session: str = "sherlock-telegram",
) -> list[Finding]:
    """Resolve phone numbers to Telegram accounts.

    Adds each number as a contact, reads what Telegram returns, then deletes
    the contact again so the account's contact list is left as it was found.
    """
    if len(numbers) > MAX_NUMBERS_PER_RUN:
        raise TooManyNumbers(
            f"This module accepts at most {MAX_NUMBERS_PER_RUN} numbers per run "
            f"(got {len(numbers)}). It is built for investigating one subject, "
            "not for bulk enumeration."
        )

    normalised = [normalise(n) for n in numbers]
    TelegramClient, functions, types = _require_telethon()
    resolved_api_id, resolved_api_hash = credentials(api_id, api_hash)

    findings: list[Finding] = []
    client = TelegramClient(session, resolved_api_id, resolved_api_hash)
    await client.start()  # prompts for login on first run only
    try:
        contacts = [
            types.InputPhoneContact(
                client_id=index, phone=number, first_name=f"probe{index}", last_name=""
            )
            for index, number in enumerate(normalised)
        ]
        result = await client(functions.contacts.ImportContactsRequest(contacts))
        by_client_id = {imported.client_id: imported.user_id for imported in result.imported}
        users = {user.id: user for user in result.users}

        imported_ids = []
        for index, number in enumerate(normalised):
            user_id = by_client_id.get(index)
            if user_id is None:
                findings.append(
                    Finding(
                        surface="MTProto phone",
                        category="phone",
                        url="",
                        status=Status.NOT_FOUND,
                        confidence=Confidence.HIGH,
                        title=number,
                        description="No Telegram account, or the owner hides their number.",
                        attributes={"phone": number},
                    )
                )
                continue

            imported_ids.append(user_id)
            user = users.get(user_id)
            attrs = _user_attributes(user) if user else {"telegram_id": user_id}
            attrs["phone"] = number
            username = attrs.get("username")

            findings.append(
                Finding(
                    surface="MTProto phone",
                    category="phone",
                    url=f"https://t.me/{username}" if username else "",
                    status=Status.FOUND,
                    confidence=Confidence.HIGH,
                    entity_type=EntityType.BOT if attrs.get("bot") else EntityType.USER,
                    title=" ".join(
                        p for p in (attrs.get("first_name"), attrs.get("last_name")) if p
                    )
                    or number,
                    description=f"@{username}" if username else "Account has no public handle.",
                    attributes=attrs,
                )
            )

        # Always tidy up, even though the caller may never look at the account.
        if imported_ids:
            await client(functions.contacts.DeleteContactsRequest(id=imported_ids))
    finally:
        await client.disconnect()

    return findings
