"""One SQLite file per market (DATA_DIR/<market>/market.sqlite3): market data, paper accounts, reviews."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS contracts (            -- raw daily bars of single contracts (jm2701 …)
  inst TEXT, contract TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, settle REAL, volume REAL, oi REAL,
  PRIMARY KEY (contract, date));
CREATE TABLE IF NOT EXISTS bars (                 -- one row per instrument per trading day: the main contract
  inst TEXT, date TEXT, contract TEXT, open REAL, high REAL, low REAL, close REAL, settle REAL, volume REAL, oi REAL,
  ret REAL,                                       -- close-to-close return inside one contract (no roll jump)
  PRIMARY KEY (inst, date));
CREATE TABLE IF NOT EXISTS points (series TEXT, date TEXT, value REAL, PRIMARY KEY (series, date));
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS users (uid TEXT PRIMARY KEY, email TEXT, name TEXT, created_at TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY, uid TEXT, name TEXT, mode TEXT DEFAULT 'manual',   -- manual | agent (the logic pack trades it)
  agent_inst TEXT, capital REAL, cash REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS positions (account TEXT, contract TEXT, inst TEXT, lots INTEGER, avg_price REAL,
  PRIMARY KEY (account, contract));
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, ts TEXT, date TEXT, inst TEXT, contract TEXT,
  side TEXT, lots INTEGER, price REAL, fee REAL, realized REAL, by TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS equity (account TEXT, date TEXT, equity REAL, PRIMARY KEY (account, date));
CREATE TABLE IF NOT EXISTS reviews (date TEXT PRIMARY KEY, pack TEXT, narrative TEXT, narrative_en TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS contracts_inst ON contracts (inst, date);
CREATE INDEX IF NOT EXISTS trades_account ON trades (account, id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        r = self.one("SELECT value FROM sync_state WHERE key=?", (key,))
        return r["value"] if r else default

    def set_state(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO sync_state (key,value,updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                      "value=excluded.value, updated_at=excluded.updated_at", (key, value, now()))

    def upsert_points(self, series: str, rows: list[tuple[str, float]]) -> int:
        rows = [(series, d, float(v)) for d, v in rows if v is not None and v == v]
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany("INSERT INTO points (series,date,value) VALUES (?,?,?) ON CONFLICT(series,date) DO UPDATE SET value=excluded.value", rows)
        return len(rows)

    def upsert_contracts(self, rows: list[tuple]) -> int:
        """rows: (inst, contract, date, open, high, low, close, settle, volume, oi)"""
        if not rows:
            return 0
        with self.tx() as c:
            c.executemany("INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def replace_bars(self, inst: str, rows: list[tuple]) -> int:
        """rows: (date, contract, open, high, low, close, settle, volume, oi, ret) for every trading day of `inst`."""
        with self.tx() as c:
            c.execute("DELETE FROM bars WHERE inst=?", (inst,))
            c.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?)", [(inst, *r) for r in rows])
        return len(rows)
