#!/usr/bin/env python
"""Ablation + red-team harness.

Three arms answer the same questions:

  no_memory     the question alone -- the floor, and the honest baseline for
                "what does a chatbot without your history actually know?"
  full_context  every raw journal entry pasted into the prompt -- the ceiling
                on accuracy and the thing MedLog has to justify itself against
  medlog        pinned facts + reconciled state + retrieved memories

Measured: fact recall (deterministic regex over required facts), correctness
(LLM judge against a gold answer), prompt tokens, latency, cost.

    python evals/run.py                  # ablation, all questions
    python evals/run.py --limit 5        # quick pass
    python evals/run.py --arms medlog    # one arm
    python evals/run.py --redteam        # safety suite instead
    python evals/run.py --no-cache       # ignore cached results
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from medlog.ask import ask  # noqa: E402
from medlog.config import get_settings  # noqa: E402
from medlog.context.assembler import full_history_prompt  # noqa: E402
from medlog.llm import Usage, complete, count_tokens, parse  # noqa: E402
from medlog.memory.client import MedLogMemory  # noqa: E402
from medlog.safety.guardrails import ANSWER_SYSTEM  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CACHE = RESULTS / "cache.json"
ARMS = ["no_memory", "full_context", "medlog"]

NO_MEMORY_SYSTEM = (
    "You are a health assistant. Answer the patient's question. You have no access "
    "to their records. Be honest about what you do not know."
)


class Verdict(BaseModel):
    correct: bool = Field(description="Does the answer convey the substance of the gold answer?")
    reason: str = Field(description="One sentence.")


JUDGE = """\
You are scoring an assistant's answer against a gold answer drawn from a patient's journal.

Mark it correct only if it conveys the substantive content of the gold answer -- the right
drug, dose, dates, counts, or conclusion. Wording, length, and extra caveats do not matter.

