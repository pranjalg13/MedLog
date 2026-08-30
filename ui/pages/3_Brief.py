"""Brief — the page you hand across the desk."""
import streamlit as st
from markdown_it import MarkdownIt

from common import api, patient_picker, setup

setup("Brief")
p = patient_picker()
pid = p["id"]

st.title("Pre-visit brief")
st.caption("One page, written for a clinician who has ninety seconds and does not know your story.")

c1, c2 = st.columns([1, 3])
with c1:
    since = st.text_input("Since (YYYY-MM-DD)", value="",
                          placeholder="auto: your last visit",
                          help="Leave blank to start from the last time a clinician "
                               "gave you an instruction.")
    if st.button("Generate brief", type="primary", use_container_width=True):
        with st.spinner("Reading your whole record..."):
            st.session_state[f"brief_{pid}"] = api(
                "POST", f"/patients/{pid}/brief",
                json={"since": since.strip() or None})

b = st.session_state.get(f"brief_{pid}")

if not b:
    saved = api("GET", f"/patients/{pid}/brief", optional=True)
    if saved:
        b = {"markdown": saved["markdown"], **(saved.get("meta") or {})}
        st.caption(f"Showing the last brief, generated {saved['generated_at']}.")

if not b:
    # In demo mode this is a cache read, not an LLM call -- there is no reason to
    # make someone click a button to see the page the product is named for.
    from medlog import demo
    if demo.enabled():
        b = api("POST", f"/patients/{pid}/brief", json={"since": None})
        st.session_state[f"brief_{pid}"] = b

if not b:
    st.info("Generate a brief to see it here.")
    st.stop()

with c2:
    st.metric("Window", f"{b.get('since','?')} → {b.get('until','?')}")
    st.caption(f"{b.get('entry_count', 0)} entries in this window")

# Only the safety-relevant findings get a banner. Everything else is already in
# the document below, and seven amber boxes would bury the one that matters.
flags = b.get("flags", [])
for f in [x for x in flags if x.get("safety")][:2]:
    conf = f" · confidence: {f['confidence']}" if f.get("confidence") else ""
    ev = f" · {', '.join(f['evidence'])}" if f.get("evidence") else ""
    st.markdown(
        f'<div class="banner">⚠️ <b>Read this first</b>{conf}<br>{f["text"]}'
        f'<span style="opacity:0.7">{ev}</span></div>',
        unsafe_allow_html=True)

rest = [x for x in flags if not x.get("safety")]
if rest:
    with st.expander(f"{len(rest)} further observations and items to verify"):
        for f in rest:
            icon = "•" if f["kind"] == "pattern" else "?"
            conf = f" · {f['confidence']}" if f.get("confidence") else ""
            st.markdown(f"{icon} **{'Pattern' if f['kind']=='pattern' else 'Verify'}**{conf} — "
                        f"{f['text']}")
            if f.get("evidence"):
                st.caption(", ".join(f["evidence"]))

# Render to HTML ourselves: a styled wrapper cannot span separate st.markdown
# calls, and the print-styled document is the whole point of this page.
st.markdown(f'<div class="brief">{MarkdownIt().render(b["markdown"])}</div>',
            unsafe_allow_html=True)

st.download_button("Download as markdown", b["markdown"],
                   file_name=f"medlog-brief-{pid}-{b.get('until','')}.md",
                   mime="text/markdown")
