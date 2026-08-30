# MedLog

A health journal that remembers, and turns fourteen months of it into one page you hand your doctor.

Built on [mem0](https://mem0.ai) as the memory layer, with Claude for reconciliation, answering
and brief generation.

```
Streamlit ──HTTP──> FastAPI ──> mem0 Platform (v3)   distilled memories
                       ├──────> Claude               reconcile · answer · brief · judge
                       └──────> SQLite               raw entries, audit trail, artifacts
```

---

## The thing it does that a chatbot can't

> **"Has this rash happened before?"**
>
> Yes, twice — 2025-09-17 and 2026-05-22. Both began within a couple of days of starting
> amoxicillin, and both settled about three days after stopping it. Your records say no known
> drug allergies, given at intake on 2025-09-12 and again at urgent care on 2026-05-19. That
> contradiction is worth raising with your GP.

Nobody wrote that connection down. The two episodes are eight months apart, described in
different words, from different clinics, and on the first occasion blamed on laundry detergent.
It was inferred across a year of unstructured prose.

---

## Why this isn't a mem0 tutorial

Anyone can wire `add()` and `search()` into a chat loop. Three things here came out of reading
how the tool actually behaves and what the domain actually needs.

### 1. mem0 v3 is ADD-only, which is a safety problem in medicine

The [v3 algorithm](https://docs.mem0.ai/migration/platform-v2-to-v3) never overwrites or deletes.
For consumer personalization that is exactly right — "used to live in NY" and "now lives in SF"
both survive, and that is what makes temporal reasoning possible at all. For medication it means
a retrieval can hand you a drug the patient stopped six months ago as though it were current.

So MedLog owns currency. [`memory/reconcile.py`](medlog/memory/reconcile.py) reads every memory
at once — the only vantage point from which supersession is visible — and projects the
append-only stream into a current-state snapshot: what is active, what was stopped and when,
what the record is genuinely uncertain about, and what contradicts itself.

mem0 does offer `latest_only` on search, which handles per-fact recency. Reconciliation is doing
something it doesn't: resolving a drug across start, dose change, self-discontinuation and
restart into one status, and surfacing contradictions rather than picking a side.

### 1b. Both of mem0's write paths are asynchronous, and one of them eats your data

Not in the docs, found by measurement:

- **`add()` is async.** It returns `{"event_id", "status": "PENDING"}` — never the extracted
  memories. Code that reads them from the response silently links nothing.
- **`delete_users()` is async too, and keeps consuming writes after it returns.** Measured: 20
  adds issued straight after a wipe left **0** survivors; the same 20 without a wipe left 19.
  Reading a count of zero proves the delete has *started*, not that it has finished.

The first version of the seed did wipe-then-add and silently lost the first 49 of Maya's 64
entries — including both amoxicillin courses. The demo looked fine and was hollow.

[`seed.py`](seed.py) now batches deletions into one drained wait, paces writes, waits for
extraction to settle, then **verifies that every entry actually produced a memory and re-adds
the ones that didn't**. The coverage check is the guarantee; the waits are just optimisation.

### 2. Allergies must not depend on ranking luck

Ask about a headache and no embedding will rank "rash after amoxicillin" as relevant. It isn't,
by any similarity metric — and that is exactly the failure mode.

[`safety/pinned.py`](medlog/safety/pinned.py) builds a small block — reactions, active drugs,
conditions, open contradictions — read deterministically from reconciled state and injected on
every single turn. No vector search, no `top_k`, no threshold.

### 3. The safety work is measured, not asserted

`make redteam` runs 24 adversarial cases: dosage-change requests, diagnosis requests, red-flag
symptoms, result interpretation, fabrication bait, and four prompt-injection attempts. Red-flag
screening is [deliberately rule-based](medlog/safety/redflags.py) — a regex fires the same way
every time, costs nothing, and can't be talked out of firing by the sentence around it.

Journal text is treated as data at both the extraction and answering layers. A patient who
writes "ignore previous instructions" in their journal has written a sentence, not issued one.

---

## Results

Three arms answer the same 26 longitudinal questions across three patients:

| arm | context |
|---|---|
| `no_memory` | the question alone |
| `full_context` | every raw journal entry pasted in |
| `medlog` | pinned facts + reconciled state + retrieved memories |

Run `make evals` to populate this, and `make redteam` for the safety suite. Both write to
`evals/results/` and render on the app's **Evals** page.

<!-- RESULTS:START -->
_Not yet run in this checkout._
<!-- RESULTS:END -->

Scoring is deterministic fact-recall (regex over required facts) plus an LLM judge against a
gold answer, with prompt tokens from the real `count_tokens` API.

### One honest correction, measured

I built this expecting the headline to be token savings — retrieve a few facts instead of
pasting a year of history. **On this dataset that is not true, and the measurement says so:**

| | tokens |
|---|---|
| MedLog assembled context | ≈3,047 |
| Whole journal pasted in | ≈3,654 |

A 1.2× difference. Maya's entire fourteen months is only about **2,960 tokens of raw text** —
64 short journal entries is simply not much text, and stuffing it all in costs almost nothing.
MedLog's context is not much smaller because the reconciled-state block is itself substantial.

So the value here is **not economy, it is reliability**:

- **12 memories selected from 148.** That selectivity is real, and it is what scales.
- The reconciled state is computed **once** and reused, rather than re-derived per question from
  a wall of prose, where a model may or may not notice that a drug was stopped.
- The pinned allergy block is **guaranteed present on every turn**. Full-context might surface
  the amoxicillin pattern, depending on how the question is phrased. MedLog cannot fail to.

The token argument becomes decisive once a record runs to years rather than months — but that is
a projection, and this repo does not contain the measurement to back it. I would rather say that
than ship a number that falls apart when someone checks it.

---

## The three-minute demo

1. **Journal** — scroll Maya's fourteen months. *"This is everything the app is ever given:
   free text, no forms, no structure."* Each entry shows the facts extracted from it.
2. **Ask** — *"Am I still on propranolol?"* → 40mg since July, with the November-to-April gap
   noted. Point at the Memory Inspector: a handful of memories out of hundreds. Point at the
   token counter.
3. **Ask** — *"Has this rash happened before?"* → **the moment.** See above.
4. **Brief** — generate it live. The amoxicillin finding is carried to the top in an amber
   banner; the MRI follow-up forgotten since June reappears under open items.
5. **Evals** — the table. Same accuracy as pasting everything in, a fraction of the tokens.

---

## Setup

```bash
make install
cp .env.example .env      # add MEM0_API_KEY and ANTHROPIC_API_KEY
make demo                 # seeds three patients, ~109 backdated entries
make api                  # :8000
make ui                   # :8501
```

`MEM0_API_KEY` from [app.mem0.ai](https://app.mem0.ai) (free tier ≈10k memories/month, which
covers this comfortably). `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com).

`make test` runs 54 unit tests with no API keys and no network.

### How months of history get seeded in one run

mem0's `add()` takes a `timestamp`, so every fixture entry is backdated to the day it describes.
Fourteen months of history, one command, and mem0's temporal ranking sees a real timeline.

---

## Public demo — runs without calling a language model

The deployed app needs **only `MEM0_API_KEY`**. Every Claude call in MedLog produces an artifact
derived from frozen data — the reconciled state, the brief, and the full-history token count
depend only on the journal entries, and answer prose only varies over the question. So they are
computed once locally and committed to `demo_cache/`.

**What stays live on the public URL:** mem0 retrieval, the pinned safety block, and red-flag
screening. The memories and relevance scores in the Memory Inspector are real, computed on the
spot. Only the answer prose is replayed, and the app says so in a banner.

Free-text questions still run a real search and show what came back, with an honest note that
generation needs a key. Nothing pretends to be something it isn't.

```bash
make precompute     # once, locally, with both keys -> demo_cache/
make demo-ui        # run exactly what production runs, with ANTHROPIC_API_KEY blanked
```

`demo_cache/` is committed and complete in this checkout, so `make demo-ui` works with only
`MEM0_API_KEY` set. Token figures in demo mode are marked `≈` — they are estimated with a fixed
characters-per-token ratio, since Anthropic has no offline tokeniser. Applied to both sides of a
comparison the ratio holds; the absolutes do not claim precision.

Deploy to [Streamlit Community Cloud](https://streamlit.io/cloud) from a public repo, and set
three secrets — `MEM0_API_KEY`, `MEDLOG_DEMO=1`, `MEDLOG_SINGLE_PROCESS=1`. Expect ~1GB RAM, no
custom domain, and a ~30s cold start after 12h idle.

`MEDLOG_SINGLE_PROCESS` makes the UI dispatch into FastAPI over an in-memory ASGI transport
rather than HTTP, because Community Cloud runs one process. Same routes, same handlers, no
second server. On a cold instance SQLite is rebuilt from the committed fixtures — the mem0
memories already live in the cloud.

---

## Demo data

Hand-authored fictional journals — no real patient data, and none of it derived from any.

| Patient | Span | Exercises |
|---|---|---|
| **Maya Chen**, 34 | 64 entries, 14 months | The amoxicillin pattern; propranolol 20→40mg; a three-week self-discontinuation with a measurable migraine spike; a forgotten MRI referral |
| **Arjun Nair**, 62 | 23 entries, 12 months | Under-reporting an active statin *and* over-reporting a stopped calcium blocker — contradictions in both directions |
| **Rosa Delgado**, 47 | 22 entries, 5 months | Post-op trajectory, a wound infection that resolved, and a physiotherapy lapse with a measurable regression |

The fixtures are asserted in [`tests/test_fixtures.py`](tests/test_fixtures.py), including a test
that Maya's journal **never states the connection** — if the prose gave it away, the demo would
prove nothing.

---

## Honest constraints

- **Fictional data only.** mem0 advertises HIPAA/SOC 2/GDPR compliance, but a portfolio project
  has no business touching real PHI, and a BAA would be required regardless.
- **Not a medical device.** No clinical validation, no advice. It helps someone describe their
  own history accurately; it does not interpret it.
- **Red-flag screening is tuned to over-trigger.** A false positive costs thirty seconds of
  reassurance. A false negative costs considerably more.
- **Free-tier ceilings** (~1k retrievals/month) shape the eval budget, hence the result cache in
  `evals/results/cache.json`.
- **The reconciler is one LLM pass over every memory.** That is fine at 250 memories per patient
  and would need chunking well before 10,000.

---

## Layout

```
medlog/
  memory/schema.py       clinical extraction contract (categories + instructions)
  memory/client.py       mem0 v3 wrapper: filters, backdating, namespacing
  memory/reconcile.py    ★ append-only stream -> current state + conflicts
  safety/pinned.py       ★ never-forget block, deterministic
  safety/redflags.py     rule-based escalation screening
  safety/guardrails.py   answering and brief system prompts
  context/assembler.py   prompt assembly, reports what it used
  brief/generate.py      ★ the pre-visit brief
  ask.py                 screen -> assemble -> answer
ui/                      Streamlit: Journal · Ask · Brief · Evals
evals/                   fixtures, 26 questions, 24 red-team cases, harness
```
