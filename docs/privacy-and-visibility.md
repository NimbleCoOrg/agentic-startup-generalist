# Privacy and Visibility

Two different questions get conflated under "privacy," and this package treats
them as separate problems with separate machinery:

1. **Repository visibility** — what the package *source* shows the world.
   Governed by this repo being public, the `.gitignore` instance overlay, and
   the sanitization gate.
2. **Cross-user visibility inside a running harness** — what one user, chat,
   or tenant of a shared deployment can see about *another's* context.
   Governed by the glocal scoping model in `hermes-agent-mt` + Swarm Map.

Getting Level 1 right does nothing for Level 2, and vice versa. Read both
before you deploy agentic-startup-generalist for more than one person.

---

## Level 1 — Repository visibility

### This repository is public

`agentic-startup-generalist` is a public, MIT-licensed repository. Anything
committed here is world-readable, permanently, including everything reachable
from its history. Deleting a file in a later commit does not unpublish it.

That single fact is the whole of Level 1, and it produces one operating rule:

> **Venture particulars never enter this tree.** Not in code, not in prose,
> not in a test fixture, not in a commit message.

Two mechanisms enforce it — one structural, one automated — and both are
described below. Neither is a substitute for the rule.

### What must never be committed

**Secrets and credentials.** API keys, tokens, private keys, connection
strings, service-account JSON, session cookies. These belong in `.env`
(gitignored) or the Swarm Map env store, and are injected at runtime. A
committed secret is a burned secret — assume it is compromised the moment it
lands, and rotate it at the provider rather than trying to scrub it from
history.

**Venture particulars.** Founder, team, advisor, investor, or customer names;
company or product names tied to one active venture; revenue, ARR, burn,
runway, valuation, cap-table, or pricing figures; real retention, activation,
or cohort numbers; Notion database IDs, Slack channel or workspace IDs, Linear
or Jira project keys; messaging identifiers tied to a real person; internal
hostnames, tailnet addresses, or deployment targets; codenames that identify
one particular venture.

That list is also the tuning surface for the semantic scanner — see
`sanitize.config.json`.

**Commit messages count.** The gate scans file contents, not commit metadata.
A commit message naming a client is as public as the diff it describes, and
nothing in this repo will catch it. That check is yours.

### Structural privacy: the instance overlay

The first mechanism is structural: the `.gitignore` instance overlay makes
venture data private **by construction** — it cannot be committed, so it
cannot leak through a PR:

```
ventures/*                # per-venture working data
instance/                 # operator-specific skills, souls, config
.overlay/                 # local overrides
.env, .env.*              # keys and secrets
*.pem, *_rsa, *.key
```

Keep live work under the overlay and the gate rarely has anything to catch.

### The sanitization gate

The second mechanism is automated. `scripts/check_sanitization.py` runs two
layers, and they fail differently:

| Layer | Protects against | Mechanism |
|---|---|---|
| Instance overlay (`.gitignore`) | committing venture data at all | structural — git never sees it |
| Deterministic scanner (Layer 1) | secrets/PII that land in tracked files anyway | regex, no deps, **hard fail** |
| Semantic scanner (Layer 2) | use-case particulars in prose/skills/souls | LLM flag → human review |

The gate exists for the cases where discipline slips — a subject name pasted
into a skill, a client identifier in a docstring. See
[CONTRIBUTING.md](../CONTRIBUTING.md) for exactly what runs in CI, and for the
conditions under which the semantic layer is skipped.

Two lanes, deliberately separate:

- **Diff mode** gates contributions — it scans only what a PR touches, so a
  contributor is never blocked on unrelated pre-existing content.
- **Full-tree mode** tends the garden — it audits everything, on a schedule,
  and proposes cleanups as its own PRs.

Run the full-tree scan yourself before publishing anything derived from this
package — a fork, an extracted skill, a downstream repo:

```bash
python scripts/check_sanitization.py --full-tree
# equivalently:
git ls-files | xargs python scripts/check_sanitization.py
```

