"""Venture-methodology engine — the deterministic core behind the generalist tools.

This module is the "genericized engine": the pure, stdlib-only, product-free
methodology that the PMF, experiment, positioning, and decision-framing tools
call into. Nothing here names a venture, a founder, a metric definition, or a
board — those are *particulars* that live in an operator's private overlay and
are enforced out by ``scripts/check_sanitization.py``. What lives here is only
the *method*: how to grade a PMF signal, how to read a retention curve, how to
tell whether a bet is falsifiable, how to fill a positioning template, and how
to frame a decision for a human gate.

Everything is deterministic and dependency-free so it is unit-testable without
an LLM or a network. The judgement calls the skills describe (see
``hermes-skill/startup-generalist-pmf.md``) stay with the agent and the
human at the gate; this module gives them honest, repeatable arithmetic and
structure to work from.

Stdlib only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ===========================================================================
# PMF — stage honesty + the Sean Ellis signal
# ===========================================================================

STAGE_IDEA = "idea"
STAGE_MVP = "mvp"
STAGE_LAUNCH = "launch"
STAGE_SCALE = "scale"
STAGES = (STAGE_IDEA, STAGE_MVP, STAGE_LAUNCH, STAGE_SCALE)

# The Sean Ellis test: "How would you feel if you could no longer use this?"
# >= 40% "very disappointed" is the conventional PMF threshold.
SEAN_ELLIS_THRESHOLD = 40.0

# Below this many counted responses the survey percentage is anecdote, not
# signal — the same spirit as ``read_retention``'s ``min_cohort_size``.
MIN_SURVEY_RESPONSES = 5

_VERY = "very"
_SOMEWHAT = "somewhat"
_NOT = "not"


def sean_ellis_score(responses: list[str]) -> dict[str, Any]:
    """Score raw Sean Ellis survey responses.

    Each response is bucketed by its leading word: "very [disappointed]",
    "somewhat [disappointed]", or "not [disappointed]". Blank/unrecognized
    responses are dropped from the denominator (and counted separately) rather
    than silently miscounted — a denominator trick is exactly what the PMF skill
    warns against.

    Returns pct_very, the counted total, and a verdict ("strong" >= 40%, else
    "weak"). Returns pct_very=None with an empty denominator so the caller can
    say "cannot know" instead of dividing by zero.
    """
    very = somewhat = nope = dropped = 0
    for raw in responses or []:
        token = (raw or "").strip().lower()
        if token.startswith(_VERY):
            very += 1
        elif token.startswith(_SOMEWHAT):
            somewhat += 1
        elif token.startswith(_NOT):
            nope += 1
        else:
            dropped += 1
    counted = very + somewhat + nope
    if counted == 0:
        return {"pct_very": None, "counted": 0, "dropped": dropped,
                "verdict": "inconclusive"}
    pct = round(100.0 * very / counted, 1)
    return {
        "pct_very": pct,
        "counted": counted,
        "dropped": dropped,
        "very": very,
        "somewhat": somewhat,
        "not": nope,
        "verdict": "strong" if pct >= SEAN_ELLIS_THRESHOLD else "weak",
    }


@dataclass
class PMFAssessment:
    """A stage-honest PMF read: never a verdict, always evidence + caveats.

    ``stage`` is the stage the EVIDENCE supports, derived by ``assess_pmf`` —
    never the caller's claim. ``stage_basis`` says why. ``claimed_stage`` echoes
    what the team believes, so a mismatch is visible rather than silently
    accepted or silently corrected.
    """

    stage: str                        # evidence-supported stage (derived)
    signal: str                       # strong | weak | no_fit | too_early | inconclusive
    sean_ellis_pct: float | None = None
    retention_signal: str | None = None
    claimed_stage: str | None = None  # what the team believes, if stated
    survey_counted: int = 0           # responses that landed in a bucket
    survey_dropped: int = 0           # responses dropped as unparseable
    stage_basis: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "signal": self.signal,
            "sean_ellis_pct": self.sean_ellis_pct,
            "retention_signal": self.retention_signal,
            "claimed_stage": self.claimed_stage,
            "survey_counted": self.survey_counted,
            "survey_dropped": self.survey_dropped,
            "stage_basis": list(self.stage_basis),
            "evidence": list(self.evidence),
            "caveats": list(self.caveats),
        }


def assess_pmf(
    *,
    claimed_stage: str | None = None,
    responses: list[str] | None = None,
    retention_signal: str | None = None,
    evidence: list[str] | None = None,
    founder_powered: bool = False,
) -> PMFAssessment:
    """Derive the evidence-supported stage and fit signal from the inputs.

    The skill's first rule is "judge the stage by evidence, not by intent" — so
    this function never takes the team's stage as an input to trust. It derives
    the stage the supplied evidence actually supports, and if ``claimed_stage``
    is given it is compared, with a mismatch surfaced as a caveat. That makes
    the tool the check on stage error rather than a party to it.

    Signal precedence mirrors the PMF skill: retention is the least gameable
    signal, so a decaying curve overrides a rosy survey, a too-young cohort
    forces "too_early" regardless of enthusiasm, and a flattening curve is the
    fit signal on its own when the survey is silent. Only when retention is
    silent or supportive does a usable survey set the signal — and a survey
    below ``MIN_SURVEY_RESPONSES`` counted responses is anecdote, not signal.

    ``founder_powered`` and a decaying curve add caveats, never hide the number.
    """
    if claimed_stage is not None and claimed_stage not in STAGES:
        raise ValueError(
            f"unknown claimed_stage {claimed_stage!r}; expected one of {STAGES}"
        )
    if retention_signal is not None and retention_signal not in RETENTION_SIGNALS:
        raise ValueError(
            f"unknown retention_signal {retention_signal!r}; "
            f"expected one of {RETENTION_SIGNALS}"
        )

    se = sean_ellis_score(responses) if responses else {"pct_very": None,
                                                        "counted": 0, "dropped": 0,
                                                        "verdict": "inconclusive"}
    pct = se.get("pct_very")
    counted = int(se.get("counted", 0))
    dropped = int(se.get("dropped", 0))
    caveats: list[str] = []

    # --- fit signal (retention outranks survey) ---
    if retention_signal == RET_DECAYS:
        signal = "no_fit"
        caveats.append(
            "retention decays to zero — no fit yet regardless of survey or growth"
        )
    elif retention_signal == RET_TOO_EARLY:
        signal = "too_early"
        caveats.append("retention cohort too young/small to read — give it a date")
    elif pct is not None and counted >= MIN_SURVEY_RESPONSES:
        signal = "strong" if pct >= SEAN_ELLIS_THRESHOLD else "weak"
        if dropped:
            caveats.append(
                f"{dropped} unparseable survey response(s) dropped from the denominator"
            )
    else:
        # Survey unusable: absent, all-unparseable, or too small a sample.
        if pct is not None:
            caveats.append(
                f"only {counted} Sean Ellis responses — below the minimum of "
                f"{MIN_SURVEY_RESPONSES}; treat the percentage as anecdote, not signal"
            )
        elif responses:
            caveats.append(
                f"{dropped} survey responses supplied but none parseable as "
                "very/somewhat/not — cannot grade the survey signal"
            )
        else:
            caveats.append("no Sean Ellis responses supplied — cannot grade the survey signal")
        if retention_signal == RET_FLATTENS:
            # Retention flattening above zero is the doctrine's fit signal —
            # a silent survey must not drag it down to inconclusive.
            signal = "strong"
            caveats.append(
                "fit signal read from flattening retention alone — corroborate with a survey"
            )
        else:
            signal = "inconclusive"

    # --- evidence-supported stage (conservative: highest stage the inputs
    # actually demonstrate; this tool never awards Scale — that takes
    # acquisition and unit-economics evidence it does not see) ---
    stage_basis: list[str] = []
    if retention_signal == RET_FLATTENS and not founder_powered:
        stage = STAGE_LAUNCH
        stage_basis.append(
            "retention flattens above zero — a definable group keeps returning"
        )
    elif retention_signal == RET_FLATTENS and founder_powered:
        stage = STAGE_MVP
        stage_basis.append(
            "retention flattens but usage is founder-powered — repeat use exists, "
            "reliability is the founder, not the product"
        )
    elif retention_signal in (RET_DECAYS, RET_TOO_EARLY, RET_INCONCLUSIVE):
        stage = STAGE_MVP
        stage_basis.append(
            "usage data exists but shows no reliable fit yet — MVP-stage evidence"
        )
    elif pct is not None:
        stage = STAGE_MVP
        stage_basis.append(
            "survey responses exist (users to survey implies a usable thing) but "
            "no retention reading — cannot evidence beyond MVP"
        )
    elif responses:
        stage = STAGE_IDEA
        stage_basis.append(
            "no usage evidence and no parseable survey responses — nothing above "
            "idea-stage is evidenced"
        )
    else:
        stage = STAGE_IDEA
        stage_basis.append(
            "no usage or survey evidence supplied — nothing above idea-stage is evidenced"
        )

    if claimed_stage and claimed_stage != stage:
        caveats.append(
            f"claimed stage {claimed_stage!r} is not supported by the evidence — "
            f"the evidence supports {stage!r}; judge the stage by evidence, not intent"
        )
    if claimed_stage == STAGE_SCALE and signal in ("weak", "no_fit", "inconclusive"):
        caveats.append("scaling a product without a fit signal burns the runway that buys the fix")

    if founder_powered:
        caveats.append(
            "usage is founder-powered — a service, not a product; discount accordingly"
        )

    return PMFAssessment(
        stage=stage,
        signal=signal,
        sean_ellis_pct=pct,
        retention_signal=retention_signal,
        claimed_stage=claimed_stage,
        survey_counted=counted,
        survey_dropped=dropped,
        stage_basis=stage_basis,
        evidence=list(evidence or []),
        caveats=caveats,
    )


# ===========================================================================
# Retention — reading the curve
# ===========================================================================

RET_FLATTENS = "flattens_above_zero"
RET_DECAYS = "decays_to_zero"
RET_TOO_EARLY = "too_early"
RET_INCONCLUSIVE = "inconclusive"     # e.g. a rising tail — not a settled read

RETENTION_SIGNALS = (RET_FLATTENS, RET_DECAYS, RET_TOO_EARLY, RET_INCONCLUSIVE)


@dataclass
class RetentionReading:
    """The classification of one retention curve. Segment before concluding."""

    signal: str                       # one of RETENTION_SIGNALS
    floor: float | None               # stabilized retention level, if it flattens
    curve: list[float] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "floor": self.floor,
            "curve": list(self.curve),
            "note": self.note,
        }


def read_retention(
    curve: list[float],
    *,
    min_periods: int = 3,
    cohort_size: int | None = None,
    min_cohort_size: int = 20,
    flat_tol: float = 0.05,
    near_zero: float = 0.03,
) -> RetentionReading:
    """Classify a retention curve as flattening, decaying, or too-early.

    ``curve`` is retention as a fraction (0..1) per period, period 0 first. The
    reading looks only at the *tail* (the later periods), because the early drop
    is universal and uninformative — what matters is whether the tail settles
    above zero (a keepable segment) or slides to it (no fit yet).

    A curve shorter than ``min_periods``, or from a cohort smaller than
    ``min_cohort_size``, reads "too_early" — the honest answer more often than
    teams like. A tail that is *rising* reads "inconclusive": a recovering
    curve is not settled and must not be labeled decay. Values outside 0..1
    (a percentage-scale curve) are a ValueError, not a misread.
    """
    curve = [float(x) for x in (curve or [])]
    if curve and (max(curve) > 1.0 or min(curve) < 0.0):
        raise ValueError(
            "retention values must be fractions in 0..1 per period — got "
            f"min {min(curve)}, max {max(curve)}; divide percentages by 100"
        )
    if len(curve) < min_periods:
        return RetentionReading(RET_TOO_EARLY, None, curve,
                                f"only {len(curve)} periods — need >= {min_periods}")
    if cohort_size is not None and cohort_size < min_cohort_size:
        return RetentionReading(RET_TOO_EARLY, None, curve,
                                f"cohort of {cohort_size} < {min_cohort_size} — too small to read")

    # Tail = later half of the curve (at least the last two points).
    tail = curve[max(1, len(curve) // 2):]
    tail_mean = sum(tail) / len(tail)
    tail_range = max(tail) - min(tail)
    final = curve[-1]

    if final <= near_zero:
        return RetentionReading(RET_DECAYS, None, curve,
                                "tail reaches ~zero — acquisition can hide this")
    if tail_range <= flat_tol and tail_mean > near_zero:
        return RetentionReading(RET_FLATTENS, round(tail_mean, 4), curve,
                                "tail flat above zero — ask WHO the retained segment is")
    if final > tail[0]:
        # Rising tail: a recovering curve is not the doctrine's strongest
        # negative — it is an unsettled read. Re-read once it stabilizes.
        return RetentionReading(RET_INCONCLUSIVE, None, curve,
                                "tail is rising — recovering, not settled; re-read "
                                "once the curve stabilizes")
    # Still trending down but not yet at zero: decaying, not settled.
    return RetentionReading(RET_DECAYS, None, curve,
                            "tail still declining — not settled above zero yet")


# ===========================================================================
# Experiments — falsifiability + significance
# ===========================================================================

# The design fields the PMF skill requires before a bet is worth running.
_DESIGN_FIELDS = ("claim", "prediction", "kill_condition", "cost_if_wrong", "action_on_each")


@dataclass
class ExperimentReview:
    """Whether an experiment design can actually come back negative."""

    falsifiable: bool
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "falsifiable": self.falsifiable,
            "missing": list(self.missing),
            "warnings": list(self.warnings),
        }


def review_experiment_design(design: dict[str, Any]) -> ExperimentReview:
    """Check a bet design for the pieces that make it falsifiable.

    "An experiment that cannot come back negative is not an experiment; it is a
    press release with a sample size." A design is falsifiable only if it names a
    kill condition *and* a prediction — the two fields that let a result contradict
    the claim. Missing pieces are listed; a design with no differential action
    ("what we do differently on each outcome") gets a warning: if the answer is
    nothing, don't run it.
    """
    design = design or {}
    missing = [f for f in _DESIGN_FIELDS
               if not str(design.get(f, "")).strip()]
    warnings: list[str] = []
    if "kill_condition" in missing:
        warnings.append("no kill condition agreed in advance — result can only be rationalized")
    if "action_on_each" in missing:
        warnings.append("no differential action — if you'd do nothing either way, don't run it")
    falsifiable = ("kill_condition" not in missing) and ("prediction" not in missing)
    return ExperimentReview(falsifiable=falsifiable, missing=missing, warnings=warnings)


def _normal_cdf(x: float) -> float:
    """Standard normal CDF via erf — no scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_proportion_z_test(
    control_conversions: int,
    control_n: int,
    variant_conversions: int,
    variant_n: int,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Two-proportion z-test for an A/B result. Returns z, two-tailed p, lift.

    ``significant`` is p < alpha. Guards the degenerate cases (empty arm, zero
    pooled variance) by reporting not-significant rather than dividing by zero —
    an underpowered test should read as "no signal", never crash.
    """
    if control_n <= 0 or variant_n <= 0:
        return {"z": 0.0, "p_value": 1.0, "significant": False, "lift": 0.0,
                "reason": "an arm has no observations"}
    if not 0 <= control_conversions <= control_n:
        raise ValueError(
            f"control_conversions must be between 0 and control_n ({control_n}); "
            f"got {control_conversions}"
        )
    if not 0 <= variant_conversions <= variant_n:
        raise ValueError(
            f"variant_conversions must be between 0 and variant_n ({variant_n}); "
            f"got {variant_conversions}"
        )
    p_c = control_conversions / control_n
    p_v = variant_conversions / variant_n
    p_pool = (control_conversions + variant_conversions) / (control_n + variant_n)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / control_n + 1.0 / variant_n))
    if se == 0.0:
        return {"z": 0.0, "p_value": 1.0, "significant": False,
                "lift": round(p_v - p_c, 6), "reason": "zero pooled variance"}
    z = (p_v - p_c) / se
    p_value = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return {
        "z": round(z, 4),
        "p_value": round(p_value, 6),
        "significant": p_value < alpha,
        "lift": round(p_v - p_c, 6),
        "control_rate": round(p_c, 6),
        "variant_rate": round(p_v, 6),
    }


def check_experiment(payload: dict[str, Any]) -> dict[str, Any]:
    """Router for the experiment tool: review a design, a result, or both.

    ``payload`` may carry ``design`` (a dict of the five design fields) and/or
    ``result`` (control/variant conversion counts). Whichever is present is
    evaluated; at least one must be.
    """
    payload = payload or {}
    out: dict[str, Any] = {}
    if "design" in payload:
        out["design_review"] = review_experiment_design(payload["design"]).to_dict()
    if "result" in payload:
        r = payload["result"] or {}
        out["result"] = two_proportion_z_test(
            int(r.get("control_conversions", 0)),
            int(r.get("control_n", 0)),
            int(r.get("variant_conversions", 0)),
            int(r.get("variant_n", 0)),
            alpha=float(r.get("alpha", 0.05)),
        )
    if not out:
        raise ValueError("check_experiment needs a 'design' and/or a 'result'")
    return out


# ===========================================================================
# Positioning — the Moore template
# ===========================================================================

_POSITIONING_FIELDS = (
    "target", "need", "product", "category", "benefit", "alternative", "differentiator",
)


def draft_positioning(**fields: Any) -> dict[str, Any]:
    """Fill Geoffrey Moore's positioning template from the supplied fields.

    "For [target] who [need], [product] is a [category] that [benefit]. Unlike
    [alternative], [differentiator]." Missing fields are listed and rendered as
    a bracketed placeholder in the statement, so a half-filled draft is visibly
    incomplete rather than quietly asserting a claim the venture never made.
    """
    vals = {f: str(fields.get(f) or "").strip() for f in _POSITIONING_FIELDS}
    missing = [f for f in _POSITIONING_FIELDS if not vals[f]]

    def slot(name: str) -> str:
        return vals[name] if vals[name] else f"[{name}]"

    statement = (
        f"For {slot('target')} who {slot('need')}, {slot('product')} is a "
        f"{slot('category')} that {slot('benefit')}. Unlike {slot('alternative')}, "
        f"{slot('differentiator')}."
    )
    return {"statement": statement, "missing": missing, "complete": not missing}


# ===========================================================================
# Decision framing — RECOMMEND, do not walk through the gate
# ===========================================================================

# Substrings that mark an action as a human's to dispose, not the agent's to take.
# Drawn from the methodology's standing division (RECOMMEND phase).
_GATED_MARKERS = (
    "merge to main", "merge to default", "merge to master", "deploy to prod",
    "production", "restart", "spend", "pay", "purchase", "buy ", "budget",
    "ads", "hire", "fire", "offer", "customer", "investor", "candidate",
    "access", "permission", "grant", "credential", "api key", "secret",
)


def classify_action(action: str | None) -> str:
    """"gated" (human disposes) or "free" (agent drives), by the standing division.

    Consequences that land on someone else — money, merges to a default branch,
    production changes, people decisions, external conversations, access grants —
    are gated. Everything else the agent drives freely. Ambiguity leans gated:
    a missing or empty action cannot be shown safe, so it gates.
    """
    a = (action or "").lower()
    if not a.strip():
        return "gated"
    return "gated" if any(m in a for m in _GATED_MARKERS) else "free"


@dataclass
class DecisionFrame:
    """A decision framed for a human gate: the question, the cases, the flip."""

    question: str
    options: list[dict[str, str]]     # [{"name", "case_for"}, ...]
    default: str | None = None
    recommendation: str | None = None
    flip_conditions: list[str] = field(default_factory=list)
    gated: bool = True
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "options": [dict(o) for o in self.options],
            "default": self.default,
            "recommendation": self.recommendation,
            "flip_conditions": list(self.flip_conditions),
            "gated": self.gated,
            "warnings": list(self.warnings),
        }


def frame_decision(
    *,
    question: str,
    options: list[dict[str, Any]],
    default: str | None = None,
    recommendation: str | None = None,
    flip_conditions: list[str] | None = None,
    action: str | None = None,
) -> DecisionFrame:
    """Frame a decision without making it.

    Enforces the shape a good frame needs: a real question, at least two options
    each with the strongest case *for* it (including the disfavoured one), and —
    if a recommendation is given — the conditions under which it would flip. It
    validates structure, never the substance of the call; that stays human.

    Raises ValueError on a malformed frame (no question, < 2 options, an option
    with no name, or a recommendation naming an option that does not exist).
    """
    if not (question or "").strip():
        raise ValueError("a decision frame needs a question with a default, not a topic")

    norm: list[dict[str, str]] = []
    warnings: list[str] = []
    for opt in options or []:
        name = str(opt.get("name", "")).strip()
        if not name:
            raise ValueError("every option needs a name")
        case_for = str(opt.get("case_for", "")).strip()
        if not case_for:
            warnings.append(f"option {name!r} has no case_for — frame the strongest case for it too")
        norm.append({"name": name, "case_for": case_for})

    if len(norm) < 2:
        raise ValueError("a decision needs at least two options to be a decision")

    names = {o["name"] for o in norm}
    if recommendation is not None and recommendation not in names:
        raise ValueError(f"recommendation {recommendation!r} is not one of the options {sorted(names)}")
    if default is not None and default not in names:
        warnings.append(f"default {default!r} is not one of the options")
    if recommendation is not None and not (flip_conditions or []):
        warnings.append("a recommendation with no flip conditions hides its own uncertainty")

    return DecisionFrame(
        question=question.strip(),
        options=norm,
        default=default,
        recommendation=recommendation,
        flip_conditions=list(flip_conditions or []),
        gated=classify_action(action) == "gated",
        warnings=warnings,
    )
