"""Ask — chat, with the retrieval made visible."""
import streamlit as st

from common import api, chip, patient_picker, setup

setup("Ask")
p = patient_picker()
pid = p["id"]

from medlog.demo import CURATED

SUGGESTED = CURATED.get(pid, [])

st.title("Ask")
st.caption("Questions about your own history. The panel on the right shows the working.")

key = f"chat_{pid}"
if key not in st.session_state:
    st.session_state[key] = []
if "pending" not in st.session_state:
    st.session_state["pending"] = None

left, right = st.columns([3, 2], gap="large")

with left:
    if not st.session_state[key]:
        st.markdown("**Try one of these:**")
        for i, q in enumerate(SUGGESTED):
            if st.button(q, key=f"sug{i}", use_container_width=True):
                st.session_state["pending"] = q
                st.rerun()

    for turn in st.session_state[key]:
        with st.chat_message(turn["role"]):
            if turn.get("escalated"):
                st.markdown(f'<div class="escalation">{turn["content"]}</div>',
                            unsafe_allow_html=True)
            elif turn.get("unanswered"):
                st.markdown(f'<div class="demo-note">{turn["content"]}</div>',
                            unsafe_allow_html=True)
            else:
                st.markdown(turn["content"])

typed = st.chat_input("Ask about your history...")
question = typed or st.session_state.pop("pending", None)

if question:
    st.session_state[key].append({"role": "user", "content": question})
    with left:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching your history..."):
                r = api("POST", f"/patients/{pid}/ask", json={"question": question})
            if r["escalated"]:
                st.markdown(f'<div class="escalation">{r["text"]}</div>', unsafe_allow_html=True)
            elif r.get("unanswered"):
                st.markdown(f'<div class="demo-note">{r["text"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(r["text"])
    st.session_state[key].append(
        {"role": "assistant", "content": r["text"], "escalated": r["escalated"],
         "unanswered": r.get("unanswered", False)}
    )
    st.session_state[f"last_{pid}"] = r

last = st.session_state.get(f"last_{pid}")

with right:
    st.markdown("#### Memory inspector")

    if not last:
        st.caption("Ask something to see which memories were used.")
    elif last["escalated"]:
        st.markdown(
            f'<div class="pin-block">Red flags matched: '
            f'<b>{", ".join(last["red_flags"])}</b>\n\n'
            f'Screening runs before retrieval and overrides it. No history was searched — '
            f'none of it would change the answer.</div>',
            unsafe_allow_html=True)
    else:
        used = last["usage"]["input_tokens"]
        stored = last.get("stored_memories") or 0
        n = len(last["retrieved"])
        try:
            full = api("GET", f"/patients/{pid}/context_stats")["full_history_tokens"]
            tokens = (f'<br><span style="opacity:0.75">≈{used:,} tokens of context · '
                      f'whole journal ≈{full:,}</span>')
        except Exception:
            tokens = f'<br><span style="opacity:0.75">≈{used:,} tokens of context</span>'
        st.markdown(
            f'<div class="counter"><b>{n} of {stored} memories</b> retrieved for this question'
            f'{tokens}</div>', unsafe_allow_html=True)
        st.caption(
            "At this journal size the token difference is small — 64 short entries is not much "
            "text. Selectivity is the point here; the token argument only bites once a record "
            "runs to years."
        )

        st.markdown("###### Always included")
        st.caption("Pulled straight from the reconciled record, never from search — "
                   "an allergy must not depend on ranking luck.")
        st.markdown(f'<div class="pin-block">{last["pinned"]}</div>', unsafe_allow_html=True)

        st.markdown(f"###### Retrieved ({len(last['retrieved'])})")
        for m in last["retrieved"]:
            score = m.get("score")
            s = f'<span class="mem-score">{score:.2f}</span>' if isinstance(score, (int, float)) else ""
            st.markdown(
                f'<div class="mem-row">{s}<b>{m.get("date") or "—"}</b> · {m["memory"]}<br>'
                f'{"".join(chip(c) for c in (m.get("categories") or []))}</div>',
                unsafe_allow_html=True)
