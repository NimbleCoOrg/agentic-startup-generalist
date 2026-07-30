---
name: startup-generalist-transcript
description: Turn any transcript or note into warm updates and candidate tasks on whatever surface the team already uses — source-agnostic ingestion, disciplined extraction, provenance you can trace back, and a human gate before anything lands on a live board. Use when asked to process a meeting, pull tasks out of a call, keep the board current from what was said, or wire a transcript source to a task surface.
version: 0.1.0
author: NimbleCo
license: MIT
metadata:
  hermes:
    tags: [meetings, transcripts, tasks, operations, cadence, surface-agnostic]
    related_skills:
      - startup-generalist-methodology
---

# Meetings into Motion: Transcripts to Warm Updates and Candidate Tasks

Most of what a startup decides is decided out loud, in a meeting, and then lost — the
commitment nobody wrote down, the risk someone named that never became a ticket, the
decision that gets relitigated three weeks later because no record survived the call. A
transcript is the raw material for closing that gap. This skill is the discipline for
turning it into motion **on the surface the team already looks at**, without inventing
work that was never agreed to.

It backs the duty's tools — `sg_fetch_transcript` (the SOURCE binding) and
`sg_route_tasks` (the SURFACE binding) — but those tools are the edges. The method in the
middle is the point, and it is what this skill owns.

The agent does **not** create tasks on anyone's board unilaterally. It reads the
transcript, extracts what is genuinely there, and frames candidate tasks for a human to
dispose. See the RECOMMEND phase in
[`startup-generalist-methodology`](./SKILL.md) — task emission is a gated action, not a
free one.

## The spine is three replaceable parts

```
  SOURCE            →   EXTRACT             →   SURFACE
  (a transcript)        (this skill)            (where work lives)

  meeting recording     normalize             Linear / GitHub Projects
  a saved note          decisions             a task database
  a call export         commitments           a markdown board / the garden
  a pasted .txt         risks                  whatever this team, or this
                        open questions         person, actually uses
                        tasks
```

The **source** and the **surface** are bindings, not the method. This skill owns only the
middle. **EXTRACT is the agent's job — reading meaning out of loose human talk — not a set
of Python heuristics.** A regex cannot tell a hedge from a commitment or an aside from a
decision; that judgment is the whole value, and it is why this stage lives in the model,
not in the pipeline code around it.

The stage must run identically whether the transcript came from a recording or a block of
text a founder pasted in, and whether the resulting tasks land in Linear, in a GitHub
Project, in a database, or as lines in a markdown file. **If any step of this skill names a
specific product as load-bearing, it is a bug.** The product is resolved from
configuration at the edges; the method in the middle never sees it.

Why this matters beyond tidiness: a team's task surface is a preference, often an
*individual* one — one founder lives in Linear, another in a database, a third in a text
file. A method coupled to one surface serves one team. A method that treats the surface as
a swappable adapter serves all of them, and lets a single person route their own tasks
where they will actually see them.

## What a "warm update" is

A **warm update** is a durable, attention-worthy change surfaced *where the team already
looks*, not buried in an artifact they would have to go find. A transcript produces warm
updates when its salient content — a decision made, a risk raised, a commitment given — is
written into the surface the team monitors, in a form that reads as "this needs you"
rather than "here is a wall of text."

A transcript dumped verbatim into a doc is not a warm update. It is cold storage. The work
of this skill is the conversion: from a recording nobody will re-listen to, into a small
number of items on a live surface that each carry a clear next step and a link back to
where they came from.

## Extraction: the five item kinds

Read the transcript against five kinds. Most of a transcript is none of them — the
discipline is in what you leave out as much as what you pull.

1. **decision** — a choice the group actually settled. Not "we discussed pricing" but "we
   decided to price at $X, starting next month." A decision needs a resolution; a
   discussion that trailed off is an `open_question`, below.
2. **commitment** — someone agreed to do a specific thing. A real commitment has an
   **owner** and, ideally, a **when**. "Someone should look at the auth bug" is not a
   commitment; it is a `task` with no owner — capture it as such, do not manufacture an
   owner.
3. **risk** — something named that could hurt the venture: a dependency, a deadline in
   doubt, a customer wobbling, a security concern. Risks are the most-dropped kind because
   they rarely come with an action attached. Capture them anyway; an unlogged risk is the
   expensive kind.
4. **open_question** — a live disagreement or an unresolved "we need to figure out X."
   These feed FRAME on the next loop; do not resolve them yourself.
5. **task** — the actionable residue. Each is a proposed unit of work, derived from a
   commitment or a decision, phrased as something a person could pick up.

**Two of the five are actionable: `commitment` and `task`.** Those are the kinds that can
become an item on a board. `decision`, `risk`, and `open_question` are surfaced as warm
updates and record — they are not tasks, and turning a risk into a task nobody agreed to is
exactly the fabrication this skill guards against.

