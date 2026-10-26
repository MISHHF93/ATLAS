"""ATLAS 14-Stage Unified Intelligence Loop.

Connects verified market-data / protocol adapters, causal price-action & order-flow strategy
detectors, Four-Box institutional structure, Gold (GC) session models, Nasdaq (NQ/QQQ) opening
drive models, scheduled-news post-release boxes, whale order-flow research, prop-firm risk
pacing, and Solana Pump.fun/PumpSwap token intelligence into one deterministic, auditable
14-stage loop:

  1. AUTHORIZED_INTERNET_AND_MARKET_DATA
  2. DATA_COLLECTION_AND_VALIDATION
  3. MARKET_CONTEXT_ANALYSIS
  4. TECHNICAL_INDICATORS
  5. MARKET_STRUCTURE_INTELLIGENCE
  6. LIQUIDITY_INTELLIGENCE
  7. STRATEGY_DETECTION
  8. MACHINE_LEARNING
  9. PROBABILITY_AND_RISK_ANALYSIS
 10. OPPORTUNITY_COMPARISON
 11. DETERMINISTIC_RISK_CONTROL
 12. PAPER_AUTHORIZED_TRADING
 13. OUTCOME_TRACKING
 14. MODEL_EVALUATION_AND_RESEARCH

HARD INVARIANTS:
- Every AI/ML/research stage carries ``execution_permission == "none"``.
- Only Stage 11 (``DETERMINISTIC_RISK_CONTROL``) approves or rejects paper orders.
- Paper trading only (``assert_paper_only()``).
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from atlas.ai.intel.fourbox import scan as scan_fourbox
from atlas.features.price_action.bars import EPS, Bar, bar_confirmed
from atlas.features.price_action.engine import EngineConfig, PriceActionEngine
from atlas.features.price_action.events import EconomicEvent
from atlas.features.price_action.extended_strategies import (
    ExtendedStrategyEngine,
    PropFirmCompetitionAdvisor,
    PropFirmCompetitionState,
    is_nasdaq_instrument,
)
from atlas.features.price_action.features import batch_features
from atlas.features.price_action.sessions import PRESETS
from atlas.features.price_action.suite import StrategyToggles, SuiteConfig, is_gold
from atlas.integrations.protocol_manifest import detect_protocol_drift, verify_protocol_compatibility
from atlas.pump.engine import PumpIntelligenceEngine
from atlas.risk.safe_stop import shared_safe_stop
from atlas.risk.safety import assert_paper_only

EXECUTION_PERMISSION = "none"

STAGE_NAMES: tuple[str, ...] = (
    "AUTHORIZED_INTERNET_AND_MARKET_DATA",
    "DATA_COLLECTION_AND_VALIDATION",
    "MARKET_CONTEXT_ANALYSIS",
    "TECHNICAL_INDICATORS",
    "MARKET_STRUCTURE_INTELLIGENCE",
    "LIQUIDITY_INTELLIGENCE",
    "STRATEGY_DETECTION",
    "MACHINE_LEARNING",
    "PROBABILITY_AND_RISK_ANALYSIS",
    "OPPORTUNITY_COMPARISON",
    "DETERMINISTIC_RISK_CONTROL",
    "PAPER_AUTHORIZED_TRADING",
    "OUTCOME_TRACKING",
    "MODEL_EVALUATION_AND_RESEARCH",
)


def _default_bars_for_instrument(instrument: str, base_ts: int = 1_761_571_800) -> list[Bar]:
    """Deterministic confirmed 5m bar fixture covering opening range, breakout, retest,
    failed breakout, stretched VWAP reversion, and institutional volume spike."""
    inst = instrument.upper()
    base_price = 2750.0 if is_gold(inst) else (20200.0 if is_nasdaq_instrument(inst) else (68000.0 if "BTC" in inst else 580.0))
    step = base_price * 0.0012
    bars: list[Bar] = []
    t0 = 1_761_571_800  # 2025-10-27 13:30:00 UTC (09:30 EDT Monday)
    dur = 300
    pattern = [
        # 0..5: 09:30 - 10:00 ET Initial Balance (6 x 5m = 30m)
        (0.0, 0.8, -0.5, 0.3, 1000.0),
        (0.3, 1.0, -0.2, 0.6, 1100.0),
        (0.6, 1.2, 0.1, 0.4, 950.0),
        (0.4, 0.9, -0.6, -0.1, 1050.0),
        (-0.1, 0.7, -0.8, 0.2, 980.0),
        (0.2, 1.1, -0.4, 0.5, 1120.0),
        # 6..11: 10:00 - 10:30 ET (completes 1h opening range + triggers NQ IB-30 breakout)
        (0.5, 2.2, 0.4, 2.0, 2600.0),
        (2.0, 2.6, 1.0, 1.15, 1300.0),
        (1.15, 2.8, 1.10, 2.65, 2900.0),
        # 9..13: Failed upside breakout above recent high followed by bearish close back inside range
        (2.65, 4.2, 2.5, 3.9, 1800.0),
        (3.9, 4.4, 2.1, 2.25, 3400.0),
        # 11..15: Pullback to VWAP/Opening range & whale volume accumulation spike
        (2.25, 2.4, 0.9, 1.15, 1200.0),
        (1.15, 2.9, 1.05, 2.75, 4800.0),
        (2.75, 3.5, 2.4, 3.3, 2100.0),
        (3.3, 3.8, 2.9, 3.6, 1950.0),
        (3.6, 4.1, 3.2, 3.95, 2200.0),
    ]
    for idx, (o_m, h_m, l_m, c_m, vol) in enumerate(pattern):
        start = t0 + idx * dur
        o = round(base_price + o_m * step, 4)
        h = round(base_price + h_m * step, 4)
        l = round(base_price + l_m * step, 4)
        c = round(base_price + c_m * step, 4)
        bars.append(
            Bar(
                start=start,
                duration=dur,
                open=o,
                high=max(h, o, c),
                low=min(l, o, c),
                close=c,
                volume=vol,
                provider_completion_verified=True,
            )
        )
    return bars


def _default_events_for_instrument(instrument: str, bars: Sequence[Bar]) -> list[EconomicEvent]:
    if not bars or len(bars) < 8:
        return []
    release_bar = bars[5]
    return [
        EconomicEvent(
            event_id=f"macro_cpi_{instrument.lower()}",
            event_type="CPI_YOY",
            scheduled_release_time=release_bar.start + 60,
            instrument_relevance=(instrument.upper(),),
            actual_release_time=release_bar.start + 60,
            reported_value=3.1,
            consensus_value=3.3,
            consensus_available_at=release_bar.start - 3600,
            previous_value=3.4,
            previous_available_at=release_bar.start - 86400,
        )
    ]


class UnifiedIntelligenceLoop:
    """Executes the 14-Stage ATLAS Intelligence Loop end-to-end across traditional multi-asset
    bars and Solana Pump.fun / PumpSwap tokens."""

    def __init__(self, pump_engine: PumpIntelligenceEngine | None = None):
        assert_paper_only()
        self.pump_engine = pump_engine or PumpIntelligenceEngine()
        self.prop_advisor = PropFirmCompetitionAdvisor()

    def run(
        self,
        instruments: Sequence[str] = ("GC", "NQ", "BTCUSDT"),
        bars_by_instrument: Mapping[str, Sequence[Bar]] | None = None,
        events_by_instrument: Mapping[str, Sequence[EconomicEvent]] | None = None,
        prop_state: PropFirmCompetitionState | None = None,
        execute_top_paper: bool = True,
    ) -> dict[str, Any]:
        assert_paper_only()
        bars_map: dict[str, list[Bar]] = {}
        events_map: dict[str, list[EconomicEvent]] = {}
        for inst in instruments:
            norm = inst.strip().upper()
            raw_bars = list((bars_by_instrument or {}).get(norm) or _default_bars_for_instrument(norm))
            bars_map[norm] = raw_bars
            raw_events = list((events_by_instrument or {}).get(norm) or _default_events_for_instrument(norm, raw_bars))
            events_map[norm] = raw_events

        stages: dict[str, dict[str, Any]] = {}

        # Stage 1: Authorized Internet and Market Data Sources
        compat = verify_protocol_compatibility()
        drift = detect_protocol_drift()
        stages["AUTHORIZED_INTERNET_AND_MARKET_DATA"] = {
            "stage_index": 1,
            "status": "ok" if compat["all_compatible"] and not drift["drift_detected"] else "degraded",
            "adapter_count": compat["adapter_count"],
            "all_compatible": compat["all_compatible"],
            "drift_detected": drift["drift_detected"],
            "ml_stack": compat["ml_analytics_stack"],
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 2: Data Collection and Validation
        validated_bars: dict[str, list[Bar]] = {}
        refused_bars: dict[str, int] = {}
        for inst, b_list in bars_map.items():
            now_ts = b_list[-1].end if b_list else 0
            admitted = [b for b in b_list if bar_confirmed(b, now_ts)]
            validated_bars[inst] = admitted
            refused_bars[inst] = len(b_list) - len(admitted)
        pump_wb = self.pump_engine.workbench_snapshot()
        pump_bundles = pump_wb["tokens"]
        stages["DATA_COLLECTION_AND_VALIDATION"] = {
            "stage_index": 2,
            "status": "ok",
            "instruments_validated": {k: len(v) for k, v in validated_bars.items()},
            "unconfirmed_or_invalid_refused": refused_bars,
            "solana_tokens_indexed": len(pump_bundles),
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 3: Market Context Analysis
        market_context: dict[str, dict[str, Any]] = {}
        for inst, b_list in validated_bars.items():
            sess_name = "us_equity_rth" if (is_gold(inst) or is_nasdaq_instrument(inst) or inst in ("SPY", "ES")) else None
            closes = [b.close for b in b_list]
            ret_pct = ((closes[-1] - closes[0]) / max(closes[0], EPS) * 100.0) if len(closes) >= 2 else 0.0
            market_context[inst] = {
                "session_preset": sess_name or "24x7_continuous",
                "is_gold": is_gold(inst),
                "is_nasdaq": is_nasdaq_instrument(inst),
                "trend_bias": "bullish" if ret_pct > 0.05 else ("bearish" if ret_pct < -0.05 else "neutral"),
                "session_return_pct": round(ret_pct, 4),
            }
        stages["MARKET_CONTEXT_ANALYSIS"] = {
            "stage_index": 3,
            "status": "ok",
            "contexts": market_context,
            "solana_venue_states": {b["token"]["mint"]: b["token"]["lifecycle_state"] for b in pump_bundles},
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 4: Technical Indicators
        indicator_snapshots: dict[str, dict[str, Any]] = {}
        for inst, b_list in validated_bars.items():
            ctxs = batch_features(b_list, 14)
            last_ctx = ctxs[-1] if ctxs else {}
            tp_v = sum(((b.high + b.low + b.close) / 3.0) * max(b.volume, 1.0) for b in b_list)
            tot_v = sum(max(b.volume, 1.0) for b in b_list)
            vwap = tp_v / max(tot_v, EPS)
            indicator_snapshots[inst] = {
                "atr_14": round(float(last_ctx.get("atr") or 0.0), 6),
                "band_a_20_2": last_ctx.get("band_a"),
                "band_b_4_4": last_ctx.get("band_b"),
                "session_vwap": round(vwap, 6),
                "last_close": b_list[-1].close if b_list else None,
            }
        stages["TECHNICAL_INDICATORS"] = {
            "stage_index": 4,
            "status": "ok",
            "indicators": indicator_snapshots,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 5: Market Structure Intelligence
        structure_intel: dict[str, Any] = {}
        for inst, b_list in validated_bars.items():
            fb = scan_fourbox(inst, b_list, events=events_map.get(inst))
            structure_intel[inst] = {
                "four_box": fb,
                "active_boxes": [b["box"] for b in fb.get("boxes", []) if b.get("status") == "enabled"],
            }
        stages["MARKET_STRUCTURE_INTELLIGENCE"] = {
            "stage_index": 5,
            "status": "ok",
            "structure_by_instrument": structure_intel,
            "pump_migrations": pump_wb["migrations"],
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 6: Liquidity Intelligence
        liquidity_intel: dict[str, Any] = {}
        for inst, b_list in validated_bars.items():
            atr_v = indicator_snapshots[inst]["atr_14"] or 1.0
            est_spread = (b_list[-1].close * 0.00015) if b_list else 0.0
            liquidity_intel[inst] = {
                "estimated_spread_price": round(est_spread, 6),
                "spread_to_atr_ratio": round(est_spread / max(atr_v, EPS), 6),
                "resting_sweep_high": max((b.high for b in b_list), default=None),
                "resting_sweep_low": min((b.low for b in b_list), default=None),
            }
        pump_liq = {b["token"]["mint"]: b["liquidity_profile"] for b in pump_bundles}
        stages["LIQUIDITY_INTELLIGENCE"] = {
            "stage_index": 6,
            "status": "ok",
            "multi_asset_liquidity": liquidity_intel,
            "solana_pool_liquidity": pump_liq,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 7: Strategy Detection
        all_bar_candidates: list[dict[str, Any]] = []
        strategy_counts_by_inst: dict[str, dict[str, int]] = {}
        for inst, b_list in validated_bars.items():
            if not b_list:
                continue
            sess_name = "us_equity_rth" if (is_gold(inst) or is_nasdaq_instrument(inst) or inst in ("SPY", "ES")) else None
            sess = PRESETS.get(sess_name) if sess_name else None
            suite_cfg = SuiteConfig(
                toggles=StrategyToggles(
                    sfp=True,
                    gold_snapback=is_gold(inst),
                    gold_orb_breakout=is_gold(inst),
                ),
                calendar="COMEX" if is_gold(inst) else ("NYSE" if is_nasdaq_instrument(inst) or inst in ("SPY", "ES") else "crypto"),
            )
            pa_eng = PriceActionEngine(inst, b_list[0].duration, EngineConfig(session=sess, suite=suite_cfg))
            pa_eng.run_batch(b_list)
            ext_eng = ExtendedStrategyEngine(inst, b_list[0].duration, events=events_map.get(inst, ()))
            ext_res = ext_eng.run_batch(b_list)

            inst_cands = [c.to_dict() for c in pa_eng.candidates] + list(ext_res["candidates"])
            counts: dict[str, int] = {}
            for c in inst_cands:
                det = str(c.get("detector") or "unknown")
                counts[det] = counts.get(det, 0) + 1
                all_bar_candidates.append(c)
            strategy_counts_by_inst[inst] = counts

        pump_signals = pump_wb["ev_leaderboard"]
        stages["STRATEGY_DETECTION"] = {
            "stage_index": 7,
            "status": "ok",
            "multi_asset_candidate_count": len(all_bar_candidates),
            "multi_asset_by_instrument": strategy_counts_by_inst,
            "solana_pump_signal_count": len(pump_signals),
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 8: Machine Learning
        ml_predictions: list[dict[str, Any]] = []
        for c in all_bar_candidates:
            entry = float(c["entry_reference"])
            stop = float(c["proposed_stop"])
            target = float(c["proposed_target"])
            risk = max(abs(entry - stop), EPS)
            reward = abs(target - entry)
            rr = reward / risk
            feats = c.get("features") or {}
            vol_z = float(feats.get("vol_zscore") or 1.0)
            bo_s = float(feats.get("breakout_strength") or feats.get("trap_magnitude_atr") or 0.6)
            raw_logit = -0.15 + 0.18 * min(bo_s, 3.0) + 0.08 * min(vol_z, 3.0)
            p_target = round(1.0 / (1.0 + math.exp(-raw_logit)), 4)
            p_stop = round(1.0 - p_target, 4)
            ml_predictions.append({
                "candidate_id": c["candidate_id"],
                "instrument": c["instrument"],
                "detector": c["detector"],
                "direction": c["direction"],
                "p_target_before_stop": p_target,
                "p_stop_before_target": p_stop,
                "reward_risk_ratio": round(rr, 4),
                "execution_permission": EXECUTION_PERMISSION,
            })
        pump_ml = {b["token"]["mint"]: b["ml_forecast"] for b in pump_bundles}
        stages["MACHINE_LEARNING"] = {
            "stage_index": 8,
            "status": "ok",
            "multi_asset_ml_predictions": ml_predictions,
            "solana_pump_ml_forecasts": pump_ml,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 9: Probability and Risk Analysis
        risk_analyses: list[dict[str, Any]] = []
        for pred in ml_predictions:
            rr = float(pred["reward_risk_ratio"])
            cost_r = 0.06 if pred["instrument"] in ("GC", "NQ", "SPY", "QQQ") else 0.09
            ev_r = round(pred["p_target_before_stop"] * rr - pred["p_stop_before_target"] * 1.0 - cost_r, 4)
            risk_analyses.append({
                **pred,
                "estimated_cost_r": cost_r,
                "expected_value_r": ev_r,
                "risk_reward_acceptable": rr >= 1.5 and cost_r <= 0.20,
            })
        pump_risk_reports = {b["token"]["mint"]: b["token_safety"] for b in pump_bundles}
        stages["PROBABILITY_AND_RISK_ANALYSIS"] = {
            "stage_index": 9,
            "status": "ok",
            "multi_asset_risk_analysis": risk_analyses,
            "solana_token_risk_reports": pump_risk_reports,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 10: Opportunity Comparison
        unified_opportunities: list[dict[str, Any]] = []
        for item in risk_analyses:
            unified_opportunities.append({
                "opportunity_id": item["candidate_id"],
                "domain": "multi_asset",
                "instrument_or_mint": item["instrument"],
                "strategy": item["detector"],
                "direction": item["direction"],
                "expected_value_score": round(item["expected_value_r"] * 100.0, 3),
                "p_win": item["p_target_before_stop"],
                "risk_acceptable": item["risk_reward_acceptable"],
                "execution_permission": EXECUTION_PERMISSION,
            })
        for sig in pump_signals:
            cand_info = sig.get("candidate") or sig
            fc_info = sig.get("forecast") or {}
            mint_id = str(cand_info.get("mint") or sig.get("mint"))
            strat_id = str(cand_info.get("strategy_id") or sig.get("strategy_id"))
            direction = str(cand_info.get("direction") or sig.get("direction") or "long")
            safety_rep = pump_risk_reports.get(mint_id) or {}
            unified_opportunities.append({
                "opportunity_id": f"pump:{mint_id}:{strat_id}",
                "domain": "solana_pump",
                "instrument_or_mint": mint_id,
                "strategy": strat_id,
                "direction": direction,
                "expected_value_score": round(float(sig.get("net_expected_value_bps", 0.0)) / 10.0, 3),
                "p_win": float(fc_info.get("prob_target_before_stop", 0.5)),
                "risk_acceptable": safety_rep.get("safety_status") == "passed",
                "execution_permission": EXECUTION_PERMISSION,
            })
        unified_opportunities.sort(key=lambda x: x["expected_value_score"], reverse=True)
        for rank_idx, opp in enumerate(unified_opportunities, start=1):
            opp["rank"] = rank_idx
        stages["OPPORTUNITY_COMPARISON"] = {
            "stage_index": 10,
            "status": "ok",
            "total_opportunities_ranked": len(unified_opportunities),
            "ranked_opportunities": unified_opportunities,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 11: Deterministic Risk Control
        prop_eval = self.prop_advisor.evaluate(prop_state)
        kill_switch_engaged = bool(shared_safe_stop().engaged)
        approved_opportunities: list[dict[str, Any]] = []
        rejected_opportunities: list[dict[str, Any]] = []
        for opp in unified_opportunities:
            reasons: list[str] = []
            if kill_switch_engaged:
                reasons.append("kill_switch_engaged")
            if prop_eval["halt_new_entries"]:
                reasons.append("prop_firm_buffer_halted")
            if not opp["risk_acceptable"]:
                reasons.append("risk_or_safety_threshold_failed")
            if opp["expected_value_score"] <= 0:
                reasons.append("non_positive_expected_value")
            decision = {
                **opp,
                "approved": len(reasons) == 0,
                "size_scalar": prop_eval["size_scalar"] if len(reasons) == 0 else 0.0,
                "reasons": reasons or ["deterministic_risk_control_approved"],
                "execution_permission": EXECUTION_PERMISSION,
            }
            if decision["approved"]:
                approved_opportunities.append(decision)
            else:
                rejected_opportunities.append(decision)

        stages["DETERMINISTIC_RISK_CONTROL"] = {
            "stage_index": 11,
            "status": "ok",
            "kill_switch_engaged": kill_switch_engaged,
            "prop_firm_pacing": prop_eval,
            "approved_count": len(approved_opportunities),
            "rejected_count": len(rejected_opportunities),
            "approved_opportunities": approved_opportunities,
            "rejected_opportunities": rejected_opportunities,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 12: Paper / Authorized Trading
        paper_executions: list[dict[str, Any]] = []
        if execute_top_paper and approved_opportunities:
            top_pump = next((o for o in approved_opportunities if o["domain"] == "solana_pump" and o["direction"] == "long"), None)
            if top_pump is not None:
                notional_sol = round(max(0.05, 0.25 * float(top_pump["size_scalar"])), 4)
                trade_res = self.pump_engine.execute_end_to_end_order(
                    client_order_id=f"loop_{top_pump['instrument_or_mint'][:8]}",
                    mint=top_pump["instrument_or_mint"],
                    side="buy",
                    size_sol=notional_sol,
                    slippage_bps=150.0,
                    requested_mode="paper",
                )
                paper_executions.append(trade_res)
        stages["PAPER_AUTHORIZED_TRADING"] = {
            "stage_index": 12,
            "status": "ok",
            "paper_only": True,
            "executions": paper_executions,
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 13: Outcome Tracking
        portfolio_snap = self.pump_engine.portfolio.summary()
        stages["OUTCOME_TRACKING"] = {
            "stage_index": 13,
            "status": "ok",
            "solana_paper_portfolio": portfolio_snap,
            "tracked_bar_candidates": len(all_bar_candidates),
            "execution_permission": EXECUTION_PERMISSION,
        }

        # Stage 14: Model Evaluation and Research
        pump_eval = self.pump_engine.monitoring.performance_summary()
        stages["MODEL_EVALUATION_AND_RESEARCH"] = {
            "stage_index": 14,
            "status": "ok",
            "pump_model_evaluation": pump_eval,
            "protocol_drift_monitor": drift,
            "research_champion_gate_strict": True,
            "execution_permission": EXECUTION_PERMISSION,
        }

        return {
            "status": "ok",
            "stage_count": len(STAGE_NAMES),
            "stage_names": list(STAGE_NAMES),
            "stages": stages,
            "summary": {
                "instruments": list(validated_bars.keys()),
                "solana_tokens": len(pump_bundles),
                "multi_asset_candidates": len(all_bar_candidates),
                "solana_signals": len(pump_signals),
                "ranked_opportunities": len(unified_opportunities),
                "approved_opportunities": len(approved_opportunities),
                "paper_executions": len(paper_executions),
            },
            "paper_only": True,
            "execution_permission": EXECUTION_PERMISSION,
        }


def run_unified_intelligence_loop(**kwargs: Any) -> dict[str, Any]:
    return UnifiedIntelligenceLoop().run(**kwargs)
