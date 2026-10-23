"""Technique selector + range-break hypothesis. All data here is SYNTHETIC test-only fixture data."""
import random
from datetime import datetime

from atlas.features.price_action.bars import Bar
from atlas.models.technique_selector import CONTEXT_FEATURES, ContextTracker, TechniqueSelector, annotate_choice, \
    feature_row, selector_registered_model
from atlas.research.setup_evidence import UTC_DAY
from atlas.research.technique_selection import binom_two_sided_p, range_break_hypothesis, walk_forward_selector, \
    summarize, wilson

T0 = int(datetime(2026, 1, 5).timestamp()) // 86400 * 86400


def _bars(n, seed=1, step=900):
    rnd, p, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = p; p = max(1.0, p + rnd.gauss(0, 0.3))
        out.append(Bar(T0 + i * step, step, o, max(o, p) + 0.1, min(o, p) - 0.1, p, 1))
    return out


def test_context_is_causal_and_prefix_invariant():
    bars = _bars(400)
    a = ContextTracker(UTC_DAY); full = [a.update(b) for b in bars]
    b2 = ContextTracker(UTC_DAY); pref = [b2.update(b) for b in bars[:250]]
    assert full[:250] == pref
    assert set(CONTEXT_FEATURES) <= set(full[-1]) and full[-1]["dist_prior_high_atr"] is not None


def _rows(n, seed=3):
    """Synthetic: technique A wins when feature 0 > 0, technique B never has edge."""
    rnd, rows = random.Random(seed), []
    for i in range(n):
        ctx = {k: rnd.gauss(0, 1) for k in CONTEXT_FEATURES}
        for tech in ("A", "B"):
            win = (ctx[CONTEXT_FEATURES[0]] > 0) if tech == "A" else rnd.random() < 0.2
            rows.append({"instrument": "SYN", "technique": tech, "t": T0 + i * 3600, "exit_at": T0 + i * 3600 + 1800,
                         "x": feature_row(ctx, 2.0, 0.05), "y": int(win), "r": 2.0 - 0.05 if win else -1.05,
                         "reward_risk": 2.0, "cost_r": 0.05})
    return rows


def test_selector_learns_context_and_abstains_without_edge():
    rows = _rows(600)
    sel = TechniqueSelector("logistic", min_train=50).fit(rows[:800], fitted_through=0)
    good = [r for r in rows[800:] if r["technique"] == "A"]
    ch_pos = [sel.choose([r, rows[800 + 2 * i + 1]])[0] for i, r in enumerate(good[:50]) if r["y"] == 1]
    assert all(c is not None and c["technique"] == "A" for c in ch_pos)
    bad = [r for r in rows[800:] if r["technique"] == "B"][:50]
    assert sum(sel.choose([r])[0] is not None for r in bad) <= 5          # B has negative EV: mostly abstain
    assert sel.choose([{**bad[0], "technique": "UNSEEN"}])[0] is None      # untrained technique -> abstain


def test_walk_forward_selector_beats_baselines_on_synthetic_edge_and_gates_report():
    wf = walk_forward_selector(_rows(900))
    out = summarize({"syn": wf})["groups"]["syn"]
    st = out["strategies"]
    assert st["selector_logistic"]["total_r_after_cost"] > st["best_single_trained"]["total_r_after_cost"] > 0
    assert st["always_abstain"]["total_r_after_cost"] == 0
    names = {g["gate"] for g in out["registry_gates"]["selector_logistic"]}
    assert "shadow_weeks" in names and out["register"] is False            # offline evidence can never register


def test_selector_output_only_via_registered_model():
    from atlas.models.predict import fit_platt

    class C:  # minimal candidate stand-in
        detector, features = "A", {}
    c = C(); annotate_choice(c, 0.7)
    assert abs(c.features["selector_logit"] - 0.8473) < 1e-3
    m = selector_registered_model("sel-test", fit_platt([-1, 1, -1, 1] * 10, [0, 1, 0, 1] * 10, fitted_through=0), "syn")
    assert m.required_features == ("selector_logit",) and m.target == "setup_success"


def test_hypothesis_stats_and_counting():
    assert wilson(0, 0) is None and binom_two_sided_p(5, 10) == 1.0
    assert binom_two_sided_p(10, 10) < 0.01
    day = 86400
    bars = []
    def add(t, o, h, l, c): bars.append(Bar(t, 900, o, h, l, c, 1))
    add(T0, 100, 110, 95, 105)                          # day0 high 110 (swing source)
    add(T0 + day, 100, 104, 96, 100)                    # day1 range 104/96
    add(T0 + 2 * day, 100, 101, 99, 100)                # day2 first bar (skipped 15 min)
    add(T0 + 2 * day + 900, 100, 105, 99.5, 104)        # break up of 104; d = 6, back = 98
    add(T0 + 2 * day + 1800, 104, 111, 103, 110)        # reaches swing 110
    h = range_break_hypothesis(bars, UTC_DAY)
    assert h["counts"]["swing"] == 1 and h["n_resolved"] == 1
