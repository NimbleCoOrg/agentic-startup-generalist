---
name: startup-generalist-pmf
description: Design and read the experiments that tell a venture whether the thing is working — stage-honest assessment, activation/retention measurement, falsifiable bets, and evidence for the ship/hold/kill/narrow gate. Use when asked whether there is product-market fit, whether a metric is good, what to measure, or whether to scale something.
version: 0.1.0
author: NimbleCo
license: MIT
metadata:
  hermes:
    tags: [pmf, product, metrics, experiments, startup]
    related_skills:
      - startup-generalist-methodology
---

# Product-Market Fit: Evidence, Not Vibes

PMF is the only question an early venture must answer, and the easiest one to fake an
answer to. The failure mode is not ignorance — it is a team that has assembled real
numbers into a story they already believed. This skill exists to make that harder. It
backs the duty's tools — `sg_assess_pmf`, `sg_read_retention`, `sg_check_experiment` —
but the discipline below is the point; the tools are replaceable.

The agent does **not** decide whether a venture has PMF. It assembles the evidence, names
what the evidence cannot support, and frames the call. See the RECOMMEND phase in
[`startup-generalist-methodology`](./SKILL.md).

## Stage honesty comes first

Before any metric, establish what stage the thing is actually at. Most PMF confusion is a
stage error: judging an Idea-stage product by Scale-stage metrics, or — far more common
and far more expensive — **running a Launch-stage playbook on an MVP-stage product**.

A rough ladder, and the question each stage is actually answering:

| Stage | The live question | What evidence looks like |
|---|---|---|
| **Idea** | Is this problem real and worth solving? | Users describe the pain unprompted; they have hacked together a workaround |
| **MVP** | Does our thing solve it *at all*, for anyone? | A small number of users use it repeatedly without being asked |
| **Launch** | Does it solve it *reliably*, for a definable group? | Retention curve flattens; you can say who it is for and who it is not |
| **Scale** | Can we reliably *get more* of that group? | Acquisition works without founder heroics; unit economics hold |

**Judge the stage by evidence, not by intent or elapsed time — and not by revenue.** A
product with paying customers can still be MVP-stage if usage depends on the founder
personally intervening; founder-dependence downgrades the stage regardless of the
top-line. Saying so is uncomfortable and is usually the most valuable thing in the
report — a team scaling an MVP burns the runway that would have bought the fix.

State the stage explicitly, with the evidence, before recommending anything.

## The measurement floor

A venture that cannot measure activation and retention cannot know whether it has PMF —
it can only feel confident. If the floor is missing, **say so and stop**; do not
substitute proxies and present the result as a fit signal. Establishing the floor *is*
the recommendation.

The floor is four definitions, written down and agreed before the numbers are read:

1. **The core action** — the single thing a user does that delivers the value. Not a
   login. Not a page view. The thing they came for.
2. **Activation** — the point a new user has plausibly felt the value. Define it as a
   concrete threshold (did the core action N times within M days), not as a feeling.
3. **Retention** — are they still doing the core action later? Cohort by signup period.
   Pick horizons that match the product's natural frequency — a daily tool and a
   quarterly one are not comparable on the same axis.
4. **The counted population** — who is in the denominator, and who was excluded and why.
   Most flattering metrics are denominator tricks.

Write these into the venture's overlay once agreed, so successive sessions measure the
same thing. A definition that drifts between reports destroys the comparison that made
the metric worth having.

## Reading a retention curve

Retention is the least gameable PMF signal available, which is why it is worth the
trouble.

- **Flattens above zero** — some group keeps coming back. This is the fit signal. Ask
  *who they are*: a flat tail among a definable segment is early PMF for that segment,
  even if the aggregate looks poor. The aggregate curve hides the finding.
- **Decays to zero** — no fit yet, regardless of growth. Acquisition can hide this for a
  long time; a rising top-line over a decaying curve is the single most expensive
  illusion in an early venture.
- **Too early to say** — the honest reading more often than teams like. If the cohort is
  small or young, the curve is noise, not signal; say so and give the date the answer
  arrives.

Segment before concluding. "No PMF" and "PMF with a segment we are not targeting" produce
opposite decisions and look identical in aggregate.

## Designing a bet worth running

An experiment that cannot come back negative is not an experiment; it is a press release
with a sample size. Before running one, write down:

- **The claim**, stated so it could be false
- **The prediction**, with a number and a date
- **The kill condition** — what result would make us stop. Agree it *in advance*, in
  writing. A kill condition invented after the result is a rationalization.
- **The cost of being wrong**, in runway
- **What we do differently** on each outcome — the differential action. If the answer is
  "nothing," do not run it — you already know, or you do not care.

Prefer the cheapest experiment that could falsify the claim. Prefer the one that fails
fast over the one that fails comprehensively.

## Frame the ship/hold/kill/narrow gate

PMF work terminates in a decision that belongs to the founder: **ship, hold, kill, or
narrow**. Produce a recommendation with caveats, per the methodology's RECOMMEND phase:

- The stage, with the evidence for that call
- What the numbers support — and, separately, what they do **not**
- The strongest case for each option, including the one you disfavour
- What you would need to know to be more sure, and whether it is worth the cost
- Your recommendation, and the conditions that would flip it

**"Narrow" is the most under-used option.** A product with no PMF often contains one with
PMF for a smaller group. Check for that before recommending a kill.

**Inconclusive is a real answer.** If the evidence cannot yet carry the call, say so and
pair it with a concrete next step — the cohort that has to mature, the definition that has
to be agreed, the number that has to be instrumented — and the date the answer arrives.
An honest "not yet" beats a confident reading the numbers cannot support.

## Honesty pressure

Notice these; they are the recurring ways a PMF report goes wrong:

- **Vanity metrics** — cumulative totals that only rise: signups, page views, stars. They
  cannot fall, so they carry no information.
- **Survivorship** — measuring only the users who stayed
- **Founder-powered usage** — retention that depends on a human chasing people. Real, but
  it is a service, not a product. Distinguish them explicitly.
- **Denominator drift** — the counted population quietly changing between cohorts or reports
- **Enthusiasm as evidence** — "they loved the demo" is not usage. Interest is not fit.
  What did they do afterwards, unprompted?
- **The metric that moved** — reporting whichever number happened to look good. If it was
  not named in advance, it is a finding to investigate, not a result to report.

If asked to make the numbers look better rather than truer, say so plainly and offer the
truer version. A venture that misreads its own fit signal loses the ability to correct —
and it will spend real money on the misreading. That is the whole cost of getting this
wrong, and it is why this skill's job is to be unwelcome sometimes.
