"""The pre-visit brief.

The product's headline output: one page a patient hands across the desk. The
reader is a clinician with about ninety seconds who does not know this story,
so the brief is written for them, not for the patient who wrote the journal.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from medlog import db, demo
from medlog.config import get_settings
from medlog.llm import Usage, complete
from medlog.memory.client import MedLogMemory
from medlog.memory.reconcile import CurrentState, get_state
from medlog.safety.guardrails import BRIEF_SYSTEM

TEMPLATE = """\
Produce the brief as markdown, in exactly these sections and this order. Omit a
section entirely if the record has nothing for it -- an empty heading wastes the
reader's attention.

## Since the last visit
One or two sentences. The window, and the single thing most worth knowing.

## Current medications
A list. Name, dose, since when. Note any change within the window and any drug the
record is uncertain about.

## What has changed
Frequency and trend, with numbers and dates. This is the section a clinician reads
most closely, so lead with the largest change.

## Worth asking about
Repeated sequences visible across the record, stated as sequences with their dates.
No conclusions, no diagnoses. Omit this section if there are none.

## To verify
Contradictions in the record the clinician should check directly with the patient.
Omit if there are none.

## Open from last time
Anything a clinician previously said to do or come back about that has not been closed.

## The patient's questions
Their own words where possible.

Rules: every claim carries its [YYYY-MM-DD]. No preamble, no closing summary, no
"I hope this helps". Start at the first heading. Keep the whole thing under 450 words --
it must fit on one page and survive a ninety-second read.
"""


@dataclass
class Brief:
    markdown: str
    since: str
    until: str
    state: CurrentState = field(default_factory=CurrentState)
    entry_count: int = 0
    usage: Usage | None = None

    @property
    def flags(self) -> list[dict[str, Any]]:
        """Banner content: patterns and contradictions, highest first."""
        out = [
            {"kind": "pattern", "text": p.observation, "confidence": p.confidence,
             "safety": p.safety_relevant, "evidence": p.evidence}
            for p in self.state.patterns_to_raise
        ]
        out += [
            {"kind": "conflict", "text": c.description, "confidence": "",
             "safety": False, "evidence": c.evidence}
            for c in self.state.conflicts
        ]
        # Safety first, then confidence. Sorting on confidence alone would put a
        # well-evidenced note about fatigue above a possible drug reaction that
        # is not on the allergy record, which is the wrong way round for a page
        # a clinician reads in ninety seconds.
        rank = {"high": 0, "moderate": 1, "low": 2, "": 1}
        out.sort(key=lambda f: (not f["safety"], f["kind"] != "pattern",
                                rank.get(f["confidence"], 1)))
        return out


def default_since(state: CurrentState, fallback_days: int = 120) -> str:
    """Start of the window: the last time a clinician gave an instruction, since
    that is what "since my last visit" actually means to the reader."""
    dates = [i.raised_on for i in state.open_items
             if i.kind == "clinician_instruction" and i.raised_on]
    if dates:
        return max(dates)
    return (dt.date.today() - dt.timedelta(days=fallback_days)).isoformat()


def generate(
    patient_id: str,
    since: str | None = None,
    memory: MedLogMemory | None = None,
    save: bool = True,
) -> Brief:
    if demo.enabled():
        cached = demo.load(f"brief_{patient_id}")
        if cached is not None:
            return Brief(
                markdown=cached["markdown"], since=cached["since"], until=cached["until"],
                state=CurrentState.model_validate(cached.get("state") or {}),
                entry_count=cached.get("entry_count", 0),
            )

    mem = memory or MedLogMemory()
    state = get_state(patient_id, memory=mem)
    since = since or default_since(state)

    entries = [e for e in db.get_entries(patient_id, ascending=True) if e["entry_date"] >= since]
    until = entries[-1]["entry_date"] if entries else dt.date.today().isoformat()

    patient = db.get_patient(patient_id) or {}
    age = ""
    if patient.get("year_of_birth"):
        age = f", {dt.date.today().year - int(patient['year_of_birth'])}"

    window = "\n\n".join(f"[{e['entry_date']}] {e['text'].strip()}" for e in entries)

    user = f"""\
Patient: {patient.get('display_name','unknown')}{age}
Window: {since} to {until} ({len(entries)} journal entries)

The reconciled picture of the whole record, not just this window:

<current_state>
{state.model_dump_json(indent=2)}
</current_state>

The journal entries within the window, verbatim:

<entries>
{window or "(no entries in this window)"}
</entries>

{TEMPLATE}"""

    md, usage = complete(
        BRIEF_SYSTEM, user,
        model=get_settings().medlog_reasoning_model,
        max_tokens=4000,
        effort="high",
    )

    brief = Brief(markdown=md, since=since, until=until, state=state,
                  entry_count=len(entries), usage=usage)
    if save:
        db.save_brief(patient_id, md, {
            "since": since, "until": until, "entry_count": len(entries),
            "flags": brief.flags,
        })
    return brief
