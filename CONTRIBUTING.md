# Contributing to agentic-startup-generalist

> New here? Read [docs/onboarding.md](docs/onboarding.md) first — the one-sitting
> tour of the layout and the one rule that matters most. This file is the
> detailed reference.

`agentic-startup-generalist` is the shared, generic early-stage startup operations
capability package — plugins, skills, tools, and the agent's base soul. Operators run
private instances on top of it; those instances keep their own working data and
venture particulars, which never live here. Anything you commit here ships to every
instance that tracks this package.

## The one rule

**Never commit venture particulars.** Names of subjects, clients, targets,
document IDs, venture codenames, datasets, or anything tied to a specific
venture belong in the operator's private instance — not here. The `.gitignore`
enforces the structural half of this model (`ventures/`, `instance/`, `.overlay/`
are all gitignored). The sanitization gate enforces the other half on every PR.

If a change only needs an API key, **you do not edit this repo** — the operator adds
the key in Swarm Map or their `.env`. That is a runtime concern, not a code change.

## Three ways to add a capability

| You want to…          | Where it goes                                    | How it ships                                     |
|-----------------------|--------------------------------------------------|--------------------------------------------------|
| Add an **API key**    | operator's Swarm Map env or `.env`                     | injected at runtime — **not a code change**      |
| Add a **tool/skill**  | `hermes-plugin/` or `hermes-skill/`              | merged here → instances pull + restart           |
| Add a **system binary** (a domain CLI tool, …) | `docker/Dockerfile` | image rebuild + redeploy (operator action) |

When in doubt, reach for `hermes-plugin/` over the Dockerfile. An image rebuild
requires a coordinated operator action across all deployed instances; a plugin pull is
just `git pull` + restart.

## Promotion flow

1. Branch from `main`.
2. Make your change. Add tests for new behavior (`python -m pytest tests/ -v`).
   Install dev deps first: `pip install pytest anthropic` — the engine itself is
   stdlib-only, `pytest` runs the suite, and `anthropic` is needed only by the
   sanitization gate's semantic layer.
3. Open a PR against `main`.
4. Both the `tests` check and the `sanitization` check must pass (or be explicitly
   cleared — see merge policy below).
5. A maintainer reviews and merges. Do not merge your own PR unreviewed.

## Sanitization

Every PR that touches `hermes-skill/`, `hermes-plugin/`, `docker/SOUL*`, `docs/`, or
top-level markdown files is scanned automatically by `scripts/check_sanitization.py`.
The scanner has two layers:

**Layer 1 — deterministic (no deps, fails closed):** regex patterns for credentials
and PII (API keys, private keys, email addresses, phone numbers, non-local IP
addresses). A hit here is a hard stop — the check fails and the PR cannot proceed
until the content is removed.

**Layer 2 — semantic (LLM-backed, advisory):** an LLM prompt, configured in
`sanitize.config.json`, asks whether the diff contains venture particulars. A
flag is **not** an automatic rejection — it routes the PR to a human maintainer who
makes the call. If your PR is flagged and you believe it's clean, say so in the PR
description; a maintainer reviews the flagged content and decides.

The semantic layer needs `ANTHROPIC_API_KEY`, and this is where the gate's coverage is
**not uniform**. Read this before you trust a green check:

| PR origin | Deterministic layer | Semantic layer |
|---|---|---|
| Same-repo branch | Runs, hard-fails on any hit | Runs, and the gate uses `--require-semantic` so a missing key exits non-zero instead of passing |
| **Fork** | Runs, hard-fails on any hit | **Cannot run** — GitHub does not expose repository secrets to `pull_request` runs from forks |

So on a fork PR, a green `sanitization` check means "no secrets or PII found". It does
**not** mean "no venture particulars found" — nothing checked for those. The workflow
emits a warning annotation saying so, and a maintainer must review the diff for
particulars by hand before merging. Closing that gap requires switching the trigger to
`pull_request_target`, which is a deliberate security decision (it exposes the key to a
workflow running alongside untrusted PR code) and is intentionally not enabled — see the
security note at the top of `.github/workflows/sanitization.yml`.

Locally, the gate skips the semantic layer with a loud warning when no key is set, and
labels its own output deterministic-only, so offline runs work without pretending to be
a full pass. Pass `--require-semantic` to make a missing key an error instead.

To tune what counts as a particular for this domain, edit `sanitize.config.json` —
that is the single configuration surface for the gate. See the inline comments in that
file.

## Merge policy

This repository is public, so GitHub branch protection and required status checks are
available and **should** be turned on — see
[docs/privacy-and-visibility.md](docs/privacy-and-visibility.md#branch-protection) for the
recommended settings. Until they are configured these rules hold by **convention only**:
the `tests` and `sanitization` checks run and are visible on every PR, but nothing
mechanically blocks a merge past a red one. Either way:

- **Red `tests` = hard stop.** Do not merge until the suite is green.
- **Deterministic SECRET/PII hit = hard stop.** Remove the flagged content; there is
  no override path.
- **Semantic FLAG = human review required.** A maintainer must inspect the flagged
  content and approve before merge. The flag is advisory; the human is the authority.
- **Do not merge your own PR unreviewed.** Wait for a maintainer's explicit approval.
- **Fork PR = review particulars by hand.** The semantic layer cannot run on fork PRs,
  so a green check does not cover venture particulars. See
  [Sanitization](#sanitization) above.

Configure branch protection to make the first two hard-enforced rather than conventional —
do it before adding contributors you haven't worked with.

## Adding a capability — worked examples

### API key only

The operator needs to call a new third-party service. No code change is needed here.
The operator adds the key to Swarm Map under the agent's environment config (or to their
`.env` for local development). The tool code that reads the key may already exist, or
it gets added as a plugin (see below) — but the key value itself is never committed.

### New tool/skill

Create the tool in `hermes-plugin/` following the existing plugin conventions, or add
a skill document to `hermes-skill/`. Open a PR. Once merged, operators pull the update
and restart their agent. No image rebuild required.

### New system binary

Add the install step to `docker/Dockerfile`. Document why the binary
is needed and what capability it unlocks. Once merged, operators rebuild the image
(`docker build`) and redeploy — this is a coordinated operator action, so minimize
these changes and batch them when possible.

## Promoting to your own package or upstream to Swarm Map

If your work generalizes beyond this package — a plugin pattern that any Hermes agent
could use, a sanitization improvement, a workflow change — see
[docs/promotion-and-upstream.md](docs/promotion-and-upstream.md) for the promotion
flow: how to extract and sanitize work from your private instance into a publishable
form, and how to submit upstream to the Swarm Map base.
