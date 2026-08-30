"""Shared UI helpers: API client, palette, styling."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

API = os.environ.get("MEDLOG_API", "http://127.0.0.1:8000")

# Streamlit Community Cloud runs one process, so the UI cannot talk to a separate
# uvicorn. In single-process mode we dispatch straight into the FastAPI app in
# memory: same routes, same handlers, no second server, and FastAPI stays the
# real interface rather than becoming decorative.
#
# Starlette's TestClient, despite the name, is the supported *synchronous* client
# over an ASGI app -- it runs the event loop on a worker thread. httpx's own
# ASGITransport is async-only (it implements handle_async_request), so pairing it
# with a sync httpx.Client raises AttributeError on the first request.
SINGLE_PROCESS = os.environ.get("MEDLOG_SINGLE_PROCESS", "").strip() in ("1", "true", "yes")


@st.cache_resource
def _in_process_client():
    from starlette.testclient import TestClient

    from medlog.api.main import app as _app
    return TestClient(_app, base_url="http://medlog")

# One colour per extraction category, so a chip's meaning is learnable at a glance.
CATEGORY_COLORS = {
    "medication":           ("#1e3a5f", "#7cc4ff"),
    "symptom":              ("#5a2a2a", "#ff9b9b"),
    "allergy_intolerance":  ("#5c3d00", "#ffc861"),
    "condition":            ("#3d2a5c", "#c4a3ff"),
    "procedure_or_test":    ("#0f3d3d", "#68d8d8"),
    "vital_or_measurement": ("#1a3d1a", "#8fd98f"),
    "adherence":            ("#4a3410", "#e8b96a"),
    "lifestyle":            ("#2a2a3d", "#a8b0d8"),
    "social_context":       ("#33283d", "#c0a8d8"),
    "care_question":        ("#123a4a", "#7fd4f0"),
    "clinician_instruction":("#14304a", "#8fbdf0"),
    "red_flag":             ("#5c1414", "#ff8080"),
}
DEFAULT_COLOR = ("#2b2b2b", "#bbbbbb")

CSS = """
<style>
.chip { display:inline-block; padding:2px 9px; margin:2px 3px 2px 0; border-radius:11px;
        font-size:0.72rem; font-weight:500; line-height:1.5; }
.entry-card { border-left:3px solid #3a3f4b; padding:0.6rem 0 0.6rem 0.9rem;
              margin-bottom:1.1rem; }
.entry-date { font-size:0.78rem; letter-spacing:0.04em; text-transform:uppercase;
              opacity:0.62; margin-bottom:0.35rem; }
.entry-text { white-space:pre-wrap; line-height:1.55; margin-bottom:0.45rem; }
.pin-block { background:rgba(255,180,80,0.09); border-left:3px solid #e0a33e;
             padding:0.7rem 0.9rem; border-radius:0 5px 5px 0; font-size:0.83rem;
             white-space:pre-wrap; font-family:ui-monospace,SFMono-Regular,monospace;
             line-height:1.5; }
.mem-row { border-left:2px solid #3a4a5a; padding:0.35rem 0 0.35rem 0.65rem;
           margin-bottom:0.5rem; font-size:0.8rem; line-height:1.45; }
.mem-score { float:right; opacity:0.5; font-size:0.72rem; font-variant-numeric:tabular-nums; }
.counter { font-family:ui-monospace,SFMono-Regular,monospace; font-size:0.8rem;
           padding:0.55rem 0.75rem; background:rgba(120,200,255,0.08);
           border-radius:5px; line-height:1.7; }
