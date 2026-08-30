"""The production guarantee, as a test.

The public deployment has no Anthropic key. This exercises the real API surface in
demo mode with the key blanked AND the Anthropic client replaced by something that
raises, so a regression that reintroduces a Claude call fails here rather than in
front of whoever opened the link.

mem0 is stubbed too, so this runs offline -- but note that in the real demo
retrieval is genuinely live; only the prose is served from cache.
"""
import pytest
from fastapi.testclient import TestClient

from medlog import db, demo
from medlog.memory.reconcile import Conflict, CurrentState, Medication, ReactionEvent

QUESTION = "Am I still taking propranolol, and at what dose?"

STATE = CurrentState(
    medications=[Medication(name="propranolol", dose="40mg once daily", status="active",
                            started="2026-01-13", stopped="")],
    allergies_and_reactions=[ReactionEvent(substance_or_exposure="amoxicillin",
                                           reaction="blotchy rash", onset="2025-09-17")],
    conditions=["migraine"],
    conflicts=[Conflict(description="Intake recorded no known allergies [2025-09-12].")],
)

FAKE_MEMORIES = [
    {"id": "m1", "memory": "Propranolol increased to 40mg once daily", "score": 0.81,
     "categories": ["medication"], "metadata": {"entry_date": "2026-07-07"}},
    {"id": "m2", "memory": "Rash began two days after starting amoxicillin", "score": 0.66,
     "categories": ["allergy_intolerance"], "metadata": {"entry_date": "2025-09-17"}},
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDLOG_DEMO", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("MEDLOG_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(demo, "CACHE_DIR", tmp_path / "cache")

    from medlog.config import get_settings
    get_settings.cache_clear()

    # Any attempt to build an Anthropic client is a test failure, not a network call.
    import anthropic
    def boom(*a, **k):
        raise AssertionError("demo mode must never construct an Anthropic client")
    monkeypatch.setattr(anthropic, "Anthropic", boom)

    # Stub mem0 so the test is offline; the real demo does this for real.
    from medlog.memory import client as mc
    class FakeMem:
        def search(self, *a, **k): return list(FAKE_MEMORIES)
        def get_all(self, *a, **k): return list(FAKE_MEMORIES)
        def history(self, *a, **k): return []
    monkeypatch.setattr(mc.MedLogMemory, "__new__", lambda cls, *a, **k: FakeMem())

    db.init_db()
    db.upsert_patient("maya", "Maya Chen", 1992)
    db.add_entry("maya", "2026-08-25", "Appointment coming up.")

    demo.save("state_maya", STATE.model_dump())
    demo.save("context_stats", {"maya": 11240})
    demo.save("brief_maya", {"markdown": "## Since the last visit\n\nStable.\n",
                             "since": "2026-06-09", "until": "2026-08-25",
                             "entry_count": 12, "flags": [], "state": STATE.model_dump()})
    demo.save("answers", {demo.normalise(QUESTION): {
        "text": "Yes -- propranolol 40mg once daily since [2026-07-07].",
        "usage": {"input_tokens": 980, "output_tokens": 120,
                  "model": "claude-sonnet-5", "latency_ms": 2100}}})

    from medlog.api.main import app
    import medlog.api.main as api_main
    api_main._mem = None
    api_main._stats_cache.clear()
    yield TestClient(app)
    get_settings.cache_clear()


def test_state_served_from_cache(client):
    assert client.get("/patients/maya/state").json()["medications"][0]["name"] == "propranolol"


def test_context_stats_served_from_cache(client):
    assert client.get("/patients/maya/context_stats").json()["full_history_tokens"] == 11240


def test_brief_served_from_cache(client):
    assert "Since the last visit" in client.post("/patients/maya/brief", json={}).json()["markdown"]


def test_curated_question_returns_cached_prose(client):
    r = client.post("/patients/maya/ask", json={"question": QUESTION}).json()
    assert r["from_cache"] and not r["unanswered"]
    assert "40mg" in r["text"]


def test_curated_question_still_retrieves_live(client):
    """The Memory Inspector must show real retrieval, not a replay of it."""
    r = client.post("/patients/maya/ask", json={"question": QUESTION}).json()
    assert len(r["retrieved"]) == len(FAKE_MEMORIES)
    assert r["retrieved"][0]["score"] == 0.81


def test_pinned_block_present_without_any_llm(client):
    r = client.post("/patients/maya/ask", json={"question": QUESTION}).json()
    assert "amoxicillin" in r["pinned"]


def test_free_text_falls_back_honestly_but_still_retrieves(client):
    r = client.post("/patients/maya/ask", json={"question": "what did I eat on tuesday"}).json()
    assert r["unanswered"] and not r["from_cache"]
    low = r["text"].lower()
    # Assert on what the fallback must convey, not on particular wording: that the
    # prose was prepared in advance, and that retrieval nonetheless ran for real.
    assert "pre-written" in low or "written ahead" in low
    assert "live" in low
    assert len(r["retrieved"]) == len(FAKE_MEMORIES)


def test_red_flags_escalate_with_no_keys_at_all(client):
    r = client.post("/patients/maya/ask",
                    json={"question": "chest pain spreading into my left arm"}).json()
    assert r["escalated"] and "911" in r["text"]
