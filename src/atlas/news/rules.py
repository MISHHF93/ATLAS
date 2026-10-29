"""Deterministic, always-on rules: event type from SEC form / 8-K item numbers, and hype / pump-and-dump red flags taken from the SEC's own
investor alerts. No model, no network. These never invent a score: they only name what the text or the form says, with the matched quote."""
from __future__ import annotations

import re
from typing import Any

# 8-K item number -> (event_type, severe_negative). Item list: SEC Form 8-K General Instructions / Form 8-K items.
ITEMS_8K: dict[str, tuple[str, bool]] = {
    "1.01": ("material_agreement", False), "1.02": ("agreement_termination", False), "1.03": ("bankruptcy", True), "1.05": ("cybersecurity_incident", True),
    "2.01": ("acquisition_or_disposition", False), "2.02": ("earnings_results", False), "2.03": ("new_debt_obligation", False), "2.04": ("debt_acceleration", True),
    "2.05": ("restructuring_exit_costs", False), "2.06": ("material_impairment", True), "3.01": ("delisting_or_listing_notice", True), "3.02": ("unregistered_equity_sale", False),
    "3.03": ("security_holder_rights_change", False), "4.01": ("auditor_change", True), "4.02": ("non_reliance_restatement", True), "5.01": ("change_in_control", False),
    "5.02": ("officer_director_change", False), "5.03": ("charter_bylaw_amendment", False), "5.07": ("shareholder_vote", False), "7.01": ("regulation_fd_disclosure", False),
    "8.01": ("other_event", False), "9.01": ("financial_statements_exhibits", False),
}
FORMS: dict[str, str] = {"10-K": "annual_report", "10-Q": "quarterly_report", "20-F": "annual_report_foreign", "6-K": "current_report_foreign", "S-1": "offering_registration",
                         "S-3": "offering_registration", "424B5": "offering_prospectus", "SC 13D": "activist_or_major_holder", "SC 13G": "passive_major_holder",
                         "SC 13D/A": "activist_or_major_holder", "SC 13G/A": "passive_major_holder", "144": "proposed_insider_sale", "DEF 14A": "proxy_statement", "4": "insider_transaction"}
EVENT_TYPES = tuple(sorted({v[0] for v in ITEMS_8K.values()} | set(FORMS.values()) | {"current_report", "macro_release", "regulator_action", "press_coverage", "other"}))
_SEVERE_ITEMS = {k for k, v in ITEMS_8K.items() if v[1]}


def split_codes(codes: str | None) -> list[str]:
    return [c.strip() for c in (codes or "").split(",") if c.strip()]


def event_for_filing(form: str | None, codes: str | None) -> dict[str, Any]:
    """Event type and severity from the form and 8-K item numbers (the filer's own classification)."""
    f = (form or "").strip()
    cs = split_codes(codes)
    if f.startswith("8-K"):
        known = [c for c in cs if c in ITEMS_8K and c != "9.01"] or [c for c in cs if c in ITEMS_8K]
        et = ITEMS_8K[known[0]][0] if known else "current_report"
        return {"event_type": et, "severe_negative": any(c in _SEVERE_ITEMS for c in cs), "codes": cs}
    return {"event_type": FORMS.get(f, "other"), "severe_negative": False, "codes": cs}


# Red flags: SEC Investor Alerts (investor.gov "Fraudulent Stock Promotions", "Social Media and Stock Tip Scams", sec.gov/investor/alerts/socialmediaandfraud.pdf).
HYPE_TYPES = ("guaranteed_returns", "urgency_pressure", "inside_information_claim", "unrealistic_upside", "unsolicited_promotion", "promotion_over_substance", "unverifiable_claim", "compensation_undisclosed")
_P = re.IGNORECASE
HYPE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("guaranteed_returns", re.compile(r"\b(guaranteed?\s+(returns?|profits?|gains?|income|upside)|risk[- ]free|zero\s+risk|can'?t\s+(miss|lose)|no\s+risk|100%\s+(safe|certain))\b", _P)),
    ("urgency_pressure", re.compile(r"\b(act\s+now|buy\s+now|last\s+chance|limited[- ]time|before\s+it'?s\s+too\s+late|don'?t\s+miss\s+(out|this)|hurry|once[- ]in[- ]a[- ]lifetime|today\s+only|about\s+to\s+explode)\b", _P)),
    ("inside_information_claim", re.compile(r"\b(inside(r)?\s+(information|info|tip|source)|confidential\s+(information|tip)|non[- ]public\s+information|leaked)\b", _P)),
    ("unrealistic_upside", re.compile(r"(\b\d{2,4}\s?x\b|\b(10|20|50|100|1000)\s?(x|X)\b|\b\d{3,}%\s+(gain|return|upside|profit)|to\s+the\s+moon|next\s+(nvidia|tesla|bitcoin|amazon)|explosive\s+(growth|gains?)|astronomical|incredible\s+gains|huge\s+upside|breakout\s+stock\s+pick)", _P)),
    ("unsolicited_promotion", re.compile(r"\b(join\s+(our|my|the)\s+(vip\s+|private\s+)?(group|chat|channel|telegram|whatsapp|discord)|dm\s+me|message\s+me|follow\s+my\s+(picks|signals))\b", _P)),
    ("compensation_undisclosed", re.compile(r"\b(sponsored\s+content|paid\s+promotion|we\s+(have\s+been|were|are)\s+compensated|not\s+a\s+registered\s+(investment\s+)?advis[eo]r)\b", _P)),
)
_CAPS = re.compile(r"\b[A-Z]{4,}\b")


def hype_flags(text: str) -> list[dict[str, str]]:
    """Rule-based flags with the matched quote. ``unverifiable_claim`` is left to the LLM: a regex cannot know whether a claim is checkable."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for t, rx in HYPE_RULES:
        m = rx.search(text or "")
        if m and t not in seen:
            seen.add(t)
            out.append({"type": t, "quote": m.group(0)[:80], "by": "rule"})
    caps = _CAPS.findall(text or "")
    if len(caps) >= 4 and (text or "").count("!") >= 2 and "promotion_over_substance" not in seen:
        out.append({"type": "promotion_over_substance", "quote": " ".join(caps[:3]), "by": "rule"})
    return out


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def quote_in(quote: str, text: str) -> bool:
    """A model-supplied quote counts only if it appears verbatim (whitespace/case-insensitive) in the item text."""
    q = normalize(quote)
    return len(q) >= 4 and q in normalize(text)
