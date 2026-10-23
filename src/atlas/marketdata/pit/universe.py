"""Survivorship-safe point-in-time universe (research item 6).

* Securities are NEVER deleted: a delisting sets ``delisted_on`` + reason + optional final
  (delisting) return, so historical universes still contain names that later died.
* Membership in an index/list is a set of [start, end) intervals per symbol (constituent changes).
* Sector history is as-of (reclassifications are new intervals).
* Corporate actions (splits / TSXV consolidations) are stored with ex-date; ``adjust`` back-adjusts
  using only actions with ex_date <= as_of (no future splits leak into older studies).
* Every mutation records ``known_at``; queries with ``known_as_of`` ignore facts learned later.
"""
from __future__ import annotations

import sqlite3

import pandas as pd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS security(symbol TEXT PRIMARY KEY, venue TEXT, asset_class TEXT, listed_on TEXT,
  delisted_on TEXT, delist_reason TEXT, delist_return REAL, known_at TEXT);
CREATE TABLE IF NOT EXISTS membership(universe TEXT, symbol TEXT, start TEXT, end TEXT, known_at TEXT);
CREATE TABLE IF NOT EXISTS sector(symbol TEXT, sector TEXT, start TEXT, end TEXT, known_at TEXT);
CREATE TABLE IF NOT EXISTS corp_action(symbol TEXT, ex_date TEXT, kind TEXT, ratio REAL, known_at TEXT);
"""
FAR = "9999-12-31"


def _d(x) -> str:
    return (x if isinstance(x, str) else x.isoformat())[:10]


class PITUniverse:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript(_SCHEMA)

    # ------------------------------------------------------------ writes (append-style)
    def add_security(self, symbol, listed_on, venue="TSX", asset_class="equity", known_at=None):
        self.db.execute("INSERT OR IGNORE INTO security VALUES(?,?,?,?,NULL,NULL,NULL,?)",
                        (symbol, venue, asset_class, _d(listed_on), _d(known_at or listed_on)))
        self.db.commit()

    def delist(self, symbol, on, reason: str, final_return: float | None = None, known_at=None):
        """Marks (never deletes). final_return: e.g. -1.0 for bankruptcy, cash-out return for M&A."""
        self.db.execute("UPDATE security SET delisted_on=?, delist_reason=?, delist_return=?, known_at=? WHERE symbol=?",
                        (_d(on), reason, final_return, _d(known_at or on), symbol))
        self.db.execute("UPDATE membership SET end=? WHERE symbol=? AND end=?", (_d(on), symbol, FAR))
        self.db.commit()

    def add_member(self, universe, symbol, start, end=None, known_at=None):
        self.db.execute("INSERT INTO membership VALUES(?,?,?,?,?)", (universe, symbol, _d(start), _d(end or FAR), _d(known_at or start)))
        self.db.commit()

    def remove_member(self, universe, symbol, on):
        self.db.execute("UPDATE membership SET end=? WHERE universe=? AND symbol=? AND end=?", (_d(on), universe, symbol, FAR))
        self.db.commit()

    def set_sector(self, symbol, sector, start, known_at=None):
        self.db.execute("UPDATE sector SET end=? WHERE symbol=? AND end=?", (_d(start), symbol, FAR))
        self.db.execute("INSERT INTO sector VALUES(?,?,?,?,?)", (symbol, sector, _d(start), FAR, _d(known_at or start)))
        self.db.commit()

    def add_corp_action(self, symbol, ex_date, kind: str, ratio: float, known_at=None):
        """ratio = new shares per old share (2:1 split -> 2.0; 1-for-10 consolidation -> 0.1)."""
        if ratio <= 0:
            raise ValueError("ratio must be > 0")
        self.db.execute("INSERT INTO corp_action VALUES(?,?,?,?,?)", (symbol, _d(ex_date), kind, float(ratio), _d(known_at or ex_date)))
        self.db.commit()

    # ------------------------------------------------------------ point-in-time reads
    def members(self, universe: str, as_of, known_as_of=None) -> list[str]:
        a, k = _d(as_of), _d(known_as_of or as_of)
        rows = self.db.execute("SELECT DISTINCT symbol FROM membership WHERE universe=? AND start<=? AND end>? AND known_at<=?",
                               (universe, a, a, k)).fetchall()
        return sorted(r[0] for r in rows)

    def tradable(self, as_of, asset_class: str | None = None) -> list[str]:
        a = _d(as_of)
        q = "SELECT symbol FROM security WHERE listed_on<=? AND (delisted_on IS NULL OR delisted_on>?)"
        args: list = [a, a]
        if asset_class:
            q += " AND asset_class=?"; args.append(asset_class)
        return sorted(r[0] for r in self.db.execute(q, args).fetchall())

    def ever_listed(self, start, end) -> list[str]:
        """All names alive at any point in [start, end] incl. those delisted since (survivorship-free)."""
        rows = self.db.execute("SELECT symbol FROM security WHERE listed_on<=? AND (delisted_on IS NULL OR delisted_on>=?)",
                               (_d(end), _d(start))).fetchall()
        return sorted(r[0] for r in rows)

    def sector_of(self, symbol, as_of) -> str | None:
        a = _d(as_of)
        r = self.db.execute("SELECT sector FROM sector WHERE symbol=? AND start<=? AND end>? AND known_at<=?", (symbol, a, a, a)).fetchone()
        return r[0] if r else None

    def delisting(self, symbol) -> dict | None:
        r = self.db.execute("SELECT delisted_on, delist_reason, delist_return FROM security WHERE symbol=? AND delisted_on IS NOT NULL", (symbol,)).fetchone()
        return {"on": r[0], "reason": r[1], "final_return": r[2]} if r else None

    def adjust(self, symbol, bars: pd.DataFrame, as_of) -> pd.DataFrame:
        """Back-adjust close/volume with actions known and effective by as_of."""
        a = _d(as_of)
        out = bars.copy()
        for ex, ratio in self.db.execute("SELECT ex_date, ratio FROM corp_action WHERE symbol=? AND ex_date<=? AND known_at<=?",
                                         (symbol, a, a)).fetchall():
            m = out.index < pd.Timestamp(ex)
            if "close" in out:
                out.loc[m, "close"] = out.loc[m, "close"] / ratio
            if "volume" in out:
                out.loc[m, "volume"] = out.loc[m, "volume"] * ratio
        return out

    def returns_with_delisting(self, symbol, close: pd.Series) -> pd.Series:
        """Simple returns with the delisting return appended on the delisting date (CRSP-style), so
        dead names contribute their final loss instead of silently vanishing."""
        r = close.pct_change()
        d = self.delisting(symbol)
        if d and d["final_return"] is not None:
            r.loc[pd.Timestamp(d["on"])] = d["final_return"]
            r = r.sort_index()
        return r


def survivorship_check(universe: PITUniverse, used_symbols: list[str], start, end) -> dict:
    """CI red-flag check: a study over [start,end] must include names that were delisted in that window."""
    alive = set(universe.ever_listed(start, end))
    dead = {s for s in alive if (d := universe.delisting(s)) and d["on"] <= _d(end)}
    missing = sorted(dead - set(used_symbols))
    return {"n_universe": len(alive), "n_delisted_in_window": len(dead), "missing_delisted": missing, "ok": not missing}
