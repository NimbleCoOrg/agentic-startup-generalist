"""Surface adapters — where extracted items get written.

A *surface* is wherever a team (or one person) actually looks at their work: a
hosted task database, an issue tracker, a project board, a markdown file. Each is
a thin adapter satisfying the ``Surface`` protocol. The pipeline's method never
names one — the surface is resolved from config.

Two reference surfaces work with zero credentials and are fully implemented:
``MarkdownFileWriter`` (the agnostic baseline / test target) and ``BoardWriter``
(writes markdown cards into a board file that some external *board tender*
process surfaces on its next cycle — no coupling to that process's code).

One surface ships as a declared-but-unimplemented example — ``ExternalSurface``
— so "surface-agnostic" is *demonstrated*: it gates on a config-named credential
and raises ``SurfaceUnavailable`` rather than silently no-opping. Filling it in
(or adding another remote adapter beside it) is an isolated change, not a change
to the method.

Stdlib only.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

from engine.pipeline_types import (
    ACTION_CREATE,
    ACTION_UPDATE,
    Item,
)


# --- Protocol ---------------------------------------------------------------

@dataclass
class ExistingItem:
    """One item already present on a surface, as seen for de-duplication."""

    dedup_key: str
    ref: str            # surface-native locator (line number, page id, issue #)
    raw: str = ""       # raw representation, used to detect "the meeting moved it"


class SurfaceUnavailable(RuntimeError):
    """Raised when a surface is selected but its credentials/config are absent."""


@runtime_checkable
class Surface(Protocol):
    """Structural protocol every surface adapter satisfies. Duck typed.

    Attributes
    ----------
    name : str
        Machine-readable id, e.g. ``"markdown"``, ``"board"``.
    is_inbox : bool
        True only for a triage/inbox lane whose entire purpose is to receive
        un-triaged candidates. Unattended runs may auto-write to an inbox; they
        must never auto-write to a live board (see the skill's "fail loud").
    """

    name: str
    is_inbox: bool

    def available(self) -> bool:
        """Cheap check that this surface can be written to (creds/paths present)."""
        ...  # pragma: no cover

    def list_existing(self) -> list[ExistingItem]:
        """Return items already on the surface, for reconciliation."""
        ...  # pragma: no cover

    def write(self, item: Item, action: str, existing_ref: str | None = None) -> dict[str, Any]:
        """Create or update *item* on the surface. Returns a small result dict."""
        ...  # pragma: no cover


# --- Rendering helpers ------------------------------------------------------

def _owner_due_suffix(item: Item) -> str:
    bits = []
    if item.owner:
        bits.append(f"@{item.owner}")
    if item.due:
        bits.append(f"due {item.due}")
    return f" ({', '.join(bits)})" if bits else ""


def _marker(dedup_key: str) -> str:
    """Embed the dedup key in an HTML comment so we can read it back exactly."""
    return f"<!--stg:{dedup_key}-->"


_MARKER_RE = re.compile(r"<!--stg:(?P<key>[^>]*?)-->")


# --- Markdown file surface (the agnostic baseline) --------------------------

class MarkdownFileWriter:
    """Append items to a markdown file. Zero config, always available.

    Actionable items render as checkboxes; warm updates render as blockquotes.
    Each line carries an ``<!--stg:KEY-->`` marker so ``list_existing`` recovers
    the exact dedup key rather than re-deriving it from prose.

    This is both the surface-agnostic default (a person who wants tasks in a
    plain file) and the test target for the whole pipeline.
    """

    name = "markdown"

    def __init__(self, path: str, *, is_inbox: bool = False) -> None:
        self.path = path
        self.is_inbox = is_inbox

    def available(self) -> bool:
        parent = os.path.dirname(os.path.abspath(self.path)) or "."
        return os.path.isdir(parent) and os.access(parent, os.W_OK)

    def render(self, item: Item) -> str:
        marker = _marker(item.dedup_key())
        if item.actionable:
            return f"- [ ] {item.summary}{_owner_due_suffix(item)} {marker}"
        return f"> **{item.kind.replace('_', ' ')}:** {item.summary} {marker}"

    def _lines(self) -> list[str]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def list_existing(self) -> list[ExistingItem]:
        out: list[ExistingItem] = []
        for idx, line in enumerate(self._lines()):
            m = _MARKER_RE.search(line)
            if m:
                out.append(ExistingItem(dedup_key=m.group("key"), ref=str(idx), raw=line))
        return out

    def write(self, item: Item, action: str, existing_ref: str | None = None) -> dict[str, Any]:
        rendered = self.render(item)
        if action == ACTION_UPDATE and existing_ref is not None:
            lines = self._lines()
            i = int(existing_ref)
            if 0 <= i < len(lines):
                lines[i] = rendered
                with open(self.path, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                return {"success": True, "action": ACTION_UPDATE, "ref": existing_ref}
            # fall through to append if the ref is stale
        # create (or fallback)
        needs_nl = os.path.exists(self.path) and os.path.getsize(self.path) > 0
        with open(self.path, "a", encoding="utf-8") as fh:
            if needs_nl:
                fh.write("\n")
            fh.write(rendered + "\n")
        return {"success": True, "action": ACTION_CREATE, "ref": None}


# --- Board surface ----------------------------------------------------------

class BoardWriter(MarkdownFileWriter):
    """Write items as markdown cards into a board file.

    The integration model is deliberately loose: some external *board tender*
    process (whatever a deployment runs — a digest job, a review loop, a person)
    scans the board markdown and surfaces the cards. Writing candidate items
    into the board file *is* the integration; this adapter needs no knowledge of
    the tender. Cards use ``- [ ] text #id`` syntax; the ``<!--stg:KEY-->``
    marker is kept for our own reconciliation and is inert to any downstream
    parser.

    If ``git_commit`` is set, each write is committed so a puller-based tender
    picks it up on its next cycle (pull → edit → commit). Pushing is left to the
    tender's own sync; this adapter only commits locally.
    """

    name = "board"

    def __init__(
        self,
        board_path: str,
        *,
        is_inbox: bool = False,
        git_commit: bool = False,
    ) -> None:
        super().__init__(board_path, is_inbox=is_inbox)
        self.git_commit = git_commit

    def _card_id(self, item: Item) -> str:
        # Short, stable, human-scannable id derived from the dedup key.
        import hashlib

        h = hashlib.sha1(item.dedup_key().encode("utf-8")).hexdigest()[:6]
        return f"m-{h}"

    def render(self, item: Item) -> str:
        marker = _marker(item.dedup_key())
        cid = self._card_id(item)
        if item.actionable:
            return f"- [ ] {item.summary}{_owner_due_suffix(item)} #{cid} {marker}"
        # Warm updates land as checked context lines so they read as notes, not to-dos.
        return f"- [x] {item.kind.replace('_', ' ')}: {item.summary} #{cid} {marker}"

    def write(self, item: Item, action: str, existing_ref: str | None = None) -> dict[str, Any]:
        result = super().write(item, action, existing_ref)
        if self.git_commit and result.get("success"):
            self._commit(item)
        return result

    def _commit(self, item: Item) -> None:
        repo = os.path.dirname(os.path.abspath(self.path))
        try:
            subprocess.run(["git", "-C", repo, "add", self.path], check=True,
                           capture_output=True, text=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "-m",
                 f"board: transcript item {self._card_id(item)}"],
                check=True, capture_output=True, text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Non-fatal: the write to the file already succeeded. Committing is a
            # convenience for a puller-based tender, not a correctness requirement.
            pass


# --- External-surface example (declared, not yet implemented) ---------------

class ExternalSurface:
    """A generic remote surface: declared for agnosticism, not yet wired.

    This exists to *prove* surface-agnosticism is real rather than aspirational.
    It gates on a credential whose env-var name is supplied in config
    (``credential_env``), so ``available()`` can tell an operator the surface is
    recognized and whether its credential is present — and any read/write raises
    ``SurfaceUnavailable`` with a pointer to what to implement, never a silent
    no-op. A deployment either fills in ``list_existing``/``write`` against its
    own API here, or registers its own adapter beside this one.

    Config
    ------
    credential_env : str
        Name of the environment variable holding this surface's credential.
    impl_hint : str, optional
        Human-readable note about what implementing the adapter entails.
    """

    name = "external"
    is_inbox = False

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.env_var = str(self.config.get("credential_env", ""))
        self.impl_hint = str(
            self.config.get("impl_hint")
            or "query the target system for existing items (list_existing) and "
            "create/update records mapping Item.kind/owner/due to its schema."
        )

    def available(self) -> bool:
        return bool(self.env_var and os.environ.get(self.env_var))

    def _fail(self) -> None:
        cred = self.env_var or "<credential_env not set in config>"
        raise SurfaceUnavailable(
            f"surface {self.name!r} is declared but not implemented. Set {cred} "
            f"and implement the adapter: {self.impl_hint}"
        )

    def list_existing(self) -> list[ExistingItem]:
        self._fail()
        return []  # pragma: no cover

    def write(self, item: Item, action: str, existing_ref: str | None = None) -> dict[str, Any]:
        self._fail()
        return {}  # pragma: no cover


# --- Registry ---------------------------------------------------------------
# Mirrors the collector registry pattern in example-collectors/base.py: a name →
# factory map, so the harness can enumerate surfaces without constructing them.
# A factory takes the surface's config dict and returns a Surface.

SurfaceFactory = Callable[[dict[str, Any]], Surface]

_REGISTRY: dict[str, SurfaceFactory] = {}


def register_surface(name: str, factory: SurfaceFactory) -> None:
    """Register *factory* under *name* in the global surface registry."""
    _REGISTRY[name] = factory


def get_surface_factory(name: str) -> SurfaceFactory | None:
    return _REGISTRY.get(name)


def build_surface(name: str, config: dict[str, Any] | None = None) -> Surface:
    """Construct a registered surface by name with *config*.

    Raises KeyError if the surface name is not registered.
    """
    factory = _REGISTRY.get(name)
    if factory is None:
        raise KeyError(
            f"unknown surface {name!r}; registered: {list_surfaces()}"
        )
    return factory(config or {})


def list_surfaces() -> list[str]:
    return sorted(_REGISTRY.keys())


# Register the reference surfaces. Config keys are documented per factory.
register_surface(
    "markdown",
    lambda cfg: MarkdownFileWriter(
        cfg["path"], is_inbox=bool(cfg.get("is_inbox", False))
    ),
)
register_surface(
    "board",
    lambda cfg: BoardWriter(
        cfg["path"],
        is_inbox=bool(cfg.get("is_inbox", False)),
        git_commit=bool(cfg.get("git_commit", False)),
    ),
)
register_surface("external", lambda cfg: ExternalSurface(cfg))
