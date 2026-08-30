#!/usr/bin/env python
"""Generate demo_cache/ so the public deployment needs no Anthropic key.

Run this locally, with both keys, after seeding. It performs every Claude call the
app would ever make against the frozen demo data and writes the results to
demo_cache/, which is committed. The deployed app then serves those artifacts and
spends nothing.

Retrieval is deliberately NOT cached: mem0 search runs live in the demo on the
mem0 key, so the Memory Inspector shows real memories and real relevance scores.

    python precompute.py              # everything
    python precompute.py maya         # one patient
    python precompute.py --answers    # curated answers only
"""
from __future__ import annotations

import os
import sys
import time

# Must be off, or we would "precompute" by reading a cache that does not exist yet.
os.environ["MEDLOG_DEMO"] = ""

from medlog import db, demo  # noqa: E402
from medlog.ask import ask  # noqa: E402
from medlog.brief.generate import generate  # noqa: E402
from medlog.config import get_settings  # noqa: E402
from medlog.context.assembler import full_history_prompt  # noqa: E402
from medlog.llm import count_tokens  # noqa: E402
from medlog.memory.client import MedLogMemory  # noqa: E402
from medlog.memory.reconcile import get_state  # noqa: E402
from medlog.safety.guardrails import ANSWER_SYSTEM  # noqa: E402


def precompute(names: list[str], answers_only: bool = False) -> None:
    s = get_settings()
    s.require("mem0_api_key", "anthropic_api_key")
    mem = MedLogMemory()
    spend = 0.0

    if not answers_only:
        stats = demo.load("context_stats") or {}
        for pid in names:
            print(f"\n{pid}")

            print("  reconciling (Opus, reads every memory)...", end="", flush=True)
            t0 = time.time()
            state = get_state(pid, force=True, memory=mem)
            demo.save(f"state_{pid}", state.model_dump())
            print(f" {len(state.medications)} meds, {len(state.conflicts)} conflicts, "
                  f"{len(state.patterns_to_raise)} patterns  ({time.time()-t0:.0f}s)")

            print("  generating brief...", end="", flush=True)
            b = generate(pid, memory=mem, save=False)
            demo.save(f"brief_{pid}", {
                "markdown": b.markdown, "since": b.since, "until": b.until,
                "entry_count": b.entry_count, "flags": b.flags,
                "state": b.state.model_dump(),
            })
            spend += b.usage.cost_usd if b.usage else 0
            print(f" {len(b.markdown)} chars, {len(b.flags)} flags")

            print("  counting full-history tokens...", end="", flush=True)
            stats[pid] = count_tokens(
                ANSWER_SYSTEM, full_history_prompt(pid, "What has changed since my last visit?"))
            print(f" {stats[pid]:,}")
        demo.save("context_stats", stats)

    # The entry -> memory links, so a cold deploy can render the Journal page's
    # category chips without re-deriving them from mem0.
    if not answers_only:
        links: dict[str, dict[str, list]] = {}
        for pid in names:
            by_date: dict[str, list] = {}
            for e in db.get_entries(pid, ascending=True):
                rows = db.memories_for_entry(e["id"])
                if rows:
                    by_date[e["entry_date"]] = [
                        {"id": r["memory_id"], "memory": r["memory"],
                         "categories": r["categories"]} for r in rows]
            links[pid] = by_date
            print(f"  {pid}: {sum(len(v) for v in by_date.values())} memory links "
                  f"across {len(by_date)} entries")
        demo.save("entry_memories", links)

    print("\ncurated answers")
    answers = demo.load("answers") or {}
    for pid in names:
        for q in demo.CURATED.get(pid, []):
            a = ask(pid, q, memory=mem, record=False)
            answers[demo.normalise(q)] = {
                "patient": pid, "question": q, "text": a.text,
                "usage": {
                    "input_tokens": a.usage.input_tokens if a.usage else 0,
                    "output_tokens": a.usage.output_tokens if a.usage else 0,
                    "model": a.usage.model if a.usage else "",
                    "latency_ms": round(a.usage.latency_ms) if a.usage else 0,
                },
            }
            spend += a.usage.cost_usd if a.usage else 0
            print(f"  [{pid}] {q[:58]:<58} {len(a.text):>5} chars")
    demo.save("answers", answers)

    print(f"\nWrote demo_cache/  ·  ~${spend:.2f} spent")
    still = demo.missing()
    print("Missing:", ", ".join(still) if still else "nothing — demo cache is complete")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    precompute(args or ["maya", "arjun", "rosa"], answers_only="--answers" in sys.argv)
