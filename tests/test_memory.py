"""Memory-layer plumbing, no network."""
import datetime as dt

from medlog.memory.client import extracted_memories, to_epoch, user_id_for
from medlog.memory.reconcile import CurrentState, Medication, active_medications
from medlog.memory.schema import CATEGORY_NAMES, CATEGORIES, INSTRUCTIONS, PINNED_CATEGORIES


def test_user_ids_are_namespaced():
    assert user_id_for("maya") == "medlog_maya"


def test_backdating_lands_on_the_right_day():
    e = to_epoch("2026-03-14")
    assert dt.datetime.fromtimestamp(e, dt.timezone.utc).date() == dt.date(2026, 3, 14)


def test_backdating_survives_timezone_offsets():
    # Midday UTC so no real-world offset can shift the calendar date.
    for d in ["2026-01-01", "2026-06-30", "2026-12-31"]:
        got = dt.datetime.fromtimestamp(to_epoch(d), dt.timezone.utc)
        assert got.date().isoformat() == d
        assert 6 <= got.hour <= 18


def test_extracted_memories_filters_incomplete_rows():
    resp = {"results": [
        {"id": "a", "memory": "x", "event": "ADD", "categories": ["symptom"]},
        {"id": "", "memory": "no id"},
        {"id": "c", "memory": ""},
    ]}
    got = extracted_memories(resp)
    assert [m["id"] for m in got] == ["a"]


def test_extracted_memories_accepts_bare_list():
    assert extracted_memories([{"id": "z", "memory": "m"}])[0]["id"] == "z"


def test_categories_are_unique_and_described():
    assert len(CATEGORY_NAMES) == len(set(CATEGORY_NAMES))
    for c in CATEGORIES:
        for name, desc in c.items():
            assert len(desc) > 30, name


def test_pinned_categories_are_real_categories():
    assert set(PINNED_CATEGORIES) <= set(CATEGORY_NAMES)


def test_extraction_instructions_cover_the_clinical_rules():
    low = INSTRUCTIONS.lower()
    for rule in ["verbatim", "negativ", "diagnosis", "instruction"]:
        assert rule in low, rule


def test_active_medications_excludes_stopped_and_uncertain():
    s = CurrentState(medications=[
        Medication(name="a", status="active", started="", stopped="", dose=""),
        Medication(name="b", status="stopped", started="", stopped="2026-01-01", dose=""),
        Medication(name="c", status="uncertain", started="", stopped="", dose=""),
    ])
    assert [m.name for m in active_medications(s)] == ["a"]
