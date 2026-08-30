"""Thin wrapper over mem0's MemoryClient.

Centralises the v3 conventions so they are stated once: entity IDs live inside
`filters` on read, `user_id` is top-level on write, and every patient is
namespaced so one mem0 project can hold many patients without collision.
"""
from __future__ import annotations

import datetime as dt
import time
from functools import lru_cache
from typing import Any

from mem0 import MemoryClient

from medlog.config import get_settings
from medlog.memory import schema

NAMESPACE = "medlog"


def user_id_for(patient_id: str) -> str:
    return f"{NAMESPACE}_{patient_id}"


def to_epoch(date_str: str) -> int:
    """ISO date -> epoch seconds at midday, so timezone drift cannot move the date."""
    d = dt.date.fromisoformat(date_str[:10])
    return int(dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=dt.timezone.utc).timestamp())


@lru_cache
def raw_client() -> MemoryClient:
    s = get_settings()
    s.require("mem0_api_key")
    return MemoryClient(api_key=s.mem0_api_key)


class MedLogMemory:
    """All mem0 access goes through here."""

    def __init__(self, client: MemoryClient | None = None):
        self.client = client or raw_client()

    # ---------- write ----------

    def add_entry(
        self,
        patient_id: str,
        text: str,
        entry_date: str,
        source: str = "patient_journal",
    ) -> dict[str, Any]:
        """Store one journal entry.

        `timestamp` backdates the memory to when the event actually happened,
        which is what lets us seed months of history in a single run and what
        makes mem0's temporal ranking meaningful.
        """
        return self.client.add(
            messages=[{"role": "user", "content": text}],
            user_id=user_id_for(patient_id),
            metadata={"source": source, "entry_date": entry_date[:10], "patient_id": patient_id},
            timestamp=to_epoch(entry_date),
        )

    # ---------- read ----------

    def search(
        self,
        patient_id: str,
        query: str,
        top_k: int | None = None,
        categories: list[str] | None = None,
        rerank: bool = False,
        latest_only: bool = False,
        reference_date: str | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        s = get_settings()
        opts: dict[str, Any] = {
            "filters": {"user_id": user_id_for(patient_id)},
            "top_k": top_k or s.search_top_k,
            "threshold": s.search_threshold if threshold is None else threshold,
            "rerank": rerank,
        }
        if categories:
            opts["categories"] = categories
        if latest_only:
            opts["latest_only"] = True
        if reference_date:
            opts["reference_date"] = reference_date
        return _results(self.client.search(query, **opts))

    def get_all(
        self,
        patient_id: str,
        categories: list[str] | None = None,
        page_size: int = 100,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Every memory for a patient, paged. Used by reconciliation."""
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            opts: dict[str, Any] = {
                "filters": {"user_id": user_id_for(patient_id)},
                "page": page,
                "page_size": page_size,
            }
            if categories:
                opts["categories"] = categories
            batch = _results(self.client.get_all(**opts))
            out.extend(batch)
            if len(batch) < page_size:
                break
        return out

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        return self.client.history(memory_id)

    # ---------- admin ----------

    def bootstrap(self) -> dict[str, Any]:
        return schema.bootstrap(self.client)

    def wipe_patients(self, patient_ids: list[str], drain_seconds: float = 90,
                      timeout: float = 240) -> list[str]:
        """Delete several patients and wait once for the deletions to drain.

        `delete_users` is ASYNCHRONOUS and keeps consuming writes after it returns:
        measured, 20 adds issued straight after a wipe left 0 survivors, while the
        same 20 without a wipe left 19. Reading a count of zero is not proof the
        delete has finished -- it is only proof it has started.

        There is no cheap positive signal that the queue has drained (a canary
        write is itself asynchronous, so a slow extraction is indistinguishable
        from a swallowed one at any sane timeout). So: skip the delete entirely
        where there is nothing to delete, batch the rest into one wait, and treat
        the seed's per-entry coverage check as the actual guarantee.
        """
        wiped = [p for p in patient_ids if self.get_all(p)]
        if not wiped:
            return []

        for p in wiped:
            self.client.delete_users(user_id=user_id_for(p))

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not any(self.get_all(p) for p in wiped):
                break
            time.sleep(4)

        time.sleep(drain_seconds)
        return wiped

    def wipe_patient(self, patient_id: str) -> None:
        """Single-patient wipe. Prefer wipe_patients for seeding."""
        self.wipe_patients([patient_id])

    def wait_until_settled(
        self,
        patient_id: str,
        expect_dates: set[str] | None = None,
        stable_checks: int = 4,
        interval: float = 15,
        timeout: float = 2400,
        on_progress=None,
    ) -> int:
        """Block until extraction stops producing new memories.

        `add()` is asynchronous: it returns PENDING and the memories appear later --
        measured at roughly two entries per thirty seconds, so sixty entries takes
        a quarter of an hour. Nothing downstream is correct until this returns, and
        a timeout that fires early is worse than useless: the caller concludes the
        missing entries were lost and re-adds them, duplicating everything still
        in flight.

        Pass `expect_dates` and it returns the moment every entry is accounted for,
        rather than waiting out a stability window it does not need.
        """
        deadline = time.time() + timeout
        last, stable = -1, 0
        while time.time() < deadline:
            rows = self.get_all(patient_id)
            n = len(rows)
            if expect_dates:
                seen = {(r.get("metadata") or {}).get("entry_date") for r in rows}
                if on_progress:
                    on_progress(n, len(seen & expect_dates), len(expect_dates))
                if expect_dates <= seen:
                    return n
            elif on_progress:
                on_progress(n, 0, 0)

            stable = stable + 1 if n == last and n > 0 else 0
            if stable >= stable_checks:
                return n
            last = n
            time.sleep(interval)
        return last


def _results(resp: Any) -> list[dict[str, Any]]:
    """mem0 returns either {'results': [...]} or a bare list depending on call."""
    if isinstance(resp, dict):
        return resp.get("results") or []
    return resp or []


def extracted_memories(add_response: Any) -> list[dict[str, Any]]:
    """Pull the memories created by an add() call out of its event response."""
    rows = _results(add_response)
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("event") in (None, "ADD", "UPDATE"):
            out.append({
                "id": r.get("id") or r.get("memory_id") or "",
                "memory": r.get("memory") or r.get("data") or "",
                "categories": r.get("categories") or [],
            })
    return [m for m in out if m["id"] and m["memory"]]


def retry(fn, attempts: int = 3, base_delay: float = 1.5):
    """Small backoff helper -- seeding makes hundreds of calls."""
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - surfaced after final attempt
            last = e
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last  # type: ignore[misc]
