"""SQLite persistence of setup state transitions and candidates (duplicates refused by key)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from atlas.features.price_action.detectors import Candidate, Transition


class TransitionStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS pa_transitions (setup_id TEXT, seq INT, from_state TEXT, to_state TEXT,"
            " at INT, reason TEXT, PRIMARY KEY(setup_id, seq));"
            "CREATE TABLE IF NOT EXISTS pa_candidates (candidate_id TEXT PRIMARY KEY, payload TEXT);")

    def record(self, items) -> int:
        n = 0
        for it in items:
            if isinstance(it, Transition):
                cur = self.db.execute("INSERT OR IGNORE INTO pa_transitions VALUES (?,?,?,?,?,?)",
                                      (it.setup_id, it.seq, it.from_state, it.to_state, it.at, it.reason))
            elif isinstance(it, Candidate):
                cur = self.db.execute("INSERT OR IGNORE INTO pa_candidates VALUES (?,?)",
                                      (it.candidate_id, json.dumps(it.to_dict(), default=str)))
            else:
                continue
            n += cur.rowcount
        self.db.commit()
        return n

    def transitions(self, setup_id: str) -> list[tuple]:
        return self.db.execute("SELECT seq, from_state, to_state, at, reason FROM pa_transitions WHERE setup_id=? ORDER BY seq",
                               (setup_id,)).fetchall()

    def candidate_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM pa_candidates").fetchone()[0]
