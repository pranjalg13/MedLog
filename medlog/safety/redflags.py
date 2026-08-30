"""Red-flag screening.

Deliberately rule-based. A regex that fires the same way every time is testable,
costs nothing, adds no latency, and cannot be talked out of firing by the phrasing
of the sentence around it. Screening runs on what the user just wrote, before any
retrieval or answering, and a hit supersedes the normal response path.

Tuned to over-trigger. A false positive costs someone thirty seconds of reassurance;
a false negative costs considerably more.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Severity = Literal["emergency", "urgent"]


@dataclass(frozen=True)
class RedFlag:
    key: str
    severity: Severity
    label: str
    pattern: re.Pattern


def _p(s: str) -> re.Pattern:
    return re.compile(s, re.I)


RULES: list[RedFlag] = [
    RedFlag("cardiac", "emergency", "possible cardiac symptoms", _p(
        r"\b(chest (pain|pressure|tightness|tightening)|crushing (pain|feeling)|"
        r"pain (radiating|spreading|going) (down|to|into) (my )?(left )?(arm|jaw|neck|shoulder)|"
        r"elephant (sitting|standing) on my chest)\b")),
    RedFlag("stroke", "emergency", "possible stroke symptoms", _p(
        # Keep the connective tissue loose. "face has gone droopy" and "face is
        # drooping" describe the same emergency; only one of them matched before.
        r"(face.{0,20}droop|droop.{0,15}face|one side of my (face|body)|"
        r"(sudden|suddenly).{0,15}(weak|numb|can'?t move|cannot move)|"
        r"weakness (on|down|in) (one|my left|my right) side|"
        r"can'?t grip|slurr(ed|ing)|can'?t (speak|find (my|the) words)|sudden(ly)? confus)")),
    RedFlag("thunderclap", "emergency", "sudden severe headache", _p(
        r"\b(worst headache of my life|thunderclap|sudden(est|ly)? (and )?(very )?severe headache|"
        r"headache (came on|hit) like)\b")),
    RedFlag("breathing", "emergency", "difficulty breathing", _p(
        r"\b(can'?t breathe|cannot breathe|struggling to breathe|gasping|"
        r"lips (are |have )?(turned |gone )?blue|fighting for (air|breath))\b")),
    RedFlag("anaphylaxis", "emergency", "possible anaphylaxis", _p(
        # Loose on the connective tissue: "throat feels like it's closing up" must hit
        # as surely as "throat closing".
        r"(throat.{0,25}(clos|tight|swell)|(tongue|lips|face).{0,15}swell|"
        r"swollen (tongue|lips|face)|can'?t swallow|cannot swallow|anaphyla)")),
    RedFlag("self_harm", "emergency", "thoughts of self-harm", _p(
        # Contractions break \b-anchored negations: "don't want to be here" has no
        # word boundary before "not". Match the phrase, not the negation.
        r"(kill myself|killing myself|end my life|ending my life|suicidal|suicide|"
        r"want to die|wish i was dead|hurt(ing)? myself|harm myself|self.harm|"
        r"want to (be here|live|go on|wake up)|better off without me|"
        r"no reason to (go on|live)|can'?t go on)")),
    RedFlag("bleeding", "emergency", "signs of serious bleeding", _p(
        r"\b(coughing (up )?blood|vomit(ing|ed)? blood|blood in my vomit|"
        r"black (tarry )?stool|bleeding (heavily|that won'?t stop))\b")),
    RedFlag("meningitis", "emergency", "possible meningitis", _p(
        r"\b(stiff neck.{0,40}(rash|fever|light)|rash that doesn'?t fade|"
        r"(fever|headache).{0,40}stiff neck)\b")),
    RedFlag("neuro_urgent", "urgent", "new neurological symptoms", _p(
        r"\b(vision (has gone|went|going) (blurry|double|dark)|lost (my )?vision|"
        r"fainted|passed out|blacked out|seizure|fit)\b")),
    RedFlag("infection_urgent", "urgent", "possible spreading infection", _p(
        r"\b(red streaks?|spreading redness|wound.{0,30}(pus|hot and)|fever (of )?(39|40|10[3-6]))\b")),
]

EMERGENCY_TEXT = (
    "**Please stop and seek emergency care now.** What you have described "
    "({labels}) can be a sign of something that needs assessing immediately, not at your "
    "next appointment.\n\n"
    "Call **911** (or your local emergency number), or get to an emergency department. "
    "If you are alone, call someone to be with you.\n\n"
    "I am a journal, not a clinician, and I cannot assess this. I have not looked anything "
    "up in your history, because nothing in it would change this answer."
)

URGENT_TEXT = (
    "**This is worth getting looked at today rather than logging.** What you have described "
    "({labels}) should be assessed promptly.\n\n"
    "Contact your GP for a same-day appointment, call **111** or your local advice line, or "
    "go to urgent care. If it gets worse or you develop chest pain, breathing trouble, or "
    "weakness on one side, treat it as an emergency and call 911.\n\n"
    "I can note this in your journal afterwards, but please get it seen first."
)


def screen(text: str) -> list[RedFlag]:
    return [r for r in RULES if r.pattern.search(text or "")]


def escalation_for(hits: list[RedFlag]) -> tuple[Severity, str] | None:
    """Highest-severity escalation message, or None if nothing fired."""
    if not hits:
        return None
    emergencies = [h for h in hits if h.severity == "emergency"]
    chosen = emergencies or hits
    labels = ", ".join(dict.fromkeys(h.label for h in chosen))
    if emergencies:
        return "emergency", EMERGENCY_TEXT.format(labels=labels)
    return "urgent", URGENT_TEXT.format(labels=labels)
