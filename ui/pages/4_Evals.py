"""Evals — the measured case, read from cached results so a demo costs nothing."""
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from common import setup

setup("Evals")
RESULTS = Path(__file__).resolve().parents[2] / "evals" / "results"

st.title("Evaluation")
st.caption("Measured, not asserted. Run `make evals` and `make redteam` to regenerate.")

ab = RESULTS / "ablation.json"
if not ab.exists():
    st.warning("No ablation results yet. Run `make evals`.")
else:
    d = json.loads(ab.read_text())
    df = pd.DataFrame(d["summary"])

    st.subheader("Ablation")
    st.caption(f"{d['n_questions']} longitudinal questions across three patients, "
               "each asked three ways.")

    show = df.rename(columns={
        "arm": "Arm", "n": "N", "correct_pct": "Correct %",
        "fact_recall_pct": "Fact recall %", "median_input_tokens": "Median prompt tokens",
        "p50_latency_ms": "p50 ms", "p95_latency_ms": "p95 ms",
        "cost_per_query_usd": "$ / query"})
    st.dataframe(
        show.style.format({"Correct %": "{:.0f}", "Fact recall %": "{:.0f}",
                           "Median prompt tokens": "{:,.0f}", "p50 ms": "{:,.0f}",
                           "p95 ms": "{:,.0f}", "$ / query": "${:.4f}"}),
        hide_index=True, use_container_width=True)

    full = df[df.arm == "full_context"]
    ml = df[df.arm == "medlog"]
    if not full.empty and not ml.empty and ml.iloc[0].median_input_tokens:
        ratio = full.iloc[0].median_input_tokens / ml.iloc[0].median_input_tokens
        c1, c2, c3 = st.columns(3)
        c1.metric("Prompt tokens vs full history", f"{ratio:.1f}× fewer")
        c2.metric("Correct", f"{ml.iloc[0].correct_pct:.0f}%",
                  f"{ml.iloc[0].correct_pct - full.iloc[0].correct_pct:+.0f} pts vs full context")
        c3.metric("Cost per query", f"${ml.iloc[0].cost_per_query_usd:.4f}",
                  f"{(ml.iloc[0].cost_per_query_usd/full.iloc[0].cost_per_query_usd - 1)*100:+.0f}%",
                  delta_color="inverse")

    st.altair_chart(
        alt.Chart(df).mark_circle(size=340).encode(
            x=alt.X("median_input_tokens:Q", scale=alt.Scale(type="log"),
                    title="Median prompt tokens (log)"),
            y=alt.Y("correct_pct:Q", scale=alt.Scale(domain=[0, 105]), title="Correct %"),
            color=alt.Color("arm:N", title="Arm"),
            tooltip=["arm", "correct_pct", "median_input_tokens", "cost_per_query_usd"],
        ).properties(height=320), use_container_width=True)

    with st.expander("Per-question detail"):
        rows = pd.DataFrame(d["rows"])[
            ["id", "patient", "arm", "correct", "fact_recall", "input_tokens", "latency_ms"]]
        st.dataframe(rows, hide_index=True, use_container_width=True)

rt = RESULTS / "redteam.json"
st.markdown("---")
st.subheader("Safety suite")
if not rt.exists():
    st.warning("No red-team results yet. Run `make redteam`.")
else:
    d = json.loads(rt.read_text())
    st.metric("Passed", f"{d['passed']}/{d['total']}")
    rows = pd.DataFrame(d["rows"])
    for cat, grp in rows.groupby("category"):
        ok = int(grp.passed.sum())
        icon = "✅" if ok == len(grp) else "❌"
        with st.expander(f"{icon} {cat} — {ok}/{len(grp)}"):
            for _, r in grp.iterrows():
                st.markdown(f"**{'PASS' if r.passed else 'FAIL'}** · `{r.id}`"
                            + (f" — {'; '.join(r.failures)}" if r.failures else ""))
                st.caption(r.answer[:400] + ("..." if len(r.answer) > 400 else ""))
