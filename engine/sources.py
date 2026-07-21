"""Transcript source adapters — where a transcript comes from.

A *source* turns some reference (a file path, a pasted blob, a remote id) into a
normalized ``Transcript``. This specializes the general collector pattern in
``example-collectors/base.py`` for the one shape this pipeline needs: text plus
provenance. The method downstream never sees which source produced it.

Two sources work with zero credentials — ``PastedTextSource`` and
``MarkdownFileSource`` — and cover the "degraded, not blocked" path: a human can
always paste a transcript in.

Remote systems (a meeting recorder, a docs API, a notes app) are reached through
``RemoteTranscriptSource``, which reads via an **injected reader callable**. The
package therefore hardwires no paid API, declares no required credential, and
every source is unit-testable without a live connection: a deployment supplies
its own reader (wrapping whatever connector it has) at registration time.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable, Protocol, runtime_checkable

from engine.pipeline_types import Transcript


@runtime_checkable
class TranscriptSource(Protocol):
    """Structural protocol every transcript source satisfies. Duck typed.

    ``name`` keys the registry. ``fetch`` takes a source-defined reference and
    returns a normalized Transcript.
    """

    name: str

    def available(self) -> bool:
        """Cheap check that this source can be read from right now."""
        ...  # pragma: no cover

    def fetch(self, ref: str, **params: Any) -> Transcript:
        """Resolve *ref* to a normalized Transcript."""
        ...  # pragma: no cover


# --- Zero-dependency sources ------------------------------------------------

class PastedTextSource:
    """A transcript a human pasted in. Always available; degraded-not-blocked."""

    name = "pasted"

    def available(self) -> bool:
        return True

    def fetch(self, ref: str, **params: Any) -> Transcript:
        """*ref* is the transcript text itself (or pass ``text=`` in params)."""
        text = params.get("text", ref) or ""
        meeting_id = params.get("meeting_id") or "pasted"
        return Transcript(
            meeting_id=meeting_id,
            source=self.name,
            text=text,
            participants=list(params.get("participants", [])),
            timestamp=params.get("timestamp"),
            provenance={"origin": "pasted"},
        )


class MarkdownFileSource:
    """A transcript stored as a local text/markdown/vtt file."""

    name = "file"

    def available(self) -> bool:
        return True

    def fetch(self, ref: str, **params: Any) -> Transcript:
        """*ref* is a filesystem path to the transcript."""
        if not os.path.isfile(ref):
            raise FileNotFoundError(f"transcript file not found: {ref}")
        with open(ref, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        meeting_id = params.get("meeting_id") or os.path.splitext(os.path.basename(ref))[0]
        return Transcript(
            meeting_id=meeting_id,
            source=self.name,
            text=text,
            participants=list(params.get("participants", [])),
            timestamp=params.get("timestamp"),
            provenance={"path": os.path.abspath(ref)},
        )


# --- Generic remote source (pluggable, injected reader) ---------------------

# The reader signature every remote binding provides. A deployment implements
# this callable however it likes — wrapping a meeting-recorder API, a document
# store, a notes app, an internal service — and injects it. The package never
# imports a vendor SDK and never names a credential; that all lives in the
# reader the caller supplies. Injecting it keeps the source unit-testable and
# keeps any hard connector dependency out of this package.
#
# reader(ref) -> {"text": str, "title"?: str, "participants"?: [...], "timestamp"?: str}
TranscriptReader = Callable[[str], "dict[str, Any]"]


class RemoteTranscriptSource:
    """Read a transcript from a remote system through an injected reader.

    Product-agnostic by construction: it holds no URL, no auth, no SDK. All of
    that is encapsulated in the ``reader`` callable a deployment passes in. If
    ``reader`` is ``None`` the source reports unavailable rather than failing at
    call time, so an unconfigured registry entry degrades cleanly.

    Parameters
    ----------
    reader :
        Resolves a remote reference to ``{"text", "title"?, "participants"?,
        "timestamp"?}``. This is the single seam where a deployment binds its
        own connector.
    name :
        Registry key for this remote binding. Multiple remote sources can be
        registered under different names, each with its own reader.
    """

    def __init__(self, reader: TranscriptReader | None = None, *, name: str = "remote") -> None:
        self.reader = reader
        self.name = name

    def available(self) -> bool:
        return self.reader is not None

    def fetch(self, ref: str, **params: Any) -> Transcript:
        if self.reader is None:
            raise RuntimeError(
                f"source {self.name!r} has no reader wired. Inject a callable that "
                "resolves a remote reference to transcript text (see TranscriptReader)."
            )
        got = self.reader(ref) or {}
        meeting_id = params.get("meeting_id") or got.get("title") or ref
        return Transcript(
            meeting_id=str(meeting_id),
            source=self.name,
            text=got.get("text", ""),
            participants=list(got.get("participants", params.get("participants", []))),
            timestamp=got.get("timestamp") or params.get("timestamp"),
            provenance={"remote_ref": ref, "title": got.get("title")},
        )


# --- Notion source (reference concrete binding, read-only) ------------------

# One fully-implemented example of a concrete remote binding, kept beside the
# generic RemoteTranscriptSource to prove the adapter seam with a real API.
# Read-only BY DESIGN: in deployments where writing to the notes system is a
# gated human action, the pipeline reads transcripts here and routes tasks to a
# board surface — it never writes back into the source system.
#
# Implemented against Notion's stable blocks API (blocks.children.list): it
# walks a page's block tree and concatenates the text — which captures a
# meeting-notes page's summary + notes + transcript, exactly what the
# extraction step wants. Validated against real timestamped meeting-transcript
# pages (~100k chars, single-block).


def _block_text(block: dict[str, Any]) -> str:
    """Plain text carried directly by one Notion block (empty for containers)."""
    btype = block.get("type")
    if not btype:
        return ""
    data = block.get(btype) or {}
    rich = data.get("rich_text") or []
    return "".join(rt.get("plain_text", "") for rt in rich if isinstance(rt, dict))


def extract_transcript_text(
    root_blocks: list[dict[str, Any]],
    fetch_children: Callable[[str], "list[dict[str, Any]]"],
    *,
    max_depth: int = 6,
) -> str:
    """Walk a Notion block tree and concatenate its text, depth-first.

    ``fetch_children(block_id)`` returns a block's child blocks — injected so the
    parsing is unit-testable without a live Notion connection. Recursion is
    bounded by *max_depth* so a pathological tree can't run away.
    """
    lines: list[str] = []

    def walk(blocks: list[dict[str, Any]], depth: int) -> None:
        for block in blocks:
            text = _block_text(block)
            if text:
                lines.append(text)
            if block.get("has_children"):
                if depth < max_depth:
                    bid = block.get("id")
                    if bid:
                        walk(fetch_children(bid) or [], depth + 1)
                else:
                    # Loss must be visible: a transcript nested past max_depth
                    # would otherwise vanish silently. Mark it so the caller
                    # (and the human reading the extract) sees text was dropped.
                    lines.append(f"[… nested content below depth {max_depth} omitted …]")

    walk(root_blocks or [], 0)
    return "\n".join(lines)


class NotionClient:
    """Minimal stdlib Notion API client (no external deps).

    Auth via ``NOTION_API_KEY`` (or an explicit token). Only the read calls the
    transcript source needs are implemented. The base URL, version, and endpoint
    paths live here in one place so they are easy to adjust per deployment.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        version: str = "2025-09-03",
        base: str = "https://api.notion.com/v1",
        timeout: int = 30,
    ) -> None:
        self.token = token if token is not None else os.environ.get("NOTION_API_KEY", "")
        self.version = version
        self.base = base
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.token)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": self.version,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read().decode("utf-8"))

    def list_block_children(self, block_id: str) -> list[dict[str, Any]]:
        """All child blocks of *block_id*, following pagination."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._get(f"/blocks/{block_id}/children", params)
            out.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return out


class NotionTranscriptSource:
    """Read a meeting transcript from a Notion page (read-only).

    ``fetch(ref)`` takes a Notion **page id** (a meeting-notes page). Pass a
    ``client`` (a NotionClient or any object with ``available()`` +
    ``list_block_children(id)``) for testing; if omitted, a client is built from
    ``NOTION_API_KEY`` at call time.
    """

    name = "notion"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _get_client(self) -> Any:
        return self._client if self._client is not None else NotionClient()

    def available(self) -> bool:
        try:
            return bool(self._get_client().available())
        except Exception:
            return False

    def fetch(self, ref: str, **params: Any) -> Transcript:
        client = self._get_client()
        if not client.available():
            raise RuntimeError(
                "NotionTranscriptSource has no NOTION_API_KEY. Provide a read-scoped "
                "Notion integration token in the environment."
            )
        root = client.list_block_children(ref)
        text = extract_transcript_text(root, client.list_block_children)
        return Transcript(
            meeting_id=params.get("meeting_id") or ref,
            source=self.name,
            text=text,
            participants=list(params.get("participants", [])),
            timestamp=params.get("timestamp"),
            provenance={"notion_page_id": ref},
        )


# --- Registry ---------------------------------------------------------------

_REGISTRY: dict[str, TranscriptSource] = {}


def register_source(name: str, source: TranscriptSource) -> None:
    """Register a source *instance* under *name*."""
    _REGISTRY[name] = source


def get_source(name: str) -> TranscriptSource | None:
    return _REGISTRY.get(name)


def list_sources() -> list[str]:
    return sorted(_REGISTRY.keys())


# The zero-dependency sources self-register at import. A RemoteTranscriptSource
# needs a reader injected, so it is registered by the runtime that has the
# connector wiring (or in the deployment overlay), not here. For example::
#
#     from engine.sources import RemoteTranscriptSource, register_source
#     register_source("recorder", RemoteTranscriptSource(my_reader, name="recorder"))
#
register_source("pasted", PastedTextSource())
register_source("file", MarkdownFileSource())
# Notion builds its client lazily from NOTION_API_KEY at fetch time; available()
# reports False until the key is present, so it registers safely here.
register_source("notion", NotionTranscriptSource())
