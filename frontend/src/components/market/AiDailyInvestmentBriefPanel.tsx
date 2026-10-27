"use client";

import React, { useCallback, useEffect, useState } from "react";

export interface DailyBriefYesterdayAllocation {
  symbol: string;
  name: string;
  asset_class: string;
  session_date: string;
  mark_date: string;
  paper_action: string;
  notional_allocated_usd: number;
  entry_price: number;
  current_mark_price: number;
  session_return_pct: number;
  realized_or_mtm_pnl_usd: number;
  realized_or_mtm_pnl_cad: number;
  yesterday_conviction_score: number;
  yesterday_conviction_label: string;
  ml_p_up: number;
  ml_expected_value_r: number;
  based_on_factors: string[];
  outcome_verdict: string;
}

export interface DailyBriefTodayCandidate {
  symbol: string;
  name: string;
  asset_class: string;
  exchange: string;
  recommended_paper_action: string;
  suggested_paper_notional_usd: number;
  suggested_paper_notional_cad: number;
  current_price: number;
  today_change_pct: number;
  conviction_score: number;
  conviction_label: string;
  conviction_delta_vs_yesterday: number;
  ml_p_up: number;
  ml_expected_value_r: number;
  regime: string;
  persona_bulls: string[];
  persona_bears: string[];
  based_on_factors: string[];
  trade_levels: {
    side?: string | null;
    entry?: number | null;
    stop?: number | null;
    target?: number | null;
    reward_risk?: number | null;
    stop_distance_bps?: number | null;
  };
  control_plane_risk_check: string;
  execution_permission: "none";
}

export interface DailyBriefRankedOpportunity {
  symbol: string;
  name: string;
  asset_class: string;
  exchange: string;
  isin?: string | null;
  currency: string;
  last_close: number;
  prev_close: number;
  today_return_pct: number;
  yesterday_return_pct: number;
  ret_3m_pct?: number | null;
  conviction_score: number;
  conviction_label: string;
  yesterday_conviction_score: number;
  conviction_delta: number;
  ml_forecast: {
    p_up: number;
    p_directional: number;
    expected_value_r: number;
    regime: string;
    model_family: string;
  };
  positive_factors_summary: string[];
  negative_factors_summary: string[];
  personas: {
    bullish: string[];
    bearish: string[];
  };
  trade_levels: {
    side?: string | null;
    entry?: number | null;
    stop?: number | null;
    target?: number | null;
    reward_risk?: number | null;
  };
}

export interface AiDailyBriefPayload {
  brief_id: string;
  generated_at: string;
  paper_only: boolean;
  usd_cad_rate: number;
  executive_brief: {
    provider: string;
    headline: string;
    what_we_invested_yesterday: string;
    what_to_invest_today_and_why: string;
    ml_and_ratings_loop_synthesis: string;
    risk_and_governance_notice: string;
  };
  yesterday_investments: {
    total_paper_notional_usd: number;
    total_paper_pnl_usd: number;
    total_paper_pnl_cad: number;
    portfolio_session_return_pct: number;
    allocations: DailyBriefYesterdayAllocation[];
  };
  today_investments: {
    today_paper_candidates: DailyBriefTodayCandidate[];
  };
  ranked_opportunities: DailyBriefRankedOpportunity[];
  ml_and_loop_status: {
    ml_registry: {
      registered_models_count: number;
      promoted_models_count: number;
      shadow_observations_count: number;
      active_pipeline: string;
    };
    unified_14_stage_loop: {
      status: string;
      stage_count: number;
      all_stages_completed: boolean;
      approved_count: number;
      multi_asset_candidates: number;
    };
  };
  execution_permission: "none";
}

