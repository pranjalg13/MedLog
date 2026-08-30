"""Journal — the timeline, and what each entry became."""
import datetime as dt

import streamlit as st

from common import api, chip, patient_picker, setup

setup("Journal")
p = patient_picker()
pid = p["id"]

st.title("Journal")
st.caption("Everything MedLog is ever given. The chips under each entry are the facts it extracted.")

with st.expander("Add an entry"):
    with st.form("new_entry", clear_on_submit=True):
        date = st.date_input("Date", value=dt.date.today())
        text = st.text_area("What's going on?", height=130,
                            placeholder="Symptoms, medications, how you've been sleeping, "
                                        "what you want to ask your doctor...")
        if st.form_submit_button("Save entry", type="primary"):
            if text.strip():
                r = api("POST", f"/patients/{pid}/entries",
                        json={"text": text, "entry_date": date.isoformat()})
                st.success(f"Saved — {len(r['memories'])} facts extracted.")
                st.rerun()
            else:
                st.warning("Nothing to save.")

entries = api("GET", f"/patients/{pid}/entries")
st.caption(f"{len(entries)} entries, most recent first")

for e in entries:
    mems = e.get("memories") or []
    cats = sorted({c for m in mems for c in (m.get("categories") or [])})
    st.markdown(
        f'<div class="entry-card">'
        f'<div class="entry-date">{e["entry_date"]}</div>'
        f'<div class="entry-text">{e["text"].strip()}</div>'
        f'{"".join(chip(c) for c in cats)}'
        f'</div>',
        unsafe_allow_html=True,
    )
    if mems:
        with st.expander(f"{len(mems)} memories from this entry"):
            for m in mems:
                st.markdown(
                    f'<div class="mem-row">{m["memory"]}<br>'
                    f'{"".join(chip(c) for c in (m.get("categories") or []))}'
                    f'<code style="font-size:0.68rem;opacity:0.45">{m["memory_id"][:8]}</code>'
                    f'</div>', unsafe_allow_html=True)
