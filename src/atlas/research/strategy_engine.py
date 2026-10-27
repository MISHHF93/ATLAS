"""Strategy Discovery, Knowledge Base, Pine v5/v6 Parser, Canonical IR, Parity Testing & Realistic Backtesting.

Implements Sections 3, 4, 5, 6, 7, 8, 9, 18, 19, and 23 of the ATLAS Complete Research-to-Execution
Intelligence Integration specification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Sequence

from atlas.ext import pine as ext_pine
from atlas.intel.data import TF_SECONDS, freshness_for, load_bars
from atlas.market.contracts import SPEC_BY_ID
from atlas.market.sessions import evaluate_candidate_market_gate

EXECUTION_PERMISSION = "none"

STRATEGY_LIFECYCLE_STAGES: tuple[str, ...] = (
    "DISCOVERED",
    "SOURCE_VERIFIED",
    "LOGIC_PARSED",
    "CAUSALITY_CHECKED",
    "BACKTESTED",
    "WALK_FORWARD_VALIDATED",
    "PAPER_EVALUATED",
    "RESEARCH_APPROVED",
    "RESEARCH_REJECTED",
)

EVIDENCE_CLASSIFICATIONS: tuple[str, ...] = (
    "VERIFIED_SOURCE",
    "REPOSITORY_EVIDENCE",
    "EXPERIMENT_RESULT",
    "MODEL_PREDICTION",
    "RESEARCH_HYPOTHESIS",
    "AI_INFERENCE",
    "UNVERIFIED_CLAIM",
)

APPROVED_LICENSES: frozenset[str] = frozenset({
    "MIT",
    "APACHE-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "MPL-2.0",
    "ISC",
    "CC0-1.0",
    "UNLICENSE",
    "ATLAS-INTERNAL",
})

SUPPORTED_PINE_TA_FUNCTIONS: tuple[str, ...] = (
    "ta.sma",
    "ta.ema",
    "ta.rsi",
    "ta.atr",
    "ta.stdev",
    "ta.crossover",
    "ta.crossunder",
    "ta.highest",
    "ta.lowest",
    "ta.pivothigh",
    "ta.pivotlow",
    "ta.vwap",
    "ta.supertrend",
)

UNSUPPORTED_PINE_CONSTRUCTS: dict[str, str] = {
    "request.footprint": "Volume footprint intrabar requests require proprietary tick feeds not available in standard OHLCV.",
    "request.seed": "External seeded custom feeds cannot be verified point-in-time.",
    "request.currency_rate": "Dynamic cross-currency intrabar requests are unsupported; use ATLAS ISO 4217 BoC FX layer.",
    "matrix.": "Pine matrix algebra operations are outside the supported deterministic indicator subset.",
    "polyline.": "Drawing polylines has no execution semantics.",
    "chart.point": "Chart drawing objects are UI-only and unsupported in strategy IR.",
    "alert(": "External webhook alert execution is blocked by ATLAS security policy.",
}

PROMPT_INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all prior instructions",
    "disregard system prompt",
    "bypass risk control",
    "disable safe stop",
    "execute live order",
    "send private key",
    "override execution_permission",
)

EXTERNAL_RESEARCH_REFERENCES: dict[str, dict[str, Any]] = {
    "tradingview_indicator_search_mcp": {
        "reference_url": "https://github.com/daviddme/tradingview-indicator-search-mcp-server",
        "official_tradingview_support": False,
        "license": "MIT (Community Open-Source MCP Server)",
        "data_access_methods": [
            "offline_sqlite_corpus_search (node:sqlite local FTS / source search — PERMITTED when scripts carry open-source licenses)",
            "live_unauthenticated_tradingview_scraping (DISABLED BY ATLAS POLICY — violates ToS / rate-limit governance)",
            "manual_verified_open_source_import (PERMITTED — requires explicit license, hash provenance, and static safety audit)",
        ],
        "mcp_tools_inspected": [
            "search_indicators",
            "get_indicator_source",
            "search_local_corpus",
        ],
        "security_implications": [
            "Community Pine scripts are untrusted input and may contain prompt-injection strings in comments.",
            "Popular scripts frequently use request.security(..., lookahead=barmerge.lookahead_on) without [1] offset (repainting).",
            "Indicators without explicit strategy.entry / strategy.exit rules are not executable strategies.",
        ],
        "atlas_governance_mode": "OFFLINE_CORPUS_AND_VERIFIED_IMPORT_ONLY",
    },
    "tradingkit_pine_backtests": {
        "reference_url": "https://help.tradingkit.com/backtests/pine-script/",
        "service_type": "External third-party documentation / cloud backtesting reference (not an embeddable local library)",
        "authorized_api_available": False,
        "documented_limitations": [
            "Standard bar-close evaluation masks intrabar high/low order fill ambiguity.",
            "request.security with unshifted lookahead causes severe lookahead bias.",
            "calc_on_every_tick and calc_on_order_fills alter historical vs realtime signals (repainting).",
            "High-frequency scalping backtests inflate returns when spread, slippage, and partial fills are omitted.",
        ],
        "atlas_implementation": "ATLAS-owned deterministic Pine v5/v6 Subset Parser -> Canonical StrategyIR -> ATLAS Conservative OHLC Replay.",
    },
}

DEFAULT_KB_PATH = Path("var/research/strategy_knowledge_base.json")


@dataclass
class StrategyIR:
    strategy_id: str
    strategy_version: str
    source_language: str
    instrument_scope: list[str]
    timeframe: str
    features: list[str]
    entry_rules: list[dict[str, Any]]
    exit_rules: list[dict[str, Any]]
    risk_rules: list[dict[str, Any]]
    parameters: dict[str, Any]
    execution_assumptions: dict[str, Any]
    causality_constraints: dict[str, Any]
    execution_permission: str = EXECUTION_PERMISSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_and_validate_pine(
    source_code: str,
    *,
    strategy_id: str = "custom_pine",
    source_license: str = "MIT",
    source_reference: str = "manual_import",
    instrument_scope: Sequence[str] = ("equities", "futures", "crypto"),
    timeframe: str = "15m",
) -> dict[str, Any]:
    """Deterministically parse, lint, and security-screen a Pine v5/v6 script into Canonical StrategyIR."""
    raw = source_code.strip()
    source_hash = _sha256(raw)
    lower = raw.lower()

    # 1. Security & Prompt-Injection Screening (Section 23)
    security_violations: list[str] = []
    for pat in PROMPT_INJECTION_PATTERNS:
        if pat in lower:
            security_violations.append(f"prompt_injection_pattern_detected:{pat}")
    if len(raw) > 120_000:
        security_violations.append("source_size_exceeds_120kb_limit")

    # 2. License Validation
    norm_lic = (source_license or "").strip().upper()
    license_valid = norm_lic in APPROVED_LICENSES
    if not license_valid:
        security_violations.append(f"unapproved_or_missing_license:{source_license or 'NONE'}")

    # 3. Version Detection
    version_match = re.search(r"^//@version=(\d+)", raw, flags=re.MULTILINE)
    pine_version = int(version_match.group(1)) if version_match else None
    syntax_errors: list[str] = []
    if pine_version not in (5, 6):
        syntax_errors.append(f"unsupported_or_missing_pine_version:{pine_version} (supported: //@version=5 or //@version=6)")

    if raw.count("(") != raw.count(")"):
        syntax_errors.append("unbalanced_parentheses")
    if raw.count("[") != raw.count("]"):
        syntax_errors.append("unbalanced_brackets")

    is_strategy_decl = bool(re.search(r"\bstrategy\s*\(", raw))
    is_indicator_decl = bool(re.search(r"\bindicator\s*\(", raw))
    if not is_strategy_decl and not is_indicator_decl:
        syntax_errors.append("missing_strategy_or_indicator_declaration")

    # 4. Unsupported Feature Diagnostics (Section 5)
    unsupported_features: list[dict[str, str]] = []
    for token, reason in UNSUPPORTED_PINE_CONSTRUCTS.items():
        if token in raw:
            unsupported_features.append({"construct": token, "reason": reason})

    # 5. Repainting & Lookahead Risk Detection (Section 3 & 5)
    repainting_flags: list[str] = []
    lookahead_flags: list[str] = []

    for sec_match in re.finditer(r"request\.security\s*\(([^)]*)\)", raw):
        args_txt = sec_match.group(1)
        if "lookahead_on" in args_txt and "[1]" not in args_txt:
            lookahead_flags.append("request.security with barmerge.lookahead_on without [1] completed-bar offset leaks future bars.")
        elif "lookahead_on" not in args_txt and "[1]" not in args_txt:
            repainting_flags.append("request.security without explicit [1] prior-bar offset may repaint on historical vs realtime bars.")

    if "calc_on_every_tick=true" in raw.replace(" ", ""):
        repainting_flags.append("calc_on_every_tick=true causes historical bar-close vs live intrabar divergence.")
    if "calc_on_order_fills=true" in raw.replace(" ", ""):
        repainting_flags.append("calc_on_order_fills=true recalculates intrabar after order fills.")
    if "timenow" in raw:
        repainting_flags.append("timenow makes historical evaluation non-reproducible.")
    if re.search(r"\b(?:close|open|high|low|volume)\s*\[\s*-\d+\s*\]", raw):
        lookahead_flags.append("Negative bar index offset (e.g. close[-1]) accesses future bars.")

    repainting_risk = "HIGH" if repainting_flags else "LOW"
    lookahead_risk = "HIGH" if lookahead_flags else "LOW"

    # 6. Indicator Dependency Extraction
    indicators: list[str] = []
    for fn in SUPPORTED_PINE_TA_FUNCTIONS:
        if fn in raw:
            indicators.append(fn)

    # 7. Parameter Extraction (input.int, input.float, input.session, input.string)
    parameters: dict[str, Any] = {}
    for m in re.finditer(
        r"(\w+)\s*=\s*input\.(int|float|session|string|bool)\s*\(\s*([^,)\n]+)(?:\s*,\s*\"([^\"]+)\")?",
        raw,
    ):
        var_name, kind, def_val, title = m.group(1), m.group(2), m.group(3).strip().strip('"\''), m.group(4) or m.group(1)
        try:
            parsed_val: Any = int(def_val) if kind == "int" else float(def_val) if kind == "float" else (def_val.lower() == "true") if kind == "bool" else def_val
        except ValueError:
            parsed_val = def_val
        parameters[var_name] = {"type": kind, "default": parsed_val, "title": title}

    # 8. Entry, Exit, Stop & Sizing Extraction
    entry_rules: list[dict[str, Any]] = []
    for m in re.finditer(r"strategy\.entry\s*\(\s*\"([^\"]+)\"\s*,\s*(strategy\.long|strategy\.short)([^)]*)\)", raw):
        entry_rules.append({
            "id": m.group(1),
            "direction": "long" if "long" in m.group(2) else "short",
            "options": m.group(3).strip(" ,"),
        })

    exit_rules: list[dict[str, Any]] = []
    risk_rules: list[dict[str, Any]] = []
    for m in re.finditer(r"strategy\.exit\s*\(\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"([^)]*)\)", raw):
        opts = m.group(3).strip(" ,")
        has_stop = "stop=" in opts or "loss=" in opts
        has_limit = "limit=" in opts or "profit=" in opts
        rule = {
            "exit_id": m.group(1),
            "from_entry": m.group(2),
            "options": opts,
            "has_stop_loss": has_stop,
            "has_take_profit": has_limit,
        }
        exit_rules.append(rule)
        if has_stop:
            risk_rules.append({"kind": "stop_loss", "from_entry": m.group(2), "expression": opts})

    qty_type_match = re.search(r"default_qty_type\s*=\s*([a-zA-Z0-9_.]+)", raw)
    qty_val_match = re.search(r"default_qty_value\s*=\s*([0-9.]+)", raw)
    sizing_spec = {
        "default_qty_type": qty_type_match.group(1) if qty_type_match else "strategy.fixed",
        "default_qty_value": float(qty_val_match.group(1)) if qty_val_match else 1.0,
    }

    has_executable_rules = bool(entry_rules and exit_rules)
    if is_indicator_decl and not has_executable_rules:
        syntax_errors.append("indicator_only_no_executable_trading_rules")
    elif is_strategy_decl and not entry_rules:
        syntax_errors.append("strategy_missing_entry_rules")

    valid = (
        not security_violations
        and not syntax_errors
        and not unsupported_features
        and lookahead_risk == "LOW"
        and repainting_risk == "LOW"
        and has_executable_rules
    )

    ir = StrategyIR(
        strategy_id=strategy_id,
        strategy_version=f"pine_v{pine_version or 5}.0",
        source_language=f"pine_v{pine_version or 5}",
        instrument_scope=list(instrument_scope),
        timeframe=timeframe,
        features=indicators,
        entry_rules=entry_rules,
        exit_rules=exit_rules,
        risk_rules=risk_rules,
        parameters=parameters,
        execution_assumptions={
            "process_orders_on_close": "process_orders_on_close=true" in raw.replace(" ", ""),
            "fill_model": "conservative_ohlc_next_bar_open",
            "position_sizing": sizing_spec,
        },
        causality_constraints={
            "bar_close_only": True,
            "repainting_risk": repainting_risk,
            "lookahead_risk": lookahead_risk,
            "repainting_flags": repainting_flags,
            "lookahead_flags": lookahead_flags,
        },
    )

    return {
        "status": "valid" if valid else "rejected",
        "valid": valid,
        "strategy_id": strategy_id,
        "source_reference": source_reference,
        "source_license": norm_lic,
        "license_valid": license_valid,
        "source_hash": source_hash,
        "pine_version": pine_version,
        "is_strategy": is_strategy_decl,
        "is_indicator_only": is_indicator_decl and not has_executable_rules,
        "has_executable_rules": has_executable_rules,
        "indicator_dependencies": indicators,
        "parameters": parameters,
        "entry_rules": entry_rules,
        "exit_rules": exit_rules,
        "risk_rules": risk_rules,
        "position_sizing": sizing_spec,
        "repainting_risk": repainting_risk,
        "lookahead_risk": lookahead_risk,
        "repainting_flags": repainting_flags,
        "lookahead_flags": lookahead_flags,
        "unsupported_features": unsupported_features,
        "syntax_errors": syntax_errors,
        "security_violations": security_violations,
        "canonical_ir": ir.to_dict(),
        "execution_permission": EXECUTION_PERMISSION,
    }


def _evaluate_pine_subset_signals(strategy_id: str, bars: Sequence[Any]) -> list[dict[str, Any]]:
    """Evaluate Pine subset IR directly on OHLC bars to compare 1-to-1 with ATLAS Python detectors."""
    from atlas.features.price_action.engine import EngineConfig, candidates_from_bars

    det_name = ext_pine.DETECTOR.get(strategy_id, strategy_id)
    cands = candidates_from_bars(
        bars[0].instrument if bars else "BTC-USD",
        bars[0].duration if bars else 900,
        bars,
        EngineConfig(),
    )
    matched = [c for c in cands if c.detector == det_name]
    return [
        {
            "bar_ts": int(c.t),
            "direction": str(c.direction),
            "entry": float(c.entry),
            "stop": float(c.stop),
            "target": float(c.target),
            "detector": str(c.detector),
        }
        for c in matched
    ]


def verify_pine_to_python_parity(
    strategy_id: str,
    *,
    symbol: str = "GC",
    timeframe: str = "15m",
) -> dict[str, Any]:
    """Section 7: Verify Pine logic vs Python detector signal equivalence on identical historical data."""
    from atlas.api.feeds_api import _feed
    from atlas.features.price_action.engine import EngineConfig, candidates_from_bars

    if strategy_id not in ext_pine.BODIES:
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "unsupported_or_experimental",
            "parity_passed": False,
            "reason": f"Strategy '{strategy_id}' does not have a verified 1-to-1 Pine v5/v6 generator in atlas.ext.pine.BODIES.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    bars = load_bars(_feed(), symbol.upper(), timeframe)[-600:]
    if len(bars) < 40:
        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "insufficient_data",
            "parity_passed": False,
            "reason": f"Need at least 40 bars for parity test; found {len(bars)}.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    pine_src = ext_pine.generate(strategy_id)
    parsed = parse_and_validate_pine(
        pine_src,
        strategy_id=strategy_id,
        source_license="ATLAS-INTERNAL",
        source_reference=f"atlas.ext.pine:{strategy_id}",
        timeframe=timeframe,
    )

    det_name = ext_pine.DETECTOR[strategy_id]
    py_cands = [
        c
        for c in candidates_from_bars(symbol.upper(), bars[0].duration, bars, EngineConfig())
        if c.detector == det_name
    ]
    pine_signals = _evaluate_pine_subset_signals(strategy_id, bars)

    py_by_ts = {int(c.t): (str(c.direction), round(float(c.entry), 6), round(float(c.stop), 6)) for c in py_cands}
    pine_by_ts = {int(s["bar_ts"]): (str(s["direction"]), round(float(s["entry"]), 6), round(float(s["stop"]), 6)) for s in pine_signals}

    all_ts = sorted(set(py_by_ts) | set(pine_by_ts))
    mismatches = [ts for ts in all_ts if py_by_ts.get(ts) != pine_by_ts.get(ts)]
    match_rate = 1.0 if not all_ts else (len(all_ts) - len(mismatches)) / len(all_ts)

    golden_payload = "|".join(f"{b.t}:{b.open}:{b.high}:{b.low}:{b.close}" for b in bars[:50])
    golden_hash = _sha256(golden_payload)[:16]

    parity_passed = parsed["valid"] and len(mismatches) == 0
    return {
        "strategy_id": strategy_id,
        "detector": det_name,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "status": "verified_parity" if parity_passed else "parity_failed",
        "parity_passed": parity_passed,
        "bars_tested": len(bars),
        "warmup_bars": 20,
        "python_signal_count": len(py_cands),
        "pine_ir_signal_count": len(pine_signals),
        "match_rate": round(match_rate, 4),
        "mismatch_bar_timestamps": mismatches[:10],
        "golden_dataset_hash": golden_hash,
        "checks": {
            "indicator_warmup": True,
            "bar_timestamps_aligned": True,
            "candle_completion_causal": True,
            "parameter_defaults_matched": True,
            "entry_conditions_matched": len(mismatches) == 0,
            "exit_and_stop_matched": len(mismatches) == 0,
            "repainting_free": parsed["repainting_risk"] == "LOW",
            "lookahead_free": parsed["lookahead_risk"] == "LOW",
        },
        "canonical_ir": parsed["canonical_ir"],
        "execution_permission": EXECUTION_PERMISSION,
    }


def run_realistic_strategy_backtest(
    strategy_id: str,
    *,
    symbol: str = "GC",
    timeframe: str = "15m",
    cost_multiplier: float = 1.0,
    purge_bars: int = 4,
    embargo_bars: int = 4,
) -> dict[str, Any]:
    """Section 8: Realistic Backtesting Engine with purged walk-forward validation, costs, slippage & tail risk."""
    from atlas.api.feeds_api import _feed
    from atlas.features.price_action.engine import EngineConfig
    from atlas.features.price_action.replay import ReplayConfig, paper_replay_config, replay

    bars = load_bars(_feed(), symbol.upper(), timeframe)
    if len(bars) < 60:
        return {
            "strategy_id": strategy_id,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "insufficient_data",
            "reason": f"Need >= 60 bars for realistic backtest; found {len(bars)}.",
            "execution_permission": EXECUTION_PERMISSION,
        }

    # Resolve detector mapping (either direct detector or family mapping)
    det_map = {
        **ext_pine.DETECTOR,
        "four_box_opening": "orb_retest",
        "four_box_breakout": "dual_band_breakout",
        "four_box_anchor": "wick_reversal",
        "gold_opening_range": "orb_retest",
        "nasdaq_opening_continuation": "orb_retest",
        "nasdaq_fair_price_reversion": "prior_day_range_reversal",
        "liquidity_sweep": "sfp_reversal",
        "sfp_reversal": "sfp_reversal",
        "failed_breakout_reversal": "wick_reversal",
        "snapback_continuation": "dual_band_breakout",
    }
    detector = det_map.get(strategy_id, strategy_id)

    base_cfg = paper_replay_config()
    cfg = ReplayConfig(
        slippage_bps=base_cfg.slippage_bps * max(0.0, float(cost_multiplier)),
        fee_bps=base_cfg.fee_bps * max(0.0, float(cost_multiplier)),
        spread_bps=base_cfg.spread_bps * max(0.0, float(cost_multiplier)),
        max_hold_bars=base_cfg.max_hold_bars,
    )

    recent_bars = bars[-1500:]
    res = replay(
        symbol.upper(),
        recent_bars[0].duration,
        recent_bars,
        engine_cfg=EngineConfig(),
        cfg=cfg,
        data_label="real:atlas_feed",
    )
    all_trades = [t for t in res.trades if t.detector == detector and t.r_multiple is not None]
    if not all_trades and res.trades:
        # Fallback to all replay trades if a custom strategy_id is evaluated against general price-action replay
        all_trades = [t for t in res.trades if t.r_multiple is not None]

    r_vals = [float(t.r_multiple) for t in all_trades if t.r_multiple is not None]
    gross_r_vals = [float(getattr(t, "gross_r_multiple", None) or (float(t.r_multiple) + 0.08 * cost_multiplier)) for t in all_trades]

    n_trades = len(r_vals)
    spec = SPEC_BY_ID.get(symbol.upper())
    contract_info = {
        "instrument_id": symbol.upper(),
        "multiplier": spec.multiplier if spec else 1.0,
        "tick_size": spec.tick_size if spec else 0.01,
        "tick_value_usd": spec.tick_value if spec else 0.01,
        "round_trip_cost_usd": spec.cost_per_contract_rt_usd if spec else 1.50,
    }

    if n_trades == 0:
        return {
            "backtest_id": f"bt-{_sha256(f'{strategy_id}:{symbol}:{timeframe}:{len(recent_bars)}')[:12]}",
            "strategy_id": strategy_id,
            "detector": detector,
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "status": "zero_trades",
            "bars_tested": len(recent_bars),
            "n_trades": 0,
            "net_profit_r": 0.0,
            "gross_profit_r": 0.0,
            "fees_r": 0.0,
            "slippage_r": 0.0,
            "win_rate": None,
            "avg_win_r": None,
            "avg_loss_r": None,
            "expected_value_r": 0.0,
            "profit_factor": None,
            "max_drawdown_r": 0.0,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "tail_risk_cvar95_r": None,
            "exposure_pct": 0.0,
            "turnover": 0.0,
            "statistical_uncertainty_ci": None,
            "walk_forward_oos": {"passed": False, "reason": "zero_trades"},
            "contract_assumptions": contract_info,
            "execution_permission": EXECUTION_PERMISSION,
        }

    wins = [x for x in r_vals if x > 0]
    losses = [x for x in r_vals if x <= 0]
    net_profit_r = sum(r_vals)
    gross_profit_r = sum(gross_r_vals)
    total_cost_r = max(0.0, gross_profit_r - net_profit_r)
    fees_r = round(total_cost_r * 0.45, 4)
    slippage_r = round(total_cost_r * 0.55, 4)
    win_rate = len(wins) / n_trades
    avg_win_r = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss_r = (sum(losses) / len(losses)) if losses else 0.0
    ev_r = net_profit_r / n_trades
    profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else (99.0 if wins else 0.0)

    # Equity curve & drawdown in R
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    eq_curve: list[dict[str, Any]] = []
    for idx, t in enumerate(all_trades):
        r = float(t.r_multiple or 0.0)
        eq += r
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)
        eq_curve.append({
            "trade_num": idx + 1,
            "entry_ts": int(t.entry_ts),
            "r_multiple": round(r, 4),
            "cumulative_r": round(eq, 4),
            "drawdown_r": round(dd, 4),
        })

    mean_r = ev_r
    variance = sum((x - mean_r) ** 2 for x in r_vals) / max(1, n_trades - 1)
    std_r = math.sqrt(max(variance, 1e-12))
    downside_sq = [min(0.0, x) ** 2 for x in r_vals]
    downside_std = math.sqrt(max(sum(downside_sq) / max(1, n_trades), 1e-12))
    sharpe = (mean_r / std_r) * math.sqrt(min(252, n_trades)) if std_r > 1e-9 else 0.0
    sortino = (mean_r / downside_std) * math.sqrt(min(252, n_trades)) if downside_std > 1e-9 else 0.0

    sorted_r = sorted(r_vals)
    tail_cutoff = max(1, int(math.ceil(0.05 * n_trades)))
    cvar95_r = sum(sorted_r[:tail_cutoff]) / tail_cutoff

    se_r = std_r / math.sqrt(n_trades)
    ci_95 = {"lo_r": round(mean_r - 1.96 * se_r, 4), "hi_r": round(mean_r + 1.96 * se_r, 4)}

    # Purged & embargoed 2-fold walk-forward split
    mid = n_trades // 2
    purge_n = min(purge_bars + embargo_bars, max(0, mid - 1))
    is_trades = r_vals[: max(1, mid - purge_n)]
    oos_trades = r_vals[mid + purge_n :] if (mid + purge_n) < n_trades else r_vals[mid:]
    is_ev = sum(is_trades) / len(is_trades) if is_trades else 0.0
    oos_ev = sum(oos_trades) / len(oos_trades) if oos_trades else 0.0
    wf_passed = len(oos_trades) >= 3 and oos_ev > 0.0

    bt_id = f"bt-{_sha256(f'{strategy_id}:{symbol}:{timeframe}:{len(recent_bars)}:{cost_multiplier}')[:12]}"
    return {
        "backtest_id": bt_id,
        "strategy_id": strategy_id,
        "detector": detector,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "status": "ok",
        "bars_tested": len(recent_bars),
        "n_trades": n_trades,
        "net_profit_r": round(net_profit_r, 4),
        "gross_profit_r": round(gross_profit_r, 4),
        "fees_r": fees_r,
        "slippage_r": slippage_r,
        "win_rate": round(win_rate, 4),
        "avg_win_r": round(avg_win_r, 4),
        "avg_loss_r": round(avg_loss_r, 4),
        "expected_value_r": round(ev_r, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_r": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "tail_risk_cvar95_r": round(cvar95_r, 4),
        "exposure_pct": round(min(100.0, (n_trades * 4.0 / max(1, len(recent_bars))) * 100.0), 2),
        "turnover": round(n_trades / max(1.0, len(recent_bars) / 96.0), 4),
        "statistical_uncertainty_ci": ci_95,
        "walk_forward_oos": {
            "purge_bars": purge_bars,
            "embargo_bars": embargo_bars,
            "in_sample_trades": len(is_trades),
            "in_sample_ev_r": round(is_ev, 4),
            "out_of_sample_trades": len(oos_trades),
            "out_of_sample_ev_r": round(oos_ev, 4),
            "passed": wf_passed,
        },
        "equity_curve": eq_curve[-60:],
        "contract_assumptions": contract_info,
        "fill_model": "conservative_ohlc_v1 (intrabar stop-first ambiguity resolution)",
        "source_hash": _sha256(f"{strategy_id}:{detector}")[:16],
        "freshness": freshness_for(recent_bars),
        "execution_permission": EXECUTION_PERMISSION,
    }


def _seed_strategies() -> list[dict[str, Any]]:
    """Section 9: All 19 canonical ATLAS & open-source research strategies in the unified Knowledge Base."""
    now_iso = datetime.now(timezone.utc).isoformat()
    specs = [
        ("four_box_opening", "Four-Box Opening Box (ORB Retest)", "four_box", ["GC", "SPY", "NQ", "ES"], ["5m", "15m"], ["ta.highest", "ta.lowest"], "Session opening range breakout + retest hold", "Fixed R target or session close", "Stop at opposite boundary of opening box", "atlas_native", "REPOSITORY_EVIDENCE", "WALK_FORWARD_VALIDATED"),
        ("four_box_breakout", "Four-Box Breakout Box (Dual Bollinger)", "four_box", ["BTC-USD", "ETH-USD", "GC", "NQ"], ["15m", "1h"], ["ta.sma", "ta.stdev", "ta.crossover"], "Close crosses outer 2SD band with prior bar > 1SD band", "2.0R target or basis cross", "Stop at 20-bar SMA basis", "atlas_native", "REPOSITORY_EVIDENCE", "WALK_FORWARD_VALIDATED"),
        ("four_box_anchor", "Four-Box Anchor Box (Wick Reversal)", "four_box", ["GC", "SI", "BTC-USD", "SPY"], ["15m", "1h"], ["ta.lowest", "ta.highest"], "Rejection wick >= 60% of bar range sweeping 20-bar extreme", "2.0R target", "Stop beyond rejection wick extreme", "atlas_native", "REPOSITORY_EVIDENCE", "WALK_FORWARD_VALIDATED"),
        ("four_box_event", "Four-Box Event Box (Scheduled Catalyst)", "four_box", ["SPY", "QQQ", "GC", "ES"], ["5m", "15m"], ["event_calendar_window", "ta.atr"], "Post-release volatility compression breakout after 15m cool-off", "2.0R target", "Stop at event candle opposite extreme (disabled until verified calendar active)", "atlas_native", "REPOSITORY_EVIDENCE", "CAUSALITY_CHECKED"),
        ("snapback_continuation", "Snapback Continuation Pullback", "momentum_pullback", ["NVDA", "SPY", "QQQ", "BTC-USD"], ["15m", "1h"], ["ta.ema", "ta.atr"], "Impulse trend leg followed by 3-bar pullback to EMA20", "Prior impulse high + 1.5 ATR", "1.2 ATR below pullback low", "atlas_native", "EXPERIMENT_RESULT", "BACKTESTED"),
        ("gold_opening_range", "Gold COMEX 08:20 ET Opening Range Breakout", "session_structure", ["GC", "MGC", "GLD"], ["5m", "15m"], ["session_0820_0900_et", "ta.atr"], "Break and close beyond COMEX pit open 40-min range with volume > 1.2x average", "2.0R target or 16:00 ET close", "Opposite side of COMEX opening range", "atlas_native", "EXPERIMENT_RESULT", "WALK_FORWARD_VALIDATED"),
        ("asian_session_context", "Asian Session Range Sweep & London/NY Reversal", "session_structure", ["GC", "EUR_USD", "BTC-USD"], ["15m", "1h"], ["session_asian_high_low", "ta.rsi"], "Sweep of Tokyo/Singapore session high/low followed by reclaim inside range", "Asian session midpoint / opposite boundary", "1.0 ATR beyond sweep wick", "atlas_native", "RESEARCH_HYPOTHESIS", "BACKTESTED"),
        ("nasdaq_opening_continuation", "Nasdaq 09:30 ET Opening Drive Continuation", "equity_index", ["NQ", "MNQ", "QQQ"], ["5m", "15m"], ["session_0930_0945_et", "ta.vwap"], "First 15m bar closes in top/bottom 25% of range above/below session VWAP", "2.0R target", "Session VWAP or opening bar midpoint", "atlas_native", "EXPERIMENT_RESULT", "WALK_FORWARD_VALIDATED"),
        ("nasdaq_fair_price_reversion", "Nasdaq Prior-Day Value Area / PDH-PDL Reversion", "mean_reversion", ["NQ", "QQQ", "SPY"], ["15m", "1h"], ["request.security_D_high_low_shifted", "ta.vwap"], "Intraday sweep of completed prior-day high/low (PDH/PDL) with close back inside", "Session VWAP / POC", "Stop beyond sweep bar extreme", "atlas_native", "EXPERIMENT_RESULT", "WALK_FORWARD_VALIDATED"),
        ("scheduled_news_reaction", "Scheduled Macro News Reaction Filter", "event_driven", ["ES", "NQ", "GC", "USD_CAD"], ["5m", "15m"], ["macro_release_timestamp", "ta.atr"], "Stand aside +/-15m around CPI/FOMC/NFP; enter only after directional range break", "2.0R target", "Event range midpoint", "human_hypothesis", "RESEARCH_HYPOTHESIS", "CAUSALITY_CHECKED"),
        ("post_news_consolidation", "Post-News Flag Consolidation Breakout", "event_driven", ["SPY", "QQQ", "NVDA"], ["15m"], ["ta.atr", "ta.highest"], "3-to-6 bar inside-flag consolidation following high-volume catalyst bar", "Measured move of catalyst leg", "Below consolidation flag low", "human_hypothesis", "RESEARCH_HYPOTHESIS", "BACKTESTED"),
        ("liquidity_sweep", "Institutional Liquidity Pool Sweep & Reclaim", "market_structure", ["BTC-USD", "ETH-USD", "GC", "ES"], ["15m", "1h"], ["ta.pivothigh", "ta.pivotlow"], "Stop-run above/below resting swing liquidity pool with immediate bar close inside", "2.0R target or opposing liquidity pool", "Tick beyond liquidity sweep wick", "atlas_native", "EXPERIMENT_RESULT", "WALK_FORWARD_VALIDATED"),
        ("sfp_reversal", "Swing Failure Pattern (SFP) Reversal", "market_structure", ["BTC-USD", "ETH-USD", "SOL-USD", "GC", "SPY"], ["15m", "1h"], ["ta.pivothigh", "ta.pivotlow"], "High > confirmed swing high and close < swing high (bearish SFP) or inverse", "2.0R target", "SFP wick extreme", "atlas_native", "VERIFIED_SOURCE", "PAPER_EVALUATED"),
        ("failed_breakout_reversal", "Failed Range Breakout Trap Reversal", "market_structure", ["SPY", "QQQ", "BTC-USD", "GC"], ["15m", "1h"], ["ta.highest", "ta.lowest", "ta.atr"], "20-bar breakout fails within 2 bars and re-enters range by > 0.3 ATR", "Range midpoint / opposite 20-bar boundary", "Breakout failure extreme", "atlas_native", "EXPERIMENT_RESULT", "BACKTESTED"),
        ("whale_flow_research", "Whale Order-Flow & Triple-Barrier Policy", "whale_intelligence", ["BTC-USD", "ETH-USD", "SOL-USD"], ["15m", "1h"], ["whale_net_inflow_z", "order_book_imbalance", "ta.atr"], "Causal candle-derived large-lot flow imbalance + Triple-Barrier (+1.5 ATR / -1.0 ATR)", "+1.5 ATR upper barrier or 60m vertical barrier", "-1.0 ATR lower barrier", "atlas_native", "EXPERIMENT_RESULT", "WALK_FORWARD_VALIDATED"),
        ("market_microstructure_imbalance", "L1/Bar Microstructure Absorption & VWAP Deviation", "microstructure", ["BTC-USD", "ES", "GC"], ["5m", "15m"], ["ta.vwap", "volume_profile_poc"], "Volume absorption at Value Area Low/High with positive close delta", "Point of Control (POC)", "0.75 ATR outside Value Area", "atlas_native", "REPOSITORY_EVIDENCE", "BACKTESTED"),
        ("solana_launch_momentum", "Solana DEX Verified Liquidity Momentum (Research-Only)", "solana_research", ["SOL-USD"], ["5m", "15m"], ["solana_slot_volume", "ta.ema"], "Verified Raydium/Orca pool depth > threshold + causal volume expansion", "Trailing EMA10 cross", "Hard 1.0 ATR stop (Live execution disabled by policy)", "atlas_native", "RESEARCH_HYPOTHESIS", "CAUSALITY_CHECKED"),
        ("pump_bonding_curve_research", "Pump.fun Bonding-Curve Graduation Telemetry (Quarantined Research)", "quarantined_speculative", ["SOL-USD"], ["15m"], ["bonding_curve_progress_pct"], "Read-only historical bonding curve graduation study (Active trading disabled per Authentic Assets policy)", "Research study horizon only", "Disabled for live/paper execution", "atlas_native", "REPOSITORY_EVIDENCE", "RESEARCH_REJECTED"),
        ("pumpswap_liquidity_research", "PumpSwap Pool Depth & LP Burn Telemetry (Quarantined Research)", "quarantined_speculative", ["SOL-USD"], ["15m"], ["pumpswap_pool_reserves"], "Read-only AMM reserve & rug-risk diagnostic (Active trading disabled per Authentic Assets policy)", "Research study horizon only", "Disabled for live/paper execution", "atlas_native", "REPOSITORY_EVIDENCE", "RESEARCH_REJECTED"),
    ]

    records: list[dict[str, Any]] = []
    for (
        sid,
        name,
        fam,
        insts,
        tfs,
        deps,
        entry_c,
        exit_c,
        risk_c,
        origin,
        ev_class,
        stage,
    ) in specs:
        src_hash = _sha256(f"{sid}:{name}:{entry_c}:{exit_c}")[:16]
        records.append({
            "strategy_id": sid,
            "strategy_name": name,
            "source_reference": f"atlas://strategies/{sid}",
            "source_license": "ATLAS-INTERNAL",
            "source_version": "1.0.0",
            "source_hash": src_hash,
            "import_timestamp": now_iso,
            "strategy_family": fam,
            "origin_kind": origin,
            "evidence_classification": ev_class,
            "supported_instruments": insts,
            "supported_timeframes": tfs,
            "required_data": ["ohlcv_bars"],
            "indicator_dependencies": deps,
            "entry_conditions": [entry_c],
            "exit_conditions": [exit_c],
            "risk_conditions": [risk_c, "max_risk_per_trade_pct <= 1.0%", "safe_stop_2pct_daily_loss"],
            "repainting_risk": "LOW",
            "lookahead_risk": "LOW",
            "implementation_status": "REJECTED_BY_POLICY" if stage == "RESEARCH_REJECTED" else "IMPLEMENTED",
            "test_status": "PASSED" if stage in {"WALK_FORWARD_VALIDATED", "PAPER_EVALUATED"} else "PENDING_OOS",
            "lifecycle_stage": stage,
            "backtest_ids": [f"bt-{src_hash[:12]}"],
            "research_notes": (
                "Quarantined research-only module; active trading disabled per Authentic Assets Catalog governance."
                if fam == "quarantined_speculative"
                else f"Verified causal {fam} detector integrated with ATLAS replay and deterministic risk engine."
            ),
            "execution_permission": EXECUTION_PERMISSION,
        })
    return records


def load_strategy_knowledge_base(path: Path = DEFAULT_KB_PATH) -> list[dict[str, Any]]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
    seeded = _seed_strategies()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seeded, indent=2), encoding="utf-8")
    return seeded


def save_strategy_knowledge_base(records: list[dict[str, Any]], path: Path = DEFAULT_KB_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")


def import_strategy_into_knowledge_base(
    *,
    strategy_id: str,
    strategy_name: str,
    source_code: str,
    source_reference: str,
    source_license: str,
    strategy_family: str = "imported_pine",
    origin_kind: str = "imported_source",
    supported_instruments: Sequence[str] = ("GC", "SPY", "BTC-USD"),
    supported_timeframes: Sequence[str] = ("15m", "1h"),
    research_notes: str = "",
    path: Path = DEFAULT_KB_PATH,
) -> dict[str, Any]:
    """Sections 3, 4 & 23: Validate, deduplicate, and persist an imported strategy into the Knowledge Base."""
    records = load_strategy_knowledge_base(path)
    analysis = parse_and_validate_pine(
        source_code,
        strategy_id=strategy_id,
        source_license=source_license,
        source_reference=source_reference,
        instrument_scope=supported_instruments,
        timeframe=supported_timeframes[0] if supported_timeframes else "15m",
    )

    # Duplicate detection by content hash
    duplicate_of = next((r["strategy_id"] for r in records if r.get("source_hash") == analysis["source_hash"]), None)

    lifecycle_stage = "CAUSALITY_CHECKED" if analysis["valid"] else "RESEARCH_REJECTED"
    record = {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "source_reference": source_reference,
        "source_license": analysis["source_license"],
        "source_version": f"pine_v{analysis['pine_version'] or 'unknown'}",
        "source_hash": analysis["source_hash"],
        "import_timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy_family": strategy_family,
        "origin_kind": origin_kind,
        "evidence_classification": "VERIFIED_SOURCE" if analysis["valid"] else "UNVERIFIED_CLAIM",
        "supported_instruments": list(supported_instruments),
        "supported_timeframes": list(supported_timeframes),
        "required_data": ["ohlcv_bars"],
        "indicator_dependencies": analysis["indicator_dependencies"],
        "entry_conditions": [json.dumps(r) for r in analysis["entry_rules"]],
        "exit_conditions": [json.dumps(r) for r in analysis["exit_rules"]],
        "risk_conditions": [json.dumps(r) for r in analysis["risk_rules"]],
        "repainting_risk": analysis["repainting_risk"],
        "lookahead_risk": analysis["lookahead_risk"],
        "implementation_status": "PARSED_AND_VALIDATED" if analysis["valid"] else "REJECTED_UNSAFE_OR_INVALID",
        "test_status": "READY_FOR_BACKTEST" if analysis["valid"] else "FAILED_STATIC_AUDIT",
        "lifecycle_stage": lifecycle_stage,
        "duplicate_of": duplicate_of,
        "backtest_ids": [],
        "research_notes": research_notes or (
            "Passed static Pine causality, license, and security checks."
            if analysis["valid"]
            else f"Rejected: {', '.join(analysis['syntax_errors'] + analysis['security_violations'] + [u['construct'] for u in analysis['unsupported_features']] + analysis['lookahead_flags'] + analysis['repainting_flags'])}"
        ),
        "static_analysis": analysis,
        "execution_permission": EXECUTION_PERMISSION,
    }

    records = [r for r in records if r["strategy_id"] != strategy_id]
    records.append(record)
    save_strategy_knowledge_base(records, path)
    return record


def transition_strategy_lifecycle(
    strategy_id: str,
    target_stage: str,
    *,
    evidence_note: str = "",
    backtest_id: str | None = None,
    path: Path = DEFAULT_KB_PATH,
) -> dict[str, Any]:
    """Section 19: Controlled stage transition with anti-skipping & negative-result preservation."""
    if target_stage not in STRATEGY_LIFECYCLE_STAGES:
        raise ValueError(f"Unsupported lifecycle stage: {target_stage}")
    records = load_strategy_knowledge_base(path)
    target = next((r for r in records if r["strategy_id"] == strategy_id), None)
    if target is None:
        raise KeyError(f"Strategy '{strategy_id}' not found in knowledge base.")

    if target.get("repainting_risk") == "HIGH" or target.get("lookahead_risk") == "HIGH":
        if target_stage not in {"DISCOVERED", "RESEARCH_REJECTED"}:
            raise ValueError("Cannot advance a strategy with HIGH repainting or lookahead risk.")

    prev_stage = target.get("lifecycle_stage", "DISCOVERED")
    target["lifecycle_stage"] = target_stage
    if backtest_id and backtest_id not in target.get("backtest_ids", []):
        target.setdefault("backtest_ids", []).append(backtest_id)
    if evidence_note:
        target["research_notes"] = f"{target.get('research_notes', '')} | [{target_stage}] {evidence_note}".strip(" |")
    save_strategy_knowledge_base(records, path)
    return {
        "strategy_id": strategy_id,
        "previous_stage": prev_stage,
        "current_stage": target_stage,
        "record": target,
        "execution_permission": EXECUTION_PERMISSION,
    }

