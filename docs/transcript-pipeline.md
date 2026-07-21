# Wiring the transcript → task pipeline

This is the operator's guide to turning meeting transcripts into warm updates and
candidate tasks on whatever surface a venture uses. The *method* is in the
`startup-generalist-transcript` skill; this page is the *plumbing* — how to bind a
transcript source and a task surface for one venture without touching the shared package.

The pipeline is three replaceable parts:

```
  SOURCE            →   EXTRACT             →   SURFACE
  engine/sources.py     the agent (LLM),        engine/surfaces.py
                        via the transcript      + engine/router.py
                        skill
```

Only the **source** and **surface** are per-venture bindings. `EXTRACT` is the agent's
job, driven by the skill, and never changes. If wiring a venture requires editing the
router or the skill, something is wrong — you are meant to edit only config and (for a new
surface/source) add one adapter.

Everything venture-specific below — page ids, database ids, tracker tokens, who routes
where — lives in the operator's private overlay and `.env`, **never** in a committed file.
The sanitization gate blocks a real id committed here.

---

## 1. Bind a SOURCE — where transcripts come from

Four sources ship with the package; two need no credentials at all.

**Zero-credential (always available):**

- `pasted` — the ref *is* the transcript text. A human pastes a transcript and the rest
  of the pipeline is identical. This is the degraded-not-blocked floor.
- `file` — the ref is a local `.txt`/`.md`/`.vtt` path.