Mark it incorrect if it contradicts the gold answer, invents specifics not in it, or
declines so thoroughly that the patient learns nothing the gold answer would have told them.
An honest "your record doesn't say" is correct ONLY when the gold answer also says nothing
is recorded.
"""


def _cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(c: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(c, indent=1))


def _key(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:20]


def recall(answer: str, patterns: list[str]) -> float:
    if not patterns:
        return 1.0
    hits = sum(1 for p in patterns if re.search(p, answer, re.I))
    return hits / len(patterns)


def run_arm(arm: str, q: dict, mem: MedLogMemory) -> dict:
    s = get_settings()
    t0 = time.perf_counter()

    if arm == "medlog":
        a = ask(q["patient"], q["question"], memory=mem, record=False)
        text, usage = a.text, a.usage or Usage(model=s.medlog_chat_model)
        retrieved = len(a.context.retrieved) if a.context else 0
    elif arm == "full_context":
        prompt = full_history_prompt(q["patient"], q["question"])
        text, usage = complete(ANSWER_SYSTEM, prompt, model=s.medlog_chat_model,
                               max_tokens=2000, effort="medium")
        retrieved = 0
    else:
        text, usage = complete(NO_MEMORY_SYSTEM, q["question"], model=s.medlog_chat_model,
                               max_tokens=2000, effort="medium")
        retrieved = 0

    return {
        "answer": text,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "latency_ms": (time.perf_counter() - t0) * 1000,
        "cost_usd": usage.cost_usd,
        "retrieved": retrieved,
        "fact_recall": recall(text, q.get("must_match") or []),
    }


def judge(q: dict, answer: str) -> bool:
    v, _ = parse(
        JUDGE,
        f"Question: {q['question']}\n\nGold answer:\n{q['gold']}\n\nAssistant's answer:\n{answer}",
        Verdict, model=get_settings().medlog_reasoning_model, max_tokens=1000, effort="low",
    )
    return v.correct


def ablation(limit: int | None, arms: list[str], use_cache: bool) -> dict:
    qs = yaml.safe_load((HERE / "questions.yaml").read_text())[: limit or None]
    mem = MedLogMemory()
    cache = _cache() if use_cache else {}
    rows: list[dict] = []

    for i, q in enumerate(qs, 1):
        for arm in arms:
            ck = _key("v2", arm, q["id"], q["question"])
            if ck in cache:
                r = cache[ck]
            else:
                r = run_arm(arm, q, mem)
                r["correct"] = judge(q, r["answer"])
                cache[ck] = r
                _save_cache(cache)
            rows.append({"id": q["id"], "patient": q["patient"], "arm": arm, **r})
            mark = "o" if r["correct"] else "x"
            print(f"\r[{i}/{len(qs)}] {q['id'][:28]:<28} {arm:<13} {mark} "
                  f"recall={r['fact_recall']:.0%} tok={r['input_tokens']:>6,}", flush=True)
    print()
    return {"rows": rows, "n_questions": len(qs)}


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        out.append({
            "arm": arm,
            "n": len(rs),
            "correct_pct": 100 * sum(r["correct"] for r in rs) / len(rs),
            "fact_recall_pct": 100 * statistics.mean(r["fact_recall"] for r in rs),
            "median_input_tokens": int(statistics.median(r["input_tokens"] for r in rs)),
            "p50_latency_ms": int(statistics.median(r["latency_ms"] for r in rs)),
            "p95_latency_ms": int(sorted(r["latency_ms"] for r in rs)[int(0.95 * len(rs)) - 1]),
            "cost_per_query_usd": statistics.mean(r["cost_usd"] for r in rs),
        })
    return out


def print_table(summary: list[dict]) -> None:
    print(f"\n{'arm':<14}{'correct':>9}{'facts':>8}{'tokens':>10}{'p50 ms':>9}{'p95 ms':>9}{'$/query':>10}")
    print("-" * 69)
    for s in summary:
        print(f"{s['arm']:<14}{s['correct_pct']:>8.0f}%{s['fact_recall_pct']:>7.0f}%"
              f"{s['median_input_tokens']:>10,}{s['p50_latency_ms']:>9,}"
              f"{s['p95_latency_ms']:>9,}{s['cost_per_query_usd']:>10.4f}")
    full = next((s for s in summary if s["arm"] == "full_context"), None)
    ml = next((s for s in summary if s["arm"] == "medlog"), None)
    if full and ml and ml["median_input_tokens"]:
        print(f"\nMedLog uses {full['median_input_tokens']/ml['median_input_tokens']:.1f}x "
              f"fewer prompt tokens than pasting the whole journal, at "
              f"{ml['correct_pct']:.0f}% vs {full['correct_pct']:.0f}% correct.")


def redteam(limit: int | None) -> dict:
    cases = yaml.safe_load((HERE / "redteam.yaml").read_text())[: limit or None]
    mem = MedLogMemory()
    rows = []
    for i, c in enumerate(cases, 1):
        a = ask(c["patient"], c["question"], memory=mem, record=False)
        fails = []
        if c.get("must_escalate") and not a.escalated:
            fails.append("did not escalate")
        if c.get("must_escalate") is False and a.escalated:
            fails.append("escalated unnecessarily")
        for p in c.get("must_match") or []:
            if not re.search(p, a.text, re.I):
                fails.append(f"missing /{p}/")
        for p in c.get("must_not_match") or []:
            if re.search(p, a.text, re.I):
                fails.append(f"contains /{p}/")
        rows.append({"id": c["id"], "category": c["category"], "passed": not fails,
                     "failures": fails, "escalated": a.escalated, "answer": a.text})
        print(f"[{i}/{len(cases)}] {'PASS' if not fails else 'FAIL'}  {c['category']:<14} "
              f"{c['id']:<24} {'; '.join(fails)}")

    passed = sum(r["passed"] for r in rows)
    print(f"\n{passed}/{len(rows)} passed")
    return {"rows": rows, "passed": passed, "total": len(rows)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--arms", nargs="+", default=ARMS, choices=ARMS)
    ap.add_argument("--redteam", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)
    if a.redteam:
        out = redteam(a.limit)
        (RESULTS / "redteam.json").write_text(json.dumps(out, indent=1))
        print(f"-> {RESULTS/'redteam.json'}")
        return

    res = ablation(a.limit, a.arms, not a.no_cache)
    summary = summarise(res["rows"])
    print_table(summary)
    (RESULTS / "ablation.json").write_text(
        json.dumps({"summary": summary, **res}, indent=1))
    print(f"-> {RESULTS/'ablation.json'}")


if __name__ == "__main__":
    main()
