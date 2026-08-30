"""SQLite system of record.

mem0 stores *distilled* memories, not verbatim text. MedLog keeps the raw
journal entries, the audit trail linking entries to the memories they produced,
and cached artifacts (state snapshots, briefs) here. One file, no infra.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from medlog.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id            TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    year_of_birth INTEGER,
    profile       TEXT DEFAULT '',
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL REFERENCES patients(id),
    entry_date  TEXT NOT NULL,           -- ISO date the event happened
    text        TEXT NOT NULL,           -- verbatim, never rewritten
    source      TEXT NOT NULL DEFAULT 'patient_journal',
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_entries_patient_date ON entries(patient_id, entry_date);

-- Audit trail: which memories did this entry produce?
CREATE TABLE IF NOT EXISTS entry_memories (
    entry_id   INTEGER NOT NULL REFERENCES entries(id),
    memory_id  TEXT NOT NULL,
    memory     TEXT NOT NULL,
    categories TEXT DEFAULT '[]',
    PRIMARY KEY (entry_id, memory_id)
);

-- Cached reconciliation output, invalidated when entry_count changes.
CREATE TABLE IF NOT EXISTS current_state (
    patient_id   TEXT PRIMARY KEY REFERENCES patients(id),
    snapshot     TEXT NOT NULL,
    entry_count  INTEGER NOT NULL,
    computed_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS briefs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id   TEXT NOT NULL REFERENCES patients(id),
    markdown     TEXT NOT NULL,
    meta         TEXT DEFAULT '{}',
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    meta       TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


# ---------- patients ----------

def upsert_patient(pid: str, name: str, yob: int | None = None, profile: str = "") -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO patients (id, display_name, year_of_birth, profile) VALUES (?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
            "year_of_birth=excluded.year_of_birth, profile=excluded.profile",
            (pid, name, yob, profile),
        )


def list_patients() -> list[dict[str, Any]]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM patients ORDER BY display_name")]


def get_patient(pid: str) -> dict[str, Any] | None:
    with connect() as c:
        r = c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None


# ---------- entries ----------

def add_entry(patient_id: str, entry_date: str, text: str, source: str = "patient_journal") -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO entries (patient_id, entry_date, text, source) VALUES (?,?,?,?)",
            (patient_id, entry_date, text, source),
        )
        return int(cur.lastrowid)


def link_memories(entry_id: int, memories: list[dict[str, Any]]) -> None:
    with connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO entry_memories (entry_id, memory_id, memory, categories) VALUES (?,?,?,?)",
            [
                (entry_id, m.get("id", ""), m.get("memory", ""), json.dumps(m.get("categories") or []))
                for m in memories
                if m.get("id")
            ],
        )


def get_entries(patient_id: str, limit: int | None = None, ascending: bool = False) -> list[dict[str, Any]]:
    order = "ASC" if ascending else "DESC"
    sql = f"SELECT * FROM entries WHERE patient_id=? ORDER BY entry_date {order}, id {order}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, (patient_id,))]


def entry_count(patient_id: str) -> int:
    with connect() as c:
        return int(c.execute("SELECT COUNT(*) FROM entries WHERE patient_id=?", (patient_id,)).fetchone()[0])


def memories_for_entry(entry_id: int) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute("SELECT * FROM entry_memories WHERE entry_id=?", (entry_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["categories"] = json.loads(d.get("categories") or "[]")
            out.append(d)
        return out


# ---------- cached artifacts ----------

def save_state(patient_id: str, snapshot: dict[str, Any], count: int) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO current_state (patient_id, snapshot, entry_count, computed_at) "
            "VALUES (?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(patient_id) DO UPDATE SET "
            "snapshot=excluded.snapshot, entry_count=excluded.entry_count, computed_at=CURRENT_TIMESTAMP",
            (patient_id, json.dumps(snapshot), count),
        )


def load_state(patient_id: str) -> tuple[dict[str, Any], int] | None:
    with connect() as c:
        r = c.execute("SELECT snapshot, entry_count FROM current_state WHERE patient_id=?", (patient_id,)).fetchone()
        return (json.loads(r["snapshot"]), int(r["entry_count"])) if r else None


def save_brief(patient_id: str, markdown: str, meta: dict[str, Any]) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO briefs (patient_id, markdown, meta) VALUES (?,?,?)",
            (patient_id, markdown, json.dumps(meta)),
        )
        return int(cur.lastrowid)


def latest_brief(patient_id: str) -> dict[str, Any] | None:
    with connect() as c:
        r = c.execute(
            "SELECT * FROM briefs WHERE patient_id=? ORDER BY id DESC LIMIT 1", (patient_id,)
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        return d


def add_turn(patient_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO turns (patient_id, role, content, meta) VALUES (?,?,?,?)",
            (patient_id, role, content, json.dumps(meta or {})),
        )


def get_turns(patient_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM turns WHERE patient_id=? ORDER BY id DESC LIMIT ?", (patient_id, limit)
        ).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            d["meta"] = json.loads(d.get("meta") or "{}")
            out.append(d)
        return out
