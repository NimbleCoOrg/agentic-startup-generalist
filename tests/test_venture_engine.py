"""Tests for the genericized venture-methodology engine (engine/venture.py).

These exercise the deterministic core the sg_* methodology tools call into:
the Sean Ellis / stage-honest PMF read, retention-curve classification, a bet's
falsifiability and A/B significance, the Moore positioning template, and the
gate-framing for a human decision. All pure, stdlib-only — no LLM, no network.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.venture import (  # noqa: E402
    MIN_SURVEY_RESPONSES,
    RET_DECAYS,
    RET_FLATTENS,
    RET_INCONCLUSIVE,
    RET_TOO_EARLY,
    SEAN_ELLIS_THRESHOLD,
    STAGES,
    assess_pmf,
    check_experiment,
    classify_action,
    draft_positioning,
    frame_decision,
    read_retention,
    review_experiment_design,
    sean_ellis_score,
    two_proportion_z_test,
)


# ---- Sean Ellis scoring -----------------------------------------------------

def test_sean_ellis_threshold_is_forty():
    assert SEAN_ELLIS_THRESHOLD == 40.0


def test_sean_ellis_strong_at_or_above_forty():
    # 4 of 10 "very" = 40% exactly → strong (>= threshold).
    responses = ["very disappointed"] * 4 + ["somewhat"] * 3 + ["not at all"] * 3
    got = sean_ellis_score(responses)
    assert got["pct_very"] == 40.0
    assert got["verdict"] == "strong"
    assert got["counted"] == 10


def test_sean_ellis_weak_below_forty():
    responses = ["very"] * 3 + ["somewhat"] * 7
    got = sean_ellis_score(responses)
    assert got["pct_very"] == 30.0
    assert got["verdict"] == "weak"


def test_sean_ellis_drops_blanks_from_denominator():
    # Blank/garbage responses must not silently pad the denominator.
    got = sean_ellis_score(["very", "", "   ", "banana", "not"])
    assert got["counted"] == 2  # only "very" and "not" are valid buckets
    assert got["dropped"] == 3
    assert got["pct_very"] == 50.0


def test_sean_ellis_empty_is_inconclusive_not_zero_division():
    got = sean_ellis_score([])
    assert got["pct_very"] is None
    assert got["verdict"] == "inconclusive"


# ---- assess_pmf -------------------------------------------------------------

def test_assess_pmf_rejects_unknown_claimed_stage():
    with pytest.raises(ValueError):
        assess_pmf(claimed_stage="unicorn")


def test_assess_pmf_rejects_unknown_retention_signal():
    # An unrecognized retention_signal must fail loud, not be silently dropped
    # from the signal/stage derivation while still echoed in the output.
    with pytest.raises(ValueError):
        assess_pmf(retention_signal="sideways")


def test_assess_pmf_derives_stage_from_evidence_not_claim():
    # The team claims launch, but supplies only a survey — the evidence supports
    # MVP at most, and the mismatch surfaces as a caveat instead of being trusted.
    a = assess_pmf(claimed_stage="launch", responses=["very"] * 5 + ["not"] * 5)
    assert a.stage == "mvp"
    assert a.claimed_stage == "launch"
    assert any("not supported by the evidence" in c for c in a.caveats)
    assert a.sean_ellis_pct == 50.0
    assert a.signal == "strong"


def test_assess_pmf_flat_retention_evidences_launch():
    a = assess_pmf(claimed_stage="launch", responses=["very"] * 5 + ["not"] * 5,
                   retention_signal="flattens_above_zero")
    assert a.stage == "launch"          # evidence agrees with the claim
    assert not any("not supported" in c for c in a.caveats)
    assert any("flattens" in b for b in a.stage_basis)


def test_assess_pmf_founder_powered_caps_stage_at_mvp():
    # Flat retention normally evidences launch — but founder-powered usage means
    # the reliability is the founder, not the product.
    a = assess_pmf(retention_signal="flattens_above_zero", founder_powered=True)
    assert a.stage == "mvp"
    assert any("founder-powered" in b for b in a.stage_basis)


def test_assess_pmf_never_awards_scale():
    # Even maximal inputs cannot evidence scale — that takes acquisition and
    # unit-economics data this tool does not see.
    a = assess_pmf(claimed_stage="scale", responses=["very"] * 10,
                   retention_signal="flattens_above_zero")
    assert a.stage == "launch"
    assert any("not supported by the evidence" in c for c in a.caveats)


def test_assess_pmf_decaying_retention_overrides_rosy_survey():
    # Retention is the least gameable signal: a decaying curve wins over a
    # survey that would otherwise read "strong".
    a = assess_pmf(claimed_stage="launch", responses=["very"] * 9 + ["not"],
                   retention_signal="decays_to_zero")
    assert a.signal == "no_fit"
    assert a.stage == "mvp"
    assert any("decays" in c for c in a.caveats)


def test_assess_pmf_too_early_retention_forces_too_early():
    a = assess_pmf(claimed_stage="mvp", responses=["very"] * 9 + ["not"],
                   retention_signal="too_early")
    assert a.signal == "too_early"


def test_assess_pmf_no_evidence_is_idea_stage_and_inconclusive():
    a = assess_pmf()
    assert a.signal == "inconclusive"
    assert a.stage == "idea"
    assert a.sean_ellis_pct is None
    assert any("no usage or survey evidence" in b for b in a.stage_basis)


def test_assess_pmf_founder_powered_adds_caveat_without_hiding_number():
    a = assess_pmf(responses=["very"] * 5 + ["not"] * 5, founder_powered=True)
    assert a.sean_ellis_pct == 50.0  # number preserved
    assert any("founder-powered" in c for c in a.caveats)


def test_assess_pmf_scaling_without_fit_warns_about_runway():
    a = assess_pmf(claimed_stage="scale", responses=["very"],
                   retention_signal="decays_to_zero")
    assert a.signal == "no_fit"
    assert any("runway" in c for c in a.caveats)


def test_assess_pmf_to_dict_roundtrips():
    d = assess_pmf(claimed_stage="launch",
                   responses=["very"] * 5 + ["not"] * 5).to_dict()
    assert set(d) == {"stage", "signal", "sean_ellis_pct", "retention_signal",
                      "claimed_stage", "survey_counted", "survey_dropped",
                      "stage_basis", "evidence", "caveats"}
    assert "launch" in STAGES


def test_assess_pmf_small_survey_is_inconclusive_with_caveat():
    # One enthusiastic response must not read as strong fit at 100%.
    a = assess_pmf(responses=["very"])
    assert a.signal == "inconclusive"
    assert a.sean_ellis_pct == 100.0  # number preserved, never trusted
    assert a.survey_counted == 1
    assert any(f"only 1" in c and str(MIN_SURVEY_RESPONSES) in c for c in a.caveats)


def test_assess_pmf_surfaces_counted_and_dropped():
    a = assess_pmf(responses=["very"] * 4 + ["not"] * 2 + ["banana"])
    assert a.survey_counted == 6
    assert a.survey_dropped == 1
    assert a.signal == "strong"
    assert any("dropped" in c for c in a.caveats)


def test_assess_pmf_all_unparseable_responses_reported_honestly():
    # Responses were supplied — the caveat and stage basis must not claim
    # nothing was supplied.
    a = assess_pmf(responses=["banana", "kiwi"])
    assert a.signal == "inconclusive"
    assert a.stage == "idea"
    assert a.survey_counted == 0
    assert a.survey_dropped == 2
    assert not any("no Sean Ellis responses supplied" in c for c in a.caveats)
    assert any("none parseable" in c for c in a.caveats)
    assert not any("no usage or survey evidence supplied" in b for b in a.stage_basis)


def test_assess_pmf_flattening_retention_alone_reads_strong():
    # Per the doctrine, flattening retention IS the fit signal — a silent
    # survey must not drag it down to inconclusive.
    a = assess_pmf(retention_signal="flattens_above_zero")
    assert a.signal == "strong"
    assert any("retention alone" in c for c in a.caveats)


# ---- read_retention ---------------------------------------------------------

def test_retention_flattens_above_zero():
    r = read_retention([1.0, 0.6, 0.45, 0.42, 0.41])
    assert r.signal == RET_FLATTENS
    assert r.floor is not None and r.floor > 0.0


def test_retention_decays_to_zero():
    r = read_retention([1.0, 0.5, 0.2, 0.05, 0.0])
    assert r.signal == RET_DECAYS
    assert r.floor is None


def test_retention_too_early_when_short():
    r = read_retention([1.0, 0.6])
    assert r.signal == RET_TOO_EARLY


def test_retention_too_early_when_cohort_small():
    r = read_retention([1.0, 0.5, 0.45, 0.44], cohort_size=5)
    assert r.signal == RET_TOO_EARLY
    assert "too small" in r.note


def test_retention_still_declining_reads_decay_not_flatten():
    # A tail that is still meaningfully sloping down has not settled.
    r = read_retention([1.0, 0.8, 0.6, 0.4, 0.2])
    assert r.signal == RET_DECAYS


def test_retention_rising_tail_is_inconclusive_not_decay():
    # A recovering curve must not read as the doctrine's strongest negative.
    r = read_retention([0.9, 0.3, 0.35, 0.45, 0.6])
    assert r.signal == RET_INCONCLUSIVE
    assert r.floor is None
    assert "rising" in r.note


def test_retention_rejects_percentage_scale():
    # [100, 40, ...] is a percentage curve — reading it as fractions would
    # classify it decays_to_zero. Tell the caller to pass fractions instead.
    with pytest.raises(ValueError, match="fraction"):
        read_retention([100, 40, 36, 35, 35])
    with pytest.raises(ValueError, match="fraction"):
        read_retention([1.0, 0.5, -0.1, 0.4])


# ---- experiment design + significance --------------------------------------

def test_experiment_design_falsifiable_when_complete():
    review = review_experiment_design({
        "claim": "onboarding email lifts activation",
        "prediction": "activation +5pp within 14 days",
        "kill_condition": "no lift after 500 signups",
        "cost_if_wrong": "two weeks of eng time",
        "action_on_each": "ship if up, revert if flat",
    })
    assert review.falsifiable is True
    assert review.missing == []


def test_experiment_design_missing_kill_condition_is_not_falsifiable():
    review = review_experiment_design({
        "claim": "x", "prediction": "y", "cost_if_wrong": "z", "action_on_each": "w",
    })
    assert review.falsifiable is False
    assert "kill_condition" in review.missing
    assert any("rationalized" in wmsg for wmsg in review.warnings)


def test_experiment_no_differential_action_warns():
    review = review_experiment_design({
        "claim": "x", "prediction": "y", "kill_condition": "k", "cost_if_wrong": "c",
    })
    assert "action_on_each" in review.missing
    assert any("don't run it" in wmsg for wmsg in review.warnings)


def test_two_proportion_z_test_detects_significant_lift():
    # 100/1000 vs 150/1000 is a clear, significant lift.
    res = two_proportion_z_test(100, 1000, 150, 1000)
    assert res["significant"] is True
    assert res["lift"] == pytest.approx(0.05, abs=1e-6)
    assert res["z"] > 0


def test_two_proportion_z_test_not_significant_on_noise():
    res = two_proportion_z_test(100, 1000, 102, 1000)
    assert res["significant"] is False


def test_two_proportion_z_test_guards_empty_arm():
    res = two_proportion_z_test(0, 0, 5, 100)
    assert res["significant"] is False
    assert res["p_value"] == 1.0


def test_two_proportion_z_test_rejects_conversions_outside_arm():
    # More conversions than observations must be a clear ValueError, not a raw
    # "math domain error" from the pooled-variance sqrt.
    with pytest.raises(ValueError, match="control_conversions"):
        two_proportion_z_test(25, 10, 5, 100)
    with pytest.raises(ValueError, match="variant_conversions"):
        two_proportion_z_test(5, 100, -1, 100)


def test_check_experiment_routes_design_and_result():
    out = check_experiment({
        "design": {"claim": "c", "prediction": "p", "kill_condition": "k",
                   "cost_if_wrong": "x", "action_on_each": "a"},
        "result": {"control_conversions": 100, "control_n": 1000,
                   "variant_conversions": 150, "variant_n": 1000},
    })
    assert out["design_review"]["falsifiable"] is True
    assert out["result"]["significant"] is True


def test_check_experiment_requires_something():
    with pytest.raises(ValueError):
        check_experiment({})


# ---- positioning ------------------------------------------------------------

def test_positioning_complete_statement():
    out = draft_positioning(
        target="solo founders", need="lose decisions made in meetings",
        product="the agent", category="ops copilot", benefit="turns calls into tracked tasks",
        alternative="a shared doc", differentiator="it proposes, a human disposes",
    )
    assert out["complete"] is True
    assert out["missing"] == []
    assert out["statement"].startswith("For solo founders who lose decisions")
    assert "Unlike a shared doc" in out["statement"]


def test_positioning_missing_fields_are_bracketed_and_listed():
    out = draft_positioning(target="solo founders", product="the agent")
    assert out["complete"] is False
    assert "need" in out["missing"] and "category" in out["missing"]
    assert "[need]" in out["statement"]  # visible placeholder, not a silent claim


# ---- decision framing -------------------------------------------------------

def test_classify_action_gates_money_and_merges():
    assert classify_action("spend $500 on ads") == "gated"
    assert classify_action("merge to main") == "gated"
    assert classify_action("email a customer") == "gated"
    assert classify_action("draft a PRD and open a PR to a feature branch") == "free"


def test_classify_action_missing_or_blank_leans_gated():
    # "Ambiguity leans gated": an action nobody named cannot be shown free.
    assert classify_action("") == "gated"
    assert classify_action("   ") == "gated"
    assert classify_action(None) == "gated"


def test_frame_decision_omitted_action_is_gated():
    frame = frame_decision(
        question="a or b?",
        options=[{"name": "a", "case_for": "x"}, {"name": "b", "case_for": "y"}],
    )
    assert frame.gated is True


def test_frame_decision_requires_question():
    with pytest.raises(ValueError):
        frame_decision(question="  ", options=[{"name": "a"}, {"name": "b"}])


def test_frame_decision_requires_two_options():
    with pytest.raises(ValueError):
        frame_decision(question="ship?", options=[{"name": "yes", "case_for": "x"}])


def test_frame_decision_recommendation_must_be_an_option():
    with pytest.raises(ValueError):
        frame_decision(
            question="ship?",
            options=[{"name": "ship", "case_for": "ready"}, {"name": "hold", "case_for": "risky"}],
            recommendation="kill",
        )


def test_frame_decision_valid_and_gated():
    frame = frame_decision(
        question="Ship v1 to the waitlist, or hold a week? Default: hold.",
        options=[
            {"name": "ship", "case_for": "momentum; the list is going cold"},
            {"name": "hold", "case_for": "one crash-on-signup bug still open"},
        ],
        default="hold",
        recommendation="hold",
        flip_conditions=["the signup crash is fixed and verified"],
        action="merge to main and deploy to production",
    )
    assert frame.gated is True
    assert frame.recommendation == "hold"
    assert frame.warnings == []  # complete frame, no nags


def test_frame_decision_recommendation_without_flip_warns():
    frame = frame_decision(
        question="raise price?",
        options=[{"name": "raise", "case_for": "margin"}, {"name": "keep", "case_for": "growth"}],
        recommendation="raise",
    )
    assert any("flip" in w for w in frame.warnings)


def test_frame_decision_missing_case_for_warns_not_raises():
    frame = frame_decision(
        question="a or b?",
        options=[{"name": "a", "case_for": "solid"}, {"name": "b"}],
    )
    assert any("case_for" in w for w in frame.warnings)
