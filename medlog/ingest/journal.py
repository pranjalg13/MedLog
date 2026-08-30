"""Journal write path: raw text -> SQLite (verbatim) + mem0 (distilled)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from medlog import db
from medlog.memory.client import MedLogMemory, extracted_memories, retry


def _iso(d: object) -> str:
    """Coerce to an ISO date string. PyYAML parses bare `2026-01-13` into a
    datetime.date, so fixtures hand us dates, not strings."""
    if isinstance(d, (dt.date, dt.datetime)):
        return d.isoformat()[:10]
    return str(d)[:10]


def ingest_entry(
    patient_id: str,
    text: str,
    entry_date: str | dt.date | None = None,
    source: str = "patient_journal",
    memory: MedLogMemory | None = None,
) -> dict[str, Any]:
    """Store one entry. The raw text is kept exactly as written; mem0 gets a
    backdated copy so the memory lands on the day the event happened."""
    entry_date = _iso(entry_date) if entry_date else dt.date.today().isoformat()
    text = text.strip()
    if not text:
        raise ValueError("entry text is empty")

    entry_id = db.add_entry(patient_id, entry_date, text, source)

    mem = memory or MedLogMemory()
    resp = retry(lambda: mem.add_entry(patient_id, text, entry_date, source))
    memories = extracted_memories(resp)
    if memories:
        db.link_memories(entry_id, memories)

    # A new entry invalidates the cached reconciliation.
    return {"entry_id": entry_id, "entry_date": entry_date, "memories": memories,
            "pending": not memories}


def backfill_entry_memories(patient_id: str, memory: MedLogMemory | None = None) -> dict[str, Any]:
    """Link entries to the memories they produced.

    `add()` is asynchronous and returns no memories, so the link cannot be made at
    write time. Afterwards it can: every memory carries `metadata.entry_date`, which
    is the entry it came from. Where a date has several entries the link is
    ambiguous, so we attach to the earliest -- fixture dates are unique, and for
    real use this only affects display.
    """
    mem = memory or MedLogMemory()
    memories = mem.get_all(patient_id)

    by_date: dict[str, int] = {}
    for e in db.get_entries(patient_id, ascending=True):
        by_date.setdefault(e["entry_date"], e["id"])

    grouped: dict[int, list[dict[str, Any]]] = {}
    orphans = 0
    for m in memories:
        d = (m.get("metadata") or {}).get("entry_date")
        eid = by_date.get(d)
        if eid is None:
            orphans += 1
            continue
        grouped.setdefault(eid, []).append({
            "id": m.get("id", ""),
            "memory": m.get("memory", ""),
            "categories": m.get("categories") or [],
        })

    for eid, rows in grouped.items():
        db.link_memories(eid, rows)

    covered = set(grouped)
    missing = [d for d, eid in by_date.items() if eid not in covered]
    return {"memories": len(memories), "entries_linked": len(covered),
            "entries_total": len(by_date), "orphans": orphans,
            "missing_dates": sorted(missing)}
