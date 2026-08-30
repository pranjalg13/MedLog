"""Demo mode must work with no Anthropic key at all.

These tests deliberately blank ANTHROPIC_API_KEY. If any of them touches Claude,
the settings layer raises and the test fails -- which is exactly the guarantee the
public deployment needs.
"""
import json

import pytest

from medlog import demo


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("MEDLOG_DEMO", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    return tmp_path


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEDLOG_DEMO", raising=False)
    assert demo.enabled() is False


@pytest.mark.parametrize("val,want", [("1", True), ("true", True), ("yes", True),
                                      ("0", False), ("", False)])
def test_enabled_parsing(monkeypatch, val, want):
    monkeypatch.setenv("MEDLOG_DEMO", val)
    assert demo.enabled() is want


def test_normalise_tolerates_punctuation_and_case():
    a = demo.normalise("Am I still taking propranolol, and at what dose?")
    b = demo.normalise("am i still taking propranolol and at what dose")
    assert a == b


def test_normalise_handles_none_and_empty():
    assert demo.normalise("") == ""
    assert demo.normalise(None) == ""


def test_cached_answer_roundtrip(cache):
    q = "Has this rash happened before?"
    demo.save("answers", {demo.normalise(q): {"text": "Yes, twice.", "usage": {}}})
    assert demo.cached_answer(q)["text"] == "Yes, twice."
    # A retyped variant must still hit, or a visitor gets the fallback by accident.
    assert demo.cached_answer("has this rash happened before") is not None


def test_cached_answer_misses_cleanly(cache):
    demo.save("answers", {})
    assert demo.cached_answer("something nobody precomputed") is None


def test_load_returns_none_for_absent_and_corrupt(cache):
    assert demo.load("nope") is None
    (cache / "broken.json").write_text("{not json")
    assert demo.load("broken") is None


def test_missing_lists_every_required_artifact(cache):
    assert set(demo.missing()) == {
        "answers", "context_stats",
        "state_maya", "state_arjun", "state_rosa",
        "brief_maya", "brief_arjun", "brief_rosa",
    }
    demo.save("answers", {})
    assert "answers" not in demo.missing()


def test_curated_questions_cover_every_demo_patient():
    assert set(demo.CURATED) == {"maya", "arjun", "rosa"}
    for pid, qs in demo.CURATED.items():
        assert qs, pid
        assert len(set(demo.normalise(q) for q in qs)) == len(qs), f"dup in {pid}"


def test_fallback_names_the_patient_and_count():
    t = demo.fallback_text("Maya Chen", 7)
    assert "Maya Chen" in t and "7" in t
    # It must be honest about what is and isn't live.
    assert "live" in t.lower()


def test_get_state_reads_cache_without_anthropic(cache, monkeypatch):
    from medlog.memory.reconcile import CurrentState, get_state
    demo.save("state_maya", CurrentState(conditions=["migraine"]).model_dump())
    # No mem0 client, no Claude client -- if either were constructed this raises.
    got = get_state("maya")
    assert got.conditions == ["migraine"]


def test_red_flag_screening_needs_no_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("MEM0_API_KEY", "")
    from medlog.safety.redflags import escalation_for, screen
    sev, text = escalation_for(screen("crushing chest pain going into my jaw"))
    assert sev == "emergency" and "911" in text
