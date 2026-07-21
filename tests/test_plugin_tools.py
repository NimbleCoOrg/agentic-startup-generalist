"""Tests for the Hermes plugin surface (hermes-plugin/).

Loads the plugin the way the loader does — from its __init__.py by file path,
since the directory name is hyphenated — and verifies the tool registry: the
seven sg_* tools are present under exactly those names, schemas agree with the
registry, register() wires every tool with the shared availability gate, and
each handler returns a well-formed JSON envelope for representative inputs.

The handlers delegate to the engine (tested directly in test_venture_engine.py
and test_transcript_pipeline.py); here we assert the plugin *contract* — names,
envelopes, validation, and the propose-not-populate gate as seen through a tool.
"""
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(ROOT))

EXPECTED_TOOLS = [
    "sg_fetch_transcript",
    "sg_route_tasks",
    "sg_assess_pmf",
    "sg_read_retention",
    "sg_check_experiment",
    "sg_draft_positioning",
    "sg_frame_decision",
]


def _load_plugin():
    path = os.path.join(ROOT, "hermes-plugin", "__init__.py")
    spec = importlib.util.spec_from_file_location("asg_hermes_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def plugin():
    return _load_plugin()


class _FakeCtx:
    """Captures register_tool calls the way the Hermes loader would receive them."""

    def __init__(self):
        self.registered = []

    def register_tool(self, *, name, toolset, schema, handler, check_fn, emoji):
        self.registered.append({
            "name": name, "toolset": toolset, "schema": schema,
            "handler": handler, "check_fn": check_fn, "emoji": emoji,
        })


# ---- registry / manifest ----------------------------------------------------

def test_tools_registered_under_expected_names(plugin):
    names = [name for name, _s, _h, _e in plugin._TOOLS]
    assert names == EXPECTED_TOOLS


def test_each_schema_name_matches_registry_name(plugin):
    for name, schema, _h, _e in plugin._TOOLS:
        assert schema["name"] == name


def test_register_wires_every_tool_with_shared_gate(plugin):
    ctx = _FakeCtx()
    plugin.register(ctx)
    assert [r["name"] for r in ctx.registered] == EXPECTED_TOOLS
    for r in ctx.registered:
        assert r["toolset"] == "agentic-startup-generalist"
        assert r["check_fn"] is plugin._check_available
        assert callable(r["handler"])
        assert r["emoji"]


def test_availability_gate_true_with_engine_importable(plugin):
    assert plugin._check_available() is True


def test_plugin_yaml_provides_matches_registry(plugin):
    yaml_path = os.path.join(ROOT, "hermes-plugin", "plugin.yaml")
    with open(yaml_path, encoding="utf-8") as fh:
        text = fh.read()
    for name in EXPECTED_TOOLS:
        assert f'"{name}"' in text, f"plugin.yaml is missing {name}"


# ---- helpers ----------------------------------------------------------------

def _ok(raw):
    d = json.loads(raw)
    assert d["success"] is True, d
    return d


def _err(raw):
    d = json.loads(raw)
    assert d["success"] is False, d
    assert "error" in d
    return d


# ---- fetch_transcript -------------------------------------------------------

def test_fetch_transcript_pasted(plugin):
    d = _ok(plugin._handle_fetch_transcript(
        {"source": "pasted", "ref": "we agreed to ship friday", "options": {"meeting_id": "standup"}}
    ))
    assert d["transcript"]["meeting_id"] == "standup"
    assert "friday" in d["transcript"]["text"]


def test_fetch_transcript_unknown_source_lists_registered(plugin):
    d = _err(plugin._handle_fetch_transcript({"source": "telepathy", "ref": "x"}))
    assert "pasted" in d["registered_sources"]


def test_fetch_transcript_requires_ref(plugin):
    _err(plugin._handle_fetch_transcript({"source": "pasted", "ref": ""}))


# ---- route_tasks: propose writes nothing, apply gates ----------------------

def _extraction():
    return {
        "meeting": {"meeting_id": "m1", "source": "pasted"},
        "items": [{"kind": "task", "summary": "send the deck"}],
    }


def test_route_tasks_propose_is_readonly(plugin, tmp_path):
    board = tmp_path / "board.md"
    d = _ok(plugin._handle_route_tasks({
        "extraction": _extraction(),
        "config": {"default": "markdown", "surfaces": {"markdown": {"path": str(board)}}},
    }))
    assert d["mode"] == "propose"
    assert d["proposals"][0]["surface"] == "markdown"
    assert not board.exists()  # propose never writes


def test_route_tasks_apply_refuses_live_board(plugin, tmp_path):
    board = tmp_path / "board.md"
    d = _ok(plugin._handle_route_tasks({
        "extraction": _extraction(),
        "config": {"default": "markdown", "surfaces": {"markdown": {"path": str(board)}}},
        "mode": "apply",
    }))
    assert d["any_refused"] is True
    assert not board.exists()


def test_route_tasks_apply_writes_to_inbox(plugin, tmp_path):
    board = tmp_path / "inbox.md"
    d = _ok(plugin._handle_route_tasks({
        "extraction": _extraction(),
        "config": {"default": "markdown",
                   "surfaces": {"markdown": {"path": str(board), "is_inbox": True}}},
        "mode": "apply",
    }))
    assert d["any_refused"] is False
    assert board.exists()
    assert "send the deck" in board.read_text()


def test_route_tasks_rejects_non_object_extraction(plugin):
    _err(plugin._handle_route_tasks({"extraction": "nope", "config": {}}))


def test_route_tasks_apply_contains_per_surface_failure(plugin, tmp_path, monkeypatch):
    # One surface's apply raising must not discard the record of the surfaces
    # that already applied — the failure lands as a per-surface refusal entry.
    import engine.router as router_mod

    orig_apply = router_mod.SurfaceRouter.apply

    def flaky_apply(self, proposal, *, allow_live=None):
        if proposal.surface == "board":
            raise RuntimeError("board exploded")
        return orig_apply(self, proposal, allow_live=allow_live)

    monkeypatch.setattr(router_mod.SurfaceRouter, "apply", flaky_apply)

    inbox = tmp_path / "inbox.md"
    d = _ok(plugin._handle_route_tasks({
        "extraction": {
            "meeting": {"meeting_id": "m1", "source": "pasted"},
            "items": [
                {"kind": "task", "summary": "send the deck"},
                {"kind": "task", "summary": "fix the board", "owner": "alice"},
            ],
        },
        "config": {
            "default": "markdown",
            "by_owner": {"alice": "board"},
            "surfaces": {
                "markdown": {"path": str(inbox), "is_inbox": True},
                "board": {"path": str(tmp_path / "board.md"), "is_inbox": True},
            },
        },
        "mode": "apply",
    }))
    applied = {a["surface"]: a for a in d["applied"]}
    assert applied["markdown"]["written"] == 1          # good surface recorded
    assert applied["board"]["refused"] is True
    assert "board exploded" in applied["board"]["reason"]
    assert d["any_refused"] is True
    assert "send the deck" in inbox.read_text()


# ---- assess_pmf -------------------------------------------------------------

def test_assess_pmf_strong(plugin):
    d = _ok(plugin._handle_assess_pmf(
        {"claimed_stage": "launch", "responses": ["very"] * 5 + ["not"] * 5}
    ))
    assert d["assessment"]["signal"] == "strong"
    assert d["assessment"]["sean_ellis_pct"] == 50.0
    # stage is derived, not taken on faith: survey-only evidence caps at mvp
    assert d["assessment"]["stage"] == "mvp"
    assert d["assessment"]["claimed_stage"] == "launch"


def test_assess_pmf_retention_override(plugin):
    d = _ok(plugin._handle_assess_pmf(
        {"claimed_stage": "scale", "responses": ["very"] * 9 + ["not"],
         "retention_signal": "decays_to_zero"}
    ))
    assert d["assessment"]["signal"] == "no_fit"


def test_assess_pmf_bad_claimed_stage_is_error(plugin):
    _err(plugin._handle_assess_pmf({"claimed_stage": "unicorn"}))


def test_assess_pmf_no_args_is_idea_stage(plugin):
    # stage is optional now — no evidence at all is an honest idea-stage read
    d = _ok(plugin._handle_assess_pmf({}))
    assert d["assessment"]["stage"] == "idea"
    assert d["assessment"]["signal"] == "inconclusive"


# ---- read_retention ---------------------------------------------------------

def test_read_retention_flattens(plugin):
    d = _ok(plugin._handle_read_retention({"curve": [1.0, 0.6, 0.45, 0.42, 0.41]}))
    assert d["reading"]["signal"] == "flattens_above_zero"
    assert d["reading"]["floor"] > 0


def test_read_retention_too_early_small_cohort(plugin):
    d = _ok(plugin._handle_read_retention(
        {"curve": [1.0, 0.5, 0.45, 0.44], "cohort_size": 4}
    ))
    assert d["reading"]["signal"] == "too_early"


def test_read_retention_requires_array(plugin):
    _err(plugin._handle_read_retention({"curve": "nope"}))


# ---- check_experiment -------------------------------------------------------

def test_check_experiment_design_and_result(plugin):
    d = _ok(plugin._handle_check_experiment({
        "design": {"claim": "c", "prediction": "p", "kill_condition": "k",
                   "cost_if_wrong": "x", "action_on_each": "a"},
        "result": {"control_conversions": 100, "control_n": 1000,
                   "variant_conversions": 150, "variant_n": 1000},
    }))
    assert d["design_review"]["falsifiable"] is True
    assert d["result"]["significant"] is True


def test_check_experiment_needs_a_payload(plugin):
    _err(plugin._handle_check_experiment({}))


# ---- draft_positioning ------------------------------------------------------

def test_draft_positioning_complete(plugin):
    d = _ok(plugin._handle_draft_positioning({
        "target": "solo founders", "need": "lose meeting decisions",
        "product": "the agent", "category": "ops copilot",
        "benefit": "turns calls into tracked tasks", "alternative": "a doc",
        "differentiator": "it proposes, a human disposes",
    }))
    assert d["complete"] is True
    assert d["statement"].startswith("For solo founders")


def test_draft_positioning_flags_gaps(plugin):
    d = _ok(plugin._handle_draft_positioning({"target": "founders"}))
    assert d["complete"] is False
    assert "[need]" in d["statement"]


# ---- frame_decision ---------------------------------------------------------

def test_frame_decision_valid_and_gated(plugin):
    d = _ok(plugin._handle_frame_decision({
        "question": "Ship or hold? Default: hold.",
        "options": [
            {"name": "ship", "case_for": "momentum"},
            {"name": "hold", "case_for": "open bug"},
        ],
        "default": "hold",
        "recommendation": "hold",
        "flip_conditions": ["bug fixed"],
        "action": "merge to main and deploy to production",
    }))
    assert d["frame"]["gated"] is True
    assert d["frame"]["recommendation"] == "hold"


def test_frame_decision_single_option_is_error(plugin):
    _err(plugin._handle_frame_decision({
        "question": "ship?", "options": [{"name": "yes", "case_for": "x"}],
    }))


def test_frame_decision_requires_options_array(plugin):
    _err(plugin._handle_frame_decision({"question": "ship?", "options": "yes"}))
