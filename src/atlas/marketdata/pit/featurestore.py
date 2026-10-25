"""Point-in-time feature store (SQLite).

Every row has `event_ts` (what time the value describes) and `available_at` (when it became
knowable: bar close + publication lag, filing time, vendor receipt time). Reads `as_of=t` only see
rows with available_at <= t, and revisions are new rows (never overwrites), so training frames
can't leak future or revised information."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

import pandas as pd


class PointInTimeFeatureStoreSQLite:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS features (entity TEXT, fset TEXT, event_ts TEXT, available_at TEXT,
                           vals TEXT, PRIMARY KEY (entity, fset, event_ts, available_at))""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_f ON features(entity, fset, available_at)")

    @staticmethod
    def _iso(t: datetime) -> str:
        if t.tzinfo is None:
            raise ValueError("timestamps must be tz-aware")
        return pd.Timestamp(t).tz_convert("UTC").isoformat()

    def put(self, entity: str, fset: str, event_ts: datetime, available_at: datetime, values: dict) -> None:
        if available_at < event_ts:
            raise ValueError("available_at cannot precede event_ts")
        self.db.execute("INSERT OR REPLACE INTO features VALUES (?,?,?,?,?)",
                        (entity, fset, self._iso(event_ts), self._iso(available_at), json.dumps(values)))

    def put_frame(self, entity: str, fset: str, df: pd.DataFrame, lag: timedelta = timedelta(0)) -> int:
        """df indexed by event time (tz-aware). available_at = event time + lag."""
        rows = [(entity, fset, self._iso(ts), self._iso(ts + lag), json.dumps({k: (None if pd.isna(v) else float(v)) for k, v in r.items()}))
                for ts, r in df.iterrows()]
        self.db.executemany("INSERT OR REPLACE INTO features VALUES (?,?,?,?,?)", rows)
        self.db.commit()
        return len(rows)

    def get(self, entity: str, fset: str, as_of: datetime) -> dict | None:
        r = self.db.execute("""SELECT vals, event_ts, available_at FROM features WHERE entity=? AND fset=? AND available_at<=?
                               ORDER BY event_ts DESC, available_at DESC LIMIT 1""", (entity, fset, self._iso(as_of))).fetchone()
        return None if r is None else json.loads(r[0]) | {"_event_ts": r[1], "_available_at": r[2]}

    def frame(self, entity: str, fset: str, times) -> pd.DataFrame:
        """Point-in-time join: for each t, the latest event (latest revision) knowable at t."""
        idx = pd.DatetimeIndex(times)
        rows = [self.get(entity, fset, t.to_pydatetime()) or {} for t in idx]
        return pd.DataFrame(rows, index=idx)


# Deprecated name; use ``PointInTimeFeatureStoreSQLite``. Not the same as atlas.features.feature_store.FeatureStore.
FeatureStore = PointInTimeFeatureStoreSQLite
