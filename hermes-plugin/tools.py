"""agentic-startup-generalist tools for Hermes — schemas, handlers, and the availability gate.

This file is loaded by __init__.py via importlib so it works under any
import path Hermes assigns to the plugin. It must be importable with no
external dependencies beyond the stdlib and whatever the ``engine`` package
library provides.

Tool names use the ``sg_`` prefix (startup-generalist), short enough to read in
a tool listing and stable across the package's slug. Two families:

  Transcript → tasks pipeline (surface-agnostic ops cadence):
    - sg_fetch_transcript   resolve a source ref to normalized transcript text
    - sg_route_tasks        reconcile an extraction against a surface, propose/apply

  Venture methodology (the deterministic engine in engine/venture.py):
    - sg_assess_pmf         stage-honest PMF read (Sean Ellis + retention)
    - sg_read_retention     classify a retention curve (flattens/decays/too-early)
    - sg_check_experiment   review a bet's falsifiability and/or test its result
    - sg_draft_positioning  fill the Moore positioning template, flag gaps
    - sg_frame_decision     frame a decision for a human gate (RECOMMEND, don't act)

Handlers are plain functions: (args: dict, **kwargs) -> str (a JSON string).
The _tool_result / _tool_error helpers standardise the envelope. Handlers never
raise — they catch and return _tool_error.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
# Mirrors the path insert in __init__.py so this file is also independently
# importable (e.g. in unit tests that import tools.py directly), and so the
# `engine` package library resolves without an install step.
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_ROOT = os.path.normpath(os.path.join(_PLUGIN_DIR, ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _tool_result(data: Any = None, **kwargs: Any) -> str:
    """Return a JSON success envelope.

    Pass either a single dict as `data`, or keyword arguments that become
    the top-level keys. `success: true` is always injected.
    """
    if data is not None:
        payload = data if isinstance(data, dict) else {"result": data}
    else:
        payload = kwargs
    payload.setdefault("success", True)
    return json.dumps(payload, default=str)


def _tool_error(message: str, **extra: Any) -> str:
    """Return a JSON error envelope.

    The `error` key carries the human-readable message. `success: false` is
    always set. Pass extra keyword arguments for structured debugging info.
    """
    payload = {"error": message, "success": False, **extra}
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------

def _check_available() -> bool:
    """Return True if this plugin's tools are ready to run.

    Called by Hermes before every tool invocation. If this returns False,
    Hermes surfaces an error to the agent without calling the handler.

    The baseline tools need no credentials: the methodology tools are pure
    functions, fetch_transcript works against pasted text and local files, and
    route_tasks works against the markdown / board surfaces with no keys.
    Per-surface credentials (an external tracker) are gated inside each surface
    adapter's ``available()`` and surfaced as a loud refusal at write time — not
    here, and not as a blanket gate that would refuse every call while the
    manifest promises no required env. Keep requires_env empty to match.
    """
    try:
        import engine  # noqa: F401
        import engine.venture  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Tool: sg_fetch_transcript
# ---------------------------------------------------------------------------

FETCH_TRANSCRIPT_SCHEMA = {
    "name": "sg_fetch_transcript",
    "description": (
        "Resolve a meeting transcript from a source to normalized text the agent "
        "can then extract from. Sources are pluggable: 'pasted' (ref is the text "
        "itself), 'file' (ref is a local path), or a remote source wired into the "
        "runtime through an injected reader. Returns the transcript text plus "
        "meeting id, participants, and provenance. Does NOT extract tasks — that "
        "is the agent's job, per the transcript skill."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Registered source name, e.g. 'pasted', 'file', or a remote binding.",
            },
            "ref": {
                "type": "string",
                "description": (
                    "Source-defined reference: the transcript text (pasted), a file "
                    "path (file), or a remote id (a remote binding)."
                ),
            },
            "options": {
                "type": "object",
                "description": (
                    "Optional source params: meeting_id, participants, timestamp, etc."
                ),
            },
        },
        "required": ["source", "ref"],
    },
}


def _handle_fetch_transcript(args: dict[str, Any], **kwargs: Any) -> str:
    source_name = (args.get("source") or "").strip()
    ref = args.get("ref") or ""
    options = args.get("options") or {}
    if not source_name:
        return _tool_error("'source' must not be empty.")
    if not ref:
        return _tool_error("'ref' must not be empty.")

    try:
        from engine.sources import get_source, list_sources

        source = get_source(source_name)
        if source is None:
            return _tool_error(
                f"unknown source {source_name!r}.",
                registered_sources=list_sources(),
            )
        if not source.available():
            return _tool_error(
                f"source {source_name!r} is not available (not wired into this runtime)."
            )
        transcript = source.fetch(ref, **options)
        return _tool_result(transcript=transcript.to_dict())
    except FileNotFoundError as exc:
        return _tool_error(f"transcript not found: {exc}")
    except Exception as exc:
        return _tool_error(
            f"fetch_transcript failed: {type(exc).__name__}: {exc}",
            source=source_name,
        )


# ---------------------------------------------------------------------------
# Tool: sg_route_tasks
# ---------------------------------------------------------------------------

ROUTE_TASKS_SCHEMA = {
    "name": "sg_route_tasks",
    "description": (
        "Reconcile an extraction (the decisions/commitments/risks/open-questions/"
        "tasks the agent pulled from a transcript) against a task surface, and "
        "PROPOSE changes — new items, updates to moved items, and already-covered "
        "items to skip. Surface-agnostic: routing config picks markdown, board, "
        "or an external tracker, per team or per person. mode='propose' (default) "
        "writes nothing and returns the proposal for a human to dispose. "
        "mode='apply' writes, but REFUSES a live (non-inbox) board unless "
        "allow_live is true — automation fails loud."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "extraction": {
                "type": "object",
                "description": (
                    "The extraction: {meeting: {meeting_id, source, timestamp}, "
                    "items: [{kind, summary, detail?, owner?, due?, provenance?}]}. "
                    "kind is one of decision|commitment|risk|open_question|task."
                ),
            },
            "config": {
                "type": "object",
                "description": (
                    "Routing config: {default: surface_name, surfaces: {name: {...}}, "
                    "by_owner?: {person: surface_name}, allow_live_write?: bool}."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["propose", "apply"],
                "description": "propose (default, read-only) or apply (gated writes).",
            },
            "allow_live": {
                "type": "boolean",
                "description": (
                    "Only for mode=apply: permit writing to a live (non-inbox) "
                    "surface. Defaults to config.allow_live_write or false."
                ),
            },
        },
        "required": ["extraction", "config"],
    },
}


def _handle_route_tasks(args: dict[str, Any], **kwargs: Any) -> str:
    extraction_raw = args.get("extraction")
    config = args.get("config")
    mode = (args.get("mode") or "propose").strip()
    allow_live = args.get("allow_live")

    if not isinstance(extraction_raw, dict):
        return _tool_error("'extraction' must be an object.")
    if not isinstance(config, dict):
        return _tool_error("'config' must be an object.")
    if mode not in ("propose", "apply"):
        return _tool_error("'mode' must be 'propose' or 'apply'.")

    try:
        from engine.pipeline_types import Extraction
        from engine.router import SurfaceRouter

        extraction = Extraction.from_dict(extraction_raw)
        router = SurfaceRouter(config)
        proposals = router.propose(extraction)

        out: dict[str, Any] = {
            "mode": mode,
            "proposals": [p.to_dict() for p in proposals],
        }

        if mode == "apply":
            applied = []
            for p in proposals:
                try:
                    applied.append(router.apply(p, allow_live=allow_live).to_dict())
                except Exception as exc:
                    # Contain per proposal: one surface failing must not discard
                    # the record of what was already applied to the others —
                    # mirror how propose contains SurfaceUnavailable per surface.
                    applied.append({
                        "surface": p.surface, "written": 0, "skipped": 0,
                        "refused": True,
                        "reason": f"apply failed: {type(exc).__name__}: {exc}",
                        "results": [],
                    })
            out["applied"] = applied
            out["any_refused"] = any(a.get("refused") for a in applied)

        return _tool_result(out)
    except Exception as exc:
        return _tool_error(f"route_tasks failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: sg_assess_pmf
# ---------------------------------------------------------------------------

ASSESS_PMF_SCHEMA = {
    "name": "sg_assess_pmf",
    "description": (
        "Produce a stage-honest product-market-fit read: DERIVE the stage the "
        "evidence supports (idea|mvp|launch — this tool never awards scale), "
        "score any Sean Ellis survey responses (>=40% 'very disappointed' is "
        "the fit threshold), fold in a retention signal, and return a signal "
        "(strong|weak|no_fit|too_early|inconclusive) with the stage basis and "
        "caveats. Pass the team's belief as claimed_stage and the tool checks "
        "it against the evidence rather than trusting it — judge the stage by "
        "evidence, not intent. Does NOT decide fit — it assembles the evidence "
        "and names what it cannot support, for the ship/hold/kill/narrow gate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "claimed_stage": {
                "type": "string",
                "enum": ["idea", "mvp", "launch", "scale"],
                "description": (
                    "Optional: the stage the team BELIEVES it is at. Compared "
                    "against the evidence-derived stage; a mismatch becomes a "
                    "caveat. Never taken on faith."
                ),
            },
            "responses": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Sean Ellis responses, each starting 'very'/'somewhat'/'not' "
                    "(disappointed). Optional."
                ),
            },
            "retention_signal": {
                "type": "string",
                "enum": ["flattens_above_zero", "decays_to_zero", "too_early",
                         "inconclusive"],
                "description": "Optional prior retention reading (see sg_read_retention).",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional supporting evidence strings, carried through verbatim.",
            },
            "founder_powered": {
                "type": "boolean",
                "description": "True if usage depends on a human chasing people — adds a caveat.",
            },
        },
        "required": [],
    },
}


def _handle_assess_pmf(args: dict[str, Any], **kwargs: Any) -> str:
    claimed = (args.get("claimed_stage") or "").strip() or None
    try:
        from engine.venture import assess_pmf

        assessment = assess_pmf(
            claimed_stage=claimed,
            responses=args.get("responses"),
            retention_signal=args.get("retention_signal"),
            evidence=args.get("evidence"),
            founder_powered=bool(args.get("founder_powered", False)),
        )
        return _tool_result(assessment=assessment.to_dict())
    except ValueError as exc:
        return _tool_error(str(exc))
    except Exception as exc:
        return _tool_error(f"assess_pmf failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: sg_read_retention
# ---------------------------------------------------------------------------

READ_RETENTION_SCHEMA = {
    "name": "sg_read_retention",
    "description": (
        "Classify a retention curve as flattens_above_zero (a keepable segment — "
        "the signal), decays_to_zero (no fit yet, which acquisition can hide), "
        "too_early (cohort too young or small to read), or inconclusive (e.g. a "
        "rising tail — not a settled read). Input is retention as a fraction "
        "(0..1) per period, period 0 first; percentage-scale values are an "
        "error. Returns the signal, the stabilized floor if it flattens, and a "
        "note. Segment before concluding."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "curve": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Retention fraction per period (0..1), period 0 first.",
            },
            "cohort_size": {
                "type": "integer",
                "description": "Optional size of the counted cohort; small cohorts read too_early.",
            },
            "min_periods": {
                "type": "integer",
                "description": "Minimum periods before a read is possible (default 3).",
            },
        },
        "required": ["curve"],
    },
}


def _handle_read_retention(args: dict[str, Any], **kwargs: Any) -> str:
    curve = args.get("curve")
    if not isinstance(curve, list):
        return _tool_error("'curve' must be an array of numbers.")
    try:
        from engine.venture import read_retention

        kwargs_ = {}
        if args.get("cohort_size") is not None:
            kwargs_["cohort_size"] = int(args["cohort_size"])
        if args.get("min_periods") is not None:
            kwargs_["min_periods"] = int(args["min_periods"])
        reading = read_retention([float(x) for x in curve], **kwargs_)
        return _tool_result(reading=reading.to_dict())
    except (TypeError, ValueError) as exc:
        return _tool_error(f"read_retention failed: {exc}")
    except Exception as exc:
        return _tool_error(f"read_retention failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: sg_check_experiment
# ---------------------------------------------------------------------------

CHECK_EXPERIMENT_SCHEMA = {
    "name": "sg_check_experiment",
    "description": (
        "Review an experiment before or after running it. Pass 'design' to check "
        "falsifiability — it needs a claim, prediction, kill_condition, "
        "cost_if_wrong, and action_on_each; a bet with no kill condition can only "
        "be rationalized. Pass 'result' (control/variant conversion counts) for a "
        "two-proportion z-test with a two-tailed p-value and lift. Provide either "
        "or both."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "design": {
                "type": "object",
                "description": (
                    "Bet design: {claim, prediction, kill_condition, cost_if_wrong, "
                    "action_on_each}. Missing fields are reported."
                ),
            },
            "result": {
                "type": "object",
                "description": (
                    "A/B result: {control_conversions, control_n, variant_conversions, "
                    "variant_n, alpha?}."
                ),
            },
        },
    },
}


def _handle_check_experiment(args: dict[str, Any], **kwargs: Any) -> str:
    payload = {}
    if isinstance(args.get("design"), dict):
        payload["design"] = args["design"]
    if isinstance(args.get("result"), dict):
        payload["result"] = args["result"]
    if not payload:
        return _tool_error("provide a 'design' object and/or a 'result' object.")
    try:
        from engine.venture import check_experiment

        return _tool_result(check_experiment(payload))
    except ValueError as exc:
        return _tool_error(str(exc))
    except Exception as exc:
        return _tool_error(f"check_experiment failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: sg_draft_positioning
# ---------------------------------------------------------------------------

DRAFT_POSITIONING_SCHEMA = {
    "name": "sg_draft_positioning",
    "description": (
        "Fill Geoffrey Moore's positioning template: 'For [target] who [need], "
        "[product] is a [category] that [benefit]. Unlike [alternative], "
        "[differentiator].' Missing fields are listed and shown as bracketed "
        "placeholders, so a half-filled draft is visibly incomplete rather than "
        "asserting a claim the venture never made."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "The customer segment."},
            "need": {"type": "string", "description": "The need or problem they have."},
            "product": {"type": "string", "description": "The product name (generic if shared)."},
            "category": {"type": "string", "description": "The market category it competes in."},
            "benefit": {"type": "string", "description": "The key benefit it delivers."},
            "alternative": {"type": "string", "description": "The primary competitive alternative."},
            "differentiator": {"type": "string", "description": "What sets it apart from that alternative."},
        },
    },
}


def _handle_draft_positioning(args: dict[str, Any], **kwargs: Any) -> str:
    try:
        from engine.venture import draft_positioning

        fields = {k: args.get(k) for k in (
            "target", "need", "product", "category", "benefit", "alternative", "differentiator",
        )}
        return _tool_result(draft_positioning(**fields))
    except Exception as exc:
        return _tool_error(f"draft_positioning failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: sg_frame_decision
# ---------------------------------------------------------------------------

FRAME_DECISION_SCHEMA = {
    "name": "sg_frame_decision",
    "description": (
        "Frame a decision for a human gate WITHOUT making it (the RECOMMEND "
        "phase). Requires a question with a default and at least two options, "
        "each with the strongest case FOR it — including the disfavoured one. If "
        "you give a recommendation, give the conditions that would flip it. Pass "
        "'action' to classify whether the call is gated (a human disposes: money, "
        "merges to a default branch, production, people, access) or free."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The decision as a question with a default.",
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "case_for": {"type": "string"},
                    },
                    "required": ["name"],
                },
                "description": "At least two options, each with its strongest case_for.",
            },
            "default": {"type": "string", "description": "The option that stands if no one decides."},
            "recommendation": {"type": "string", "description": "The option you recommend (must be one of options)."},
            "flip_conditions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Conditions under which the recommendation would flip.",
            },
            "action": {
                "type": "string",
                "description": (
                    "The action this decision would authorize, for gated/free "
                    "classification. Omitted or empty means gated — ambiguity "
                    "leans gated."
                ),
            },
        },
        "required": ["question", "options"],
    },
}


def _handle_frame_decision(args: dict[str, Any], **kwargs: Any) -> str:
    options = args.get("options")
    if not isinstance(options, list):
        return _tool_error("'options' must be an array.")
    try:
        from engine.venture import frame_decision

        frame = frame_decision(
            question=args.get("question", ""),
            options=options,
            default=args.get("default"),
            recommendation=args.get("recommendation"),
            flip_conditions=args.get("flip_conditions"),
            action=args.get("action"),
        )
        return _tool_result(frame=frame.to_dict())
    except ValueError as exc:
        return _tool_error(str(exc))
    except Exception as exc:
        return _tool_error(f"frame_decision failed: {type(exc).__name__}: {exc}")
