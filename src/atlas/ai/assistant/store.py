"""Conversation history (sqlite, owner-scoped): list / search / rename / delete / export, feedback."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path


class ConversationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS conv(id TEXT PRIMARY KEY, owner TEXT, title TEXT, scope TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS msg(id TEXT PRIMARY KEY, conv TEXT, role TEXT, content TEXT, meta TEXT, created REAL, feedback INTEGER);
            CREATE INDEX IF NOT EXISTS msg_conv ON msg(conv, created);""")
        os.chmod(self.path, 0o600)

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def create(self, owner: str, title: str = "New chat", scope: str = "trading") -> str:
        cid = "c_" + secrets.token_hex(6)
        now = time.time()
        with self.lock, self._db() as db:
            db.execute("INSERT INTO conv VALUES(?,?,?,?,?,?)", (cid, owner, title[:80], scope, now, now))
        return cid

    def get(self, owner: str, cid: str) -> dict | None:
        with self._db() as db:
            c = db.execute("SELECT id,title,scope,created,updated FROM conv WHERE id=? AND owner=?", (cid, owner)).fetchone()
            if not c:
                return None
            ms = db.execute("SELECT id,role,content,meta,created,feedback FROM msg WHERE conv=? ORDER BY created", (cid,)).fetchall()
        return {"id": c[0], "title": c[1], "scope": c[2], "created": c[3], "updated": c[4],
                "messages": [{"id": m[0], "role": m[1], "content": m[2], "meta": json.loads(m[3] or "{}"), "created": m[4], "feedback": m[5]} for m in ms]}

    def list(self, owner: str, q: str = "", limit: int = 50) -> list[dict]:
        with self._db() as db:
            if q:
                like = f"%{q[:80]}%"
                rows = db.execute("""SELECT DISTINCT c.id,c.title,c.scope,c.updated FROM conv c LEFT JOIN msg m ON m.conv=c.id
                                     WHERE c.owner=? AND (c.title LIKE ? OR m.content LIKE ?) ORDER BY c.updated DESC LIMIT ?""",
                                  (owner, like, like, limit)).fetchall()
            else:
                rows = db.execute("SELECT id,title,scope,updated FROM conv WHERE owner=? ORDER BY updated DESC LIMIT ?", (owner, limit)).fetchall()
        return [{"id": r[0], "title": r[1], "scope": r[2], "updated": r[3]} for r in rows]

    def add(self, cid: str, role: str, content: str, meta: dict | None = None) -> str:
        mid = "m_" + secrets.token_hex(6)
        now = time.time()
        with self.lock, self._db() as db:
            db.execute("INSERT INTO msg VALUES(?,?,?,?,?,?,NULL)", (mid, cid, role, content, json.dumps(meta or {}, default=str), now))
            db.execute("UPDATE conv SET updated=? WHERE id=?", (now, cid))
        return mid

    def drop_last_assistant(self, owner: str, cid: str) -> str | None:
        """For Regenerate: return the last user message and remove the assistant reply after it (kept in meta history)."""
        c = self.get(owner, cid)
        if not c:
            return None
        msgs = c["messages"]
        users = [m for m in msgs if m["role"] == "user"]
        return users[-1]["content"] if users else None

    def rename(self, owner: str, cid: str, title: str) -> bool:
        with self.lock, self._db() as db:
            return db.execute("UPDATE conv SET title=? WHERE id=? AND owner=?", (title.strip()[:80] or "Untitled", cid, owner)).rowcount == 1

    def delete(self, owner: str, cid: str) -> bool:
        with self.lock, self._db() as db:
            n = db.execute("DELETE FROM conv WHERE id=? AND owner=?", (cid, owner)).rowcount
            if n:
                db.execute("DELETE FROM msg WHERE conv=?", (cid,))
        return n == 1

    def feedback(self, owner: str, mid: str, value: int) -> bool:
        with self.lock, self._db() as db:
            return db.execute("""UPDATE msg SET feedback=? WHERE id=? AND conv IN (SELECT id FROM conv WHERE owner=?)""",
                              (1 if value > 0 else -1 if value < 0 else None, mid, owner)).rowcount == 1

    def count_bytes(self, owner: str, cid: str) -> int:
        c = self.get(owner, cid) or {"messages": []}
        return sum(int(a.get("size", 0)) for m in c["messages"] for a in m["meta"].get("attachments", []))


def export_markdown(conv: dict) -> str:
    L = [f"# {conv['title']}", "", f"_Exported from the Trading Bot assistant · scope {conv['scope']} · paper only_", ""]
    for m in conv["messages"]:
        who = "You" if m["role"] == "user" else "Assistant"
        t = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["created"]))
        L += [f"### {who} · {t}", "", m["content"], ""]
        calls = m["meta"].get("tool_calls") or []
        if calls:
            L.append("Sources: " + "; ".join(f"[{i + 1}] {c['tool']}({json.dumps(c.get('args') or {})})" for i, c in enumerate(calls)))
            L.append("")
    return "\n".join(L)


def export_pdf(conv: dict) -> bytes:
    """Minimal dependency-free PDF (Helvetica, wrapped text, multiple pages)."""
    import textwrap
    lines: list[str] = []
    for raw in export_markdown(conv).splitlines():
        lines += textwrap.wrap(raw.replace("#", "").strip(), 95) or [""]
    pages = [lines[i:i + 54] for i in range(0, len(lines), 54)] or [[]]
    esc = lambda s: s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for pg in pages:
        stream = "BT /F1 10 Tf 50 800 Td 13 TL " + " ".join(f"({esc(l)}) '" for l in pg) + " ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)
