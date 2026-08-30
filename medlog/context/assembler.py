"""Assemble the prompt, and report exactly what went into it.

Returning the memory IDs alongside the prompt is not a debugging nicety: it is
what lets the UI show its work, what lets answers be checked against sources,
and what lets the eval measure retrieval rather than guess at it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from medlog import db
from medlog.memory.client import MedLogMemory
from medlog.memory.reconcile import CurrentState, get_state
from medlog.memory.schema import CLINICAL_CATEGORIES
from medlog.safety import pinned


@dataclass
class Assembled:
    prompt: str
    pinned_block: str
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    state: CurrentState = field(default_factory=CurrentState)
    stored_memories: int = 0

    @property
    def memory_ids(self) -> list[str]:
        return [m.get("id", "") for m in self.retrieved if m.get("id")]


def _fmt_memories(memories: list[dict[str, Any]]) -> str:
    rows = []
    for m in memories:
        meta = m.get("metadata") or {}
        date = meta.get("entry_date") or (m.get("created_at") or "")[:10] or "undated"
        score = m.get("score")
        tail = f"  (relevance {score:.2f})" if isinstance(score, (int, float)) else ""
        rows.append(f"[{date}] {m.get('memory','')}{tail}")
    return "\n".join(rows) or "(nothing matched)"


def _fmt_state(s: CurrentState) -> str:
    out: list[str] = []
    if s.symptoms:
        out.append("Symptom threads:")
        for t in s.symptoms:
            freq = f", {t.frequency}" if t.frequency else ""
            out.append(f"  - {t.description} [{t.status}, {t.trend}{freq}] "
                       f"first {t.first_recorded}, latest {t.most_recent}")
    if s.patterns_to_raise:
        out.append("\nRepeated sequences noticed across the record "
                   "(observations to raise, not conclusions):")
        for p in s.patterns_to_raise:
            out.append(f"  - {p.observation} (confidence: {p.confidence}; "
                       f"occurrences: {', '.join(p.evidence)})")
    if s.open_items:
        open_ = [i for i in s.open_items if i.still_open]
        if open_:
            out.append("\nOutstanding items:")
            for i in open_:
                out.append(f"  - [{i.raised_on}] ({i.kind}) {i.item}")
    return "\n".join(out) or "(nothing recorded)"


def assemble(
    patient_id: str,
    query: str,
    top_k: int = 12,
    recent_entries: int = 3,
    rerank: bool = True,
    memory: MedLogMemory | None = None,
    state: CurrentState | None = None,
) -> Assembled:
    mem = memory or MedLogMemory()
    st = state or get_state(patient_id, memory=mem)

    retrieved = mem.search(
        patient_id, query, top_k=top_k, categories=CLINICAL_CATEGORIES, rerank=rerank
    )
    recent = db.get_entries(patient_id, limit=recent_entries)
    pin = pinned.build(st)

    prompt = f"""\
<always_relevant>
{pin}
</always_relevant>

<reconciled_history>
{_fmt_state(st)}
</reconciled_history>

<retrieved_from_journal>
{_fmt_memories(retrieved)}
</retrieved_from_journal>

<most_recent_entries>
{chr(10).join(f"[{e['entry_date']}] {e['text'].strip()}" for e in recent) or "(none)"}
</most_recent_entries>

Question from the patient: {query}"""

    return Assembled(prompt=prompt, pinned_block=pin, retrieved=retrieved, recent=recent, state=st)


def full_history_prompt(patient_id: str, query: str) -> str:
    """The comparison arm: every raw entry, no memory layer. This is what MedLog
    is measured against."""
    entries = db.get_entries(patient_id, ascending=True)
    body = "\n\n".join(f"[{e['entry_date']}] {e['text'].strip()}" for e in entries)
    return (
        f"<complete_journal>\n{body}\n</complete_journal>\n\n"
        f"Question from the patient: {query}"
    )
