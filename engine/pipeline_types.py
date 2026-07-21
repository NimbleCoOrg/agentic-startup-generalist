"""Normalized data model for the transcript → tasks pipeline.

These types are the contract between the three replaceable parts of the
pipeline (see ``hermes-skill/startup-generalist-transcript.md``):

    SOURCE  → produces a Transcript
    EXTRACT → (agent/LLM, driven by the skill) produces an Extraction of Items
    SURFACE → consumes Items and writes them where the team looks

Nothing here names a product. A hosted task database, an issue tracker, a
meeting-recording service — those are bindings resolved at the edges
(sources.py / surfaces.py / the deployment overlay), never in this model. Keep
it that way: a product name in this file is a coupling bug.

Stdlib only. No external dependencies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- Item kinds -------------------------------------------------------------
# The five buckets the extraction skill reads a transcript against. Every Item
# carries exactly one. A Surface adapter maps each kind to its own native
# representation (a task → a board card; a decision → a logged note; etc.).

KIND_DECISION = "decision"
KIND_COMMITMENT = "commitment"
KIND_RISK = "risk"
KIND_OPEN_QUESTION = "open_question"
KIND_TASK = "task"

KINDS = (KIND_DECISION, KIND_COMMITMENT, KIND_RISK, KIND_OPEN_QUESTION, KIND_TASK)

# Kinds that represent actionable work a person could pick up. The rest are
# informational warm updates — still written to the surface, but not "to-dos".
ACTIONABLE_KINDS = frozenset({KIND_COMMITMENT, KIND_TASK})


# --- Provenance -------------------------------------------------------------

@dataclass(frozen=True)
class SourceRef:
    """Where an item or transcript came from — enough to trace it back.

    A task that cannot point back to the moment it came from cannot be
    verified, and will be argued with. Provenance is what makes the extraction
    trustable rather than a paraphrase the team must take on faith.
    """

    meeting_id: str
    source: str                       # e.g. "pasted", "file", "remote"
    timestamp: str | None = None      # ISO 8601 of the meeting, if known
    location: str | None = None       # rough position: "~00:12:30", "line 40"

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "location": self.location,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceRef":
        return cls(
            meeting_id=str(d.get("meeting_id", "")),
            source=str(d.get("source", "unknown")),
            timestamp=d.get("timestamp"),
            location=d.get("location"),
        )


# --- Transcript -------------------------------------------------------------

@dataclass
class Transcript:
    """A normalized transcript. Every source produces exactly this shape.

    The source binding (a shared-drive folder, a cloud recording, a pasted blob)
    lives in sources.py; by the time a transcript reaches EXTRACT it is just this.
    """

    meeting_id: str
    source: str
    text: str
    participants: list[str] = field(default_factory=list)
    timestamp: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def ref(self, location: str | None = None) -> SourceRef:
        """A SourceRef pointing at this transcript (optionally a position in it)."""
        return SourceRef(
            meeting_id=self.meeting_id,
            source=self.source,
            timestamp=self.timestamp,
            location=location,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting_id": self.meeting_id,
            "source": self.source,
            "text": self.text,
            "participants": list(self.participants),
            "timestamp": self.timestamp,
            "provenance": dict(self.provenance),
        }


# --- Item -------------------------------------------------------------------

_WS = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[\s.,;:!?\-–—]+$")


def normalize_summary(text: str) -> str:
    """Normalize a summary for stable de-duplication.

    Lowercase, collapse whitespace, strip trailing punctuation. Two items whose
    summaries differ only in casing/spacing/trailing punctuation collide — which
    is what we want for "is this already on the board?".
    """
    t = _WS.sub(" ", (text or "").strip().lower())
    t = _TRAILING_PUNCT.sub("", t)
    return t


@dataclass
class Item:
    """One extracted unit: a decision, commitment, risk, open question, or task.

    ``owner`` and ``due`` are meaningful only for actionable kinds, and are
    ``None`` unless the transcript actually supplied them. Do not invent them —
    an empty field is filled by a human at the gate; an invented one is a lie
    the board will then enforce.
    """

    kind: str
    summary: str                          # one line, the "needs you" headline
    detail: str = ""
    owner: str | None = None              # None = unassigned (transcript silent)
    due: str | None = None                # None = no date in transcript
    provenance: SourceRef | None = None
    labels: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                f"unknown item kind {self.kind!r}; expected one of {KINDS}"
            )

    @property
    def actionable(self) -> bool:
        return self.kind in ACTIONABLE_KINDS

    def dedup_key(self) -> str:
        """Stable key for reconciliation against a surface's existing items."""
        return f"{self.kind}|{normalize_summary(self.summary)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
            "owner": self.owner,
            "due": self.due,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Item":
        prov = d.get("provenance")
        return cls(
            kind=str(d.get("kind", "")),
            summary=str(d.get("summary", "")).strip(),
            detail=str(d.get("detail", "")),
            owner=(d.get("owner") or None),
            due=(d.get("due") or None),
            provenance=SourceRef.from_dict(prov) if isinstance(prov, dict) else None,
            labels=list(d.get("labels", [])),
        )


