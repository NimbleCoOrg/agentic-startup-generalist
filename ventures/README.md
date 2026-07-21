# ventures/

This directory holds **per-venture private data** — query inputs, raw artifacts,
intermediate outputs, and any operational state that is specific to one venture the agent
serves (its board, metrics, team, roadmap, and the particulars behind them).

It is **gitignored** by `.gitignore` at the repo root.  Nothing placed here will be
committed, so it is safe to store sensitive operational data here while the agent works a
live venture.

## One directory per venture

`ventures/` is the domain-neutral home for these particulars — a startup's board, metrics,
team, and roadmap are its particulars and must never land in the shared package.  Give each
venture its own subdirectory, named by you:

```
ventures/
  {venture-slug}/            # one dir per venture, named by you
    artifacts/               # raw archived bytes from collectors (binary, gitignored)
    outputs/                 # processed results, reports, exports
    state.json               # local pipeline state/cache (gitignored)
    notes.md                 # operator notes — never committed
```

Nothing in this directory is ever passed through the sanitization gate
(`scripts/check_sanitization.py`) — that gate operates on committed code and
config only.  A venture's private operational data never touches it.

## The `.gitkeep` file

The empty `.gitkeep` file at this level exists solely to allow git to track the
directory while it is otherwise empty.  Delete it once you have real content here.
