"""P8 — Persistence & reporting (SQLite).

Records answers + session events for teacher/parent reports and CSV export.
Low write volume (classroom scale) → stdlib sqlite3 is plenty; one shared
connection guarded for asyncio use (writes are tiny and quick).
"""
from __future__ import annotations

import io
import csv
import sqlite3
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)
DB = DATA / "r4swarm.db"

_conn: sqlite3.Connection | None = None


def init_db() -> None:
    global _conn
    _conn = sqlite3.connect(DB, check_same_thread=False)
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS answers (
            ts REAL, device TEXT, seat INTEGER, grp TEXT,
            act TEXT, q INTEGER, choice INTEGER, correct INTEGER
        );
        CREATE TABLE IF NOT EXISTS events (ts REAL, type TEXT, detail TEXT);
        CREATE INDEX IF NOT EXISTS idx_ans_act ON answers(act);
        CREATE INDEX IF NOT EXISTS idx_ans_seat ON answers(seat);
        """
    )
    _conn.commit()


def record_answer(device: str, seat: int, grp: str, act: str, q: int,
                  choice: int | None, correct: bool) -> None:
    if _conn is None:
        return
    _conn.execute(
        "INSERT INTO answers VALUES (?,?,?,?,?,?,?,?)",
        (time.time(), device, seat, grp, act, q, choice, int(correct)),
    )
    _conn.commit()


def record_event(type_: str, detail: str) -> None:
    if _conn is None:
        return
    _conn.execute("INSERT INTO events VALUES (?,?,?)", (time.time(), type_, detail))
    _conn.commit()


def report_activity(act: str) -> dict:
    if _conn is None:
        return {}
    cur = _conn.execute(
        "SELECT q, COUNT(*), SUM(correct) FROM answers WHERE act=? GROUP BY q ORDER BY q",
        (act,),
    )
    rows = [{"q": q, "answered": n, "correct": c or 0,
             "rate": round((c or 0) / n, 3) if n else 0.0} for q, n, c in cur.fetchall()]
    return {"activity": act, "by_question": rows}


def report_seats() -> list[dict]:
    if _conn is None:
        return []
    cur = _conn.execute(
        "SELECT seat, grp, COUNT(*), SUM(correct) FROM answers GROUP BY seat ORDER BY seat"
    )
    return [{"seat": s, "group": g, "answered": n, "correct": c or 0,
             "rate": round((c or 0) / n, 3) if n else 0.0} for s, g, n, c in cur.fetchall()]


def export_csv() -> str:
    if _conn is None:
        return ""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ts", "device", "seat", "group", "activity", "q", "choice", "correct"])
    for row in _conn.execute("SELECT * FROM answers ORDER BY ts"):
        w.writerow(row)
    return out.getvalue()
