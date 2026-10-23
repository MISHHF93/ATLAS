"""Assistant (chat) endpoints. Read-only: the assistant never executes actions; it returns deep links.
Attachments are uploaded as raw bytes (X-Filename header), parsed locally, quarantined (0600) and deletable."""
from __future__ import annotations

from pathlib import Path

from atlas.ai.assistant.attachments import AttachmentError, AttachmentStore
from atlas.ai.assistant.engine import Assistant, RateLimited
from atlas.ai.assistant.providers import provider_list
from atlas.ai.assistant.store import ConversationStore, export_markdown, export_pdf
from atlas.ai.assistant.tools import ToolBox

from atlas.console.web import Request, Response, Router

UPLOAD_TYPES = ("application/octet-stream", "text/csv", "text/plain", "application/pdf", "application/xml", "text/xml",
                "image/png", "image/jpeg", "image/gif", "image/webp",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/tab-separated-values")
ERR_STATUS = {"too_large": 413, "unsupported": 415, "unsafe_xml": 415, "empty": 422, "parse_failed": 422, "not_found": 404}


class ChatAPI:
    def __init__(self, svc, config_dir: str | Path, var_dir: str | Path, docs_dir: str | Path | None = None, extra_tools=None):
        var = Path(var_dir)
        self.attachments = AttachmentStore(var / "chat" / "attachments")
        self.attachments.purge_expired()
        tb = ToolBox(svc, str(config_dir), str(var), self.attachments, docs_dir, extra_tools)
        self.store = ConversationStore(var / "chat" / "chat.sqlite")
        self.assistant = Assistant(tb, self.store, svc.audit)
        self.audit = svc.audit

    def routes(self, r: Router) -> None:
        r.add("GET", "/api/chat/providers", lambda q: {"providers": provider_list(), "ocr": self.attachments.ocr,
                                                         "limits_mb": {k: v // (1024 * 1024) for k, v in __import__("atlas.ai.assistant.attachments", fromlist=["LIMITS"]).LIMITS.items()}})
        r.add("GET", "/api/chat/conversations", self.list)
        r.add("GET", "/api/chat/conversations/<cid>", self.get)
        r.add("GET", "/api/chat/conversations/<cid>/export/<fmt>", self.export)
        r.add("POST", "/api/chat/conversations/<cid>/rename", self.rename)
        r.add("POST", "/api/chat/conversations/<cid>/delete", self.delete)
        r.add("POST", "/api/chat/send", self.send)
        r.add("POST", "/api/chat/feedback", self.feedback)
        r.add("POST", "/api/chat/attachments", self.upload, max_body=16 * 1024 * 1024, body_types=UPLOAD_TYPES)
        r.add("POST", "/api/chat/attachments/<aid>/delete", self.delete_attachment)

    @staticmethod
    def _user(req: Request) -> str:
        return req.session.user

    def list(self, req: Request):
        return {"conversations": self.store.list(self._user(req), str(req.query.get("q", ""))[:80])}

    def get(self, req: Request):
        c = self.store.get(self._user(req), req.params["cid"])
        if not c:
            return Response.json({"error": "conversation not found"}, 404)
        return c

    def export(self, req: Request):
        c = self.store.get(self._user(req), req.params["cid"])
        if not c:
            return Response.json({"error": "conversation not found"}, 404)
        name = "".join(ch if ch.isalnum() else "-" for ch in c["title"])[:40] or "chat"
        if req.params["fmt"] == "md":
            return Response.download(export_markdown(c), "text/markdown; charset=utf-8", f"{name}.md")
        if req.params["fmt"] == "pdf":
            return Response.download(export_pdf(c), "application/pdf", f"{name}.pdf")
        return Response.json({"error": "format must be md or pdf"}, 400)

    def rename(self, req: Request):
        ok = self.store.rename(self._user(req), req.params["cid"], str(req.body.get("title", "")))
        return {"renamed": ok} if ok else Response.json({"error": "conversation not found"}, 404)

    def delete(self, req: Request):
        ok = self.store.delete(self._user(req), req.params["cid"])
        if ok:
            self.audit.append("chat.conversation_deleted", {"conversation": req.params["cid"]}, actor=self._user(req))
        return {"deleted": ok}

    def send(self, req: Request):
        b = req.body
        text = str(b.get("text", ""))
        if len(text) > 4000:
            return Response.json({"error": "message too long (max 4000 characters)", "field": "text"}, 422)
        atts = [str(a) for a in (b.get("attachments") or [])][:5]
        try:
            return self.assistant.ask(self._user(req), text, b.get("conversation_id") or None, str(b.get("scope", "trading")),
                                      str(b.get("provider", "local")), atts, bool(b.get("regenerate")))
        except RateLimited as e:
            return Response.json({"error": str(e), "code": "rate_limited"}, 429)
        except ValueError as e:
            return Response.json({"error": str(e), "field": "text"}, 422)

    def feedback(self, req: Request):
        v = int(req.body.get("value", 0)) if str(req.body.get("value", "0")).lstrip("-").isdigit() else 0
        return {"saved": self.store.feedback(self._user(req), str(req.body.get("message_id", "")), v)}

    def upload(self, req: Request):
        name = str(req.headers.get("X-Filename", ""))[:200]
        cid = str(req.headers.get("X-Conversation", ""))[:40]
        used = self.store.count_bytes(self._user(req), cid) if cid else 0
        try:
            a = self.attachments.save(self._user(req), name, req.raw, used)
        except AttachmentError as e:
            return Response.json({"error": str(e), "code": e.code}, ERR_STATUS.get(e.code, 422))
        self.audit.append("chat.attachment", {"id": a.id, "kind": a.kind, "size": a.size, "sha256": a.sha256[:16],
                                              "injection_flags": len(a.injection), "redactions": a.redactions}, actor=self._user(req))
        return a.public()

    def delete_attachment(self, req: Request):
        try:
            self.attachments.delete(req.params["aid"], self._user(req))
        except AttachmentError as e:
            return Response.json({"error": str(e), "code": e.code}, 404)
        return {"deleted": True}
