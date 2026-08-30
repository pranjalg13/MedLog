"""Demo mode: serve the Claude-derived artifacts from a committed cache.

Every Anthropic call in MedLog produces something derived from data that does not
change -- the reconciled state, the brief, and the full-history token count depend
only on the journal entries, and the answer prose only varies over the question.
Precompute those once and the public deployment needs no Anthropic key at all.

What deliberately stays live: mem0 retrieval. The Memory Inspector shows real
memories with real relevance scores, because that is the part worth showing and a
replay of it would be a lie. Red-flag screening is rule-based and needs no key
either, so the safety path is real too.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "demo_cache"
REPO_URL = "https://github.com/pranjalg13/MedLog"

FALLBACK = """\
**That one isn't pre-written, so I can't compose an answer for it here.**

The panel on the right is real, though — mem0 just searched {n} memories from {name}'s journal
to answer it. Retrieval, relevance scores, the pinned safety block and red-flag screening all
run live; only the answer text is prepared in advance.

Any of the listed questions will answer in full. To ask whatever you like, clone the repo
({repo}) and add your own API key — it's a two-line change.
"""


# The questions answered in full on the public demo. Defined here so the UI's
# suggestion buttons and the precompute step cannot drift apart -- a suggested
# question with no cached answer would be the worst possible first impression.
CURATED: dict[str, list[str]] = {
    "maya": [
        "Am I still taking propranolol, and at what dose?",
        "Has this rash happened before?",
        "Did stopping the propranolol change anything?",
        "What did my doctor want me to follow up on?",
        "How have my migraines changed over the past year?",
        "What do my records say about drug allergies?",
        "What did I want to ask at my next appointment?",
    ],
    "arjun": [
        "Am I taking anything for cholesterol?",
        "Am I still on amlodipine?",
        "What dose of metformin am I on and when did it change?",
        "How long have I had this cough?",
        "List everything I'm currently taking.",
    ],
    "rosa": [
        "Did I have any complications after surgery?",
        "Did skipping physio actually make a difference?",
        "How has my pain changed since the operation?",
        "How long was I on the strong painkillers?",
    ],
}


def enabled() -> bool:
    return os.environ.get("MEDLOG_DEMO", "").strip() in ("1", "true", "yes")


def _path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def load(name: str) -> Any | None:
    p = _path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def save(name: str, obj: Any) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    p = _path(name)
    p.write_text(json.dumps(obj, indent=1, default=str))
    return p


def normalise(question: str) -> str:
    """Match questions ignoring case, punctuation and spacing, so a visitor who
    retypes a suggested question with a stray comma still gets the real answer."""
    return re.sub(r"[^a-z0-9 ]", "", (question or "").lower()).strip()


def cached_answer(question: str) -> dict[str, Any] | None:
    answers = load("answers") or {}
    return answers.get(normalise(question))


def fallback_text(patient_name: str, n_retrieved: int) -> str:
    return FALLBACK.format(name=patient_name, n=n_retrieved, repo=REPO_URL)


def missing() -> list[str]:
    """Which cache files a demo deployment still needs. Used by precompute and by
    the UI banner so a half-populated cache announces itself rather than 500ing."""
    need = ["answers", "context_stats"]
    need += [f"state_{p}" for p in ("maya", "arjun", "rosa")]
    need += [f"brief_{p}" for p in ("maya", "arjun", "rosa")]
    return [n for n in need if not _path(n).exists()]