For every item, keep the **provenance**: which meeting, roughly where in it, and — for a
commitment — who said it. A task that cannot point back to the moment it came from cannot
be verified, and will be argued with. Provenance is what makes the extraction trustable
rather than a paraphrase you are asking the team to take on faith.

## Extraction honesty

The failure mode here is not missing things. It is **manufacturing** them — turning a
hedge into a commitment, an aside into a decision, a hypothetical into a task. A transcript
invites this because talk is loose and tasks are crisp, and the crispening is where
fabrication sneaks in.

Guardrails:

- **A commitment requires the person to have actually agreed.** "Could you take the deck?"
  "…maybe, let me see" is not a commitment. Attributing one puts words in someone's mouth
  and lands a task on them they never accepted.
- **Do not invent owners or dates.** If the transcript did not name them, the field is
  empty and the human fills it at the gate. An invented due-date is a lie the board will
  then enforce.
- **Prefer under-extraction to over-extraction.** A missed task surfaces again next
  meeting. A fabricated one wastes someone's attention and erodes trust in every item on
  the board beside it.
- **Never resolve an open_question by picking a side.** Surface the disagreement; that is
  the honest artifact.

## Reconcile against the surface: CREATE / UPDATE / COVERED

A meeting mostly revisits live work. Before proposing anything, check each candidate
against what already exists on the target surface and label it with one of three
reconciliation verbs:

- **CREATE** — genuinely new; nothing on the surface covers it. Propose it.
- **UPDATE** — already on the surface, but the meeting moved it (status, owner, a new
  blocker). Propose the change to the existing item, not a new one.
- **COVERED** — already there, unchanged. Reference it; propose nothing.

Skipping this step produces the most common way a transcript pipeline destroys its own
credibility: a board that doubles every item after every meeting until people stop reading
it. These semantics are what let a **recurring** pipeline run after every meeting without
ever doubling the board — reconciliation is not optional polish, it is the difference
between a live surface and a landfill.

## The gated apply: propose, do not populate

Task emission is a **gated action** under the methodology's standing division. Writing to
someone's board is writing to a surface other people depend on and act from — it is a
"human disposes" action, not an "agent drives freely" one.

So the terminal output of this skill is a **proposal**, not a fait accompli:

- The warm updates and candidate tasks, each with its provenance
- Which surface each is proposed for, and why (team default, or a specific person's
  preference)
- The reconciliation verb for each — CREATE, UPDATE, or COVERED
- The owner/date fields the transcript supported, and the ones left blank for a human

Then surface it and let a human confirm before anything is written. An agent that silently
populates a board has not saved anyone effort; it has made the board a thing people now
have to audit rather than trust.

**A live, non-inbox board refuses unattended writes and fails loud.** If the pipeline runs
on a schedule after each meeting, it proposes into a review queue or a clearly-marked
"needs triage" lane — it does not self-approve items into the live board, and if it cannot
reach a human it holds and says so rather than proceeding silently.

The one safe exception is a surface designated as an inbox/triage lane whose entire purpose
is to receive un-triaged candidates for later human disposition. Writing there is writing
to a waiting room, not to the board. Make that designation explicit in configuration; never
assume it.

## Where the surface binding lives

This shared skill names no product. The concrete bindings — *this venture's* recordings
source, *this venture's* task database and its property schema, which person's tasks route
where — live in the operator's private per-venture overlay
(`$HERMES_HOME/skills/startup-generalist-{venture-slug}.md`) and in the plugin's runtime
configuration, never in this file. The sanitization gate backs that boundary: a database
ID or a source folder ID committed here is the kind of leak its semantic layer is tuned
to flag — but that layer cannot run on fork PRs, so it is a backstop and not a guarantee.
See the overlay mechanism in [`SKILL.md`](./SKILL.md), `sanitize.config.json`, and
[CONTRIBUTING.md](../CONTRIBUTING.md#sanitization).

When you add a new source or a new surface, you are adding an **adapter**, not editing this
method. A new transcript source satisfies the source contract (give the pipeline a
normalized transcript: id, timestamp, participants, text, provenance). A new task surface
satisfies the surface contract (accept a normalized task/update, write it, and report what
already exists there for reconciliation). The method above does not change when you do this
— that invariance is the whole design.

## Quality floor

Inherits the methodology's floor, with three additions specific to transcripts:

- **Preserve the raw transcript** with provenance before extracting. The extraction is
  lossy by design; the source must remain recoverable so a disputed item can be checked
  against what was actually said.
- **A transcript is sensitive material.** It contains people speaking candidly. Treat it as
  venture particulars: it belongs in the gitignored working area, never in the shared
  package, and the participant list is PII the sanitization gate will flag.
- **Attribute carefully or not at all.** Getting "who committed to what" wrong is worse
  than leaving it unattributed. When the transcript is ambiguous about who said something,
  say it is ambiguous rather than guessing a name.
