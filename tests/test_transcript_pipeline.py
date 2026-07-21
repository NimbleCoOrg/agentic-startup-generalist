"""Tests for the transcript → tasks pipeline (types, sources, surfaces, router).

Covers the load-bearing behavior of the genericized engine: de-duplication
against a surface, that a propose run writes nothing, that apply refuses to touch
a live board unless explicitly allowed (the "propose, do not populate" gate),
and that sources and surfaces are product-agnostic — a remote source reaches its
system through an injected reader, and an external surface gates on a
config-named credential rather than naming a vendor.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.pipeline_types import (  # noqa: E402
    ACTION_COVERED,
    ACTION_CREATE,
    ACTION_UPDATE,
    Extraction,
    Item,
    KIND_DECISION,
    KIND_RISK,
    KIND_TASK,
    SourceRef,
    normalize_summary,
)
from engine.sources import (  # noqa: E402
    MarkdownFileSource,
    NotionTranscriptSource,
    PastedTextSource,
    RemoteTranscriptSource,
    extract_transcript_text,
    get_source,
    list_sources,
    register_source,
)
from engine.surfaces import (  # noqa: E402
    BoardWriter,
    ExternalSurface,
    MarkdownFileWriter,
    SurfaceUnavailable,
    build_surface,
    list_surfaces,
)
from engine.router import SurfaceRouter, reconcile  # noqa: E402


# ---- types -----------------------------------------------------------------

def test_normalize_summary_collapses_and_strips():
    assert normalize_summary("  Ship  the   Deck. ") == "ship the deck"
    assert normalize_summary("Ship the deck") == normalize_summary("ship the deck!!!")


def test_dedup_key_is_kind_scoped():
    a = Item(kind=KIND_TASK, summary="Fix auth")
    b = Item(kind=KIND_DECISION, summary="Fix auth")
    assert a.dedup_key() != b.dedup_key()  # same text, different kind → distinct


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        Item(kind="banter", summary="nope")


def test_actionable_partition():
    e = Extraction(
        meeting=SourceRef(meeting_id="m1", source="pasted"),
        items=[
            Item(kind=KIND_TASK, summary="do a thing"),
            Item(kind=KIND_RISK, summary="vendor might slip"),
            Item(kind=KIND_DECISION, summary="price at X"),
        ],
    )
    assert [i.summary for i in e.tasks()] == ["do a thing"]
    assert {i.summary for i in e.warm_updates()} == {"vendor might slip", "price at X"}


def test_extraction_from_dict_backfills_provenance():
    e = Extraction.from_dict(
        {
            "meeting": {"meeting_id": "m9", "source": "remote", "timestamp": "2026-07-18"},
            "items": [{"kind": "task", "summary": "email the investor"}],
        }
    )
    assert e.items[0].provenance is not None
    assert e.items[0].provenance.meeting_id == "m9"
    assert e.items[0].provenance.source == "remote"


# ---- sources ---------------------------------------------------------------

def test_pasted_source_available_and_fetch():
    src = PastedTextSource()
    assert src.available()
    t = src.fetch("we agreed to ship friday", meeting_id="standup")
    assert t.meeting_id == "standup"
    assert t.source == "pasted"
    assert "friday" in t.text


def test_file_source_reads_file(tmp_path):
    p = tmp_path / "call.txt"
    p.write_text("alice: let's raise the price\n")
    t = MarkdownFileSource().fetch(str(p))
    assert "raise the price" in t.text
    assert t.meeting_id == "call"


def test_file_source_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        MarkdownFileSource().fetch(str(tmp_path / "nope.txt"))


def test_zero_dep_sources_are_registered():
    assert "pasted" in list_sources()
    assert "file" in list_sources()
    assert get_source("pasted") is not None


# ---- remote source (product-agnostic, injected reader) ---------------------

def test_remote_source_unavailable_without_reader():
    src = RemoteTranscriptSource(reader=None)
    assert not src.available()
    with pytest.raises(RuntimeError):
        src.fetch("some-ref")


def test_remote_source_with_injected_reader():
    def fake_reader(ref):
        return {"text": "we decided to hire", "title": "Weekly Sync",
                "participants": ["kathryn"], "timestamp": "2026-07-18"}

    src = RemoteTranscriptSource(reader=fake_reader)
    assert src.available()
    t = src.fetch("recorder-file-123")
    assert t.source == "remote"
    assert t.meeting_id == "Weekly Sync"          # falls back to the reader's title
    assert t.participants == ["kathryn"]
    assert t.provenance["remote_ref"] == "recorder-file-123"


def test_remote_source_custom_name_and_registration():
    def fake_reader(ref):
        return {"text": "notes", "title": "T"}

    src = RemoteTranscriptSource(reader=fake_reader, name="recorder")
    assert src.name == "recorder"
    register_source("recorder", src)
    try:
        assert "recorder" in list_sources()
        assert get_source("recorder").fetch("x").source == "recorder"
    finally:
        # keep the global registry clean for other tests
        from engine.sources import _REGISTRY
        _REGISTRY.pop("recorder", None)


# ---- Notion source (reference concrete binding) ----------------------------

class _FakeNotion:
    """Fake Notion client: a {block_id -> [child blocks]} tree, no network."""

    def __init__(self, tree, token="fake-token"):
        self.tree = tree
        self.token = token

    def available(self):
        return bool(self.token)

    def list_block_children(self, block_id):
        return self.tree.get(block_id, [])


def _para(bid, text, has_children=False):
    return {"id": bid, "type": "paragraph",
            "paragraph": {"rich_text": [{"plain_text": text}]},
            "has_children": has_children}


def test_extract_transcript_text_walks_nested_blocks():
    tree = {
        "pg1": [
            {"id": "mn1", "type": "meeting_notes", "meeting_notes": {}, "has_children": True},
            _para("p1", "top-level note"),
        ],
        "mn1": [_para("t1", "alice: ship it friday"), _para("t2", "bob: agreed")],
    }
    client = _FakeNotion(tree)
    text = extract_transcript_text(tree["pg1"], client.list_block_children)
    assert "alice: ship it friday" in text
    assert "bob: agreed" in text
    assert "top-level note" in text


def test_extract_transcript_text_respects_max_depth():
    # self-referential tree would loop forever without the depth bound
    tree = {"a": [_para("a", "x", has_children=True)]}
    client = _FakeNotion(tree)
    text = extract_transcript_text(tree["a"], client.list_block_children, max_depth=3)
    assert text.count("x") <= 4  # bounded, not infinite


def test_extract_transcript_text_marks_depth_omission():
    # text dropped at the depth bound must leave a visible marker, not vanish
    tree = {"a": [_para("a", "x", has_children=True)]}
    client = _FakeNotion(tree)
    text = extract_transcript_text(tree["a"], client.list_block_children, max_depth=1)
    assert "omitted" in text


def test_notion_source_fetch_with_fake_client():
    tree = {"pg1": [_para("p1", "we decided to raise the price")]}
    src = NotionTranscriptSource(client=_FakeNotion(tree))
    assert src.available()
    t = src.fetch("pg1", meeting_id="weekly-sync")
    assert t.source == "notion"
    assert t.meeting_id == "weekly-sync"
    assert "raise the price" in t.text
    assert t.provenance["notion_page_id"] == "pg1"


def test_notion_source_unavailable_without_token():
    src = NotionTranscriptSource(client=_FakeNotion({}, token=""))
    assert not src.available()
    with pytest.raises(RuntimeError):
        src.fetch("pg1")


def test_notion_source_registered():
    assert "notion" in list_sources()


# ---- surfaces --------------------------------------------------------------

def test_markdown_writer_roundtrip(tmp_path):
    board = str(tmp_path / "board.md")
    w = MarkdownFileWriter(board)
    assert w.available()
    item = Item(kind=KIND_TASK, summary="send the deck", owner="kathryn")
    w.write(item, ACTION_CREATE)
    existing = w.list_existing()
    assert len(existing) == 1
    assert existing[0].dedup_key == item.dedup_key()
    # the rendered line carries the owner and a checkbox
    assert "- [ ] send the deck (@kathryn)" in existing[0].raw


def test_markdown_warm_update_renders_as_blockquote(tmp_path):
    board = str(tmp_path / "board.md")
    w = MarkdownFileWriter(board)
    w.write(Item(kind=KIND_RISK, summary="runway tight"), ACTION_CREATE)
    assert w.list_existing()[0].raw.startswith("> **risk:**")


def test_board_writer_uses_card_id(tmp_path):
    board = str(tmp_path / "board.md")
    w = BoardWriter(board)
    assert w.name == "board"
    w.write(Item(kind=KIND_TASK, summary="wire the thing"), ACTION_CREATE)
    raw = w.list_existing()[0].raw
    assert "- [ ] wire the thing" in raw
    assert "#m-" in raw  # board-style short id


def test_external_surface_reports_availability_but_refuses_ops(monkeypatch):
    monkeypatch.delenv("MY_TRACKER_TOKEN", raising=False)
    s = ExternalSurface({"credential_env": "MY_TRACKER_TOKEN"})
    assert not s.available()
    monkeypatch.setenv("MY_TRACKER_TOKEN", "secret")
    assert s.available()  # recognized once keyed...
    with pytest.raises(SurfaceUnavailable):  # ...but still not implemented
        s.list_existing()


def test_surface_registry_builds_reference_surfaces(tmp_path):
    for name in ("markdown", "board", "external"):
        assert name in list_surfaces()
    s = build_surface("markdown", {"path": str(tmp_path / "b.md")})
    assert s.name == "markdown"


# ---- router: reconcile -----------------------------------------------------

def test_reconcile_create_covered_update(tmp_path):
    board = str(tmp_path / "board.md")
    w = MarkdownFileWriter(board)
    # pre-existing item with no owner
    w.write(Item(kind=KIND_TASK, summary="ship the deck"), ACTION_CREATE)

    items = [
        Item(kind=KIND_TASK, summary="ship the deck"),                    # covered
        Item(kind=KIND_TASK, summary="ship the deck", owner="kathryn"),   # update (new owner)
        Item(kind=KIND_TASK, summary="book the venue"),                   # create (new)
    ]
    changes = reconcile(items, w)
    actions = [c.action for c in changes]
    assert actions == [ACTION_COVERED, ACTION_UPDATE, ACTION_CREATE]


def test_reconcile_disposition_matching_is_boundary_aware(tmp_path):
    # Substring matching would let owner "kat" hide inside "@kathryn" and a
    # month "2026-07" hide inside "2026-07-18" — both must read as movement.
    board = str(tmp_path / "board.md")
    w = MarkdownFileWriter(board)
    w.write(Item(kind=KIND_TASK, summary="ship the deck",
                 owner="kathryn", due="2026-07-18"), ACTION_CREATE)

    covered = reconcile([Item(kind=KIND_TASK, summary="ship the deck",
                              owner="kathryn", due="2026-07-18")], w)
    assert covered[0].action == ACTION_COVERED

    owner_prefix = reconcile([Item(kind=KIND_TASK, summary="ship the deck",
                                   owner="kat")], w)
    assert owner_prefix[0].action == ACTION_UPDATE

    due_prefix = reconcile([Item(kind=KIND_TASK, summary="ship the deck",
                                 due="2026-07")], w)
    assert due_prefix[0].action == ACTION_UPDATE


# ---- router: propose writes nothing ----------------------------------------

def _extraction(items):
    return Extraction(meeting=SourceRef(meeting_id="m1", source="pasted"), items=items)


def test_propose_does_not_write(tmp_path):
    board = tmp_path / "board.md"  # does not exist yet
    router = SurfaceRouter({"default": "markdown", "surfaces": {"markdown": {"path": str(board)}}})
    proposals = router.propose(_extraction([Item(kind=KIND_TASK, summary="new task")]))
    assert len(proposals) == 1
    assert proposals[0].creates()
    assert not board.exists()  # propose is read-only


# ---- router: apply gate ----------------------------------------------------

def test_apply_refuses_live_board_by_default(tmp_path):
    board = tmp_path / "board.md"
    router = SurfaceRouter({"default": "markdown", "surfaces": {"markdown": {"path": str(board)}}})
    proposal = router.propose(_extraction([Item(kind=KIND_TASK, summary="do it")]))[0]
    result = router.apply(proposal)
    assert result.refused is True
    assert not board.exists()


def test_apply_writes_to_inbox_lane(tmp_path):
    board = tmp_path / "inbox.md"
    router = SurfaceRouter(
        {"default": "markdown", "surfaces": {"markdown": {"path": str(board), "is_inbox": True}}}
    )
    proposal = router.propose(_extraction([Item(kind=KIND_TASK, summary="triage me")]))[0]
    result = router.apply(proposal)
    assert result.refused is False
    assert result.written == 1
    assert board.exists()
    assert "triage me" in board.read_text()


def test_apply_allow_live_writes_and_skips_covered(tmp_path):
    board = tmp_path / "board.md"
    MarkdownFileWriter(str(board)).write(Item(kind=KIND_TASK, summary="already here"), ACTION_CREATE)
    router = SurfaceRouter(
        {"default": "markdown", "surfaces": {"markdown": {"path": str(board)}}, "allow_live_write": True}
    )
    proposal = router.propose(
        _extraction([
            Item(kind=KIND_TASK, summary="already here"),  # covered → skipped
            Item(kind=KIND_TASK, summary="brand new"),     # create → written
        ])
    )[0]
    result = router.apply(proposal)
    assert result.written == 1
    assert result.skipped == 1


class _FlakySurface:
    """Surface whose write raises for items marked 'boom' — mid-batch failure."""

    name = "flaky"
    is_inbox = True

    def available(self):
        return True

    def list_existing(self):
        return []

    def write(self, item, action, existing_ref=None):
        if "boom" in item.summary:
            raise RuntimeError("disk on fire")
        return {"success": True, "action": action, "ref": None}


def test_apply_contains_mid_batch_write_failure(monkeypatch):
    # One write raising must not discard the record of already-applied writes:
    # the failure lands as a per-item error and the batch result survives.
    router = SurfaceRouter({"default": "flaky"})
    monkeypatch.setattr(router, "build", lambda name: _FlakySurface())
    proposal = router.propose(_extraction([
        Item(kind=KIND_TASK, summary="first fine"),
        Item(kind=KIND_TASK, summary="boom in the middle"),
        Item(kind=KIND_TASK, summary="last fine"),
    ]))[0]
    result = router.apply(proposal)
    assert result.written == 2
    assert result.skipped == 1
    errors = [r for r in result.results if not r.get("success")]
    assert len(errors) == 1
    assert "disk on fire" in errors[0]["error"]


def test_by_kind_routes_warm_updates_to_board(tmp_path):
    # tasks → default (external); decisions/risks → board. This is the
    # "hosted tracker for tasks, board for warm updates" split, in config.
    router = SurfaceRouter(
        {
            "default": "external",
            "surfaces": {
                "external": {"credential_env": "MY_TRACKER_TOKEN"},
                "board": {"path": str(tmp_path / "board.md")},
            },
            "by_kind": {"decision": "board", "risk": "board"},
        }
    )
    proposals = router.propose(
        _extraction([
            Item(kind=KIND_TASK, summary="send the deck"),      # → external (default)
            Item(kind=KIND_DECISION, summary="price at X"),     # → board
            Item(kind=KIND_RISK, summary="runway tight"),       # → board
        ])
    )
    routed = {p.surface: len(p.changes) for p in proposals}
    assert routed == {"external": 1, "board": 2}


def test_owner_beats_kind_in_routing(tmp_path):
    # An owned task follows by_owner even if a by_kind rule also exists.
    router = SurfaceRouter(
        {
            "default": "markdown",
            "surfaces": {
                "markdown": {"path": str(tmp_path / "b.md")},
                "external": {"credential_env": "MY_TRACKER_TOKEN"},
                "board": {"path": str(tmp_path / "g.md")},
            },
            "by_owner": {"kathryn": "external"},
            "by_kind": {"task": "board"},
        }
    )
    name = router.surface_name_for(Item(kind=KIND_TASK, summary="x", owner="kathryn"))
    assert name == "external"  # owner wins


def test_by_owner_routing_splits_surfaces(tmp_path):
    team_board = tmp_path / "team.md"
    router = SurfaceRouter(
        {
            "default": "markdown",
            "surfaces": {
                "markdown": {"path": str(team_board)},
                "external": {"credential_env": "MY_TRACKER_TOKEN"},
            },
            "by_owner": {"kathryn": "external"},
        }
    )
    proposals = router.propose(
        _extraction([
            Item(kind=KIND_TASK, summary="team task"),                    # → markdown
            Item(kind=KIND_TASK, summary="kat task", owner="kathryn"),    # → external
        ])
    )
    surfaces = {p.surface for p in proposals}
    assert surfaces == {"markdown", "external"}
