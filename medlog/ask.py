"""The answering path: screen, assemble, answer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from medlog import db, demo
from medlog.context.assembler import Assembled, assemble
from medlog.llm import Usage, complete
from medlog.config import get_settings
from medlog.memory.client import MedLogMemory
from medlog.safety import redflags
from medlog.safety.guardrails import ANSWER_SYSTEM


@dataclass
class Answer:
    text: str
    escalated: bool = False
    from_cache: bool = False
    unanswered: bool = False
    severity: str = ""
    red_flags: list[str] = field(default_factory=list)
    context: Assembled | None = None
    usage: Usage | None = None

    def to_dict(self) -> dict[str, Any]:
        c = self.context
        return {
            "text": self.text,
            "escalated": self.escalated,
            "from_cache": self.from_cache,
            "unanswered": self.unanswered,
            "severity": self.severity,
            "red_flags": self.red_flags,
            "retrieved": [
                {
                    "id": m.get("id"),
                    "memory": m.get("memory"),
                    "score": m.get("score"),
                    "date": (m.get("metadata") or {}).get("entry_date"),
                    "categories": m.get("categories") or [],
                }
                for m in (c.retrieved if c else [])
            ],
            "pinned": c.pinned_block if c else "",
            "stored_memories": c.stored_memories if c else 0,
            "usage": {
                "input_tokens": self.usage.input_tokens if self.usage else 0,
                "output_tokens": self.usage.output_tokens if self.usage else 0,
                "latency_ms": round(self.usage.latency_ms) if self.usage else 0,
                "cost_usd": round(self.usage.cost_usd, 6) if self.usage else 0,
            },
        }


def ask(
    patient_id: str,
    question: str,
    memory: MedLogMemory | None = None,
    record: bool = True,
) -> Answer:
    # Screening comes first and short-circuits everything. Retrieval cannot change
    # the right response to someone describing chest pain, so we do not spend the
    # time or risk burying the answer under history.
    hits = redflags.screen(question)
    esc = redflags.escalation_for(hits)
    if esc:
        severity, text = esc
        ans = Answer(text=text, escalated=True, severity=severity,
                     red_flags=[h.key for h in hits])
        if record:
            db.add_turn(patient_id, "user", question)
            db.add_turn(patient_id, "assistant", text,
                        {"escalated": True, "severity": severity})
        return ans

    # Retrieval runs in every mode, including the keyless demo. The Memory
    # Inspector is the most convincing thing on the page and replaying it would
    # make it worthless.
    ctx = assemble(patient_id, question, memory=memory)
    try:
        ctx.stored_memories = len((memory or MedLogMemory()).get_all(patient_id))
    except Exception:  # noqa: BLE001 - a count is cosmetic, never fail the answer for it
        ctx.stored_memories = 0

    if demo.enabled():
        ans = _demo_answer(patient_id, question, ctx)
    else:
        text, usage = complete(
            ANSWER_SYSTEM,
            ctx.prompt,
            model=get_settings().medlog_chat_model,
            max_tokens=2000,
            effort="medium",
        )
        ans = Answer(text=text, context=ctx, usage=usage)

    if record:
        db.add_turn(patient_id, "user", question)
        db.add_turn(patient_id, "assistant", ans.text, {"memory_ids": ctx.memory_ids})
    return ans


def _demo_answer(patient_id: str, question: str, ctx: Assembled) -> Answer:
    """Serve the prose from cache; everything else already ran for real."""
    hit = demo.cached_answer(question)
    if hit:
        u = hit.get("usage") or {}
        return Answer(
            text=hit["text"], context=ctx, from_cache=True,
            usage=Usage(input_tokens=u.get("input_tokens", 0),
                        output_tokens=u.get("output_tokens", 0),
                        model=u.get("model", ""), latency_ms=u.get("latency_ms", 0)),
        )

    name = (db.get_patient(patient_id) or {}).get("display_name", "this patient")
    return Answer(
        text=demo.fallback_text(name, len(ctx.retrieved)),
        context=ctx, unanswered=True,
        usage=Usage(model=""),
    )