**`notion` — the reference concrete binding (read-only).** Many teams' meeting notes and
transcriptions already live in Notion pages (meeting-notes pages, or a "Meeting
Transcriptions" page with one child page per meeting). `NotionTranscriptSource` reads a
page's block tree and returns its text — validated against real timestamped transcript
pages. It needs only a read-scoped integration token:

```bash
# .env (standalone) or the HSM env store — never committed
NOTION_API_KEY=<read-scoped integration token>
```

```python
# ref = the Notion page id of one meeting's transcript page
sg_fetch_transcript({"source": "notion", "ref": "<page-id>",
                     "options": {"meeting_id": "weekly-sync"}})
```

It is read-only **by design**: in deployments where writing to the notes system is a
gated human action, the pipeline reads transcripts out and routes tasks to a board
surface — it never writes back into the source system.

**`RemoteTranscriptSource` — any other remote system.** A generic source that reads
through an **injected reader callable**, so the package hardwires no vendor SDK and no
credential. Wrap whatever connector your deployment has (a Drive/Docs MCP for Google
Meet transcripts, a Zoom API client, an internal service) and register it:

```python
# runtime wiring (deployment glue or venture overlay — NOT the shared package)
from engine.sources import RemoteTranscriptSource, register_source

def my_reader(ref: str) -> dict:
    """Resolve a remote reference to transcript text via your connector."""
    doc = my_connector.fetch(ref)
    return {"text": doc.text, "title": doc.title, "timestamp": doc.modified}

register_source("recorder", RemoteTranscriptSource(my_reader, name="recorder"))
```

---

## 2. Bind a SURFACE — where tasks land

Three surface types are registered; a deployment can register its own beside them.

- **`markdown`** — fully implemented, zero config: writes checkbox lines to a local file.
  The agnostic default, and the natural **inbox/triage lane** (`"is_inbox": true`).
- **`board`** — fully implemented: writes garden-format board lines (`- [ ] text #id`)
  into a board file that some tender maintains — e.g. a gardener process that scans the
  board each cycle and surfaces new items as warm updates. `git_commit: true` commits
  each write so the tender picks it up on its next pull. **No tender code required** —
  writing its format *is* the integration.
- **`external`** — a declared adapter for any external tracker (a Notion database, a
  Linear team, a GitHub Project). It gates on the env var named in its config
  (`credential_env`) and **refuses loudly** until a deployment implements
  `list_existing`/`write` against that tracker's API — never a silent no-op. Implement
  the two methods, keep the `dedup_key` derivation identical to `MarkdownFileWriter`'s
  so reconciliation matches across surfaces, and map `Item.kind/owner/due` to the
  tracker's schema (the schema names are venture config, not code constants).

---

## 3. Routing config — who gets what, where

The `sg_route_tasks` tool takes a routing config that maps items to surfaces. A team
default, per-kind and per-person overrides, and the write gate. See
[`examples/routing.config.example.json`](examples/routing.config.example.json):

```json
{
  "default": "markdown",
  "by_kind":  { "decision": "board", "risk": "board", "open_question": "board" },
  "by_owner": { "<person-slug>": "external" },
  "surfaces": {
    "markdown": { "path": "<abs path to tasks.md>", "is_inbox": true },
    "board":    { "path": "<abs path to the tended board.md>", "git_commit": true },
    "external": { "credential_env": "<YOUR_TRACKER_TOKEN_ENV_VAR>" }
  },
  "allow_live_write": false
}
```

Precedence is **owner → kind → default**:

- `by_owner` — one person's items land on *their* surface. This is how "each team
  member's preference" works: one person lives in an external tracker, another in a
  plain file, without forking the pipeline.
- `by_kind` — actionable work (tasks, commitments) goes one place; informational warm
  updates (decisions, risks, open questions) go another — typically the tended board,
  so whatever tends it surfaces them next cycle.
- `allow_live_write` — leave `false`. With it false, `apply` **refuses** to write to any
  non-inbox surface; the agent proposes and a human disposes. Mark exactly one surface
  `"is_inbox": true` as the triage lane automation may write to unattended.

---

## 4. Running it

The loop, once source and surface are bound:

1. **Fetch** — `sg_fetch_transcript` with `{source, ref}` → normalized transcript text.
2. **Extract** — the agent reads the transcript per the `startup-generalist-transcript`
   skill and produces an `extraction` object: `{meeting, items:[{kind, summary, owner?,
   due?, ...}]}`. This step is the LLM's, not a tool's.
3. **Propose** — `sg_route_tasks` with `{extraction, config, mode:"propose"}` → a
   per-surface proposal (new / update / already-covered), **no writes**.
4. **Dispose** — a human reviews the proposal and confirms.
5. **Apply** — `sg_route_tasks` with `mode:"apply"`. It writes creates/updates and skips
   covered items; it **refuses** a live board unless it's an inbox lane or `allow_live`
   is set.

---

## 5. Automating the "auto-feed"

To feed transcripts automatically after each meeting, schedule a runner on an always-on
host (a gardener-style tender is the natural choice — it is already autonomous and
already maintains the board):

```
poll the source for new transcripts (new pages under the meeting-notes parent,
new files in a folder, ...)
  → sg_fetch_transcript
  → agent extracts per the skill
  → sg_route_tasks mode=apply, into the surface with "is_inbox": true   ← triage lane
  → a human triages the lane into the live board
```

The inbox lane is the safety property: automation writes to a waiting room, never to the
board people act from. That is the skill's "automation fails loud" rule made operational —
do not point an unattended runner at a non-inbox surface.

---

## Where the particulars live

| Thing | Where it goes | Committed? |
|---|---|---|
| Notion page ids, database ids, property names | routing config in the venture overlay / deployment glue | no |
| `NOTION_API_KEY`, tracker tokens | `.env` (standalone) or the HSM env store | no |
| Remote-source refs and connector scope | venture overlay / deployment glue | no |
| Who routes to which surface | `by_owner` / `by_kind` in the routing config | no |
| Adapter code (an implemented external surface) | `engine/surfaces.py` — generic, no ids | **yes** |
| The method | the transcript skill | **yes** |

Copy [`examples/venture-overlay.example.md`](examples/venture-overlay.example.md) to
`$HERMES_HOME/skills/startup-generalist-{venture-slug}.md` and fill it in — that file is
auto-discovered by Hermes, gitignored, and never enters the shared package.
