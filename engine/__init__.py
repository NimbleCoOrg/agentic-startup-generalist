"""agentic-startup-generalist engine — the package's importable core.

Four modules, one pipeline:

  pipeline_types  — the normalized model: Transcript, Item (five kinds),
                    Extraction, Proposal. The contract between the pipeline's
                    replaceable ends.
  sources         — where a transcript comes from: pasted text, a local file,
                    a Notion page, or any remote system via an injected reader.
  surfaces        — where extracted items land: a markdown file, a tended
                    board, or an external tracker via a config-declared adapter.
  router          — reconcile items against a surface (create/update/covered)
                    and propose; apply is gated and refuses live boards.
  venture         — the pure-logic evidence engines: stage-honest PMF read,
                    Sean Ellis scoring, retention-curve reading, experiment
                    falsifiability checks, positioning drafts, decision frames.

Everything is stdlib-only and offline-testable. Import from the submodules
directly (``from engine.pipeline_types import Item``) — this package exposes no
top-level convenience names, so the import graph stays explicit.
"""
