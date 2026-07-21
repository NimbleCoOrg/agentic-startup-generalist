"""Surface router — reconcile extracted items against a surface and propose changes.

The router is the surface-agnostic core. It takes an ``Extraction`` and a routing
config, resolves which surface each item belongs on (a team default, or a
per-person override), de-duplicates against what is already there, and returns a
``Proposal`` — **without writing anything**. Writing is a separate, gated step
(``apply``) that refuses to touch a live board unless explicitly allowed.

Routing config shape::

    {
      "default": "markdown",                 # surface name for the team
      "surfaces": {                          # per-surface construction config
        "markdown": {"path": "tasks.md"},
        "board":    {"path": ".../board.md", "git_commit": true},
        "external": {"credential_env": "MY_TRACKER_TOKEN"},
      },
      "by_kind":  {"decision": "board", "risk": "board"},  # optional per-kind routing
      "by_owner": {"alice": "external"},      # optional per-person routing
      "allow_live_write": false               # may apply() write to a non-inbox surface?
    }

Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from engine.pipeline_types import (
    ACTION_COVERED,
    ACTION_CREATE,
    ACTION_UPDATE,
    Extraction,
    Item,
    Proposal,
    ProposedChange,
)
from engine.surfaces import ExistingItem, Surface, SurfaceUnavailable, build_surface


class RoutingError(RuntimeError):
    """Raised when the config cannot resolve a surface for an item."""


def _has_new_disposition(item: Item, existing_raw: str) -> bool:
    """True if *item* carries owner/due info the existing surface line lacks.

    Conservative: only flags an update when the transcript actually supplied a
    new owner or due date that is not already reflected. Never invents movement.
    Matching is boundary-aware — owner "kat" must not hide inside "@kathryn",
    and a month "2026-07" must not hide inside "2026-07-18".
    """
    if item.owner and not re.search(
        rf"@{re.escape(item.owner)}(?![\w-])", existing_raw
    ):
        return True
    if item.due and not re.search(
        rf"(?<![\w-]){re.escape(item.due)}(?![\w-])", existing_raw
    ):
        return True
    return False


def reconcile(items: list[Item], surface: Surface) -> list[ProposedChange]:
    """De-duplicate *items* against *surface*'s existing items.

    Each item resolves to exactly one of: CREATE (new), UPDATE (present but the
    meeting moved it), or COVERED (present, unchanged — reference, don't dupe).
    Skipping this is how a transcript pipeline doubles a board every meeting.
    """
    existing: dict[str, ExistingItem] = {
        e.dedup_key: e for e in surface.list_existing()
    }
    changes: list[ProposedChange] = []
    for item in items:
        match = existing.get(item.dedup_key())
        if match is None:
            changes.append(ProposedChange(item, ACTION_CREATE, None, "new"))
        elif _has_new_disposition(item, match.raw):
            changes.append(
                ProposedChange(item, ACTION_UPDATE, match.ref, "meeting moved an existing item")
            )
        else:
            changes.append(
                ProposedChange(item, ACTION_COVERED, match.ref, "already present, unchanged")
            )
    return changes


@dataclass
class ApplyResult:
    """Outcome of writing a proposal to a surface."""

    surface: str
    written: int = 0
    skipped: int = 0
    refused: bool = False
    reason: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "written": self.written,
            "skipped": self.skipped,
            "refused": self.refused,
            "reason": self.reason,
            "results": self.results,
        }


class SurfaceRouter:
    """Resolve surfaces, reconcile items, propose and (gated) apply changes."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config or {}

    # -- surface resolution --------------------------------------------------

    def surface_name_for(self, item: Item | None = None) -> str:
        """Which surface an item routes to.

        Precedence: per-owner override (who acts on it) → per-kind override
        (tasks vs. informational warm updates) → team default. This is how one
        config sends tasks to the team's default surface while decisions/risks
        go to a board a tender surfaces — and still lets a named person's tasks
        land on their own surface.
        """
        if item is not None and item.owner:
            by_owner = self.config.get("by_owner", {})
            name = by_owner.get(item.owner) or by_owner.get(item.owner.lower())
            if name:
                return name
        if item is not None:
            name = self.config.get("by_kind", {}).get(item.kind)
            if name:
                return name
        default = self.config.get("default")
        if not default:
            raise RoutingError("routing config has no 'default' surface")
        return default

    def build(self, name: str) -> Surface:
        surfaces_cfg = self.config.get("surfaces", {})
        return build_surface(name, surfaces_cfg.get(name, {}))

    # -- propose (no writes) -------------------------------------------------

    def propose(self, extraction: Extraction) -> list[Proposal]:
        """Group items by resolved surface, reconcile each. No writes happen.

        Returns one Proposal per distinct surface the items route to.
        """
        by_surface: dict[str, list[Item]] = {}
        for item in extraction.items:
            name = self.surface_name_for(item)
            by_surface.setdefault(name, []).append(item)

        proposals: list[Proposal] = []
        for name, items in by_surface.items():
            surface = self.build(name)
            try:
                changes = reconcile(items, surface)
            except SurfaceUnavailable as exc:
                # Surface is declared but unimplemented/unconfigured: still propose
                # every item as CREATE so the human sees the work, and record why
                # reconciliation could not run. Fail loud, not silent.
                changes = [
                    ProposedChange(it, ACTION_CREATE, None, f"surface unavailable: {exc}")
                    for it in items
                ]
            proposals.append(Proposal(surface=name, changes=changes))
        return proposals

    # -- apply (gated writes) ------------------------------------------------

    def apply(self, proposal: Proposal, *, allow_live: bool | None = None) -> ApplyResult:
        """Write a proposal's CREATE/UPDATE changes to its surface.

        Gated: writing to a non-inbox (live) surface is refused unless
        ``allow_live`` is true (or ``config['allow_live_write']`` is set). An
        inbox/triage surface may always be written to. COVERED items are never
        written. This is the "propose, do not populate" rule in code.
        """
        if allow_live is None:
            allow_live = bool(self.config.get("allow_live_write", False))

        surface = self.build(proposal.surface)

        if not surface.available():
            return ApplyResult(
                surface=proposal.surface,
                refused=True,
                reason=f"surface {proposal.surface!r} is not available (missing creds/config)",
            )

        if not surface.is_inbox and not allow_live:
            return ApplyResult(
                surface=proposal.surface,
                refused=True,
                reason=(
                    f"refusing to auto-write to live surface {proposal.surface!r}; "
                    "it is not an inbox/triage lane and allow_live_write is false. "
                    "A human must dispose these changes."
                ),
            )

        res = ApplyResult(surface=proposal.surface)
        for change in proposal.changes:
            if change.action == ACTION_COVERED:
                res.skipped += 1
                continue
            try:
                out = surface.write(change.item, change.action, change.existing_ref)
            except Exception as exc:
                # Contain per item: one write raising mid-batch must not discard
                # the record of what was already applied. Fail loud, per item.
                out = {"success": False, "action": change.action,
                       "error": f"{type(exc).__name__}: {exc}"}
            res.results.append(out)
            if out.get("success"):
                res.written += 1
            else:
                res.skipped += 1
        return res
