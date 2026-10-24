"""End-to-end paper journey on REPLAY of real feed bars (GC 15m, atlas feed DB):

data -> indicators/detection (PriceActionEngine + level suite SFP) -> ML (walk-forward setup_success model,
Platt-calibrated on out-of-fold scores only) -> ranking (serve(): status + EV_R) -> deterministic risk
(ActionableControlPlaneEngine under the founder rulebook) -> paper execution (PaperConnector) -> outcome
(conservative_ohlc_v1 replay) -> chart. Every decision carries a correlation id into control-plane + paper records.

Research only: the model is registered in a throw-away in-memory registry (NOT promoted, NOT eligible in
var/ml/registry). Nothing goes live. Usage: PYTHONPATH=src ATLAS_FEED_DB=... python scripts/run_e2e_journey.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, time, timezone
from pathlib import Path

import numpy as np
if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)


sys.path.insert(0, "scripts")
from run_level_research import load  # noqa: E402

from atlas.autopilot.setups import SetupAutopilot, Stream  # noqa: E402
from atlas.control.setup_autopilot_approval import approve_request  # noqa: E402
from atlas.features.price_action.engine import EngineConfig  # noqa: E402
from atlas.features.price_action.replay import ReplayConfig, outcome_labels, replay  # noqa: E402
from atlas.features.price_action.suite import GoldBox, GoldConfig, StrategyToggles, SuiteConfig  # noqa: E402
from atlas.feeds.feed import get_feed  # noqa: E402
from atlas.ml.drift import reference  # noqa: E402
from atlas.models.predict import ModelRegistry, RegisteredModel, fit_platt  # noqa: E402
from atlas.models.serving import DriftGuard, catalog  # noqa: E402

OUT = Path("/workspace/shots/full1/e2e")
from atlas.feeds.contracts import contract_for  # noqa: E402
INST, TF = "GC", 900
COST = contract_for(INST).cost_price_units   # contract-spec research assumption (2 ticks + fees RT), not measured
FEATS = ("reward_risk", "net_reward_risk", "cost_r", "htf_aligned", "htf_against", "level_priority", "level_age_h",
         "level_touches", "sweep_depth_atr", "sweep_bars", "wick_frac", "reclaim_close_dist_atr", "confluence")


def brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def auc(p, y):
    p, y = np.asarray(p), np.asarray(y)
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    return float(np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg]))


def main() -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    OUT.mkdir(parents=True, exist_ok=True)
    feed = get_feed()
    bars = load(feed, INST, "15m", TF)
    daily = tuple((int(b.event_time), b.high, b.low, b.close) for b in feed.bars(INST, "1d"))
    suite = SuiteConfig(toggles=StrategyToggles(True, True, True), tick=0.1, calendar="COMEX", daily=daily, cost_price=COST,
                        gold=GoldConfig(boxes=(GoldBox("GOLD_OPENING_ORB", time(8, 20), time(8, 50)),)))
    ecfg = EngineConfig(suite=suite)
    rcfg = ReplayConfig(entry_window=3, max_hold_bars=96, cost_per_unit=COST)

    # 1) data -> detection -> labelled replay (deterministic; no model)
    res = replay(INST, TF, bars, engine_cfg=ecfg, cfg=rcfg, data_label="atlas-feed GC 15m")
    lab = dict(outcome_labels(res))
    cands = sorted((c for c in res.candidates if c.candidate_id in lab), key=lambda c: c.detected_at)
    X = np.array([[float(c.features.get(k, np.nan)) for k in FEATS] for c in cands])
    y = np.array([lab[c.candidate_id] for c in cands])
    n = len(y)
    cut = int(n * 0.77)
    test_start = cands[cut].detected_at

    # 2) ML: expanding walk-forward OOF scores on the dev slice -> Platt; final fit on the dev slice; untouched test.
    mk = lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))  # noqa: E731
    folds = np.array_split(np.arange(cut), 5)
    oof_s, oof_y = [], []
    for k in range(1, 5):
        tr = np.concatenate(folds[:k])
        if len(set(y[tr])) < 2:
            continue
        m = mk().fit(X[tr], y[tr])
        oof_s += list(m.decision_function(X[folds[k]])); oof_y += list(y[folds[k]])
    cal = fit_platt(oof_s, oof_y, fitted_through=int(cands[cut - 1].detected_at), min_samples=50)
    final = mk().fit(X[:cut], y[:cut])
    p_test = [cal.apply(float(s), observation_time=int(c.detected_at)) for s, c in zip(final.decision_function(X[cut:]), cands[cut:])]
    base = float(y[:cut].mean())
    ml = {"n_labelled": n, "n_dev": cut, "n_oof_calibration": len(oof_s), "n_test": n - cut,
          "test_span_utc": [datetime.fromtimestamp(test_start, timezone.utc).isoformat(),
                            datetime.fromtimestamp(cands[-1].detected_at, timezone.utc).isoformat()],
          "dev_base_rate": base, "test_base_rate": float(y[cut:].mean()),
          "test_brier_model": brier(p_test, y[cut:]), "test_brier_base_rate": brier([base] * (n - cut), y[cut:]),
          "test_auc": auc(p_test, y[cut:]), "label": "setup_success = target before stop (conservative_ohlc_v1)",
          "features": list(FEATS), "model": "logistic(C=0.5) + Platt on walk-forward OOF scores",
          "status": "research_only_not_promoted"}
    ml["test_brier_skill"] = 1 - ml["test_brier_model"] / ml["test_brier_base_rate"] if ml["test_brier_base_rate"] else None

    reg = ModelRegistry()
    mv = "research-e2e-gc-sfp-v1"

    def score(vals, m=final):
        return float(m.decision_function(np.array([[vals[k] for k in FEATS]]))[0])
    reg.register(RegisteredModel(mv, f"atlas-feed:GC:15m:{bars[0].start}-{bars[-1].end}", "setup_resolution", "setup_success",
                                 FEATS, score, cal, frozenset({"probability_positive"}), instruments=frozenset({INST}),
                                 max_feature_age_seconds=3600))

    # 3-6) ranking -> deterministic risk -> paper execution -> outcome, via the ONE autopilot path
    import tempfile
    stream = Stream(INST, TF)
    tmp = tempfile.mkdtemp(prefix="atlas-e2e-")
    ap = SetupAutopilot(lambda s, tf: bars, [stream], audit_db=f"{tmp}/audit.sqlite", registry=reg, model_version=mv,
                        engine_cfgs={stream: ecfg}, replay_cfg=rcfg)
    import pandas as pd
    ap.drift = DriftGuard(reference(pd.DataFrame(X[:cut], columns=FEATS), FEATS), min_n=20)
    rid = ap.request_on("owner", "e2e replay journey (paper)")["id"]
    approve_request(ap.store, ap.audit, rid, "owner", True, ap.expected_owner, ap.safe_stop.engaged)
    tick = ap.tick(bars[-1].end + 1)
    entries = ap.audit.entries()
    decisions = [e["payload"] if "payload" in e else e.get("data") for e in entries if e["event"] == "setup_autopilot.decision"]
    exits = [e.get("payload") or e.get("data") for e in entries if e["event"] == "setup_autopilot.paper_exit"]
    receipts = ap.connector.receipts
    for d in decisions:
        d["segment"] = "oos_test" if d["detected_at"] >= test_start else "dev_in_sample"
    oos = [d for d in decisions if d["segment"] == "oos_test"]
    ex_by = {e["candidate_id"]: e for e in exits}
    oos_auth = [d for d in oos if d["decision"] == "proposal_authorized"]
    r_auth = [ex_by[d["candidate_id"]]["r_multiple"] for d in oos_auth if d["candidate_id"] in ex_by
              and ex_by[d["candidate_id"]]["r_multiple"] is not None]
    cid_ok = all(r.get("correlation_id") for r in receipts) and all(
        d.get("correlation_id") for d in decisions)
    journey = {
        "bars": len(bars), "bar_span_utc": [datetime.fromtimestamp(bars[0].start, timezone.utc).isoformat(),
                                            datetime.fromtimestamp(bars[-1].end, timezone.utc).isoformat()],
        "deterministic_replay_summary": res.summary, "ml": ml, "tick": {k: tick[k] for k in ("bars", "halted", "state")},
        "decisions_total": len(decisions), "status_counts_all": dict(Counter(d["serving_status"] for d in decisions)),
        "status_counts_oos": dict(Counter(d["serving_status"] for d in oos)),
        "decision_counts_oos": dict(Counter(d["decision"] for d in oos)),
        "oos_authorized_paper_trades": len(oos_auth), "oos_authorized_resolved_r": r_auth,
        "oos_authorized_mean_r": float(np.mean(r_auth)) if r_auth else None,
        "paper_receipts": len(receipts), "correlation_ids_present_everywhere": cid_ok,
        "risk_view_end": ap.risk_view(), "audit_chain_verified_entries": ap.audit.verify(),
        "catalog": catalog(serving=reg, ml_root="/nonexistent", quant_root=None),
        "caveats": ["single instrument, ~2 months of 15m bars; small OOS sample -> metrics are noisy",
                    "fills are conservative OHLC simulation, not measured; costs are assumptions",
                    "dev-segment decisions are in-sample for the model and are excluded from OOS figures",
                    "research model only; not registered in var/ml/registry, not promoted, execution_permission none"],
    }
    sample = next((d for d in oos_auth), None) or (oos[0] if oos else None)
    if sample:
        journey["trace_example"] = {"decision": sample,
                                    "receipt": next((r for r in receipts if r["order_id"] == sample.get("order_id")), None),
                                    "exit": ex_by.get(sample["candidate_id"])}
    (OUT / "journey.json").write_text(json.dumps(journey, indent=1, default=str))
    (OUT / "decisions.jsonl").write_text("\n".join(json.dumps(d, default=str) for d in decisions))
    (OUT / "paper_receipts.jsonl").write_text("\n".join(json.dumps(r, default=str) for r in receipts))
    (OUT / "paper_exits.jsonl").write_text("\n".join(json.dumps(e, default=str) for e in exits))
    chart(bars, decisions, ex_by, test_start)
    return journey


def chart(bars, decisions, ex_by, test_start) -> None:
    w, h, pad = 1400, 520, 50
    seg = [b for b in bars if b.start >= test_start - 96 * 900]
    lo, hi = min(b.low for b in seg), max(b.high for b in seg)
    t0, t1 = seg[0].start, seg[-1].end
    X = lambda t: pad + (t - t0) / (t1 - t0) * (w - 2 * pad)  # noqa: E731
    Y = lambda p: h - pad - (p - lo) / (hi - lo) * (h - 2 * pad)  # noqa: E731
    path = " ".join(f"{'M' if i == 0 else 'L'}{X(b.start):.1f},{Y(b.close):.1f}" for i, b in enumerate(seg))
    el = [f'<rect width="{w}" height="{h}" fill="#0b0f14"/>', f'<path d="{path}" stroke="#8aa4c0" fill="none" stroke-width="1"/>',
          f'<line x1="{X(test_start):.1f}" x2="{X(test_start):.1f}" y1="{pad}" y2="{h - pad}" stroke="#666" stroke-dasharray="4"/>',
          f'<text x="{X(test_start) + 4:.1f}" y="{pad + 12}" fill="#999" font-size="12">OOS test starts</text>',
          f'<text x="{pad}" y="24" fill="#ddd" font-size="15">GC 15m replay (atlas feed) — paper journey: authorized (green/red = outcome), '
          f'abstained (grey). Research model; not live.</text>',
          f'<text x="{pad}" y="{h - 12}" fill="#888" font-size="11">{lo:.1f} – {hi:.1f}</text>']
    for d in decisions:
        if d["detected_at"] < t0:
            continue
        e = ex_by.get(d["candidate_id"])
        x = X(d["detected_at"])
        if d["decision"] == "proposal_authorized":
            col = "#3fb950" if e and (e.get("r_multiple") or 0) > 0 else "#f85149"
            y0 = Y(next((b.close for b in seg if b.start >= d["detected_at"]), seg[-1].close))
            el.append(f'<circle cx="{x:.1f}" cy="{y0:.1f}" r="5" fill="{col}"><title>{d["candidate_id"]} {d["serving_status"]} '
                      f'p={d["probability"]} R={e and e.get("r_multiple")}</title></circle>')
        else:
            el.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{h - pad}" y2="{h - pad - 10}" stroke="#777"><title>{d["serving_status"]} '
                      f'{",".join(d.get("reasons") or [])}</title></line>')
    (OUT / "journey_chart.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">{"".join(el)}</svg>')


if __name__ == "__main__":
    j = main()
    print(json.dumps({k: j[k] for k in ("ml", "status_counts_oos", "decision_counts_oos", "oos_authorized_paper_trades",
                                        "oos_authorized_mean_r", "paper_receipts", "correlation_ids_present_everywhere",
                                        "tick")}, indent=1, default=str))
