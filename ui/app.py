"""MedLog — entry page."""
import streamlit as st

from common import api, patient_picker, setup

setup("Overview")
p = patient_picker()
info = api("GET", f"/patients/{p['id']}")

st.title("MedLog")
st.caption("A health journal that remembers, and turns months of it into one page for your doctor.")

c1, c2, c3 = st.columns(3)
c1.metric("Journal entries", info.get("entry_count", 0))
try:
    stats = api("GET", f"/patients/{p['id']}/context_stats")
    c2.metric("Whole journal, in tokens", f"≈{stats['full_history_tokens']:,}")
except Exception:
    pass
c3.metric("Patient", p["display_name"])

st.markdown("---")
st.markdown("""
**Journal** — everything the app is given: free text, no forms, no structure. Each entry shows
the facts extracted from it.

**Ask** — questions about your own history. The panel on the right shows exactly which memories
were retrieved, out of everything stored.

**Brief** — the one page you hand your doctor.

**Evals** — the harness that measures this against pasting the whole journal into the prompt.
""")
st.info("Pick a page from the sidebar.", icon="👈")
