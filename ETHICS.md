# Scope and ethics

This tool collects **public** information about Telegram identities. That is a legitimate and well-established activity — journalists verify sources with it, trust-and-safety teams trace scam networks with it, security teams check their own brand's exposure with it, and researchers map disinformation ecosystems with it.

It is also a tool that points at people. This document is about where the line sits.

---

## What the tool does by default

Every default-enabled surface is **passive**: it requests a page that Telegram, Fragment or a third-party site serves to any anonymous browser. No account, no authentication, no interaction with the subject, nothing written anywhere.

You are not "hacking" anything by running `slt scan`. You are reading a public profile page faster than you could by hand.

## What this tool will not do

**Bulk phone-number enumeration.** The messenger-recon tool that inspired this project verifies numbers in bulk — 100k at a time, resumable, batched from a spreadsheet. That capability is deliberately absent here.

`slt phone` hard-caps at **10 numbers per run**, has no file input, no batch mode and no resume state. The cap is enforced in code before credentials are even read, so no flag or config raises it.

The distinction is about consent, not volume:

- Resolving the two numbers already tied to a subject you are investigating is **research**.
- Feeding a list of numbers through it to learn which strangers have Telegram is **enumeration of people who never opted in**. It is a privacy harm regardless of who runs it, and in many jurisdictions it is also unlawful processing.

If you need the second thing, this is the wrong tool, and no issue asking for a `--bulk` flag will be accepted.

**Anything that requires deceiving the subject.** No joining private groups under a pretext, no messaging targets, no scraping member lists of groups you were not invited to.

---

## The one authenticated module

`slt phone` is the exception to "passive by default", and it is quarantined accordingly: an optional dependency, your own API credentials, and a typed confirmation prompt.

Before you run it, know what it does:

- It authenticates **as you**. Anything it does is attributable to your account.
- It **temporarily adds each number to your contact list**, reads what Telegram returns, then deletes the contact. If the process dies mid-run, a contact may be left behind.
- Telegram bans accounts for contact-import abuse. Use a research account you can afford to lose, never your primary.
- A negative result means "no account, **or** the owner hides their number." It is not proof of absence.

---

## Before you scan someone

Ask yourself three questions:

1. **Do I have a lawful basis?** Curiosity is not one. Under GDPR and similar regimes, "it was publicly available" is not by itself a legal basis for processing personal data — you still need legitimate interest, and you still owe data minimisation.
2. **Would I be comfortable explaining this scan to the person?** If the honest answer involves hoping they never find out, stop.
3. **Am I about to publish a conclusion the evidence does not support?** See below.

## Read your results honestly

The tool separates `found`, `not_found` and `unknown` because they are three different claims, and it will not collapse them for you:

- `unknown` means the surface **did not answer** — it was rate-limited, blocked, or broken. It is not a negative.
- A **handle match is not an identity match.** Two people can hold the same string on two platforms; squatters register names deliberately. A GitHub account with the same handle is a *lead*, not a link.
- **Avatar and cadence data are circumstantial.** They generate hypotheses. They do not confirm them.
- Findings are a **snapshot**. Handles get sold, renamed and abandoned; the `Sold` status exists precisely because the person behind a name can change.

Every export carries this warning in its footer for a reason. If you publish or act on a finding, publish the uncertainty with it.

---

## Situations where you should not use this tool

- Locating, monitoring or harassing an individual — including an ex-partner, a critic, or an anonymous account whose author does not want to be identified.
- Building a dataset of people for resale, marketing, or credential-stuffing target lists.
- Deanonymising activists, dissidents, journalists or whistleblowers. Telegram is a lifeline in repressive contexts, and this tooling works just as well against people it should not be pointed at.
- Any use where being wrong would hurt someone and you cannot verify the conclusion independently.

## Reporting a problem

If this project is being used against you, or you believe a surface in the manifest exposes data it should not, open an issue. Surfaces can be disabled, and entries have been removed before for producing conclusions they could not support.

**You are responsible for what you point this at.** The licence disclaims warranty; it does not disclaim your judgement.
