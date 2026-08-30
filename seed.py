#!/usr/bin/env python
"""Seed the demo patients.

Two things about the mem0 v3 API shape this script exists to work around, both
measured rather than assumed:

  add()          is ASYNCHRONOUS. It returns {"event_id", "status": "PENDING"} and
                 the extracted memories appear seconds later. Nothing downstream is
                 correct until extraction settles.

  delete_users() is ASYNCHRONOUS TOO, and keeps consuming writes after it returns.
                 Wiping and immediately adding loses everything: 20 adds after a
                 wipe left 0 survivors; the same 20 without a wipe left 19.

So: wipe and confirm it drained, add with light pacing, wait for extraction to
settle, backfill the entry->memory links, then verify every entry actually
produced something and retry the ones that did not.

    python seed.py                  # all fixtures
    python seed.py maya             # one patient
    python seed.py --backfill-only  # re-link without re-seeding
    python seed.py --skip-bootstrap
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

from medlog import db
from medlog.config import get_settings
from medlog.ingest.journal import backfill_entry_memories, ingest_entry
from medlog.memory.client import MedLogMemory

FIXTURES = Path(__file__).parent / "evals" / "fixtures"
PACE = 0.4  # seconds between adds; bursting drops a few extractions


def load(name: str) -> dict:
    return yaml.safe_load((FIXTURES / f"{name}.yaml").read_text())


def _ingest_all(pid: str, entries: list[dict], mem: MedLogMemory, label: str) -> None:
    for i, e in enumerate(entries, 1):
        ingest_entry(pid, e["text"], e["date"], memory=mem)
        bar = "#" * (i * 30 // len(entries))
        print(f"\r  {label} [{bar:<30}] {i}/{len(entries)}", end="", flush=True)
        time.sleep(PACE)
    print()


def seed_one(name: str, mem: MedLogMemory) -> None:
    fx = load(name)
    p, entries = fx["patient"], fx["entries"]
    pid = p["id"]
    print(f"\n{p['name']}  ({len(entries)} entries)")

    with db.connect() as c:
        c.execute("DELETE FROM entry_memories WHERE entry_id IN "
                  "(SELECT id FROM entries WHERE patient_id=?)", (pid,))
        for t in ("entries", "current_state", "briefs", "turns"):
            c.execute(f"DELETE FROM {t} WHERE patient_id=?", (pid,))
    db.upsert_patient(pid, p["name"], p.get("year_of_birth"), p.get("profile", ""))

    t0 = time.time()
    _ingest_all(pid, entries, mem, "writing ")

    expect = {str(e["date"]) for e in entries}

    def progress(n, covered, total):
        print(f"\r  extracting [{'#' * (covered * 30 // max(1, total)):<30}] "
              f"{covered}/{total} entries · {n} memories", end="", flush=True)

    n = mem.wait_until_settled(pid, expect_dates=expect, on_progress=progress)
    print()

    # Every entry must have produced something. Retry the ones that did not.
    for attempt in range(4):
        r = backfill_entry_memories(pid, memory=mem)
        missing = r["missing_dates"]
        if not missing:
            break
        print(f"  {len(missing)} entries produced no memories; retrying them "
              f"(attempt {attempt + 1}/4)")
        retry_entries = [e for e in entries if str(e["date"]) in missing]
        _ingest_all(pid, retry_entries, mem, "retrying")
        mem.wait_until_settled(pid)

    r = backfill_entry_memories(pid, memory=mem)
    cov = 100 * r["entries_linked"] / max(1, r["entries_total"])
    print(f"  {r['memories']} memories · {r['entries_linked']}/{r['entries_total']} "
          f"entries linked ({cov:.0f}% coverage) · {time.time()-t0:.0f}s")
    if r["missing_dates"]:
        print(f"  still uncovered: {', '.join(r['missing_dates'][:8])}"
              f"{' ...' if len(r['missing_dates']) > 8 else ''}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    names = args or ["maya", "arjun", "rosa"]
    get_settings().require("mem0_api_key")
    db.init_db()
    mem = MedLogMemory()

    if "--backfill-only" in sys.argv:
        for n in names:
            r = backfill_entry_memories(n, memory=mem)
            print(f"{n}: {r['memories']} memories, "
                  f"{r['entries_linked']}/{r['entries_total']} entries linked, "
                  f"{r['orphans']} orphans")
        return

    print("Clearing any previous copies (one batched wait for the async delete)...")
    wiped = mem.wipe_patients(names)
    print(f"  wiped: {', '.join(wiped) if wiped else 'nothing to clear'}")

    if "--skip-bootstrap" not in sys.argv:
        print("Applying clinical extraction contract to mem0 project...")
        mem.bootstrap()
        print("  done")

    for n in names:
        seed_one(n, mem)
    print("\nSeeded. Next:  make api   and   make ui")


if __name__ == "__main__":
    main()
