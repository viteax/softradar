"""SQLite в DATA_DIR: закупки, результаты анализа, прогоны, кэш каталога."""

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenders (
    key TEXT PRIMARY KEY,
    source TEXT, number TEXT, title TEXT, price REAL, deadline TEXT,
    data TEXT NOT NULL,              -- Tender.to_dict()
    filter_ok INTEGER, filter_reasons TEXT,
    analysis TEXT,                   -- итог агента (JSON)
    trace TEXT,                      -- шаги агента: вызовы инструментов и ответы
    kp TEXT,                         -- строки КП и экономика (JSON)
    score REAL, verdict TEXT,        -- fit | partial | reject
    tokens INTEGER DEFAULT 0,
    first_seen REAL, updated REAL, analyzed REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started REAL, finished REAL, stats TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY, value TEXT, ts REAL
);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid or 0

    # --- кэш (страницы каталога, документы) ---
    def cache_get(self, key: str, ttl: float) -> str | None:
        rows = self.q("SELECT value, ts FROM cache WHERE key=?", (key,))
        if rows and time.time() - rows[0]["ts"] < ttl:
            return rows[0]["value"]
        return None

    def cache_put(self, key: str, value: str) -> None:
        self.x("INSERT OR REPLACE INTO cache(key, value, ts) VALUES (?,?,?)", (key, value, time.time()))

    # --- закупки ---
    def upsert_tender(self, t: dict, filter_ok: bool, reasons: list[str]) -> bool:
        """True – закупка новая."""
        now = time.time()
        exists = self.q("SELECT 1 FROM tenders WHERE key=?", (f"{t['source']}:{t['number']}",))
        self.x(
            """INSERT INTO tenders(key, source, number, title, price, deadline, data, filter_ok, filter_reasons,
                   first_seen, updated)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET title=excluded.title, price=excluded.price,
                   deadline=excluded.deadline, data=excluded.data, filter_ok=excluded.filter_ok,
                   filter_reasons=excluded.filter_reasons, updated=excluded.updated""",
            (
                f"{t['source']}:{t['number']}",
                t["source"],
                t["number"],
                t["title"],
                t["price"],
                t["deadline"],
                json.dumps(t, ensure_ascii=False),
                int(filter_ok),
                json.dumps(reasons, ensure_ascii=False),
                now,
                now,
            ),
        )
        return not exists

    def save_analysis(
        self, key: str, analysis: dict, trace: list, kp: dict, score: float, verdict: str, tokens: int
    ) -> None:
        self.x(
            "UPDATE tenders SET analysis=?, trace=?, kp=?, score=?, verdict=?, tokens=?, analyzed=? WHERE key=?",
            (
                json.dumps(analysis, ensure_ascii=False),
                json.dumps(trace, ensure_ascii=False),
                json.dumps(kp, ensure_ascii=False),
                score,
                verdict,
                tokens,
                time.time(),
                key,
            ),
        )

    def tender(self, key: str) -> dict | None:
        rows = self.q("SELECT * FROM tenders WHERE key=?", (key,))
        return _row(rows[0]) if rows else None

    def tenders(self) -> list[dict]:
        return [_row(r) for r in self.q("SELECT * FROM tenders ORDER BY score DESC NULLS LAST, updated DESC")]

    def to_analyze(self, limit: int) -> list[dict]:
        rows = self.q(
            "SELECT * FROM tenders WHERE filter_ok=1 AND analyzed IS NULL ORDER BY first_seen DESC LIMIT ?",
            (limit,),
        )
        return [_row(r) for r in rows]


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for k in ("data", "analysis", "trace", "kp", "filter_reasons"):
        if d.get(k):
            d[k] = json.loads(d[k])
    return d