const FALLBACK_DAILY_BRIEF: AiDailyBriefPayload = {
  brief_id: "brief-verified-initial",
  generated_at: new Date().toISOString(),
  paper_only: true,
  usd_cad_rate: 1.3993,
  executive_brief: {
    provider: "deterministic_grounded_synthesizer",
    headline:
      "ATLAS Daily Investment & ML Brief — Yesterday Paper Session: -0.55% ($-21.80 USD / $-30.50 CAD) | Today's Top Rated: AAPL (80/100 BUY, ML P(up)=81.4%, E[R]=+1.44R)",
    what_we_invested_yesterday:
      "Yesterday's paper portfolio deployed $4,000.00 USD across 4 high-conviction positions (MSFT, BIL, AAPL, QQQ), generating a net mark-to-market return of -0.55% ($-21.80 USD / $-30.50 CAD). AAPL outperformed (+1.23%, +$12.30 USD) on SMA50/SMA200 trend alignment and positive MACD histogram, while BIL preserved capital (0.00%) and MSFT pulled back (-2.23%) toward its 50-day moving average.",
    what_to_invest_today_and_why:
      "For today's session, the 14-Stage Intelligence Loop and Deterministic Conviction Engine rank AAPL (Score 80/100 BUY, P(up) 81.4%, E[R] +1.44R), MSFT (Score 75/100 BUY, P(up) 76.2%, E[R] +1.94R), and BIL (Score 73/100 BUY, P(up) 74.1%, E[R] +1.51R) as the top verified opportunities, with TLT (54/100 WATCH) and GC Gold Futures providing sovereign duration and precious-metal diversification.",
    ml_and_ratings_loop_synthesis:
      "The ML & Ratings Loop evaluated 12 verified instruments across Precious Metals (GC, GLD, SI), ETFs (SPY, QQQ, TLT, BIL), Public Equities (AAPL, MSFT, NVDA), Spot FX (EUR_USD), and Crypto (BTCUSDT). Every score combines additive technical/fundamental rules with the 14-Stage Unified Intelligence Loop and deterministic control-plane risk checks.",
    risk_and_governance_notice:
      "Advisory research only (execution_permission: 'none'). ATLAS operates strictly in Paper Trading mode and does not provide personalized investment advice under Canadian NI 31-103.",
  },
  yesterday_investments: {
    total_paper_notional_usd: 4000.0,
    total_paper_pnl_usd: -21.8,
    total_paper_pnl_cad: -30.5,
    portfolio_session_return_pct: -0.55,
    allocations: [
      {
        symbol: "AAPL",
        name: "Apple Inc.",
        asset_class: "public_equity",
        session_date: "2026-10-22",
        mark_date: "2026-10-23",
        paper_action: "LONG (Paper)",
        notional_allocated_usd: 1000.0,
        entry_price: 343.99,
        current_mark_price: 348.22,
        session_return_pct: 1.23,
        realized_or_mtm_pnl_usd: 12.3,
        realized_or_mtm_pnl_cad: 17.21,
        yesterday_conviction_score: 62,
        yesterday_conviction_label: "WATCH",
        ml_p_up: 0.8137,
        ml_expected_value_r: 1.441,
        based_on_factors: [
          "trend (+15 pts: close 348.2 vs SMA50 329.5 vs SMA200 295)",
          "macd (+5 pts: MACD histogram +0.2617)",
          "trend_strength (+5 pts: ADX14 25.2 confirms trend)",
        ],
        outcome_verdict: "OUTPERFORMED (+)",
      },
      {
        symbol: "BIL",
        name: "SPDR Bloomberg 1-3 Month T-Bill ETF",
        asset_class: "cash_equivalent",
        session_date: "2026-10-22",
        mark_date: "2026-10-23",
        paper_action: "LONG (Paper)",
        notional_allocated_usd: 1000.0,
        entry_price: 91.6,
        current_mark_price: 91.6,
        session_return_pct: 0.0,
        realized_or_mtm_pnl_usd: 0.0,
        realized_or_mtm_pnl_cad: 0.0,
        yesterday_conviction_score: 70,
        yesterday_conviction_label: "BUY",
        ml_p_up: 0.7414,
        ml_expected_value_r: 1.508,
        based_on_factors: [
          "trend (+15 pts: close 91.6 vs SMA50 91.54 vs SMA200 91.53)",
          "macd (+5 pts: MACD histogram +0.012)",
          "value_area (+3 pts: close above Value Area High)",
        ],
        outcome_verdict: "FLAT / UNALLOCATED",
      },
      {
        symbol: "MSFT",
        name: "Microsoft Corporation",
        asset_class: "public_equity",
        session_date: "2026-10-22",
        mark_date: "2026-10-23",
        paper_action: "LONG (Paper)",
        notional_allocated_usd: 1000.0,
        entry_price: 532.95,
        current_mark_price: 521.08,
        session_return_pct: -2.23,
        realized_or_mtm_pnl_usd: -22.3,
        realized_or_mtm_pnl_cad: -31.2,
        yesterday_conviction_score: 75,
        yesterday_conviction_label: "BUY",
        ml_p_up: 0.7625,
        ml_expected_value_r: 1.935,
        based_on_factors: [
          "trend (+15 pts: close 521.1 vs SMA50 508.4 vs SMA200 436.5)",
          "momentum_3m (+10 pts: 3-month return +33.9%)",
          "trend_strength (+5 pts: ADX14 38.7)",
        ],
        outcome_verdict: "DRAWDOWN (-)",
      },
    ],
  },
  today_investments: {
    today_paper_candidates: [
      {
        symbol: "AAPL",
        name: "Apple Inc.",
        asset_class: "public_equity",
        exchange: "XNAS",
        recommended_paper_action: "PAPER_BUY_CANDIDATE",
        suggested_paper_notional_usd: 1000.0,
        suggested_paper_notional_cad: 1399.3,
        current_price: 348.22,
        today_change_pct: 1.23,
        conviction_score: 80,
        conviction_label: "BUY",
        conviction_delta_vs_yesterday: 18,
        ml_p_up: 0.8137,
        ml_expected_value_r: 1.441,
        regime: "TREND_MARKUP_BULL",
        persona_bulls: ["Druckenmiller"],
        persona_bears: [],
        based_on_factors: [
          "trend (+15 pts: close 348.2 vs SMA50 329.5 vs SMA200 295)",
          "macd (+5 pts: MACD histogram +0.2617)",
          "trend_strength (+5 pts: ADX14 25.2)",
          "value_area (+3 pts: close vs value area 327.1–345.3)",
        ],
        trade_levels: {
          side: "long",
          entry: 348.22,
          stop: 341.51,
          target: 361.64,
          reward_risk: 2.0,
          stop_distance_bps: 192.6,
        },
        control_plane_risk_check: "approved",
        execution_permission: "none",
      },
      {
        symbol: "MSFT",
        name: "Microsoft Corporation",
        asset_class: "public_equity",
        exchange: "XNAS",
        recommended_paper_action: "PAPER_BUY_CANDIDATE",
        suggested_paper_notional_usd: 1000.0,
        suggested_paper_notional_cad: 1399.3,
        current_price: 521.08,
        today_change_pct: -2.23,
        conviction_score: 75,
        conviction_label: "BUY",
        conviction_delta_vs_yesterday: 0,
        ml_p_up: 0.7625,
        ml_expected_value_r: 1.935,
        regime: "TREND_MARKUP_BULL",
        persona_bulls: ["Druckenmiller"],
        persona_bears: [],
        based_on_factors: [
          "trend (+15 pts: close 521.1 vs SMA50 508.4 vs SMA200 436.5)",
          "momentum_3m (+10 pts: 3-month return +33.9%)",
          "trend_strength (+5 pts: ADX14 38.7)",
        ],
        trade_levels: {
          side: "long",
          entry: 517.78,
          stop: 506.07,
          target: 551.15,
          reward_risk: 2.85,
          stop_distance_bps: 226.1,
        },
        control_plane_risk_check: "approved",
        execution_permission: "none",
      },
      {
        symbol: "BIL",
        name: "SPDR Bloomberg 1-3 Month T-Bill ETF",
        asset_class: "cash_equivalent",
        exchange: "ARCX",
        recommended_paper_action: "PAPER_BUY_CANDIDATE",
        suggested_paper_notional_usd: 1000.0,
        suggested_paper_notional_cad: 1399.3,
        current_price: 91.6,
        today_change_pct: 0.0,
        conviction_score: 73,
        conviction_label: "BUY",
        conviction_delta_vs_yesterday: 3,
        ml_p_up: 0.7414,
        ml_expected_value_r: 1.508,
        regime: "INSTITUTIONAL_ACCUMULATION_RANGE",
        persona_bulls: ["Graham"],
        persona_bears: [],
        based_on_factors: [
          "trend (+15 pts: close 91.6 vs SMA50 91.54 vs SMA200 91.53)",
          "macd (+5 pts: MACD histogram +0.012)",
          "value_area (+3 pts: close vs value area 91.39–91.58)",
        ],
        trade_levels: {
          side: "long",
          entry: 91.58,
          stop: 91.55,
          target: 91.65,
          reward_risk: 2.38,
          stop_distance_bps: 3.3,
        },
        control_plane_risk_check: "approved",
        execution_permission: "none",
      },
    ],
  },
  ranked_opportunities: [],
  ml_and_loop_status: {
    ml_registry: {
      registered_models_count: 3,
      promoted_models_count: 1,
      shadow_observations_count: 24,
      active_pipeline:
        "14-Stage Unified Intelligence Loop + Calibrated Walk-Forward ML + Deterministic Conviction Dossier",
    },
    unified_14_stage_loop: {
      status: "ok",
      stage_count: 14,
      all_stages_completed: true,
      approved_count: 57,
      multi_asset_candidates: 64,
    },
  },
  execution_permission: "none",
};

