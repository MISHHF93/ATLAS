"""Investor statements as CSV and a minimal dependency-free PDF."""
from __future__ import annotations
import csv, io
from atlas.ledgers.money import D, q

def statement_rows(c, iid, nav):
    inv = c.execute("SELECT * FROM investors WHERE id=?", (iid,)).fetchone()
    rows = [("date_ts", "type", "amount_cad", "units", "nav")]
    for o in c.execute("SELECT * FROM orders WHERE investor_id=? AND status='dealt' ORDER BY id", (iid,)):
        rows.append((f"{o['dealt_at']:.0f}", "subscription" if o["kind"] == "sub" else "redemption", o["amount"], o["units"], o["nav"]))
    for f in c.execute("SELECT * FROM fees WHERE investor_id=? ORDER BY id", (iid,)):
        rows.append((f"{f['ts']:.0f}", f"{f['kind']} fee", f["amount"], "", ""))
    p = nav.nav_per_unit()
    rows.append(("", "closing", str(q(D(inv["units"]) * p)), inv["units"], str(p)))
    return inv, rows

def to_csv(c, iid, nav) -> str:
    _, rows = statement_rows(c, iid, nav)
    buf = io.StringIO(); csv.writer(buf).writerows(rows); return buf.getvalue()

def _esc(s): return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def simple_pdf(lines: list[str], per_page: int = 62) -> bytes:
    """Minimal multi-page Courier PDF (no dependencies). Latin-1 text only."""
    pages = [lines[i:i + per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]
    n = len(pages); objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2*k} 0 R" for k in range(n)) + f"] /Count {n} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    for pg in pages:
        text = "BT /F1 9 Tf 40 800 Td 12 TL " + " ".join(f"({_esc(l.encode('latin-1', 'replace').decode('latin-1'))}) '" for l in pg) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {len(objs) + 2} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(text.encode('latin-1'))} >>\nstream\n{text}\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out

def to_pdf(c, iid, nav) -> bytes:
    inv, rows = statement_rows(c, iid, nav)
    lines = [f"Investor statement - {inv['name']} (SIMULATION)", "Not legal/tax advice. Figures in CAD.", ""]
    lines += ["  ".join(str(x).ljust(14) for x in r) for r in rows]
    return simple_pdf(lines)