**Scan history, not just the working tree.** A full-tree scan reads files as
they exist now. Making a repository public publishes its *entire history*, so
if earlier commits predate your sanitization discipline, a clean working tree
tells you nothing about what a reader can recover. Audit the history before you
publish it.

### The inbound trust gate

Visibility cuts both ways: in a commons you also *consume* artifacts other
teams published. The reason that's safe is the gate on the install side, not
trust in the author. When Swarm Map installs an artifact from a git source, it:

1. **Enforces the pin** — fetches exactly the declared tag
   (`git:<org>/<repo>#v0.1.0`); the artifact can't silently change under you
   after review.
2. **Runs a threat-pattern scan** over the artifact body (injection patterns,
   credential exfil shapes) before it reaches any agent.
3. **Optionally checks a declared-capabilities allow-list** — the artifact
   declares what it needs; the deployment decides what it gets.

That is the inbound boundary. Your sanitization gate protects *others* from
your particulars; the trust gate protects *you* from others' artifacts. A
commons needs both directions.

### Branch protection

Because this repo is public, GitHub's branch protection and required status
checks are available on the free plan — use them rather than relying on
convention. On the default branch:

- Require the `sanitization` and `tests` checks to pass before merge.
- Require a pull request, and at least one approving review, before merge.
- Dismiss stale approvals when new commits land.

Until those are configured, the checks still run and are visible on every PR,
but nothing mechanically stops a merge past a red one. The convention-enforced
policy in [CONTRIBUTING.md](../CONTRIBUTING.md) is the fallback: red check =
hard stop, flagged sanitization = human review before merge, no self-merging
unreviewed PRs. Don't pretend convention is enforcement — it works at 2–4
trusted people and degrades from there.

---

## Level 2 — Cross-user visibility inside a running harness

This level only matters if your deployment serves **more than one context** —
multiple Signal/Telegram groups, multiple DM users, multiple tenants — from
one agent. If you run strictly solo, skim the read-floor section and move on.

### The problem

A single Hermes agent process serves many contexts. Without scoping, its
capabilities are global to the process, and context leaks across chats:

- **Skills** load into one process-wide registry and are injected into the
  system prompt uniformly across every chat.
- **The working filesystem** is one directory per process. A dataset
  downloaded while serving group A sits there, reachable while serving
  group B.
- **Structured memory** is the exception — see below.
- **SOUL** is global per agent by design (one identity).

For a venture-oriented package this is concrete: two
ventures served by one agent must not see each other's subjects,
files, or notes.

### The model: a scope ladder

The glocal scoping design (hermes-agent-mt + Swarm Map) is one primitive — **a
scope ladder + role-within-scope + a gated promotion edge + a read floor** —
governing four resource types: skills, structured memory, working
filesystem, SOUL.

```
  global scope        ── deployment-admin owned ──▶ reads inherit DOWN
     ▲                                              writes need role-in-scope
     │  PROMOTION (sanitize → admin-approve)
     │
  context scope       ── members author here ────▶ confined: recurse DOWN, never UP
  (context_id =
   platform:chat_id)

  ════ READ FLOOR (every scope, even admin) ════
  secret-bearing paths are never readable by file tools
```

- Reads inherit down: a context sees `global ∪ its own context`.
- Writes gate by role: members write context-local; only the deployment
  admin writes global.
- Promotion (sanitize → admin approval) is the only context→global edge —
  the same shape as this package's contribute-back gate, one level down.

### What's already scoped: structured memory

`MEMORY.md`/`USER.md` are **already context-scoped** in `hermes-agent-mt` via
`MemoryStore(context_id=…)`: each context reads `contexts/{id}/MEMORY.md`
merged over the global file, path-traversal-sanitized and tested
(`HERMES_MEMORY_SCOPE=channel` is the default). Memory written while serving
one chat does not surface in another.

So the real exposure surface in a multi-context deployment today is **skills
and the working filesystem**, not memory. Plan accordingly.

