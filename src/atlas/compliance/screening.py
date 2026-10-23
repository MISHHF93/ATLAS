"""Sanctions screening (SIMULATION / OFFLINE): lists from local files, fuzzy matching, two-person hit review, and a
gate that blocks money movement while a hit is open or confirmed.

Policy implemented (configurable in settings):
* sanctions_required (default "1"): with no active lists loaded, the gate FAILS CLOSED (no subscriptions, payouts,
  redemptions or onboarding submissions).
* sanctions_threshold (default 0.88): name score at/above which a potential match becomes a hit for review.
* sanctions_stale_days (default 8): lists older than this raise a warning (not a block) - reload them.
* Hit lifecycle: open -> pending_second (one reviewer decided) -> cleared (two distinct reviewers: false positive)
  | confirmed (two distinct reviewers: true match) | escalated (reviewers disagree; stays blocking).
  A confirmed match keeps the investor blocked permanently and creates a FINTRAC listed-person property record draft
  (compliance/fintrac.py). Clearing is remembered per (subject name, list entry) so the same false positive is not
  re-raised on every rescreen.
Screening is an internal control; it does not replace the administrator's / dealer's own screening and reporting."""
from __future__ import annotations

import json
import re
import time

from atlas.compliance import lists as L
from atlas.compliance.matching import block_keys, normalise, score_entry, tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS s_lists(id INTEGER PRIMARY KEY, source TEXT, file TEXT, sha256 TEXT, published TEXT, entries INTEGER,
  loaded_at REAL, loaded_by TEXT, active INTEGER DEFAULT 1, sample INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS s_entries(id INTEGER PRIMARY KEY, list_id INTEGER, source TEXT, uid TEXT, kind TEXT, name TEXT,
  names TEXT, dobs TEXT, countries TEXT, programs TEXT, listed_on TEXT);
CREATE INDEX IF NOT EXISTS s_entries_list ON s_entries(list_id);
CREATE TABLE IF NOT EXISTS s_hits(id INTEGER PRIMARY KEY, investor_id INTEGER, subject TEXT, subject_role TEXT, context TEXT,
  source TEXT, uid TEXT, entry_id INTEGER, listed_name TEXT, entry_kind TEXT, programs TEXT, score REAL, reasons TEXT,
  status TEXT, created_at REAL, closed_at REAL, decision TEXT);
CREATE TABLE IF NOT EXISTS s_dispositions(hit_id INTEGER, reviewer TEXT, decision TEXT, reason TEXT, ts REAL, UNIQUE(hit_id, reviewer));
CREATE TABLE IF NOT EXISTS s_screens(id INTEGER PRIMARY KEY, investor_id INTEGER, context TEXT, subjects INTEGER, hits INTEGER,
  lists TEXT, ts REAL);
CREATE TRIGGER IF NOT EXISTS s_disp_immutable_u BEFORE UPDATE ON s_dispositions BEGIN SELECT RAISE(ABORT, 'dispositions are append-only'); END;
CREATE TRIGGER IF NOT EXISTS s_disp_immutable_d BEFORE DELETE ON s_dispositions BEGIN SELECT RAISE(ABORT, 'dispositions are append-only'); END;
"""
BLOCKING = ("open", "pending_second", "escalated", "confirmed")
DECISIONS = ("false_positive", "true_match")
_INDEX: dict[str, tuple] = {}


class SanctionsBlock(PermissionError):
    ...


class Screener:
    def __init__(self, c, clock=time.time, audit=None, auth=None, on_confirm=None):
        self.c, self.clock, self._audit, self.auth = c, clock, audit or (lambda *a, **k: None), auth
        self.on_confirm = on_confirm
        c.executescript(SCHEMA)

    # ------------------------------------------------------------------ settings
    def _setting(self, k, default):
        r = self.c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone() if self._has_settings() else None
        return r[0] if r else default

    def _has_settings(self):
        return self.c.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone() is not None

    @property
    def required(self) -> bool:
        return self._setting("sanctions_required", "1") == "1"

    @property
    def threshold(self) -> float:
        return float(self._setting("sanctions_threshold", "0.88"))

    # ------------------------------------------------------------------ lists
    def load_docs(self, actor: str, docs: list[dict], sample: bool = False) -> list[dict]:
        out = []
        for d in docs:
            prev = self.c.execute("SELECT id FROM s_lists WHERE source=? AND active=1", (d["source"],)).fetchall()
            lid = self.c.execute("INSERT INTO s_lists(source,file,sha256,published,entries,loaded_at,loaded_by,active,sample) VALUES(?,?,?,?,?,?,?,1,?)",
                                 (d["source"], d.get("file"), d.get("sha256"), d.get("published"), len(d["entries"]), self.clock(), actor,
                                  int(sample))).lastrowid
            self.c.executemany("INSERT INTO s_entries(list_id,source,uid,kind,name,names,dobs,countries,programs,listed_on) VALUES(?,?,?,?,?,?,?,?,?,?)",
                               [(lid, d["source"], e["uid"], e["kind"], e["name"], json.dumps(e["names"]), json.dumps(e["dobs"]),
                                 json.dumps(e["countries"]), json.dumps(e["programs"]), e.get("listed_on")) for e in d["entries"]])
            for (pid,) in prev:                         # superseded list versions: keep the metadata row, drop entries
                self.c.execute("UPDATE s_lists SET active=0 WHERE id=?", (pid,))
                self.c.execute("DELETE FROM s_entries WHERE list_id=?", (pid,))
            self._audit(actor, "sanctions.list_load", source=d["source"], entries=len(d["entries"]), sha256=d.get("sha256"),
                        published=d.get("published"), sample=sample)
            out.append({"id": lid, "source": d["source"], "entries": len(d["entries"]), "published": d.get("published"), "sha256": d.get("sha256")})
        return out

    def load_dir(self, actor: str, directory) -> list[dict]:
        return self.load_docs(actor, L.parse_dir(directory))

    def load_samples(self, actor: str = "system") -> list[dict]:
        return self.load_docs(actor, L.parse_dir(L.SAMPLE_DIR), sample=True)

    def active_lists(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT * FROM s_lists WHERE active=1 ORDER BY source")]

    def status(self) -> dict:
        act = self.active_lists()
        stale_days = float(self._setting("sanctions_stale_days", "8"))
        now = self.clock()
        for a in act:
            a["age_days"] = round((now - a["loaded_at"]) / 86400, 1)
            a["stale"] = a["age_days"] > stale_days
        warn = []
        if not act:
            warn.append("no sanctions lists loaded" + (" - money movement is BLOCKED (sanctions_required=1)" if self.required else ""))
        missing = sorted(set(L.SOURCES) - {a["source"] for a in act})
        if act and missing:
            warn.append("missing lists: " + ", ".join(missing))
        if any(a["stale"] for a in act):
            warn.append("stale lists (reload): " + ", ".join(a["source"] for a in act if a["stale"]))
        if any(a["sample"] for a in act):
            warn.append("SYNTHETIC SAMPLE lists loaded (demo/testing only) - load the official files for real screening")
        open_hits = self.c.execute(f"SELECT COUNT(*) FROM s_hits WHERE status IN ({','.join('?' * len(BLOCKING))})", BLOCKING).fetchone()[0]
        return {"required": self.required, "threshold": self.threshold, "lists": act, "warnings": warn, "blocking_hits": open_hits,
                "sources": L.SOURCES}

    def _index(self):
        act = self.active_lists()
        key = "|".join(f"{a['id']}:{a['sha256']}" for a in act)
        if key not in _INDEX:
            entries, blocks = {}, {}
            for r in self.c.execute("SELECT * FROM s_entries WHERE list_id IN (SELECT id FROM s_lists WHERE active=1)"):
                e = {"id": r["id"], "source": r["source"], "uid": r["uid"], "kind": r["kind"], "name": r["name"],
                     "names": json.loads(r["names"]), "dobs": json.loads(r["dobs"]), "countries": json.loads(r["countries"]),
                     "programs": json.loads(r["programs"])}
                e["tokens"] = [tokens(n) for n in e["names"]]
                entries[r["id"]] = e
                for n in e["names"]:
                    for k in block_keys(n):
                        blocks.setdefault(k, set()).add(r["id"])
            near: dict[str, set] = {}
            for k in blocks:
                near.setdefault(k[:2], set()).add(k)
            _INDEX.clear()
            _INDEX[key] = (entries, blocks, near)
        return _INDEX[key], act

    # ------------------------------------------------------------------ matching
    def match(self, name: str, dob=None, country=None, kind=None, threshold=None) -> list[dict]:
        (entries, blocks, near), _ = self._index()
        th = self.threshold if threshold is None else threshold
        cand = set()
        for k in block_keys(name):
            cand |= blocks.get(k, set())
            for kk in near.get(k[:2], ()):                   # tolerate a typo in the 3rd letter
                cand |= blocks[kk]
        subj = {"name": name, "dob": dob, "country": country, "kind": kind, "tokens": tokens(name)}
        out = []
        for eid in cand:
            e = entries[eid]
            s, best, reasons = score_entry(subj, e)
            if s >= th:
                out.append({"entry_id": eid, "source": e["source"], "uid": e["uid"], "listed_name": best, "kind": e["kind"],
                            "programs": e["programs"], "score": s, "reasons": reasons})
        return sorted(out, key=lambda h: -h["score"])

    @staticmethod
    def subjects(inv: dict, pii: dict) -> list[dict]:
        kind = "individual" if pii.get("entity_type", "individual") == "individual" else "entity"
        out = [{"name": inv["legal_name"], "role": "investor", "dob": pii.get("dob_or_incorporation"), "country": pii.get("country"), "kind": kind}]
        bo = pii.get("beneficial_owners")
        names = []
        if isinstance(bo, str):
            names = [re.sub(r"\(?\d+(\.\d+)?\s*%\)?", "", x).strip(" ,") for x in re.split(r"[;\n]", bo)]
        elif isinstance(bo, list):
            names = [(x.get("name") if isinstance(x, dict) else str(x)) for x in bo]
        out += [{"name": n, "role": "beneficial_owner", "kind": "individual"} for n in names if n]
        return out

    def screen(self, actor: str, investor_id: int, subjects: list[dict], context: str) -> dict:
        """Screen subjects; create hits (deduplicated; previously two-person-cleared pairs are suppressed)."""
        _, act = self._index()
        new, suppressed, existing = [], [], []
        for s in subjects:
            for h in self.match(s["name"], s.get("dob"), s.get("country"), s.get("kind")):
                same = self.c.execute("SELECT id, status FROM s_hits WHERE investor_id=? AND source=? AND uid=? AND subject=? ORDER BY id DESC LIMIT 1",
                                      (int(investor_id), h["source"], h["uid"], normalise(s["name"]))).fetchone()
                if same and same["status"] == "cleared":
                    suppressed.append(same["id"])
                    continue
                if same and same["status"] in BLOCKING:
                    existing.append(same["id"])
                    continue
                hid = self.c.execute("INSERT INTO s_hits(investor_id,subject,subject_role,context,source,uid,entry_id,listed_name,entry_kind,programs,"
                                     "score,reasons,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (int(investor_id), normalise(s["name"]), s["role"], context, h["source"], h["uid"], h["entry_id"],
                                      h["listed_name"], h["kind"], json.dumps(h["programs"]), h["score"], json.dumps(h["reasons"]), "open",
                                      self.clock())).lastrowid
                new.append(hid)
                self._audit(actor, "sanctions.hit", hit=hid, investor=int(investor_id), source=h["source"], uid=h["uid"], score=h["score"],
                            context=context)
        self.c.execute("INSERT INTO s_screens(investor_id,context,subjects,hits,lists,ts) VALUES(?,?,?,?,?,?)",
                       (int(investor_id), context, len(subjects), len(new), json.dumps([a["source"] for a in act]), self.clock()))
        return {"new_hits": new, "existing_hits": existing, "suppressed": suppressed, "lists": [a["source"] for a in act]}

    # ------------------------------------------------------------------ gate
    def blocking_hits(self, investor_id) -> list[dict]:
        return [self.hit(r[0]) for r in self.c.execute(
            f"SELECT id FROM s_hits WHERE investor_id=? AND status IN ({','.join('?' * len(BLOCKING))}) ORDER BY id", (int(investor_id), *BLOCKING))]

    def gate(self, investor_id, context: str) -> None:
        if self.required and not self.active_lists():
            raise SanctionsBlock(f"{context}: blocked - no sanctions lists loaded (load lists or set sanctions_required=0 for testing)")
        hits = self.blocking_hits(investor_id)
        if hits:
            conf = [h for h in hits if h["status"] == "confirmed"]
            raise SanctionsBlock(f"{context}: blocked - {'confirmed sanctions match' if conf else 'sanctions hit under review'} "
                                 f"(hit #{hits[0]['id']}: {hits[0]['listed_name']}, {hits[0]['source']})")

    # ------------------------------------------------------------------ review
    def hit(self, hid) -> dict:
        r = self.c.execute("SELECT * FROM s_hits WHERE id=?", (int(hid),)).fetchone()
        if not r:
            raise KeyError(f"hit {hid}")
        d = dict(r)
        d["reasons"], d["programs"] = json.loads(d["reasons"]), json.loads(d["programs"] or "[]")
        d["dispositions"] = [dict(x) for x in self.c.execute("SELECT reviewer, decision, reason, ts FROM s_dispositions WHERE hit_id=? ORDER BY ts", (int(hid),))]
        return d

    def hits(self, status: str | None = None, limit: int = 200) -> list[dict]:
        if status == "blocking":
            q, a = f"SELECT id FROM s_hits WHERE status IN ({','.join('?' * len(BLOCKING))}) ORDER BY id DESC LIMIT ?", (*BLOCKING, limit)
        elif status:
            q, a = "SELECT id FROM s_hits WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)
        else:
            q, a = "SELECT id FROM s_hits ORDER BY id DESC LIMIT ?", (limit,)
        return [self.hit(r[0]) for r in self.c.execute(q, a)]

    def review(self, hid, reviewer: str, passphrase: str, code: str, decision: str, reason: str) -> dict:
        """One of two required dispositions. Reviewers authenticate (passphrase + TOTP) and must be different people."""
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        if len((reason or "").strip()) < 10:
            raise ValueError("a written rationale (>= 10 chars) is required for every disposition")
        if self.auth is None:
            raise SanctionsBlock("no approver registry configured")
        self.auth.verify(reviewer, passphrase, code)
        h = self.hit(hid)
        if h["status"] in ("cleared", "confirmed"):
            raise SanctionsBlock(f"hit already {h['status']}")
        if reviewer in {d["reviewer"] for d in h["dispositions"]}:
            raise SanctionsBlock("already reviewed by this reviewer; a second, different reviewer must decide")
        self.c.execute("INSERT INTO s_dispositions VALUES(?,?,?,?,?)", (int(hid), reviewer, decision, reason.strip()[:500], self.clock()))
        ds = self.hit(hid)["dispositions"]
        votes = {k: sum(d["decision"] == k for d in ds) for k in DECISIONS}
        top = max(votes, key=votes.get)
        if len(ds) == 1:
            st = "pending_second"
        elif votes[top] >= 2 and votes[top] > min(votes.values()):       # two agreeing reviewers (a third breaks a tie)
            st = "cleared" if top == "false_positive" else "confirmed"
        else:
            st = "escalated"
        decision = top
        self.c.execute("UPDATE s_hits SET status=?, closed_at=?, decision=? WHERE id=?",
                       (st, self.clock() if st in ("cleared", "confirmed") else None, decision if st in ("cleared", "confirmed") else None, int(hid)))
        self._audit(reviewer, "sanctions.review", hit=int(hid), decision=decision, status=st)
        if st == "confirmed" and self.on_confirm:
            self.on_confirm(reviewer, self.hit(hid))
        return self.hit(hid)
