"""Read-only dashboard (GET only, binds 127.0.0.1). Uses BalanceView (mode=ro)."""
from __future__ import annotations
import html, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from atlas.ledgers.readonly import BalanceView

def render(view: BalanceView) -> str:
    s = view.summary()
    bal = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(k)}</td><td>{v}</td></tr>"
                  for a, d in s["balances"].items() for k, v in d.items())
    tr = "".join("<tr>" + "".join(f"<td>{html.escape(str(t[k]))}</td>" for k in ("id", "status", "amount", "currency", "rail", "purpose")) + "</tr>"
                 for t in s["transfers"])
    pm = "".join("<tr>" + "".join(f"<td>{html.escape(str(t[k]))}</td>" for k in ("id", "status", "reference", "amount", "currency", "rail", "value_date", "flag")) + "</tr>"
                 for t in s["pending_manual"])
    return (f"<html><head><title>Payments (read-only, SIMULATION)</title></head><body>"
            f"<h1>Payments / Treasury - read-only (SIMULATION)</h1><p>Kill switch: <b>{'ENGAGED' if s['kill_switch'] else 'off'}</b>"
            f" &middot; audit entries: {s['audit_entries']}</p><h2>Balances</h2><table border=1><tr><th>Account</th><th>Ccy</th><th>Amount</th></tr>{bal}</table>"
            f"<h2>Pending manual transfers</h2><table border=1><tr><th>id</th><th>status</th><th>reference</th><th>amount</th><th>ccy</th><th>rail</th><th>value date</th><th>flag</th></tr>{pm}</table>"
            f"<h2>Recent transfers</h2><table border=1><tr><th>id</th><th>status</th><th>amount</th><th>ccy</th><th>rail</th><th>purpose</th></tr>{tr}</table></body></html>")

def serve(db_path: str, port: int = 8766):
    view = BalanceView(db_path)
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/summary":
                body, ctype = json.dumps(view.summary()).encode(), "application/json"
            else:
                body, ctype = render(view).encode(), "text/html"
            self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)
        def _deny(self): self.send_response(405); self.end_headers()
        do_POST = do_PUT = do_DELETE = do_PATCH = _deny
    HTTPServer(("127.0.0.1", port), H).serve_forever()
