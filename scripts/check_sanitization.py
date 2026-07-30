"""Two-layer sanitization gate for a use-case agent package.

Layer 1 (deterministic): scans changed text for credentials / PII — API keys,
private keys, tokens, emails, phones, IPs. NO external dependencies. FAILS CLOSED.
Always runs, even offline / without an API key.

Layer 2 (semantic): sends content-bearing files (skills, souls, docs, prose) to
an LLM that flags operator/engagement *particulars* — names, case IDs, hostnames,
anything that would make a "generic" artifact actually specific to one operator.
Requires ANTHROPIC_API_KEY; skipped with a loud warning if unset (so local runs
work), REQUIRED in CI (pass --require-semantic to fail when the key is missing).
A key that is present but unusable — malformed, revoked, rate-limited, or the API
unreachable — is treated the same as unset: the layer "did not run", and
--require-semantic decides whether that is fatal. A green result never silently
means fewer layers ran than you think.

A flag routes to a human maintainer — it is advisory, not an automatic final
rejection. But the deterministic layer's hits (real secrets/PII) are hard fails.

Modes:
  check_sanitization.py a.md b.py        # explicit file list (CI diff mode)
  check_sanitization.py --full-tree      # every git-tracked file (gardener/audit)
  check_sanitization.py --all            # alias for --full-tree

Config: sanitize.config.json at repo root (see that file's comments).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- config

def load_config(root="."):
    path = os.path.join(root, "sanitize.config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        # Sensible defaults so the gate still runs on a fresh template.
        return {
            "package_kind": "SHARED, public agent package",
            "sensitive_prefixes": ["hermes-skill/", "hermes-plugin/", "docker/SOUL", "docs/"],
            "semantic": {"domain_noun": "operational engagement", "flag_examples": [],
                         "do_not_flag_examples": [], "model": "claude-opus-4-8"},
            "deterministic": {"enabled": True, "allow_substrings": []},
        }

# ---------------------------------------------------------------- layer 1: deterministic

# Conservative, low-false-positive credential/PII patterns. Each is (label, regex).
_DETERMINISTIC_PATTERNS = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("notion-token", re.compile(r"\bntn_[A-Za-z0-9]{20,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("us-phone", re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")),
    # E.164 international (e.g. a contact wired into config/SOUL): "+" + 7–15 digits,
    # no separators. The us-phone pattern only covers North-American formatting.
    ("intl-phone", re.compile(r"(?<!\d)\+\d{7,15}(?!\d)")),
    ("ipv4", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
]


def scan_deterministic(content, allow_substrings):
    """Return a list of (label, matched_text) for credential/PII hits, minus
    any line containing an allowlisted substring."""
    hits = []
    for label, pat in _DETERMINISTIC_PATTERNS:
        for m in pat.finditer(content):
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.end())
            line = content[line_start: line_end if line_end != -1 else len(content)]
            if any(allow in line for allow in allow_substrings):
                continue
            hits.append((label, m.group(0)))
    return hits

# ---------------------------------------------------------------- layer 2: semantic

def build_system_prompt(cfg):
    sem = cfg.get("semantic", {})
    kind = cfg.get("package_kind", "SHARED, public agent package")
    noun = sem.get("domain_noun", "operational engagement")
    flag = "\n".join(f"- {x};" for x in sem.get("flag_examples", [])) or \
        f"- any particular tied to one specific {noun};"
    keep = "\n".join(f"- {x};" for x in sem.get("do_not_flag_examples", [])) or \
        "- generic methodology, tool/API names, well-known public reference material;"
    return (
        f"You review proposed content for a {kind}. It must contain only generic "
        f"methodology and tooling. It must NOT contain particulars of any specific "
        f"{noun}.\n\nFlag the content if it contains any of:\n{flag}\n\n"
        f"Do NOT flag:\n{keep}\nWhen uncertain whether something is a particular vs. "
        f"generic, lean toward flagging so a human can decide.\n\nRespond with ONLY a "
        f'JSON object: {{"flagged": <bool>, "reasons": [<short strings>]}}.'
    )


def _extract_json(text):
    """Pull the verdict object out of a model reply that may carry prose or fences.

    The naive first-`{`-to-last-`}` span breaks on the single most common reply
    shape: a correct verdict followed by a sentence that happens to contain a
    brace. That span then holds `{...}\n\n...{...}` and fails with "Extra data",
    and a last-`{` retry lands on the brace *inside the prose* — so a perfectly
    good verdict is thrown away and the gate hard-fails with a parse error.

    Instead, walk every `{` and let the decoder consume exactly one value from
    that offset, taking the first object that actually looks like a verdict.
    That tolerates prose on both sides, ```json fences, nested braces, and a
    trailing second object, without ever guessing at where the object ends.
    """
    decoder = json.JSONDecoder()
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(obj, dict) and "flagged" in obj:
                return obj
        idx = text.find("{", idx + 1)
    shown = text if len(text) <= 400 else text[:400] + "…"
    raise ValueError(f"no verdict object in model reply: {shown!r}")


_ASSESS_CACHE = {}


def assess(content, client, filename, system_prompt, model):
    # Identical bytes MUST get an identical verdict. On 2026-07-31 three
    # byte-identical LICENSE files got two different verdicts inside a single
    # run, because each file is its own model call. That makes the gate a coin
    # flip: it can block at random and, worse, pass a dirty file at random.
    #
    # Memoising on a hash of (content, filename-independent) collapses duplicates
    # to one call and one verdict, by construction. `temperature` is NOT the fix
    # here — it is deprecated on this model family and the API rejects it.
    #
    # This does not make judgment stable ACROSS runs; nothing short of not using
    # a model would. That is why a semantic hit exits 123 ("needs human review")
    # rather than 1 ("secret found") — it is a review prompt, not a verdict.
    key = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
    if key in _ASSESS_CACHE:
        return _ASSESS_CACHE[key]
    msg = client.messages.create(
        model=model, max_tokens=1024, system=system_prompt,
        messages=[{"role": "user", "content": f"File: {filename}\n\n---\n{content}\n---"}],
    )
    verdict = _extract_json(msg.content[0].text)
    if "flagged" not in verdict:
        raise ValueError(f"model response missing 'flagged' key: {verdict!r}")
    reasons = verdict.get("reasons", [])
    if isinstance(reasons, str):
        reasons = [reasons]
    result = {"flagged": bool(verdict["flagged"]), "reasons": list(reasons)}
    _ASSESS_CACHE[key] = result
    return result


def api_key():
    """The semantic layer's credential, whitespace-stripped.

    A key pasted into a CI secret or a .env very often carries a trailing
    newline. An API key never legitimately contains surrounding whitespace, but
    an un-stripped one is sent as an HTTP header value and blows up deep in the
    transport as `LocalProtocolError: Illegal header value` — a traceback that
    says nothing about the real cause. Strip once, here, so both the
    is-it-present check and the client construction agree.
    """
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def _make_client():  # pragma: no cover - thin wrapper, mocked in tests
    import anthropic
    return anthropic.Anthropic(api_key=api_key())


def _report_det_hits(det_hits):
    """Print the deterministic SECRET/PII block.

    Called from the report section, and also before any early fail-closed return:
    a hard-fail credential hit is the single most actionable thing the gate can
    say, and it must not be swallowed just because the semantic layer separately
    failed to run.
    """
    for rel, hits in det_hits.items():
        print(f"SECRET/PII {rel}:")
        for label, text in hits:
            shown = text if len(text) < 12 else text[:6] + "…"
            print(f"  - {label}: {shown}")


def _describe_failure(exc):
    """Render an exception plus its cause chain, with a hint where we can give one.

    The Anthropic SDK wraps transport problems in `APIConnectionError`, whose own
    message is the useless string "Connection error." The actionable detail —
    e.g. `LocalProtocolError: Illegal header value` — is only on `__cause__`, so
    printing just the outer exception hides the one fact you need.
    """
    chain, seen, cur = [], set(), exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        # httpx re-raises the same error through several layers; repeating an
        # identical line three times buries the hint rather than adding detail.
        line = f"{type(cur).__name__}: {cur}"
        if line not in chain:
            chain.append(line)
        cur = cur.__cause__ or cur.__context__
    detail = " <- caused by ".join(chain)

    if "Illegal header value" in detail:
        detail += (
            "\n  HINT: the API key contains a character that is illegal in an HTTP "
            "header — stray whitespace, a trailing newline, or a newline in the "
            "middle from a key pasted across two lines. Surrounding whitespace is "
            "stripped automatically, so an interior newline is the likely cause: "
            "re-enter the ANTHROPIC_API_KEY secret as a single unbroken line."
        )
    elif "APIStatusError" in detail or "authentication" in detail.lower():
        detail += ("\n  HINT: the key was well-formed but rejected. Check that it is "
                   "current and has access to the configured model.")
    return detail

# ---------------------------------------------------------------- file selection

def select_sensitive_files(paths, prefixes):
    """Content-bearing files for the SEMANTIC layer: anything under a sensitive
    prefix, plus top-level prose .md (README, CONTRIBUTING)."""
    out = []
    for p in paths:
        if p.startswith(tuple(prefixes)):
            out.append(p)
        elif p.endswith(".md") and "/" not in p:
            out.append(p)
    return out


def git_tracked_files(root="."):
    """All git-tracked files, for --full-tree mode."""
    res = subprocess.run(["git", "-C", root, "ls-files"],
                         capture_output=True, text=True, check=True)
    return [ln for ln in res.stdout.splitlines() if ln.strip()]

# ---------------------------------------------------------------- main

def main(argv, root=".", client_factory=_make_client):
    args = list(argv)
    require_semantic = "--require-semantic" in args
    args = [a for a in args if a != "--require-semantic"]

    cfg = load_config(root)
    prefixes = cfg.get("sensitive_prefixes", [])
    det_cfg = cfg.get("deterministic", {})
    allow = det_cfg.get("allow_substrings", [])

    if args and args[0] in ("--full-tree", "--all"):
        candidates = git_tracked_files(root)
    elif args:
        candidates = args
    else:
        print("sanitization: no files given (use a file list or --full-tree).")
        return 0

    # ---- Layer 1: deterministic, over ALL candidate text files (fails closed)
    det_hits = {}
    skip_paths = tuple(det_cfg.get("skip_paths", []))
    if det_cfg.get("enabled", True):
        for rel in candidates:
            if skip_paths and rel.startswith(skip_paths):
                continue  # e.g. tests/ — legitimately holds credential-shaped fixtures
            path = os.path.join(root, rel)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
            except (UnicodeDecodeError, OSError):
                continue  # binary / unreadable — skip
            hits = scan_deterministic(content, allow)
            if hits:
                det_hits[rel] = hits

    # ---- Layer 2: semantic, over content-bearing files only
    sensitive = select_sensitive_files(candidates, prefixes)
    sem_flagged = {}
    sem_ran = False
    if sensitive:
        if api_key():
            system_prompt = build_system_prompt(cfg)
            model = cfg.get("semantic", {}).get("model", "claude-opus-4-8")
            # A key being present is not the same as the semantic layer working:
            # the key can be malformed, revoked, or rate-limited, and the model
            # can be unreachable. Treat that as "the layer did not run" and let
            # require_semantic decide whether that is fatal — never let an
            # unhandled transport traceback stand in for a verdict.
            try:
                client = client_factory()
                for rel in sensitive:
                    path = os.path.join(root, rel)
                    if not os.path.exists(path):
                        continue
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        content = fh.read()
                    verdict = assess(content, client, rel, system_prompt, model)
                    if verdict["flagged"]:
                        sem_flagged[rel] = verdict["reasons"]
                sem_ran = True
            except Exception as exc:  # noqa: BLE001 - any failure means "did not run"
                sem_flagged = {}
                detail = _describe_failure(exc)
                if require_semantic:
                    _report_det_hits(det_hits)
                    print(f"ERROR: the semantic layer could not run — {detail}\n"
                          f"--require-semantic is set, so failing closed rather than "
                          f"reporting a half-checked diff.")
                    if det_hits:
                        print("Note: the deterministic layer DID run and hard-failed "
                              "above — fix those hits regardless of the semantic layer.")
                    return 2
                print(f"WARNING: the semantic layer could not run — {detail}\n"
                      f"Continuing with the deterministic layer only. Venture "
                      f"particulars were NOT checked.")
        elif require_semantic:
            _report_det_hits(det_hits)
            print(f"ERROR: --require-semantic set but ANTHROPIC_API_KEY is missing, "
                  f"and {len(sensitive)} content-bearing file(s) need the semantic layer. "
                  f"Failing closed rather than reporting a half-checked diff.")
            if det_hits:
                print("Note: the deterministic layer DID run and hard-failed above — "
                      "fix those hits regardless of the semantic layer.")
            return 2
        else:
            print(f"WARNING: ANTHROPIC_API_KEY unset — semantic layer SKIPPED for "
                  f"{len(sensitive)} content-bearing file(s). The deterministic layer "
                  f"still ran, so secrets/PII are covered, but venture particulars are "
                  f"NOT. This result is not a full pass. Set the key, or pass "
                  f"--require-semantic to fail closed instead of warning.")

    # ---- report
    _report_det_hits(det_hits)
    for rel, reasons in sem_flagged.items():
        print(f"FLAGGED {rel}:")
        for r in reasons:
            print(f"  - {r}")
    clean = [r for r in sensitive if r not in sem_flagged and r not in det_hits]
    for rel in clean:
        print(f"ok      {rel}")

    if det_hits:
        print("\nsanitization: credentials/PII detected — HARD FAIL (remove before merge).")
        return 1
    if sem_flagged:
        print("\nsanitization: possible particulars found — needs human review.")
        return 1
    # Be precise about WHICH layers actually ran. "clean" from a deterministic-only
    # run is a weaker claim than "clean" from both layers, and the difference must
    # not be silent — that is how a gate reports green while doing half its job.
    if sem_ran:
        tail = " (both layers ran)"
    elif sensitive:
        tail = " — DETERMINISTIC ONLY; semantic layer did not run (see warning above)"
    else:
        tail = " (deterministic only; no content-bearing files in scope)"
    print(f"\nsanitization: clean{tail}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