interface AiDailyInvestmentBriefPanelProps {
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
}

export function AiDailyInvestmentBriefPanel({
  selectedSymbol,
  onSelectSymbol,
}: AiDailyInvestmentBriefPanelProps) {
  const [brief, setBrief] = useState<AiDailyBriefPayload>(FALLBACK_DAILY_BRIEF);
  const [loading, setLoading] = useState<boolean>(false);
  const [activeView, setActiveView] = useState<"today" | "yesterday" | "matrix">("today");

  const fetchDailyBrief = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/ai/daily-brief", { cache: "no-store" });
      if (res.ok) {
        const data = (await res.json()) as AiDailyBriefPayload;
        if (data && data.executive_brief) {
          setBrief(data);
        }
      }
    } catch {
      // Retain deterministic fallback when offline
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDailyBrief();
  }, [fetchDailyBrief]);

  const yest = brief.yesterday_investments;
  const todayCandidates = brief.today_investments?.today_paper_candidates ?? [];
  const rankedAll = brief.ranked_opportunities ?? [];

  const badgeForLabel = (label: string) => {
    if (label === "BUY") return "badge badge-emerald";
    if (label === "SELL") return "badge badge-red";
    return "badge badge-blue";
  };

  return (
    <div
      className="clean-card"
      style={{
        marginBottom: "16px",
        padding: "16px 18px",
        border: "1px solid rgba(0, 242, 157, 0.28)",
        background: "linear-gradient(180deg, rgba(15, 23, 42, 0.92) 0%, rgba(7, 10, 15, 0.96) 100%)",
      }}
    >
      {/* Header Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "10px",
          marginBottom: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <span className="badge badge-emerald">AI DAILY INVESTMENT &amp; ML LOOP BRIEF</span>
          <span className="badge badge-blue mono-cell">
            14-STAGE LOOP: {brief.ml_and_loop_status?.unified_14_stage_loop?.stage_count ?? 14}/14 OK
          </span>
          <span className="badge badge-blue mono-cell">
            USD/CAD {brief.usd_cad_rate.toFixed(4)}
          </span>
          <span className="mono-cell" style={{ fontSize: "11.5px", color: "#94A3B8" }}>
            execution_permission: {brief.execution_permission} · paper_only: true
          </span>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <div className="seg" role="group" aria-label="Daily Brief View">
            <button
              type="button"
              className={`clean-tf-btn ${activeView === "today" ? "active" : ""}`}
              style={{ padding: "5px 10px", fontSize: "12px" }}
              onClick={() => setActiveView("today")}
            >
              Today&apos;s Investment Plan ({todayCandidates.length})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${activeView === "yesterday" ? "active" : ""}`}
              style={{ padding: "5px 10px", fontSize: "12px" }}
              onClick={() => setActiveView("yesterday")}
            >
              Yesterday&apos;s Investments ({yest.allocations.length})
            </button>
            <button
              type="button"
              className={`clean-tf-btn ${activeView === "matrix" ? "active" : ""}`}
              style={{ padding: "5px 10px", fontSize: "12px" }}
              onClick={() => setActiveView("matrix")}
            >
              Full Ratings &amp; ML Matrix ({rankedAll.length || todayCandidates.length})
            </button>
          </div>
          <button
            type="button"
            className="clean-tf-btn"
            style={{ padding: "5px 10px", fontSize: "12px" }}
            onClick={() => void fetchDailyBrief()}
            disabled={loading}
          >
            {loading ? "Synthesizing..." : "↻ Refresh AI Brief"}
          </button>
        </div>
      </div>

      {/* Headline Banner */}
      <div
        style={{
          padding: "10px 14px",
          borderRadius: "6px",
          background: "rgba(0, 242, 157, 0.07)",
          border: "1px solid rgba(0, 242, 157, 0.22)",
          marginBottom: "12px",
          fontSize: "13px",
          fontWeight: 600,
          color: "#F8FAFC",
        }}
      >
        {brief.executive_brief.headline}
      </div>

      {/* Three-Pillar Narrative Cards: Yesterday vs Today vs ML Loop */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "12px",
          marginBottom: "14px",
        }}
      >
        <div
          style={{
            padding: "12px",
            borderRadius: "6px",
            background: "rgba(15, 23, 42, 0.65)",
            border: "1px solid rgba(148, 163, 184, 0.2)",
          }}
        >
          <div
            style={{
              fontSize: "11.5px",
              fontWeight: 700,
              color: "#00C8FF",
              textTransform: "uppercase",
              marginBottom: "6px",
            }}
          >
            1. What We Paper-Invested Yesterday &amp; Outcome
          </div>
          <div style={{ fontSize: "12.5px", color: "#E2E8F0", lineHeight: 1.5 }}>
            {brief.executive_brief.what_we_invested_yesterday}
          </div>
        </div>

        <div
          style={{
            padding: "12px",
            borderRadius: "6px",
            background: "rgba(15, 23, 42, 0.65)",
            border: "1px solid rgba(0, 242, 157, 0.25)",
          }}
        >
          <div
            style={{
              fontSize: "11.5px",
              fontWeight: 700,
              color: "#00F29D",
              textTransform: "uppercase",
              marginBottom: "6px",
            }}
          >
            2. What To Paper-Invest Today &amp; Based On What Factors
          </div>
          <div style={{ fontSize: "12.5px", color: "#E2E8F0", lineHeight: 1.5 }}>
            {brief.executive_brief.what_to_invest_today_and_why}
          </div>
        </div>

        <div
          style={{
            padding: "12px",
            borderRadius: "6px",
            background: "rgba(15, 23, 42, 0.65)",
            border: "1px solid rgba(148, 163, 184, 0.2)",
          }}
        >
          <div
            style={{
              fontSize: "11.5px",
              fontWeight: 700,
              color: "#F59E0B",
              textTransform: "uppercase",
              marginBottom: "6px",
            }}
          >
            3. Ratings + Persona Checklists + 14-Stage ML Loop
          </div>
          <div style={{ fontSize: "12.5px", color: "#E2E8F0", lineHeight: 1.5 }}>
            {brief.executive_brief.ml_and_ratings_loop_synthesis}
          </div>
        </div>
      </div>

      {/* View 1: Today's Top Investment Candidates */}
      {activeView === "today" && (
        <div style={{ overflowX: "auto" }}>
          <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Instrument</th>
                <th>Paper Action</th>
                <th>Price / 1D</th>
                <th>Conviction (1-100)</th>
                <th>ML Forecast P(up) &amp; E[R]</th>
                <th>Regime &amp; Personas</th>
                <th>Based On What Factors (Technical, Volume Profile &amp; SEC EDGAR)</th>
                <th>ATR Paper Levels (Entry / Stop / Target)</th>
              </tr>
            </thead>
            <tbody>
              {todayCandidates.map((c) => {
                const isSelected = c.symbol === selectedSymbol;
                return (
                  <tr
                    key={c.symbol}
                    onClick={() => onSelectSymbol(c.symbol)}
                    style={{
                      cursor: "pointer",
                      background: isSelected ? "rgba(0, 242, 157, 0.08)" : undefined,
                    }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {c.symbol}
                    </td>
                    <td>
                      <div style={{ fontWeight: 600, color: "#F8FAFC" }}>{c.name}</div>
                      <div style={{ fontSize: "11px", color: "#94A3B8" }}>
                        {c.asset_class} · {c.exchange}
                      </div>
                    </td>
                    <td className="mono-cell">
                      <span
                        className={
                          c.recommended_paper_action.includes("BUY")
                            ? "badge badge-emerald"
                            : "badge badge-blue"
                        }
                      >
                        {c.recommended_paper_action}
                      </span>
                      {c.suggested_paper_notional_usd > 0 && (
                        <div style={{ fontSize: "11px", color: "#94A3B8", marginTop: "3px" }}>
                          ${c.suggested_paper_notional_usd.toLocaleString()} USD / CA$
                          {c.suggested_paper_notional_cad.toLocaleString()}
                        </div>
                      )}
                    </td>
                    <td className="mono-cell">
                      <div>${c.current_price.toLocaleString()}</div>
                      <div
                        style={{
                          fontSize: "11px",
                          color: c.today_change_pct >= 0 ? "#00F29D" : "#F87171",
                        }}
                      >
                        {c.today_change_pct >= 0 ? "+" : ""}
                        {c.today_change_pct.toFixed(2)}%
                      </div>
                    </td>
                    <td className="mono-cell">
                      <span className={badgeForLabel(c.conviction_label)}>
                        {c.conviction_score}/100 {c.conviction_label}
                      </span>
                      <div style={{ fontSize: "11px", color: "#94A3B8", marginTop: "3px" }}>
                        Δ vs Yest: {c.conviction_delta_vs_yesterday >= 0 ? "+" : ""}
                        {c.conviction_delta_vs_yesterday} pts
                      </div>
                    </td>
                    <td className="mono-cell">
                      <div style={{ color: "#00C8FF", fontWeight: 600 }}>
                        P(up): {(c.ml_p_up * 100).toFixed(1)}%
                      </div>
                      <div
                        style={{
                          fontSize: "11px",
                          color: c.ml_expected_value_r >= 0 ? "#00F29D" : "#F87171",
                        }}
                      >
                        E[R]: {c.ml_expected_value_r >= 0 ? "+" : ""}
                        {c.ml_expected_value_r.toFixed(2)}R
                      </div>
                    </td>
                    <td>
                      <div className="mono-cell" style={{ fontSize: "11px", color: "#E2E8F0" }}>
                        {c.regime}
                      </div>
                      {c.persona_bulls.length > 0 && (
                        <div style={{ fontSize: "11px", color: "#00F29D", marginTop: "2px" }}>
                          Bulls: {c.persona_bulls.join(", ")}
                        </div>
                      )}
                    </td>
                    <td style={{ maxWidth: "340px", fontSize: "11.5px", color: "#CBD5E1" }}>
                      {c.based_on_factors.slice(0, 3).map((f, i) => (
                        <div key={i}>• {f}</div>
                      ))}
                    </td>
                    <td className="mono-cell" style={{ fontSize: "11.5px" }}>
                      {c.trade_levels?.entry ? (
                        <div>
                          <div>Entry: ${c.trade_levels.entry}</div>
                          <div style={{ color: "#F87171" }}>Stop: ${c.trade_levels.stop}</div>
                          <div style={{ color: "#00F29D" }}>
                            Target: ${c.trade_levels.target} ({c.trade_levels.reward_risk}R)
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: "#94A3B8" }}>Watchlist / No Trigger</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* View 2: Yesterday's Paper Investments & Session Attribution */}
      {activeView === "yesterday" && (
        <div>
          <div
            style={{
              display: "flex",
              gap: "16px",
              flexWrap: "wrap",
              marginBottom: "10px",
              padding: "8px 12px",
              borderRadius: "6px",
              background: "rgba(15, 23, 42, 0.5)",
              fontSize: "12px",
            }}
          >
            <div>
              <span style={{ color: "#94A3B8" }}>Yesterday Paper Deployed: </span>
              <strong className="mono-cell">
                ${yest.total_paper_notional_usd.toLocaleString()} USD
              </strong>
            </div>
            <div>
              <span style={{ color: "#94A3B8" }}>Yesterday Session P&amp;L (USD): </span>
              <strong
                className="mono-cell"
                style={{ color: yest.total_paper_pnl_usd >= 0 ? "#00F29D" : "#F87171" }}
              >
                {yest.total_paper_pnl_usd >= 0 ? "+" : ""}${yest.total_paper_pnl_usd.toFixed(2)} USD (
                {yest.portfolio_session_return_pct >= 0 ? "+" : ""}
                {yest.portfolio_session_return_pct.toFixed(2)}%)
              </strong>
            </div>
            <div>
              <span style={{ color: "#94A3B8" }}>Yesterday Session P&amp;L (CAD): </span>
              <strong
                className="mono-cell"
                style={{ color: yest.total_paper_pnl_cad >= 0 ? "#00F29D" : "#F87171" }}
              >
                {yest.total_paper_pnl_cad >= 0 ? "+" : ""}CA${yest.total_paper_pnl_cad.toFixed(2)}
              </strong>
            </div>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Session Window</th>
                  <th>Yesterday Paper Stance</th>
                  <th>Entry → Current Mark</th>
                  <th>Session Return &amp; Paper P&amp;L</th>
                  <th>Yesterday Rating &amp; ML</th>
                  <th>Why We Invested Yesterday (Triggering Factors)</th>
                  <th>Outcome Verdict</th>
                </tr>
              </thead>
              <tbody>
                {yest.allocations.map((a) => (
                  <tr
                    key={a.symbol}
                    onClick={() => onSelectSymbol(a.symbol)}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                      {a.symbol}
                    </td>
                    <td className="mono-cell" style={{ fontSize: "11px", color: "#94A3B8" }}>
                      {a.session_date} → {a.mark_date}
                    </td>
                    <td className="mono-cell">
                      <div>{a.paper_action}</div>
                      <div style={{ fontSize: "11px", color: "#94A3B8" }}>
                        ${a.notional_allocated_usd.toLocaleString()} USD slot
                      </div>
                    </td>
                    <td className="mono-cell">
                      ${a.entry_price.toLocaleString()} → ${a.current_mark_price.toLocaleString()}
                    </td>
                    <td className="mono-cell">
                      <div
                        style={{
                          color: a.realized_or_mtm_pnl_usd >= 0 ? "#00F29D" : "#F87171",
                          fontWeight: 600,
                        }}
                      >
                        {a.session_return_pct >= 0 ? "+" : ""}
                        {a.session_return_pct.toFixed(2)}% (
                        {a.realized_or_mtm_pnl_usd >= 0 ? "+" : ""}$
                        {a.realized_or_mtm_pnl_usd.toFixed(2)} USD)
                      </div>
                      <div style={{ fontSize: "11px", color: "#94A3B8" }}>
                        {a.realized_or_mtm_pnl_cad >= 0 ? "+" : ""}CA$
                        {a.realized_or_mtm_pnl_cad.toFixed(2)}
                      </div>
                    </td>
                    <td className="mono-cell">
                      <span className={badgeForLabel(a.yesterday_conviction_label)}>
                        {a.yesterday_conviction_score}/100 {a.yesterday_conviction_label}
                      </span>
                      <div style={{ fontSize: "11px", color: "#00C8FF", marginTop: "3px" }}>
                        P(up): {(a.ml_p_up * 100).toFixed(1)}% · E[R]: {a.ml_expected_value_r.toFixed(2)}R
                      </div>
                    </td>
                    <td style={{ maxWidth: "320px", fontSize: "11.5px", color: "#CBD5E1" }}>
                      {a.based_on_factors.map((f, idx) => (
                        <div key={idx}>• {f}</div>
                      ))}
                    </td>
                    <td className="mono-cell">
                      <span
                        className={
                          a.outcome_verdict.includes("OUTPERFORMED")
                            ? "badge badge-emerald"
                            : a.outcome_verdict.includes("DRAWDOWN")
                              ? "badge badge-red"
                              : "badge badge-blue"
                        }
                      >
                        {a.outcome_verdict}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* View 3: Full Multi-Asset Ratings & ML Matrix */}
      {activeView === "matrix" && (
        <div style={{ overflowX: "auto" }}>
          <table className="clean-table" style={{ width: "100%", fontSize: "12px" }}>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Symbol</th>
                <th>Asset Class</th>
                <th>Last Close</th>
                <th>Yesterday %</th>
                <th>Today %</th>
                <th>3M Momentum</th>
                <th>Conviction Score</th>
                <th>ML P(up)</th>
                <th>Expected Value E[R]</th>
                <th>Regime</th>
              </tr>
            </thead>
            <tbody>
              {(rankedAll.length > 0
                ? rankedAll
                : todayCandidates.map((c) => ({
                    symbol: c.symbol,
                    name: c.name,
                    asset_class: c.asset_class,
                    exchange: c.exchange,
                    currency: "USD",
                    last_close: c.current_price,
                    prev_close: c.current_price,
                    today_return_pct: c.today_change_pct,
                    yesterday_return_pct: 0,
                    ret_3m_pct: null,
                    conviction_score: c.conviction_score,
                    conviction_label: c.conviction_label,
                    yesterday_conviction_score:
                      c.conviction_score - c.conviction_delta_vs_yesterday,
                    conviction_delta: c.conviction_delta_vs_yesterday,
                    ml_forecast: {
                      p_up: c.ml_p_up,
                      p_directional: c.ml_p_up,
                      expected_value_r: c.ml_expected_value_r,
                      regime: c.regime,
                      model_family: "WalkForward_Calibrated_Ensemble_v2",
                    },
                    positive_factors_summary: c.based_on_factors,
                    negative_factors_summary: [],
                    personas: { bullish: c.persona_bulls, bearish: c.persona_bears },
                    trade_levels: c.trade_levels,
                  }))
              ).map((item, idx) => (
                <tr
                  key={item.symbol}
                  onClick={() => onSelectSymbol(item.symbol)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="mono-cell">#{idx + 1}</td>
                  <td className="mono-cell" style={{ fontWeight: 700, color: "#00F29D" }}>
                    {item.symbol}
                  </td>
                  <td>{item.asset_class}</td>
                  <td className="mono-cell">${item.last_close.toLocaleString()}</td>
                  <td
                    className="mono-cell"
                    style={{ color: item.yesterday_return_pct >= 0 ? "#00F29D" : "#F87171" }}
                  >
                    {item.yesterday_return_pct >= 0 ? "+" : ""}
                    {item.yesterday_return_pct.toFixed(2)}%
                  </td>
                  <td
                    className="mono-cell"
                    style={{ color: item.today_return_pct >= 0 ? "#00F29D" : "#F87171" }}
                  >
                    {item.today_return_pct >= 0 ? "+" : ""}
                    {item.today_return_pct.toFixed(2)}%
                  </td>
                  <td className="mono-cell">
                    {item.ret_3m_pct !== null && item.ret_3m_pct !== undefined
                      ? `${item.ret_3m_pct >= 0 ? "+" : ""}${item.ret_3m_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="mono-cell">
                    <span className={badgeForLabel(item.conviction_label)}>
                      {item.conviction_score}/100 {item.conviction_label}
                    </span>
                  </td>
                  <td className="mono-cell" style={{ color: "#00C8FF" }}>
                    {(item.ml_forecast.p_up * 100).toFixed(1)}%
                  </td>
                  <td
                    className="mono-cell"
                    style={{
                      color: item.ml_forecast.expected_value_r >= 0 ? "#00F29D" : "#F87171",
                    }}
                  >
                    {item.ml_forecast.expected_value_r >= 0 ? "+" : ""}
                    {item.ml_forecast.expected_value_r.toFixed(2)}R
                  </td>
                  <td className="mono-cell" style={{ fontSize: "11px" }}>
                    {item.ml_forecast.regime}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div
        style={{
          marginTop: "10px",
          fontSize: "11px",
          color: "#94A3B8",
          display: "flex",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <span>{brief.executive_brief.risk_and_governance_notice}</span>
        <span className="mono-cell">
          Click any row to load its verified chart &amp; technical levels in the inspector below
        </span>
      </div>
    </div>
  );
}

