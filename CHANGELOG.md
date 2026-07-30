# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `LICENSE` in `hermes-skill/` and `hermes-plugin/`. Swarm Map installs those two as **whole
  subdirectory trees**, not the repository root, so a root-only licence left an installed
  artifact unlicensed in place. CI fails if either goes missing.

  Not `docker/`: it is the registry's `soul` source, and that path extracts exactly one file
  (`SOUL.template.md`, written out as `SOUL.md`) and discards the rest of the clone. No licence
  can travel with it by that mechanism.
- A `release-audit` CI job: full-tree scan with the semantic layer **mandatory**
  (`--require-semantic` exits non-zero when the key is absent rather than degrading to a
  deterministic-only pass). `workflow_dispatch` is the gate — run it green against the release
  candidate *before* tagging. The `v*` tag trigger is an alarm, not a gate: a tag is public the
  moment it exists, and the template registry pins by tag name.

### Changed

- Sanitization scope widened from `docker/SOUL` to all of `docker/`. The narrower prefix
  meant `docker/instance-setup.sh` and `docker/Dockerfile` were never seen by the semantic
  layer — and those were the files that carried content the public-hygiene pass removed.
- The semantic layer now memoises verdicts on a content hash, so **byte-identical files get an
  identical verdict by construction**. On 2026-07-31 three byte-identical `LICENSE` files
  received two different verdicts within a single run — a gate that blocks at random can also
  pass at random. (`temperature` is not the lever: it is deprecated on this model family and
  the API rejects it.) This does not stabilise judgment *across* runs, which is why a semantic
  hit exits `123` — "needs human review" — rather than `1`, "secret found". It is a review
  prompt, not a verdict.
- The package's own identity — the maintaining org, this repository's name, its MIT copyright
  line, and the runtime it targets by design — is now explicitly allow-listed for the semantic
  layer. A *different* venture's org or repo still flags. Without this the full-tree release
  audit was guaranteed to fail: 13 of the 23 files in semantic scope name the publishing org.
- `README.md` no longer claims instance data *cannot* reach the shared package. `.gitignore`
  is a default, not a seal; `git add -f` overrides it. The sanitization gate is the half of
  the model that actually enforces.

### Notes on `v0.1.0`

`v0.1.0` was tagged at `6a0dec6`, one commit **before** the public-hygiene pass that added
the MIT licence and corrected several overstated claims about what the sanitization gate
enforces. Swarm Map's template registry pinned that tag, so installs resolved to the
pre-hygiene tree.

On 2026-07-31 the tag was re-pointed to `e85fb67` (the hygiene commit, and a direct
descendant, so no commit was orphaned). This repaired the registry pin without a registry
change, since it pins by tag name.

What is checkable about the blast radius: no GitHub release was ever cut, and the repository
has no stars and no forks. Clone traffic over the preceding fortnight was **57 clones from 30
unique cloners** — much of it plausibly CI and maintainer machines, but the honest statement is
that we do not know whether anything installed the pre-hygiene tree, not that nothing did. A
Swarm Map install is a shallow `git clone --branch v0.1.0`, which leaves no star behind.

The lesson, recorded because the failure was invisible to every check we had: the tag and
the branch had diverged by exactly one commit, and nothing in CI ever looked at the tree
being *released* — only at diffs on the way in. Hence `release-audit`.

## [0.1.0] — 2026-07-21

First public release, tagged at `6a0dec6`. **The tag was re-pointed to `e85fb67` on 2026-07-31**
(see the note above), so `v0.1.0` today resolves to a tree one commit ahead of what was
originally published under that name.

### Added

- The `FRAME → GATHER → ASSESS → RECOMMEND → HANDOFF` lifecycle as an executable
  methodology, applied to every unit of work from a two-hour research question to a
  multi-week PMF experiment.
- Seven tools in `hermes-plugin/`: transcript fetch, task routing, PMF assessment,
  retention read, experiment check, positioning draft, decision framing.
- Per-duty skills for PMF work and for turning meeting transcripts into warm updates and
  candidate tasks.
- Two-layer sanitization gate — a deterministic secrets/PII layer that fails closed, and an
  LLM semantic layer for venture particulars — with self-tests and a CI workflow.
- MIT licence; open-core posture, with hosting as the paid tier and nothing in the package
  crippled to sell an upgrade.

[Unreleased]: https://github.com/NimbleCoOrg/agentic-startup-generalist/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/NimbleCoOrg/agentic-startup-generalist/releases/tag/v0.1.0
