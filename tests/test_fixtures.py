"""The demo data carries the demo. If the planted pattern drifts, the whole
thing stops being a demonstration of anything, so it is asserted here."""
import re
from pathlib import Path

import pytest
import yaml

FIX = Path(__file__).resolve().parents[1] / "evals" / "fixtures"
NAMES = ["maya", "arjun", "rosa"]


@pytest.fixture(scope="module")
def fixtures():
    return {n: yaml.safe_load((FIX / f"{n}.yaml").read_text()) for n in NAMES}


def blob(fx) -> str:
    """All entry text, lowercased with newlines collapsed -- fixture prose wraps,
    so phrase assertions must not depend on where a line happens to break."""
    return re.sub(r"\s+", " ", " ".join(e["text"] for e in fx["entries"])).lower()


def dates(fx) -> list[str]:
    """PyYAML gives back datetime.date for bare ISO dates."""
    return [str(e["date"]) for e in fx["entries"]]


@pytest.mark.parametrize("name", NAMES)
def test_entries_are_chronological_and_unique(fixtures, name):
    ds = dates(fixtures[name])
    assert ds == sorted(ds)
    assert len(set(ds)) == len(ds)


@pytest.mark.parametrize("name", NAMES)
def test_dates_are_iso(fixtures, name):
    for e in fixtures[name]["entries"]:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["date"])), e["date"]


@pytest.mark.parametrize("name", NAMES)
def test_patient_block_is_complete(fixtures, name):
    p = fixtures[name]["patient"]
    assert p["id"] == name and p["name"] and p["year_of_birth"]


def test_maya_has_two_amoxicillin_episodes(fixtures):
    """The wow moment: two rashes, both following amoxicillin, ~8 months apart."""
    entries = fixtures["maya"]["entries"]
    amox = [str(e["date"]) for e in entries if "amoxicillin" in e["text"].lower()]
    rash = [str(e["date"]) for e in entries if "rash" in e["text"].lower()]
    assert len(amox) >= 2, "need two separate amoxicillin courses"
    assert len(rash) >= 4, "need rash entries across both episodes"

    ep1 = [d for d in rash if d < "2026-01-01"]
    ep2 = [d for d in rash if d >= "2026-01-01"]
    assert ep1 and ep2, "the two episodes must sit in different years"

    gap_months = (int(ep2[0][:4]) - int(ep1[0][:4])) * 12 + int(ep2[0][5:7]) - int(ep1[0][5:7])
    assert 6 <= gap_months <= 10, f"episodes {gap_months} months apart, want ~8"


def test_maya_never_states_the_connection(fixtures):
    """The system has to find it. If the journal says it, we prove nothing."""
    text = blob(fixtures["maya"])
    for giveaway in ["allergic to amoxicillin", "amoxicillin allergy",
                     "reaction to the amoxicillin", "allergic reaction"]:
        assert giveaway not in text, f"journal gives the answer away: {giveaway!r}"


def test_maya_records_no_known_allergies(fixtures):
    """The contradiction the brief must surface."""
    text = blob(fixtures["maya"])
    assert "none" in text and "allerg" in text


def test_maya_propranolol_dose_escalation(fixtures):
    text = blob(fixtures["maya"])
    assert "20mg" in text and "40mg" in text


def test_maya_adherence_gap_is_recoverable(fixtures):
    """Stop, a spike, and a restart -- all three must be recoverable."""
    text = blob(fixtures["maya"])
    assert "i stopped taking the propranolol" in text
    assert "restarted the propranolol" in text
    assert "five migraines" in text


def test_maya_has_an_unclosed_clinician_instruction(fixtures):
    text = blob(fixtures["maya"])
    assert "mri" in text


def test_arjun_carries_both_directions_of_misreport(fixtures):
    text = blob(fixtures["arjun"])
    # Under-report: on atorvastatin, but says nothing for cholesterol.
    assert "atorvastatin" in text
    assert "don't take anything for cholesterol" in text
    # Over-report: stopped amlodipine, still lists it later.
    assert "stopped the amlodipine" in text


def test_rosa_has_a_measurable_regression(fixtures):
    text = blob(fixtures["rosa"])
    assert "88 degrees" in text and "82 degrees" in text


def test_eval_questions_reference_real_patients(fixtures):
    qs = yaml.safe_load((FIX.parent / "questions.yaml").read_text())
    assert {q["patient"] for q in qs} <= set(NAMES)
    for q in qs:
        for pat in q["must_match"]:
            re.compile(pat)


def test_redteam_cases_reference_real_patients(fixtures):
    cases = yaml.safe_load((FIX.parent / "redteam.yaml").read_text())
    assert {c["patient"] for c in cases} <= set(NAMES)
    assert any(c["category"] == "injection" for c in cases)
    assert any(c["category"] == "red_flag" for c in cases)