.counter b { color:#7cc4ff; }
.counter s { opacity:0.45; }
.brief { background:#fbfaf7; color:#1a1a1a; padding:2.6rem 3rem; border-radius:3px;
         max-width:52rem; margin:0 auto; box-shadow:0 1px 14px rgba(0,0,0,0.28);
         font-family:Georgia,'Times New Roman',serif; line-height:1.62; }
.brief h2 { font-size:1.02rem; text-transform:uppercase; letter-spacing:0.07em;
            border-bottom:1px solid #d8d3c8; padding-bottom:0.28rem;
            margin:1.7rem 0 0.7rem; color:#2a2a2a; }
.brief h2:first-child { margin-top:0; }
.brief ul { margin:0.4rem 0 0.4rem 1.1rem; }
.brief li { margin-bottom:0.32rem; }
.brief p { margin:0.5rem 0; }
.banner { background:#fff4d6; border:1px solid #e0a33e; border-left:4px solid #e0a33e;
          color:#4a3410; padding:0.85rem 1.1rem; border-radius:4px; margin-bottom:1.1rem;
          font-size:0.88rem; line-height:1.55; }
.escalation { background:rgba(220,50,50,0.11); border-left:4px solid #d63a3a;
              padding:0.9rem 1.1rem; border-radius:0 5px 5px 0; }
.demo-banner { background:rgba(120,200,255,0.10); border:1px solid rgba(120,200,255,0.35);
               padding:0.6rem 0.9rem; border-radius:5px; font-size:0.82rem;
               line-height:1.5; margin-bottom:1rem; }
.demo-note { background:rgba(255,180,80,0.08); border-left:3px solid #e0a33e;
             padding:0.7rem 0.95rem; border-radius:0 5px 5px 0; font-size:0.88rem; }
</style>
"""


def setup(title: str) -> None:
    st.set_page_config(page_title=f"MedLog · {title}", page_icon="🩺", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    _boot_sqlite()
    demo_banner()


@st.cache_resource
def _boot_sqlite() -> bool:
    """Rebuild SQLite from the committed fixtures on a cold deploy.

    medlog.db is gitignored, so a fresh instance starts with no entries. The
    fixtures are committed and the mem0 memories already exist in the cloud, so
    this only reloads the local raw text -- no keys, no mem0 writes, under a second.
    """
    from medlog import db as _db
    _db.init_db()
    if _db.list_patients():
        return True

    import yaml
    from medlog.ingest.journal import _iso
    root = Path(__file__).resolve().parents[1]
    for f in sorted((root / "evals" / "fixtures").glob("*.yaml")):
        fx = yaml.safe_load(f.read_text())
        p = fx["patient"]
        _db.upsert_patient(p["id"], p["name"], p.get("year_of_birth"), p.get("profile", ""))
        for e in fx["entries"]:
            _db.add_entry(p["id"], _iso(e["date"]), e["text"])

    links = json.loads((root / "demo_cache" / "entry_memories.json").read_text()) \
        if (root / "demo_cache" / "entry_memories.json").exists() else {}
    for pid, by_date in links.items():
        for entry in _db.get_entries(pid, ascending=True):
            rows = by_date.get(entry["entry_date"])
            if rows:
                _db.link_memories(entry["id"], rows)
    return True


def demo_banner() -> None:
    from medlog import demo
    if not demo.enabled():
        return
    st.markdown(
        '<div class="demo-banner">🔎 <b>Public demo.</b> Search, the pinned safety block and '
        'red-flag screening all run <b>live</b> — every memory and relevance score below is '
        'computed as you click. Answers to the listed questions were written ahead of time, so '
        'nothing here calls a language model. '
        '<a href="https://github.com/pranjalg13/MedLog" target="_blank">Source on GitHub</a>.</div>',
        unsafe_allow_html=True)


def chip(label: str) -> str:
    bg, fg = CATEGORY_COLORS.get(label, DEFAULT_COLOR)
    return f'<span class="chip" style="background:{bg};color:{fg}">{label.replace("_"," ")}</span>'


def api(method: str, path: str, optional: bool = False, **kw) -> Any:
    """optional=True returns None on a 404 instead of halting the page -- some
    endpoints legitimately have nothing yet."""
    try:
        if SINGLE_PROCESS:
            r = _in_process_client().request(method, path, **kw)
        else:
            r = httpx.request(method, f"{API}{path}", timeout=180.0, **kw)
    except httpx.ConnectError:
        st.error(f"Cannot reach the MedLog API at {API}. Start it with `make api`.")
        st.stop()
    if r.status_code == 404 and optional:
        return None
    if r.status_code >= 400:
        detail = r.json().get("detail", r.text) if r.headers.get("content-type","").startswith("application/json") else r.text
        st.error(f"API error {r.status_code}: {detail}")
        st.stop()
    return r.json()


def patient_picker() -> dict[str, Any]:
    people = api("GET", "/patients")
    if not people:
        st.warning("No patients yet. Run `make demo` to seed the demo data.")
        st.stop()
    names = {p["display_name"]: p for p in people}
    default = "Maya Chen" if "Maya Chen" in names else list(names)[0]
    with st.sidebar:
        st.markdown("### Patient")
        chosen = st.selectbox("Patient", list(names), index=list(names).index(default),
                              label_visibility="collapsed")
        p = names[chosen]
        if p.get("profile"):
            st.caption(p["profile"])
    st.session_state["patient_id"] = p["id"]
    return p
