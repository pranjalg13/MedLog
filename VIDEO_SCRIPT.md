# MedLog — demo video script

**~6 minutes** spoken (~865 words). Record locally (`make demo-ui`) — no cold start, no network jitter, and no
"Hosted with Streamlit" badge.

Before recording: open the Journal page scrolled to the top, with Ask loaded in a second tab.

---

## 0:00 · What this is

> *[Journal page, top of Maya's entries]*

"This is MedLog. Someone writes free text about how they're feeling, whenever they feel like
it — no forms, no dropdowns.

You're looking at fourteen months of that. Sixty-four entries from a fictional patient, Maya.

What MedLog does with it is produce one page she hands her doctor."

---

## 0:20 · The problem

> *[Scroll slowly — let both 2025 and 2026 entries pass]*

"You get ten minutes with a GP, and you're expected to remember a year. When a symptom
started, what you tried, what the last doctor said to follow up on. Nobody can do that.

Meanwhile it's all written down. It's just spread across fourteen months in someone's own
words.

So the interesting question isn't summarising this. It's whether there's something in here
the person who wrote it hasn't noticed."

---

## 0:50 · Extraction is visible

> *[Point at the chips under an entry, expand "N memories from this entry"]*

"Every entry gets broken into facts, tagged by type. You can open any entry and see exactly
what came out of it — so when the system tells you something later, you can trace it back."

---

## 1:05 · The demo that matters

> *[Ask page → "Am I still taking propranolol, and at what dose?"]*

"A simple one first."

> *[Answer renders. Point at the right panel.]*

"Forty milligrams, since July — with the whole history. She was on twenty, stopped taking it
herself in April, restarted three weeks later, dose went up in July. Four events across seven
months, reconciled into one answer.

And on the right: **twelve memories out of a hundred and forty-eight.** That search just ran.
Those relevance scores are real."

> *[Click "Has this rash happened before?" — then stop talking and let it render]*

"Now the one that matters."

> *[Pause. Let people read.]*

"A rash, twice. September 2025 and May 2026. Both within days of starting amoxicillin. Both
gone about three days after stopping it.

Nobody wrote that connection down. The episodes are eight months apart, in completely
different words. The first time she blamed a new laundry detergent — and the second time she
ruled that out herself, because she'd used the same brand for eight months, and then had no
other explanation.

Her records say **no known drug allergies**. She gave that answer twice, including at an
urgent care where the doctor prescribing the second course couldn't see her history.

And notice it doesn't say she's allergic. It says the sequence happened twice and is worth
asking about. That's deliberate — spotting a coincidence is useful; asserting a cause is a
clinician's call."

---

## 2:35 · The brief

> *[Brief page]*

"This is the actual product. Written for someone who has ninety seconds and doesn't know her
story — what's changed with numbers, current medications with dates, her own questions in her
words.

The amoxicillin finding is at the top because it's most likely to change what the doctor
does. And every line carries the date it came from. Nothing here is a claim you can't trace."

---

## 3:05 · How mem0 is used

"The memory layer is **mem0**. It extracts facts from each entry, stores them, and returns the
relevant ones when you ask — that's the twelve out of a hundred and forty-eight.

But mem0 gives you facts, not conclusions. It'll hand you six memories mentioning a rash. It
won't tell you they're two episodes following the same antibiotic, contradicting the allergy
record. That part I built.

And there's a specific reason it needs building. mem0's current algorithm is **append-only —
it never overwrites or deletes.** For a memory layer that's correct: 'used to live in New
York' and 'now lives in San Francisco' both survive, which is what makes reasoning about time
possible.

For medication it's a hazard. If nothing is ever superseded, a drug someone stopped six
months ago can look current. So MedLog reads every memory at once — the only place you can
see that one fact replaced another — and works out what's true *now*.

Second piece: safety facts never go through search. Ask about a headache and no embedding
ranks 'rash after amoxicillin' as relevant. It's right — it isn't, by any similarity metric.
That's the failure. So allergies and current medications come straight from the reconciled
record on every turn. No top-k, no threshold."

---

## 4:35 · One honest note

"I expected the headline to be token savings — retrieve a few facts instead of pasting a
year. I measured it, and on this data it isn't true. Fourteen months is only about three
thousand tokens; pasting it all in costs almost nothing.

The real argument is reliability. The reconciliation happens once instead of being re-derived
from a wall of prose every time, and the allergy block can't be missed. Tokens only start to
matter once a record runs to years — and I haven't measured that, so I don't claim it."

---

## 5:05 · Deploy your own

> *[README or the Streamlit deploy screen]*

"It's a public repo. Clone it, add a mem0 key and an Anthropic key, and `make demo` seeds all
three patients — mem0 lets you backdate entries, so fourteen months loads in one command.

For a public URL there's a trick. Everything Claude produces here depends only on journal data
that doesn't change, so you compute it once locally and commit it. The deployed app then needs
**only the mem0 key** — no LLM key on the server, and it costs nothing to run. Search still
runs live, which is why those scores were real.

All fictional data, incidentally — no real patient records anywhere near it. Code's on GitHub.
Thanks for watching."

---

## Notes

**90-second cut:** Journal scroll (10s) → the rash question, full answer (40s) → Brief with
the amber banner (20s) → "mem0 is append-only, so MedLog owns currency" (20s).

**Don't skip** the pause after the rash answer. It's the only moment that does the
persuading — let people read it.

**Likely question — "isn't it just summarising?"** No: the journal never states the
connection, and there's a test asserting exactly that
([`tests/test_fixtures.py`](tests/test_fixtures.py) ·
`test_maya_never_states_the_connection`). If the prose gave it away, the demo would prove
nothing.
