# agentic-startup-generalist

A generalist operator for an early-stage venture, packaged as a Hermes agent — runnable
standalone or managed via Swarm Map.

In a venture with no specialists and no slack, this agent closes open loops: it researches,
gathers and assesses evidence for product-market-fit questions, turns meetings into tracked
work, keeps the board and the cadence honest, and supports the founder directly. Its job
is not to make the consequential calls — it is to arrive at each call with the evidence
assembled, the options framed, and the tradeoffs named, so a human can decide in five minutes
what would otherwise take a week.

The methodology it runs is a single lifecycle applied to every unit of work, from a two-hour
research question to a six-week PMF experiment:

```
FRAME → GATHER → ASSESS → RECOMMEND → HANDOFF
```

`RECOMMEND` is the phase that defines the agent and the one most likely to be skipped under
pressure — it frames a gated decision for a human instead of walking through it. Per-duty
skills (PMF; turning meeting transcripts into warm updates and candidate tasks) extend this
spine and are added as they earn their place.

---

## Open-core

The whole self-hostable package — the methodology skill, the core tools, and the agent's
soul — is free and public. Run it yourself with your own keys and Docker via Swarm Map. The hosted,
managed agent and premium skills are the paid tier; nothing here is crippled to sell the
upgrade. If you want to run it yourself, everything you need is in this repository.

---

## Multiplayer by design

This package targets [**hermes-agent-mt**](https://github.com/NimbleCoOrg/hermes-agent-mt) —
the multi-tenant Hermes runtime — not a single-user harness. One deployment can serve many
users and contexts (Signal DMs, group chats, tenants) at once, which is the whole reason the
privacy model has two levels rather than one: what your *repository* shows the world, and what
one *user* of a running deployment can see of another. The instance overlay, the sanitization
gate, and the glocal cross-context read floor are all here because multiplayer is the default,
not an afterthought. If you only ever run one venture against one agent, this still works — you
just won't need half of it. See [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md).

The package layer itself is runtime-agnostic (a plugin + a skill + a soul + an optional
engine), but the scaffolding — base image, instance bootstrap, Swarm Map consumption — assumes the
`hermes-agent-mt` image as its base. See [docs/onboarding.md](docs/onboarding.md).

---

## Two ways to run

**Standalone** — clone the repo, mount `hermes-plugin/` into an existing Hermes instance, and
start the agent. See [docs/onboarding.md](docs/onboarding.md).

**Swarm Map-managed** — register the package in Swarm Map, which handles image builds, env injection, and
lifecycle. See [docs/onboarding.md](docs/onboarding.md#b-run-it-through-swarm-map).

Once source and surface are bound, the transcript → task pipeline runs on its own; see
[docs/transcript-pipeline.md](docs/transcript-pipeline.md).

---

## What you get

- **The methodology skill** — `hermes-skill/SKILL.md` encodes the `FRAME → GATHER → ASSESS →
  RECOMMEND → HANDOFF` spine, with per-duty extensions for PMF and the transcript pipeline.
- **The agent's soul** — `docker/SOUL.template.md` carries the standing disposition:
  evidence over assertion, stage honesty, frame-the-gate-don't-walk-through-it, and the
  action policy that divides "drive freely" from "propose; a human disposes."
  `docs/examples/SOUL.example.md` is a filled-in example for one concrete persona.
- **A transcript → task pipeline** — turn meeting transcripts into warm updates and candidate
  tasks on whatever surface a venture uses (a markdown file, a tended board, or any external
  tracker via a config-declared adapter), with an inbox-lane safety property so automation
  never writes to a live board unattended. Sources are pluggable too: paste text, read a
  file, read a Notion page, or inject a reader for any remote system.
- **`hermes-plugin/` tools** — seven real tools exposing the engine to the agent: transcript
  fetch and task routing, the stage-honest PMF read, retention-curve reading, experiment
  falsifiability checks, positioning drafts, and decision framing.
- **Two-layer sanitization gate** — deterministic regex (secrets, PII, API keys) as a
  hard-fail floor; an LLM-semantic scan for venture particulars routed to human review.
  The deterministic layer runs on every PR diff. The semantic layer needs
  `ANTHROPIC_API_KEY`, which GitHub does not expose to PRs from forks — so on a fork PR
  it cannot run, and the gate reports deterministic-only coverage instead of claiming a
  full pass. On same-repo PRs the gate runs with `--require-semantic` and fails closed if
  the key is missing. See [CONTRIBUTING.md](CONTRIBUTING.md#sanitization).
- **Instance-overlay `.gitignore`** — `ventures/`, `instance/`, `.overlay/`, and `.env` are
  kept out of the shared package by construction, so a venture's operational data is not
  committed by accident. It is a default, not a seal: `git add -f` overrides any ignore rule,
  which is why the sanitization gate below exists as the second half of the model.
- **CI workflow** — `.github/workflows/sanitization.yml` runs the test suite, the scanner
  self-tests, and the diff-mode gate on every PR — plus a `release-audit` job on every `v*`
  tag that scans the **whole tree** with the semantic layer mandatory. A release is not a
  diff, so the PR gate cannot cover it.

---

## The model

```
run privately under operational pressure
  → generalize + sanitize
  → contribute through the gate
```

You build under real conditions in your private instance. When a capability proves itself
generic, you strip the particulars, run the gate, and open a PR. The gate catches what you
missed. A maintainer makes the final call. That loop — not upfront design — is how the shared
package stays both useful and clean.

---

## Layout

| Path | What it's for | Customize? |
|------|---------------|-----------|
| `engine/` | Domain logic: transcript sources, task surfaces, routing, pipeline types | Yes — the core |
| `example-collectors/` | Example data-source integrations; copy and adapt | Yes — add real collectors here |
| `hermes-plugin/` | Plugin `register()` + tool definitions for the agent | Yes — expose the engine as agent tools |
| `hermes-skill/SKILL.md` | Agent methodology: how to reason, grade sources, iterate | Yes — the reasoning patterns |
| `docker/SOUL.template.md` | Agent identity / soul (seeded by `instance-setup.sh`) | Yes — set role, defaults, tone |
| `docs/examples/SOUL.example.md` | Filled-in soul example (one concrete persona) | Copy/adapt — not wired |
| `docker/Dockerfile` | System-level deps for the agent image | Only if you need system deps |
| `ventures/` | Per-venture working data — gitignored, stays local | N/A — ignored by construction |
| `instance/` `.overlay/` | Operator-local overrides, instance-specific config | N/A — ignored by construction |
| `scripts/check_sanitization.py` | The sanitization gate — runs in CI and via gardener | No — leave alone |
| `.github/workflows/sanitization.yml` | CI gate | No — leave alone |
| `.gitignore` | Instance-overlay privacy model | No — leave alone |
| `sanitize.config.json` | **The one tuning surface** — teach the gate your venture's particulars | Yes |

---

## Privacy

A venture's operational data is private by construction (`.gitignore`) and by automated scan
(the sanitization gate). See [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the three ways to add a capability and the
sanitization workflow.

When a capability is ready to promote from your private instance back to this shared package,
see [docs/promotion-and-upstream.md](docs/promotion-and-upstream.md).

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 NimbleCo.
