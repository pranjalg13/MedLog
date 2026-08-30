# MedLog

A health journal that remembers, and turns months of it into one page you hand your doctor.

Built on [mem0](https://mem0.ai) for memory, Claude for reconciliation and writing.
**[Live demo](https://medlog.streamlit.app)** · runs without calling a language model.

```
Streamlit ──> FastAPI ──> mem0 (v3)   distilled memories
                 ├──────> Claude      reconcile · answer · brief
                 └──────> SQLite      raw entries, audit trail
```

---

## What it does that a chatbot can't

> **"Has this rash happened before?"**
>
> Yes — twice, [2025-09-17] and [2026-05-22]. Both began within days of starting
> amoxicillin and settled about three days after stopping it. Your records say no known
> drug allergies, given [2025-09-12] and again [2026-05-19]. Worth raising with your GP.

Nobody wrote that down. The episodes are eight months apart, described in different words,
from different clinics, and the first was blamed on laundry detergent. It was inferred
across a year of unstructured prose.

---

## Three things that aren't in the tutorial

**1. mem0 v3 is append-only, which is a safety problem in medicine.**
The [v3 algorithm](https://docs.mem0.ai/migration/platform-v2-to-v3) never overwrites or
deletes. Right for a memory layer — "used to live in NY" and "now lives in SF" both
survive. Wrong for medication, where a drug stopped six months ago can surface as current.
[`memory/reconcile.py`](medlog/memory/reconcile.py) reads every memory at once and projects
the stream into a current-state snapshot: what's active, what stopped and when, what's
uncertain, what contradicts itself.

**2. Both mem0 write paths are async, and one eats your data.**
Not documented — found by measurement. `add()` returns `PENDING`, never the memories.
`delete_users()` keeps consuming writes after it returns: 20 adds after a wipe left **0**
survivors; the same 20 without a wipe left 19. The first seed silently lost 49 of Maya's 64
entries, including both amoxicillin courses. The demo looked fine and was hollow.
[`seed.py`](seed.py) now drains deletions, paces writes, waits on coverage, and re-adds any
entry that produced nothing.

**3. Allergies must not depend on ranking luck.**
Ask about a headache and no embedding ranks "rash after amoxicillin" as relevant — it
isn't, by any similarity metric, and that's exactly the failure.
[`safety/pinned.py`](medlog/safety/pinned.py) builds a small block from reconciled state
and injects it on every turn. No vector search, no `top_k`.

Safety is measured, not asserted: `make redteam` runs 24 adversarial cases — dosage
requests, diagnosis requests, red-flag symptoms, fabrication bait, four prompt injections.
Red-flag screening is [rule-based](medlog/safety/redflags.py) so it can't be talked out of
firing. Journal text is data, never instructions, at both extraction and answering.

---

## An honest correction

I expected the headline to be token savings. **Measured, it isn't:**

| | tokens |
|---|---|
| MedLog context | ≈3,047 |
| Whole journal pasted in | ≈3,654 |

1.2×. Maya's entire fourteen months is ~2,960 tokens — 64 short entries isn't much text, and
pasting it all in costs almost nothing.

So the value is **reliability, not economy**: 12 memories selected from 148; reconciled state
computed once rather than re-derived per question; the allergy block guaranteed present every
turn. Full-context *might* surface the amoxicillin pattern depending on phrasing. MedLog
can't fail to. The token argument only bites once a record runs to years — a projection this
repo doesn't measure, so I won't claim it.

`make evals` runs the three-arm ablation (no-memory / full-context / MedLog) on 26 labelled
questions. Not yet run in this checkout.

---

## Setup

```bash
make install                    # venv + deps
cp .env.example .env            # add MEM0_API_KEY and ANTHROPIC_API_KEY
make demo                       # seed 3 patients, 109 backdated entries
make api && make ui             # :8000 and :8501
make test                       # 85 tests, no keys, no network
```

Keys: [app.mem0.ai](https://app.mem0.ai) (free tier covers this) and
[console.anthropic.com](https://console.anthropic.com).

mem0's `add()` takes a `timestamp`, so every fixture entry is backdated to the day it
describes — fourteen months of history in one command.

---

## Deploying your own

The public demo needs **only `MEM0_API_KEY`**. Every Claude call produces something derived
from frozen data, so it's computed once and committed to `demo_cache/`. Retrieval, the
pinned block and red-flag screening still run live.

```bash
make precompute     # once, with both keys -> demo_cache/
make demo-ui        # exactly what production runs, ANTHROPIC_API_KEY blanked
```

Then on [Streamlit Community Cloud](https://share.streamlit.io): deploy from a public repo,
main file `ui/app.py`, and set three secrets —

```toml
MEM0_API_KEY = "m0-..."
MEDLOG_DEMO = "1"
MEDLOG_SINGLE_PROCESS = "1"
```

`MEDLOG_SINGLE_PROCESS` makes the UI dispatch into FastAPI in-process, since Community Cloud
runs one process. SQLite rebuilds from committed fixtures on cold boot. Expect ~1GB RAM and a
~30s wake after 12h idle.

---

## Demo data

Fictional, hand-authored. No real patient data, none derived from any.

| Patient | Span | Exercises |
|---|---|---|
| **Maya Chen**, 34 | 64 entries, 14 months | The amoxicillin pattern; propranolol 20→40mg; a self-discontinuation with a measurable migraine spike; a forgotten MRI referral |
| **Arjun Nair**, 62 | 23 entries, 12 months | Under-reporting an active statin *and* over-reporting a stopped drug — errors in both directions |
| **Rosa Delgado**, 47 | 22 entries, 5 months | Post-op trajectory, a resolved wound infection, a physio lapse with measurable regression |

[`tests/test_fixtures.py`](tests/test_fixtures.py) asserts the planted pattern survives —
including that Maya's journal **never states the connection**. If the prose gave it away, the
demo would prove nothing.

---

## Constraints

- **Fictional data only.** A portfolio project has no business touching real PHI, and a BAA
  would be required regardless.
- **Not a medical device.** No clinical validation, no advice. It helps someone describe
  their history; it does not interpret it.
- **Red-flag screening over-triggers by design.** A false positive costs thirty seconds of
  reassurance.
- **Reconciliation is one pass over every memory.** Fine at 250/patient; needs chunking well
  before 10,000.

---

## Layout

```
medlog/
  memory/schema.py     clinical extraction contract
  memory/client.py     mem0 v3 wrapper: filters, backdating, async handling
  memory/reconcile.py  ★ append-only stream -> current state + conflicts
  safety/pinned.py     ★ never-forget block, deterministic
  safety/redflags.py   rule-based escalation
  context/assembler.py prompt assembly, reports what it used
  brief/generate.py    ★ the pre-visit brief
ui/                    Streamlit: Journal · Ask · Brief · Evals
evals/                 fixtures, 26 questions, 24 red-team cases, harness
```