# --- Extraction -------------------------------------------------------------

@dataclass
class Extraction:
    """The structured residue of one transcript, produced by the EXTRACT step.

    The extraction itself is the agent's (LLM's) job — driven by the transcript
    skill, not by Python heuristics. This container is what the agent hands to
    the router: a meeting ref plus the items it found.
    """

    meeting: SourceRef
    items: list[Item] = field(default_factory=list)

    def of_kind(self, *kinds: str) -> list[Item]:
        return [it for it in self.items if it.kind in kinds]

    def tasks(self) -> list[Item]:
        """Actionable items only (commitments + tasks)."""
        return [it for it in self.items if it.actionable]

    def warm_updates(self) -> list[Item]:
        """Informational items (decisions, risks, open questions)."""
        return [it for it in self.items if not it.actionable]

    def to_dict(self) -> dict[str, Any]:
        return {
            "meeting": self.meeting.to_dict(),
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Extraction":
        """Parse an extraction produced by the skill (LLM JSON output).

        Tolerant of missing provenance on items — it backfills each item's
        provenance from the meeting ref when the item did not carry its own.
        """
        meeting = SourceRef.from_dict(d.get("meeting", {}))
        items: list[Item] = []
        for raw in d.get("items", []):
            item = Item.from_dict(raw)
            if item.provenance is None:
                item = Item(
                    kind=item.kind,
                    summary=item.summary,
                    detail=item.detail,
                    owner=item.owner,
                    due=item.due,
                    provenance=meeting,
                    labels=item.labels,
                )
            items.append(item)
        return cls(meeting=meeting, items=items)


# --- Reconciliation output --------------------------------------------------

ACTION_CREATE = "create"     # genuinely new — propose adding
ACTION_UPDATE = "update"     # already there, but the meeting moved it
ACTION_COVERED = "covered"   # already there, unchanged — reference, don't dupe


@dataclass
class ProposedChange:
    """What the router proposes doing with one item against a surface."""

    item: Item
    action: str                        # ACTION_CREATE | ACTION_UPDATE | ACTION_COVERED
    existing_ref: str | None = None    # surface-native id of the matched item
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "action": self.action,
            "existing_ref": self.existing_ref,
            "reason": self.reason,
        }


@dataclass
class Proposal:
    """The terminal output of a propose run — no writes have happened.

    This is the artifact a human disposes at the gate. ``apply`` (in router.py)
    turns confirmed changes into writes; on its own a Proposal touches nothing.
    """

    surface: str
    changes: list[ProposedChange] = field(default_factory=list)

    def creates(self) -> list[ProposedChange]:
        return [c for c in self.changes if c.action == ACTION_CREATE]

    def updates(self) -> list[ProposedChange]:
        return [c for c in self.changes if c.action == ACTION_UPDATE]

    def covered(self) -> list[ProposedChange]:
        return [c for c in self.changes if c.action == ACTION_COVERED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "summary": {
                "create": len(self.creates()),
                "update": len(self.updates()),
                "covered": len(self.covered()),
            },
            "changes": [c.to_dict() for c in self.changes],
        }