### The read floor: three layers, stated honestly

The floor stops the "agent reads a secret and launders it into a softer
store" class. It is three layers, and **only the third is an actual security
boundary** — the code itself says so (`file_safety.py`: "This is NOT a
security boundary… the agent can still `cat auth.json`"):

| Layer | Where | What it is | Stops a terminal `cat` of a secret? |
|---|---|---|---|
| **L1** — in-process read-deny on secret paths (`.env`, credential stores, service-account JSON, `*.pem`, …) | image | defense-in-depth | No — the terminal tool bypasses file-tool guards |
| **L2** — terminal command guard: secret-read commands (`cat`/`cp`/`base64` of credential paths) route through the approval flow | image | defense-in-depth + approval | At the command layer, via human approval |
| **L3** — secret not in the agent's mount at all (Swarm Map compose / secret provisioning) | Swarm Map | **the real boundary** | Yes — you can't read what isn't there |

An in-process deny is bypassable by anything running as the same OS user.
L1/L2 raise the cost and create an approval checkpoint; L3 is the only layer
that *removes the capability*. Don't describe L1/L2 as isolation in your own
docs.

### Phase status (as of 2026-06)

Be clear with your team about what's live versus designed:

| Piece | Status |
|---|---|
| Context-scoped structured memory (`MemoryStore(context_id=)`) | **Shipped** in hermes-agent-mt |
| Read floor L1 + L2 (Phase 0) | **Shipped** in the hermes-agent-mt image |
| L3 — secrets out of the agent mount (Phase 0b) | Designed / in progress |
| Per-context skills + working-fs confinement (Phase 1) | Designed / in progress |
| Swarm Map policy plane — roles, promotion workflow (Phase 2) | Designed / in progress |

Until Phase 1 lands, skills and working files are shared across contexts on
a single deployment. If that's unacceptable for your domain (it usually is
for anything client- or subject-sensitive), run one deployment per context.

### Practical guidance for instantiators

If you run multi-tenant — multiple users or contexts on one deployment:

- **Keep per-venture data under the ignored overlay**
  (`ventures/`, `instance/`). It stays off the shared repo *and*
  gives you one obvious root to confine per-context once Phase 1 lands.
- **Rely on `context_id` memory scoping** — it works today. Don't build a
  parallel memory mechanism that bypasses it.
- **Don't mount shared secrets into the agent namespace.** Anything mounted
  readable is one approval (L2) or one guard gap away from agent-readable.
  Inject per-context credentials at the narrowest scope your setup allows;
  this is L3 thinking applied now, by hand.
- **Don't put venture particulars in skills.** Skills are currently
  process-global *and* they're package-shaped — particulars in a skill leak
  both across contexts (Level 2) and into this public repo (Level 1).

---

## Deciding your posture

Level 1 is settled for this repository: it is public, and particulars stay
out. What's left to decide is how you run *your* deployment.

| | **Solo** | **Team** | **Multi-tenant** |
|---|---|---|---|
| **What it is** | One operator, one venture, one agent | A few trusted people contributing to a shared instance | One deployment serving multiple chats, users, or ventures |
| **Sanitization gate** | Run it anyway — free discipline, and it keeps your work publishable | Required on every PR; turn on branch protection so it's enforced rather than conventional | Required, plus `--require-semantic` in CI so the gate can't report clean while doing half its job |
| **Cross-user scoping** | Not applicable; still honor the read floor (don't mount secrets you don't need) | Matters as soon as one deployment serves multiple chats: overlay + `context_id` memory scoping today | Overlay + `context_id` scoping today; **one deployment per context** if skills or working files must not be shared, since Phase 1 hasn't shipped |
| **Inbound artifacts** | Pin every install to a tag | Pin, and review the artifact body before enabling it | Pin, review, and prefer a declared-capabilities allow-list |

Move rightward when the deployment actually serves more people — and let the
gate and the overlay, not vigilance, be what makes that safe.
