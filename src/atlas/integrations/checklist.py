"""Settings -> Setup checklist: every environment variable and connector ATLAS reads, one row each, ordered by impact.

States: ``verified`` (the last Verify call succeeded with the key now entered), ``needs_verification`` (key missing or entered but not yet
verified; a failed Verify is flagged ``failed``) and ``optional`` (nothing entered and the service is not on the core path). Names and booleans only:
no value is ever returned. Nothing here sets a key, calls a vendor or places an order (``execution_permission`` none)."""
from __future__ import annotations

from typing import Any, Mapping

from atlas.integrations.registry import SERVICES, EXECUTION_PERMISSION, _is_set

# (rank, service ids that satisfy this row, headline, why it matters). The first five are the core path, in order of impact.
CORE: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("massive", ("polygon",), "Massive (stock & ETF bars)",
     "Primary free source for US stocks and ETFs (15m and daily, 2 years). Without it the stock charts, the ML training pools and the stock predictions have no bars."),
    ("gemini", ("gemini",), "Gemini (LLM reviewer)",
     "Powers the news/proposal reviewer. Used only when ATLAS_GEMINI_TIER=paid (the free tier may train on your data, so ATLAS refuses it). Advisory and shadow only; "
     "without it the reviewer-evidence gate can never accumulate."),
    ("edgar", ("sec_edgar",), "SEC EDGAR (ATLAS_SEC_USER_AGENT)",
     "Free filings and fundamentals. No key: SEC fair-access rules need a User-Agent like 'AppName you@example.com' with a real contact address you own."),
    ("fred", ("fred",), "FRED (macro series)",
     "Free macro and rates series (point-in-time vintages) for the macro features and regime context."),
    ("broker_paper", ("oanda", "ibkr"), "Broker paper account (OANDA practice or IBKR paper)",
     "Both are open to Canadian residents. A verified paper account is a go-live readiness gate and lets ATLAS read balances and constraints. Paper or practice only: live is refused."),
)

# Variables ATLAS fixes itself (non-secret): shown as "practice (fixed)" so the user knows not to enter anything.
FIXED_VARS = {"OANDA_ENV": "practice"}
# Where to enter the values for a row (the Setup wizard below the checklist, one read-only Verify per service).
ENTER_IN = {"broker_paper": "Setup wizard below, 'OANDA (practice)': paste OANDA_API_TOKEN (the personal access token from the fxTrade Practice portal: Manage API Access). "
                            "OANDA_ACCOUNT_ID is optional (found from the token via GET /v3/accounts on api-fxpractice.oanda.com); OANDA_ENV is fixed to practice."}

NOT_FOR_CANADA = {"alpaca": "Alpaca is not offered to Canadian residents; optional."}


def _item(rank: int, key: str, ids: tuple[str, ...], title: str, why: str, core: bool, env: Mapping[str, str], states: Mapping[str, dict], by_id: Mapping[str, Any]) -> dict[str, Any]:
    svcs = [by_id[i] for i in ids if i in by_id]
    members, vars_, any_key, any_verified, any_failed = [], [], False, False, False
    for s in svcs:
        st = states.get(s.id) or {"state": "needs_verification", "detail": "", "key_present": False}
        req = {k: _is_set(env, k) for k in s.required}
        opt = {k: _is_set(env, k) for k in s.optional}
        keyless = st["state"] == "keyless" or not s.required
        present = bool(st.get("key_present")) or (bool(req) and all(req.values()))
        any_key = any_key or present
        any_verified = any_verified or st["state"] == "verified"
        any_failed = any_failed or st["state"] == "failed"
        members.append({"id": s.id, "title": s.title, "state": st["state"], "detail": st.get("detail") or "", "signup": s.signup, "cost": s.cost,
                        "required_vars": req, "optional_vars": opt, "keyless": keyless})
        vars_ += [{"name": k, "set": v, "required": True, "service": s.id} for k, v in req.items()]
        vars_ += [{"name": k, "set": v, "required": False, "service": s.id, **({"fixed": FIXED_VARS[k]} if k in FIXED_VARS else {})} for k, v in opt.items()]
    if any_verified:
        state, nxt = "verified", "Nothing to do. Re-verify any time."
    elif any_failed and any_key:
        state, nxt = "needs_verification", "The last Verify failed: check the value and press Verify again."
    elif any_key:
        state, nxt = "needs_verification", "Key entered: press Verify (one read-only call)."
    elif core:
        state, nxt = "needs_verification", "Not entered yet: get the free key from the official link, save it in the step below, then press Verify."
    else:
        state, nxt = "optional", "Optional: only needed if you want this source or channel."
    if all(m["keyless"] for m in members) and members and not any_verified:
        state, nxt = "optional", "No key needed; works without setup."
    return {"rank": rank, "key": key, "title": title, "why": why, "core": core, "state": state, "failed": bool(any_failed and not any_verified),
            "key_present": any_key, "next_step": nxt, "services": members, "vars": vars_,
            "enter_in": ENTER_IN.get(key), "note": " ".join(NOT_FOR_CANADA[i] for i in ids if i in NOT_FOR_CANADA) or None}


def build(env: Mapping[str, str], states: Mapping[str, dict] | None = None) -> dict[str, Any]:
    from atlas.integrations import verify as v
    states = v.all_states(dict(env)) if states is None else states
    by_id = {s.id: s for s in SERVICES}
    items, used = [], set()
    for i, (key, ids, title, why) in enumerate(CORE, 1):
        items.append(_item(i, key, ids, title, why, True, env, states, by_id)); used.update(ids)
    # Everything else: verified first, then entered-but-unverified, then untouched; data providers before alerts and billing.
    cat_order = {"market_data": 0, "ai": 1, "broker_paper": 2, "filings": 3, "macro": 4, "alerts": 5, "billing": 6, "external_mcp": 7}
    rest = [s for s in SERVICES if s.id not in used and s.default_on]
    rest += [s for s in SERVICES if s.id not in used and not s.default_on]
    rows = [_item(0, s.id, (s.id,), s.title, s.notes or f"Optional {s.cost.replace('_', ' ')} service ({s.category.replace('_', ' ')}).", False, env, states, by_id) for s in rest]
    rows.sort(key=lambda r: ({"verified": 0, "needs_verification": 1, "optional": 2}[r["state"]], cat_order.get(by_id[r["key"]].category, 9)))
    for n, r in enumerate(rows, len(items) + 1):
        r["rank"] = n
        r["category"] = by_id[r["key"]].category
        items.append(r)
    for r in items[:len(CORE)]:
        r["category"] = "core"
    counts = {k: sum(1 for r in items if r["state"] == k) for k in ("verified", "needs_verification", "optional")}
    return {"items": items, "counts": counts, "core_verified": sum(1 for r in items if r["core"] and r["state"] == "verified"), "core_total": len(CORE),
            "secrets_echoed": False, "keys_set_by_atlas": False, "paper_only": True, "execution_permission": EXECUTION_PERMISSION}
