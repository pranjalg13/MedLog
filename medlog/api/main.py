"""FastAPI service. Holds the logic; the Streamlit app is a client of this."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from medlog import db, demo
from medlog.ask import ask as ask_
from medlog.brief.generate import generate as generate_brief
from medlog.ingest.journal import ingest_entry
from medlog.memory.client import MedLogMemory
from medlog.memory.reconcile import get_state

app = FastAPI(title="MedLog", version="0.1.0",
              description="Memory-native pre-visit brief generator")

_mem: MedLogMemory | None = None


def memory() -> MedLogMemory:
    global _mem
    if _mem is None:
        _mem = MedLogMemory()
    return _mem


class EntryIn(BaseModel):
    text: str = Field(min_length=1)
    entry_date: str | None = None


class AskIn(BaseModel):
    question: str = Field(min_length=1)


class BriefIn(BaseModel):
    since: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "patients": len(db.list_patients())}


@app.get("/patients")
def patients() -> list[dict[str, Any]]:
    return db.list_patients()


def _require(pid: str) -> dict[str, Any]:
    p = db.get_patient(pid)
    if not p:
        raise HTTPException(404, f"no such patient: {pid}")
    return p


@app.get("/patients/{pid}")
def patient(pid: str) -> dict[str, Any]:
    p = _require(pid)
    p["entry_count"] = db.entry_count(pid)
    return p


@app.get("/patients/{pid}/entries")
def entries(pid: str, limit: int | None = None) -> list[dict[str, Any]]:
    _require(pid)
    rows = db.get_entries(pid, limit=limit)
    for r in rows:
        r["memories"] = db.memories_for_entry(r["id"])
    return rows


@app.post("/patients/{pid}/entries", status_code=201)
def create_entry(pid: str, body: EntryIn) -> dict[str, Any]:
    _require(pid)
    return ingest_entry(pid, body.text, body.entry_date, memory=memory())


@app.post("/patients/{pid}/ask")
def ask(pid: str, body: AskIn) -> dict[str, Any]:
    _require(pid)
    return ask_(pid, body.question, memory=memory()).to_dict()


@app.get("/patients/{pid}/state")
def state(pid: str, force: bool = False) -> dict[str, Any]:
    _require(pid)
    return get_state(pid, force=force, memory=memory()).model_dump()


@app.post("/patients/{pid}/brief")
def brief(pid: str, body: BriefIn) -> dict[str, Any]:
    _require(pid)
    b = generate_brief(pid, since=body.since, memory=memory())
    return {
        "markdown": b.markdown, "since": b.since, "until": b.until,
        "entry_count": b.entry_count, "flags": b.flags,
        "usage": {"input_tokens": b.usage.input_tokens if b.usage else 0,
                  "output_tokens": b.usage.output_tokens if b.usage else 0,
                  "cost_usd": round(b.usage.cost_usd, 4) if b.usage else 0},
    }


@app.get("/patients/{pid}/brief")
def latest_brief(pid: str) -> dict[str, Any]:
    _require(pid)
    b = db.latest_brief(pid)
    if not b:
        raise HTTPException(404, "no brief generated yet")
    return b


_stats_cache: dict[str, dict[str, Any]] = {}


@app.get("/patients/{pid}/context_stats")
def context_stats(pid: str) -> dict[str, Any]:
    """How big would the whole journal be if we just pasted it in? Measured with
    the real token counter, cached because it only moves when entries are added."""
    _require(pid)
    n = db.entry_count(pid)

    if demo.enabled():
        cached = (demo.load("context_stats") or {}).get(pid)
        if cached:
            return {"entry_count": n, "full_history_tokens": cached}

    hit = _stats_cache.get(pid)
    if hit and hit["entry_count"] == n:
        return hit

    from medlog.context.assembler import full_history_prompt
    from medlog.llm import count_tokens
    from medlog.safety.guardrails import ANSWER_SYSTEM

    prompt = full_history_prompt(pid, "What has changed since my last visit?")
    out = {"entry_count": n, "full_history_tokens": count_tokens(ANSWER_SYSTEM, prompt)}
    _stats_cache[pid] = out
    return out


@app.get("/memories/{memory_id}/history")
def memory_history(memory_id: str) -> list[dict[str, Any]]:
    return memory().history(memory_id)
