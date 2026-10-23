"""Local bar store with point-in-time reads. Backends: Parquet (pyarrow) or SQLite."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from atlas.marketdata.pit.models import Bar

COLS = ["symbol", "ts", "open", "high", "low", "close", "volume", "available_at"]


class SqliteBarStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS bars (symbol TEXT, ts TEXT, open REAL, high REAL, low REAL, close REAL,"
                        " volume REAL, available_at TEXT, PRIMARY KEY(symbol, ts))")

    def write(self, bars: list[Bar]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?)",
                            [(b.symbol, b.ts.isoformat(), b.open, b.high, b.low, b.close, b.volume, b.available_at.isoformat()) for b in bars])
        self.db.commit()

    def read(self, symbol: str, as_of: datetime | None = None) -> list[Bar]:
        q, args = "SELECT * FROM bars WHERE symbol=?", [symbol]
        if as_of is not None:
            q += " AND available_at <= ?"; args.append(as_of.isoformat())
        rows = self.db.execute(q + " ORDER BY ts", args).fetchall()
        return [Bar(**dict(zip(COLS, r))) for r in rows]


class ParquetBarStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str) -> Path:
        return self.root / f"{symbol.replace('/', '_')}.parquet"

    def write(self, bars: list[Bar]) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq
        by: dict[str, list[Bar]] = {}
        for b in bars:
            by.setdefault(b.symbol, []).append(b)
        for sym, bs in by.items():
            existing = {b.ts: b for b in self.read(sym)}
            existing.update({b.ts: b for b in bs})
            rows = sorted(existing.values(), key=lambda b: b.ts)
            table = pa.table({c: [getattr(b, c) for b in rows] for c in COLS})
            pq.write_table(table, self._path(sym))

    def read(self, symbol: str, as_of: datetime | None = None) -> list[Bar]:
        import pyarrow.parquet as pq
        p = self._path(symbol)
        if not p.exists():
            return []
        t = pq.read_table(p).to_pylist()
        bars = [Bar(**r) for r in t]
        return [b for b in bars if as_of is None or b.available_at <= as_of]
