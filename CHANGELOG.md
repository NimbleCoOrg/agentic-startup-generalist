# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `LICENSE` in `hermes-skill/`, `hermes-plugin/` and `docker/`. Swarm Map installs
  **subdirectories**, not the repository root, so a root-only licence left an installed
  artifact unlicensed in place. CI now fails if any of the three is missing.
- A `release-audit` CI job on every `v*` tag and on manual dispatch: full-tree scan with
  the semantic layer **mandatory** (`--require-semantic`, which exits non-zero when the key
  is absent rather than degrading to a deterministic-only pass).

### Changed

- Sanitization scope widened from `docker/SOUL` to all of `docker/`. The narrower prefix
  meant `docker/instance-setup.sh` and `docker/Dockerfile` were never seen by the semantic
  layer — and those were the files that carried content the public-hygiene pass removed.
- `README.md` no longer claims instance data *cannot* reach the shared package. `.gitignore`
  is a default, not a seal; `git add -f` overrides it. The sanitization gate is the half of
  the model that actually enforces.

### Notes on `v0.1.0`

`v0.1.0` was tagged at `6a0dec6`, one commit **before** the public-hygiene pass that added
the MIT licence and corrected several overstated claims about what the sanitization gate
enforces. No GitHub release was ever cut from it, and the repository had no stars or forks,
so nothing had consumed it — but Swarm Map's template registry pinned that tag, meaning
installs resolved to the pre-hygiene tree.

On 2026-07-31 the tag was re-pointed to `e85fb67` (the hygiene commit, and a direct
descendant, so no commit was orphaned). This repaired the registry pin without a registry
change, since it pins by tag name.

The lesson, recorded because the failure was invisible to every check we had: the tag and
the branch had diverged by exactly one commit, and nothing in CI ever looked at the tree
being *released* — only at diffs on the way in. Hence `release-audit`.

## [0.1.0] — 2026-07-21

First public release. Content is the `e85fb67` tree (see above).

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
