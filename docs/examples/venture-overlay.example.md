---
name: startup-generalist-<venture-slug>
description: Private per-venture overlay for <Venture Name>. Standing orders, bindings, and particulars for this one venture. NEVER committed to the shared package.
version: 0.1.0
---

<!--
  HOW TO USE THIS FILE
  ────────────────────
  1. Copy it to:  $HERMES_HOME/skills/startup-generalist-<venture-slug>.md
  2. Replace every <placeholder>.
  3. It is auto-discovered by Hermes (any skill named startup-generalist-*
     in HERMES_HOME/skills/ loads alongside the shared skill) and is gitignored —
     it never enters the shared package. The sanitization gate is your backstop if
     you ever put a real id in a *committed* file by mistake.

  This file is the RIGHT place for the particulars the shared package must never hold:
  the founder, the current bet, source page ids, tracker ids, who routes where.
-->

# <Venture Name> — standing orders

**Founder:** <name>  ·  **Stage (your honest read):** <idea | mvp | launch | scale>
**Current bet:** <the one hypothesis the venture is testing right now>
**Working measurement floor:** core action = <…>; activation = <…>; retention horizon = <…>

## Meeting source

- **Source:** `<notion | pasted | file | your-registered-remote>`
- **If notion:** transcripts parent page `<page-id>` (one child page per meeting);
  read-scoped `NOTION_API_KEY` in the env store. The pipeline reads transcripts out
  and never writes back into the notes system.
- **If a remote reader:** registered source name `<name>`, connector + scope `<…>`.
- **Fallback:** paste a transcript via the `pasted` source anytime; the pipeline is identical.

## Task surfaces (routing)

Use the routing config in `docs/examples/routing.config.example.json` as the template.
For this venture:

- **Tasks/commitments →** `<markdown | board | external>`
  (if external: tracker `<which>`, id `<database/team/project id>`, property map `<…>`)
- **Warm updates (decisions/risks/open questions) →** `board` at
  `<abs path to the tended board .md>`
- **Per-person overrides:** `<person → surface, if any>`
- **Unattended runs →** the `is_inbox: true` triage lane at `<abs path>`. Never point the
  automation at a live board.

## Env (in .env / HSM env store — NOT here as values)

- `NOTION_API_KEY` — <where it lives, if the notion source or an external Notion surface is used>
- `<YOUR_TRACKER_TOKEN_ENV_VAR>` — <where it lives, if an external surface is used>

## Standing gate notes

- Anything that spends money, merges to a default branch, or reaches a customer/investor
  is a propose-and-stop for this venture. Named exceptions (if the founder has granted
  any standing authorization): <list them explicitly, or "none">.
