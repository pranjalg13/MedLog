"""The never-forget block.

Built deterministically from the reconciled state -- no vector search, no top_k,
no similarity threshold. If someone asks about a headache, the fact that they
react to amoxicillin is not "relevant" by any embedding metric, and a retrieval
system will correctly decline to return it. That is precisely the failure this
block exists to prevent.

Small on purpose: allergies, active drugs, conditions, and open contradictions.
Everything else can be retrieved.
"""
from __future__ import annotations

from medlog.memory.reconcile import CurrentState


def build(state: CurrentState) -> str:
    lines: list[str] = []

    reactions = state.allergies_and_reactions
    if reactions:
        lines.append("REACTIONS ON RECORD (always consider these):")
        for r in reactions:
            # Substance first: it is what a clinician scans this block for.
            sub = r.substance_or_exposure or "unidentified trigger"
            when = f" [{r.onset}]" if r.onset else ""
            lines.append(f"  - {sub}{when}")
            lines.append(f"      -> {r.reaction}")
    else:
        lines.append("REACTIONS ON RECORD: none documented.")

    active = [m for m in state.medications if m.status == "active"]
    uncertain = [m for m in state.medications if m.status == "uncertain"]
    if active:
        lines.append("\nCURRENTLY TAKING:")
        for m in active:
            dose = f" {m.dose}" if m.dose else ""
            since = f" (since {m.started})" if m.started else ""
            lines.append(f"  - {m.name}{dose}{since}")
    else:
        lines.append("\nCURRENTLY TAKING: nothing recorded.")

    if uncertain:
        lines.append("\nUNCERTAIN WHETHER STILL TAKING (verify before relying on this):")
        for m in uncertain:
            lines.append(f"  - {m.name} {m.dose}".rstrip())

    if state.conditions:
        lines.append("\nCONDITIONS: " + "; ".join(state.conditions))

    if state.conflicts:
        lines.append("\nUNRESOLVED CONTRADICTIONS IN THE RECORD:")
        for c in state.conflicts:
            lines.append(f"  - {c.description}")

    return "\n".join(lines)


def token_estimate(text: str) -> int:
    """Rough count for UI display only. The eval uses the real count_tokens API."""
    return max(1, len(text) // 4)
