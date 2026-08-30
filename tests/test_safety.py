"""Safety behaviour that must hold without any network call."""
import pytest

from medlog.memory.reconcile import CurrentState, Medication, ReactionEvent, Conflict
from medlog.safety import pinned, redflags
from medlog.safety.guardrails import ANSWER_SYSTEM, BRIEF_SYSTEM

EMERGENCIES = [
    "I've had chest pain for an hour and it's spreading into my left arm",
    "my face has gone droopy on one side",
    "worst headache of my life, came on in seconds",
    "took the antibiotic and my throat feels like it's closing",
    "honestly I don't want to be here anymore",
    "I've been coughing up blood",
    "can't breathe properly and my lips have gone blue",
    "I keep thinking everyone would be better off without me",
]
BENIGN = [
    "I have a mild headache behind my left eye again",
    "am I still taking propranolol and at what dose?",
    "has this rash happened before?",
    "sore throat from a cold, nothing dramatic",
    "my ankle swells a bit in the evenings",
    "what should I ask about at my appointment?",
    "slept badly, about five hours",
    "BP was 102/68 this morning",
]


@pytest.mark.parametrize("text", EMERGENCIES)
def test_emergencies_escalate(text):
    assert redflags.escalation_for(redflags.screen(text)) is not None, text


@pytest.mark.parametrize("text", BENIGN)
def test_benign_does_not_escalate(text):
    assert redflags.escalation_for(redflags.screen(text)) is None, text


def test_emergency_outranks_urgent():
    both = "I fainted and now I have chest pain going into my jaw"
    sev, _ = redflags.escalation_for(redflags.screen(both))
    assert sev == "emergency"


def test_escalation_text_names_emergency_number():
    _, text = redflags.escalation_for(redflags.screen("crushing chest pain"))
    assert "911" in text


@pytest.fixture
def state():
    return CurrentState(
        medications=[
            Medication(name="propranolol", dose="40mg daily", status="active",
                       started="2026-01-13", stopped=""),
            Medication(name="amlodipine", dose="5mg", status="stopped",
                       started="2025-01-01", stopped="2025-12-08",
                       reason_stopped="ankle swelling"),
            Medication(name="atorvastatin", dose="20mg", status="uncertain",
                       started="2025-09-10", stopped=""),
        ],
        allergies_and_reactions=[
            ReactionEvent(substance_or_exposure="amoxicillin",
                          reaction="blotchy rash", onset="2025-09-17")],
        conditions=["migraine"],
        conflicts=[Conflict(description="intake says no allergies", evidence=["2025-09-12"])],
    )


def test_pinned_always_carries_reactions(state):
    assert "amoxicillin" in pinned.build(state)


def test_pinned_lists_active_not_stopped(state):
    block = pinned.build(state)
    assert "propranolol" in block
    # A stopped drug must not appear under "currently taking" -- the whole point
    # of reconciliation over an append-only store.
    current = block.split("CURRENTLY TAKING:")[1].split("\n\n")[0]
    assert "amlodipine" not in current


def test_pinned_flags_uncertain_separately(state):
    block = pinned.build(state)
    assert "UNCERTAIN" in block and "atorvastatin" in block


def test_pinned_surfaces_conflicts(state):
    assert "CONTRADICTION" in pinned.build(state)


def test_pinned_handles_empty_state():
    block = pinned.build(CurrentState())
    assert "none documented" in block and "nothing recorded" in block


@pytest.mark.parametrize("prompt", [ANSWER_SYSTEM, BRIEF_SYSTEM])
def test_prompts_defend_against_injection(prompt):
    low = prompt.lower()
    assert "instruct" in low and ("follow none of it" in low or "data" in low)


def test_answer_prompt_forbids_diagnosis_and_dosing():
    low = ANSWER_SYSTEM.lower()
    assert "do not diagnose" in low
    assert "dose" in low and "clinician" in low
