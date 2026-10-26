"use client";

import React, { useCallback, useEffect, useState } from "react";

type PumpWorkbenchData = {
  as_of_ts: number;
  data_mode: string;
  rpc_configured: boolean;
  freshness: {
    fresh: boolean;
    age_seconds: number | null;
    last_slot: number;
    status: string;
    reorg_rollbacks?: number;
    missed_slot_backfills?: number;
    reconnect_count?: number;
  };
  program_ids: Record<string, string>;
  tokens: Array<{
    token: {
      mint: string;
      symbol: string;
      name: string;
      creator_wallet: string;
      quote_symbol: string;
      token_program: string;
      lifecycle_state: string;
      graduation_state: string;
      active_venue: string;
      price_quote: number;
      market_cap_quote: number;
      volume_24h_quote: number;
      trade_count_24h: number;
      unique_buyers_24h: number;
      liquidity_quote: number;
      curve_progress_pct: number;
      creator_holding_pct: number;
      top1_holder_pct: number;
      top10_holder_pct: number;
      data_provenance: string;
      last_slot: number;
      tradable: boolean;
      transitions: Array<{
        from_state: string;
        to_state: string;
        slot: number;
        reason: string;
        venue_before: string;
        venue_after: string;
      }>;
    };
    bonding_curve: null | {
      bonding_curve_address: string;
      virtual_token_reserves: number;
      virtual_quote_reserves: number;
      effective_virtual_quote_reserves: number;
      signed_virtual_quote_reserves_offset: number;
      real_token_reserves: number;
      real_quote_reserves: number;
      unswept_protocol_fees: number;
      unswept_creator_fees: number;
      progress_pct: number;
      complete: boolean;
    };
    pumpswap_pool: null | {
      pool_address: string;
      base_vault_amount: number;
      quote_vault_amount: number;
      virtual_quote_reserves: number;
      effective_quote_reserves: number;
      liquidity_quote: number;
      lp_burned: boolean;
    };
    wallet_intelligence: {
      verified_on_chain_facts: Record<string, unknown>;
      heuristic_indicators: Record<string, unknown>;
      whale_activity: Record<string, number>;
      disclaimer: string;
    };
    liquidity_profile: {
      active_venue: string;
      effective_liquidity_sol: number;
      buy_price_impact_bps: number;
      sell_price_impact_bps: number;
      round_trip_cost_bps: number;
      solana_fee_sol: number;
      sell_simulation_passed: boolean;
      max_safe_order_sol: number;
    };
    token_safety: {
      safety_status: string;
      safe_guaranteed: boolean;
      verified_on_chain_facts: Record<string, unknown>;
      heuristic_risk_scores: Record<string, number>;
      hard_reject_reasons: string[];
      caution_flags: string[];
      safety_disclaimer: string;
      cluster_disclaimer: string;
    };
    strategy_candidates: Array<{
      candidate_id: string;
      strategy: string;
      direction: string;
      actionable_research_entry: boolean;
      signal_strength: number;
      reward_risk_ratio: number;
      rationale: string[];
      risk_veto: boolean;
    }>;
    ml_forecast: {
      model_id: string;
      calibrated: boolean;
      abstained: boolean;
      abstain_reasons: string[];
      prob_positive_return: number;
      prob_target_before_stop: number;
      prob_severe_drawdown: number;
      expected_adverse_excursion_bps: number;
      expected_favorable_excursion_bps: number;
      liquidity_deterioration_prob: number;
      price_impact_risk_bps: number;
      migration_completion_prob: number;
      model_uncertainty: number;
    };
  }>;
  ev_leaderboard: Array<{
    global_rank: number;
    candidate: {
      mint: string;
      symbol: string;
      strategy: string;
      direction: string;
      venue: string;
    };
    gross_expected_value_bps: number;
    round_trip_cost_bps: number;
    net_expected_value_bps: number;
    net_expected_value_r: number;
    recommended_research_action: string;
  }>;
  portfolio: {
    cash_sol: number;
    equity_sol: number;
    total_cost_exposure_sol: number;
    realizable_positions_value_sol: number;
    realized_pnl_sol: number;
    unrealized_pnl_sol: number;
    total_pnl_sol: number;
    consecutive_losses: number;
    positions: Array<{
      mint: string;
      symbol: string;
      tokens_whole: number;
      cost_basis_sol: number;
      realizable_exit_value_sol: number;
      unrealized_pnl_sol: number;
      last_venue: string;
    }>;
  };
  risk_limits: Record<string, number | boolean>;
  wallet_security: {
    wallet_pubkey: string;
    live_signing_authorized: boolean;
    private_key_exposed_to_frontend: boolean;
    llm_signing_access: string;
    max_sol_per_tx: number;
    max_daily_sol_spend: number;
    daily_sol_spent: number;
    remaining_daily_sol_budget: number;
  };
  orders: Array<{
    client_order_id: string;
    mint: string;
    side: string;
    venue: string;
    instruction: string;
    status: string;
    quote_amount_sol: number;
    price_impact_bps: number;
    network_fee_sol: number;
    tx_signature: string;
    error?: string | null;
  }>;
  monitored_transactions: Array<{
    signature: string;
    mint: string;
    side: string;
    confirmation_level: string;
    submitted_slot: number;
    reconciled: boolean;
  }>;
  execution_permission: string;
};

export function PumpIntelligenceView() {
  const [data, setData] = useState<PumpWorkbenchData | null>(null);
  const [searchMint, setSearchMint] = useState("");
  const [selectedMint, setSelectedMint] = useState<string>("");
  const [orderSide, setOrderSide] = useState<"buy" | "sell">("buy");
  const [orderSizeSol, setOrderSizeSol] = useState<string>("0.5");
  const [slippageBps, setSlippageBps] = useState<string>("150");
  const [orderFeedback, setOrderFeedback] = useState<string>("");
  const [replaySummary, setReplaySummary] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadWorkbench = useCallback(async (q = "") => {
    try {
      const res = await fetch(`/api/pump/workbench?q=${encodeURIComponent(q)}`);
      if (!res.ok) return;
      const body: PumpWorkbenchData = await res.json();
      setData(body);
      if (!selectedMint && body.tokens.length > 0) {
        setSelectedMint(body.tokens[0].token.mint);
      }
    } finally {
      setLoading(false);
    }
  }, [selectedMint]);

  useEffect(() => {
    void loadWorkbench();
  }, [loadWorkbench]);

  const activeBundle =
    data?.tokens.find((b) => b.token.mint === selectedMint) ?? data?.tokens[0] ?? null;

  async function handlePaperOrder() {
    if (!activeBundle) return;
    setOrderFeedback("Submitting paper order through deterministic risk engine...");
    const clientOrderId = `pump-ui-${Date.now()}`;
    const res = await fetch("/api/pump/paper-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_order_id: clientOrderId,
        mint: activeBundle.token.mint,
        side: orderSide,
        size_sol: Number(orderSizeSol) || 0.5,
        slippage_bps: Number(slippageBps) || 150,
        requested_mode: "paper",
      }),
    });
    const out = await res.json();
    if (!res.ok) {
      setOrderFeedback(`Order error: ${out.detail ?? res.statusText}`);
    } else if (out.status === "rejected_by_risk_control") {
      setOrderFeedback(
        `Rejected by deterministic risk control: ${(out.risk_decision?.reject_reasons ?? []).join(", ")}`
      );
    } else {
      setOrderFeedback(
        `Paper ${orderSide.toUpperCase()} ${out.status}: venue=${out.order?.venue}, ix=${out.order?.instruction}, sig=${out.order?.tx_signature || "none"}`
      );
    }
    await loadWorkbench(searchMint);
  }

  async function handleToggleKillSwitch(nextActive: boolean) {
    await fetch("/api/pump/kill-switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active: nextActive }),
    });
    await loadWorkbench(searchMint);
  }

  async function handleRunReplay() {
    const res = await fetch("/api/pump/replay", { method: "POST" });
    if (res.ok) {
      setReplaySummary(await res.json());
    }
  }

  if (loading && !data) {
    return <div className="p-6 text-sm">Loading ATLAS Pump Intelligence Workbench...</div>;
  }

  return (
    <div className="space-y-6 p-4" data-testid="pump-intelligence-workbench">
      {/* Top Banner: Provenance, Freshness, Wallet Security & Kill Switch */}
      <div className="rounded border border-slate-700 bg-slate-900/70 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">
              ATLAS Pump Intelligence — Solana Token Discovery, Risk, ML & Paper Execution
            </h2>
            <p className="text-xs text-slate-300">
              Primary key: base58 Solana Mint Address (never symbol alone). Mode:{" "}
              <strong>{data?.data_mode ?? "simulated_reference"}</strong> | Freshness:{" "}
              <strong>{data?.freshness.status ?? "unknown"}</strong> (slot {data?.freshness.last_slot ?? 0}) |
              ML execution_permission: <strong>{data?.execution_permission ?? "none"}</strong>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleToggleKillSwitch(!Boolean(data?.risk_limits.kill_switch_active))}
              className="rounded border border-rose-500/60 bg-rose-950/50 px-3 py-1.5 text-xs font-medium text-rose-200"
            >
              Kill Switch: {data?.risk_limits.kill_switch_active ? "ACTIVE (HALTED)" : "ARMED (NORMAL)"}
            </button>
            <button
              type="button"
              onClick={() => void handleRunReplay()}
              className="rounded border border-sky-500/60 bg-sky-950/50 px-3 py-1.5 text-xs font-medium text-sky-200"
            >
              Run Event-Driven Replay
            </button>
          </div>
        </div>
      </div>

      {/* Search by Mint Address & Token Discovery Table */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="rounded border border-slate-700 bg-slate-900/50 p-4 lg:col-span-2">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">1. Live / Reference Token Discovery (Mint-Indexed)</h3>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={searchMint}
                onChange={(e) => setSearchMint(e.target.value)}
                placeholder="Search by Mint Address (or symbol collision check)..."
                className="w-72 rounded border border-slate-600 bg-slate-950 px-2.5 py-1 text-xs"
              />
              <button
                type="button"
                onClick={() => void loadWorkbench(searchMint)}
                className="rounded border border-slate-600 bg-slate-800 px-2.5 py-1 text-xs"
              >
                Filter
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400">
                  <th className="py-1.5 pr-2">Mint (Primary ID)</th>
                  <th className="py-1.5 pr-2">Symbol</th>
                  <th className="py-1.5 pr-2">Lifecycle</th>
                  <th className="py-1.5 pr-2">Venue</th>
                  <th className="py-1.5 pr-2">Curve %</th>
                  <th className="py-1.5 pr-2">Eff. Liq (SOL)</th>
                  <th className="py-1.5 pr-2">Safety</th>
                  <th className="py-1.5 pr-2">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {(data?.tokens ?? []).map((b) => {
                  const t = b.token;
                  const isSel = t.mint === activeBundle?.token.mint;
                  return (
                    <tr
                      key={t.mint}
                      onClick={() => setSelectedMint(t.mint)}
                      className={`cursor-pointer border-b border-slate-800 ${
                        isSel ? "bg-slate-800/80" : "hover:bg-slate-800/40"
                      }`}
                    >
                      <td className="py-1.5 pr-2 font-mono">{t.mint.slice(0, 14)}…</td>
                      <td className="py-1.5 pr-2 font-semibold">{t.symbol}</td>
                      <td className="py-1.5 pr-2">{t.lifecycle_state}</td>
                      <td className="py-1.5 pr-2">{t.active_venue}</td>
                      <td className="py-1.5 pr-2">{t.curve_progress_pct.toFixed(1)}%</td>
                      <td className="py-1.5 pr-2">{b.liquidity_profile.effective_liquidity_sol.toFixed(2)}</td>
                      <td className="py-1.5 pr-2">{b.token_safety.safety_status.toUpperCase()}</td>
                      <td className="py-1.5 pr-2">{t.data_provenance}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Portfolio, Wallet Security & Paper Order Ticket */}
        <div className="rounded border border-slate-700 bg-slate-900/50 p-4 space-y-3">
          <h3 className="text-sm font-semibold">2. Paper Execution & Dedicated Wallet Guard</h3>
          <div className="text-xs space-y-1 text-slate-300">
            <div>
              Selected Mint: <code className="text-amber-300">{activeBundle?.token.mint ?? "none"}</code>
            </div>
            <div>
              Dedicated Wallet: <code>{data?.wallet_security.wallet_pubkey.slice(0, 16)}…</code> (Live signing:{" "}
              <strong>DISABLED</strong>, LLM access: <strong>{data?.wallet_security.llm_signing_access}</strong>)
            </div>
            <div>
              Paper Cash: <strong>{data?.portfolio.cash_sol.toFixed(4)} SOL</strong> | Equity (Liquidation-Marked):{" "}
              <strong>{data?.portfolio.equity_sol.toFixed(4)} SOL</strong>
            </div>
            <div>
              Realized P&L: <strong>{data?.portfolio.realized_pnl_sol.toFixed(4)} SOL</strong> | Unrealized (Exit-Quote Marked):{" "}
              <strong>{data?.portfolio.unrealized_pnl_sol.toFixed(4)} SOL</strong>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 pt-1 text-xs">
            <select
              aria-label="Order side"
              value={orderSide}
              onChange={(e) => setOrderSide(e.target.value as "buy" | "sell")}
              className="rounded border border-slate-600 bg-slate-950 px-2 py-1"
            >
              <option value="buy">BUY (SOL in)</option>
              <option value="sell">SELL (All Pos)</option>
            </select>
            <input
              aria-label="Order size SOL"
              type="number"
              step="0.1"
              value={orderSizeSol}
              onChange={(e) => setOrderSizeSol(e.target.value)}
              className="rounded border border-slate-600 bg-slate-950 px-2 py-1"
              placeholder="SOL size"
            />
            <input
              aria-label="Slippage bps"
              type="number"
              step="25"
              value={slippageBps}
              onChange={(e) => setSlippageBps(e.target.value)}
              className="rounded border border-slate-600 bg-slate-950 px-2 py-1"
              placeholder="Slippage bps"
            />
          </div>
          <button
            type="button"
            onClick={() => void handlePaperOrder()}
            className="w-full rounded border border-emerald-500/60 bg-emerald-950/60 px-3 py-1.5 text-xs font-semibold text-emerald-200"
          >
            Simulate & Submit Paper {orderSide.toUpperCase()} via Risk Control Plane
          </button>
          {orderFeedback && (
            <div className="rounded border border-slate-700 bg-slate-950 p-2 text-xs text-slate-200">
              {orderFeedback}
            </div>
          )}
        </div>
      </div>

      {/* Selected Token Deep-Dive: Bonding Curve / PumpSwap / Safety / Wallet Intelligence / ML Forecasts */}
      {activeBundle && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {/* Bonding Curve & PumpSwap Pool State */}
          <div className="rounded border border-slate-700 bg-slate-900/50 p-4 space-y-2 text-xs">
            <h3 className="text-sm font-semibold">
              3. On-Chain Venue State ({activeBundle.token.symbol} — {activeBundle.token.lifecycle_state})
            </h3>
            <div>Full Mint: <code className="break-all">{activeBundle.token.mint}</code></div>
            <div>Creator: <code className="break-all">{activeBundle.token.creator_wallet}</code></div>
            {activeBundle.bonding_curve && (
              <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
                <div className="font-semibold text-sky-300">Bonding Curve (v3 17-Account Layout)</div>
                <div>Progress: <strong>{activeBundle.bonding_curve.progress_pct.toFixed(2)}%</strong> (Complete: {String(activeBundle.bonding_curve.complete)})</div>
                <div>Effective Virtual Quote Reserves: <strong>{(activeBundle.bonding_curve.effective_virtual_quote_reserves / 1e9).toFixed(4)} SOL</strong></div>
                <div>Signed Reserve Offset (Unswept Fees): <strong>{(activeBundle.bonding_curve.signed_virtual_quote_reserves_offset / 1e9).toFixed(4)} SOL</strong></div>
              </div>
            )}
            {activeBundle.pumpswap_pool && (
              <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
                <div className="font-semibold text-emerald-300">PumpSwap Canonical AMM Pool</div>
                <div>Pool: <code className="break-all">{activeBundle.pumpswap_pool.pool_address}</code></div>
                <div>Quote Vault Raw: <strong>{(activeBundle.pumpswap_pool.quote_vault_amount / 1e9).toFixed(4)} SOL</strong></div>
                <div>Signed Pool::virtual_quote_reserves: <strong>{(activeBundle.pumpswap_pool.virtual_quote_reserves / 1e9).toFixed(4)} SOL</strong></div>
                <div>Effective Quote Reserves: <strong>{(activeBundle.pumpswap_pool.effective_quote_reserves / 1e9).toFixed(4)} SOL</strong> (LP Burned: {String(activeBundle.pumpswap_pool.lp_burned)})</div>
              </div>
            )}
            <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
              <div className="font-semibold">Liquidity & Exit Impact Simulation</div>
              <div>Buy Impact: <strong>{activeBundle.liquidity_profile.buy_price_impact_bps} bps</strong> | Sell Impact: <strong>{activeBundle.liquidity_profile.sell_price_impact_bps} bps</strong></div>
              <div>Round-Trip Cost: <strong>{activeBundle.liquidity_profile.round_trip_cost_bps} bps</strong> | Solana Fee: <strong>{activeBundle.liquidity_profile.solana_fee_sol} SOL</strong></div>
              <div>Sell Simulation Passed: <strong>{String(activeBundle.liquidity_profile.sell_simulation_passed)}</strong> | Max Safe Size: <strong>{activeBundle.liquidity_profile.max_safe_order_sol} SOL</strong></div>
            </div>
          </div>

          {/* Token Safety & Wallet Intelligence */}
          <div className="rounded border border-slate-700 bg-slate-900/50 p-4 space-y-2 text-xs">
            <h3 className="text-sm font-semibold">
              4. Token Safety & Wallet Intelligence ({activeBundle.token_safety.safety_status.toUpperCase()})
            </h3>
            <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
              <div className="font-semibold text-emerald-300">Verified On-Chain Facts</div>
              <div>Mint Authority Active: <strong>{String(activeBundle.token_safety.verified_on_chain_facts.mint_authority_active)}</strong></div>
              <div>Freeze Authority Active: <strong>{String(activeBundle.token_safety.verified_on_chain_facts.freeze_authority_active)}</strong></div>
              <div>Creator Holding: <strong>{String(activeBundle.token_safety.verified_on_chain_facts.creator_holding_pct)}%</strong> | Top-10 Holders: <strong>{String(activeBundle.token_safety.verified_on_chain_facts.top10_holder_pct)}%</strong></div>
              <div>Whale Net Flow: <strong>{activeBundle.wallet_intelligence.whale_activity.whale_net_flow_sol} SOL</strong> ({activeBundle.wallet_intelligence.whale_activity.whale_trade_count} whale trades)</div>
            </div>
            <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
              <div className="font-semibold text-amber-300">Heuristic Risk Scores (Not Proof of Coordination)</div>
              <div>Suspicious Cluster Share: <strong>{activeBundle.token_safety.heuristic_risk_scores.suspicious_cluster_pct}%</strong></div>
              <div>Creator Prior Early-Dump Rate: <strong>{activeBundle.token_safety.heuristic_risk_scores.creator_prior_early_dump_rate}</strong></div>
              <div>Composite Risk Score: <strong>{activeBundle.token_safety.heuristic_risk_scores.composite_risk_score} / 100</strong></div>
              {activeBundle.token_safety.hard_reject_reasons.length > 0 && (
                <div className="text-rose-300">Hard Rejects: {activeBundle.token_safety.hard_reject_reasons.join(", ")}</div>
              )}
            </div>
            <p className="text-[11px] text-slate-400">{activeBundle.token_safety.safety_disclaimer}</p>
            <p className="text-[11px] text-slate-400">{activeBundle.token_safety.cluster_disclaimer}</p>
          </div>

          {/* Strategy Candidates & Calibrated ML Forecast */}
          <div className="rounded border border-slate-700 bg-slate-900/50 p-4 space-y-2 text-xs">
            <h3 className="text-sm font-semibold">5. Strategy Candidates & Calibrated ML Forecast</h3>
            <div className="rounded border border-slate-800 bg-slate-950/70 p-2.5 space-y-1">
              <div className="font-semibold text-sky-300">
                ML Model: {activeBundle.ml_forecast.model_id} (Abstained: {String(activeBundle.ml_forecast.abstained)})
              </div>
              <div>P(Positive Return): <strong>{(activeBundle.ml_forecast.prob_positive_return * 100).toFixed(1)}%</strong> | P(Target Before Stop): <strong>{(activeBundle.ml_forecast.prob_target_before_stop * 100).toFixed(1)}%</strong></div>
              <div>P(Severe Drawdown): <strong>{(activeBundle.ml_forecast.prob_severe_drawdown * 100).toFixed(1)}%</strong> | P(Migration): <strong>{(activeBundle.ml_forecast.migration_completion_prob * 100).toFixed(1)}%</strong></div>
              <div>Expected MFE: <strong>+{activeBundle.ml_forecast.expected_favorable_excursion_bps} bps</strong> | Expected MAE: <strong>-{activeBundle.ml_forecast.expected_adverse_excursion_bps} bps</strong></div>
              <div>Uncertainty: <strong>{activeBundle.ml_forecast.model_uncertainty}</strong> | Liquidity Deterioration Prob: <strong>{(activeBundle.ml_forecast.liquidity_deterioration_prob * 100).toFixed(1)}%</strong></div>
            </div>
            <div className="space-y-1.5">
              <div className="font-semibold">Detected Strategy Candidates ({activeBundle.strategy_candidates.length})</div>
              {activeBundle.strategy_candidates.map((c) => (
                <div key={c.candidate_id} className="rounded border border-slate-800 bg-slate-950/60 p-2">
                  <div className="flex justify-between font-medium">
                    <span>{c.strategy} ({c.direction})</span>
                    <span>strength={c.signal_strength} | R:R={c.reward_risk_ratio}</span>
                  </div>
                  <div className="text-[11px] text-slate-400">{c.rationale.join(" • ")}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* EV Leaderboard & Replay Results */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded border border-slate-700 bg-slate-900/50 p-4 text-xs">
          <h3 className="mb-2 text-sm font-semibold">6. Expected-Value (EV) Ranking After All Costs</h3>
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-700 text-slate-400">
                <th className="py-1 pr-2">#</th>
                <th className="py-1 pr-2">Mint</th>
                <th className="py-1 pr-2">Strategy</th>
                <th className="py-1 pr-2">Gross EV</th>
                <th className="py-1 pr-2">Cost</th>
                <th className="py-1 pr-2">Net EV</th>
                <th className="py-1 pr-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {(data?.ev_leaderboard ?? []).map((row) => (
                <tr key={`${row.candidate.mint}-${row.candidate.strategy}`} className="border-b border-slate-800">
                  <td className="py-1 pr-2">{row.global_rank}</td>
                  <td className="py-1 pr-2 font-mono">{row.candidate.mint.slice(0, 10)}… ({row.candidate.symbol})</td>
                  <td className="py-1 pr-2">{row.candidate.strategy}</td>
                  <td className="py-1 pr-2">{row.gross_expected_value_bps} bps</td>
                  <td className="py-1 pr-2">{row.round_trip_cost_bps} bps</td>
                  <td className="py-1 pr-2 font-semibold">{row.net_expected_value_bps} bps</td>
                  <td className="py-1 pr-2">{row.recommended_research_action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="rounded border border-slate-700 bg-slate-900/50 p-4 text-xs space-y-2">
          <h3 className="text-sm font-semibold">7. Deterministic Risk Limits & Event-Driven Replay</h3>
          <div className="grid grid-cols-2 gap-1 text-slate-300">
            <div>Max SOL Exposure: <strong>{String(data?.risk_limits.max_sol_exposure)} SOL</strong></div>
            <div>Max Position Size: <strong>{String(data?.risk_limits.max_position_size_sol)} SOL</strong></div>
            <div>Max Trade Loss Budget: <strong>{String(data?.risk_limits.max_trade_loss_budget_sol)} SOL</strong></div>
            <div>Max Slippage / Impact: <strong>{String(data?.risk_limits.max_slippage_bps)} / {String(data?.risk_limits.max_price_impact_bps)} bps</strong></div>
            <div>Min Exit Liquidity: <strong>{String(data?.risk_limits.min_exit_liquidity_sol)} SOL</strong></div>
            <div>Max Correlated Creator: <strong>{String(data?.risk_limits.max_correlated_creator_exposure_sol)} SOL</strong></div>
          </div>
          {replaySummary && (
            <div className="rounded border border-sky-800/60 bg-slate-950 p-2.5 space-y-1">
              <div className="font-semibold text-sky-300">Event-Driven Replay Result (Liquidation-Quote Exits Only)</div>
              <div>
                Frames: <strong>{String(replaySummary.total_frames)}</strong> | Inactive Tokens Included:{" "}
                <strong>{String(replaySummary.inactive_tokens_seen)}</strong> | Completed Round-Trips:{" "}
                <strong>{String(replaySummary.completed_round_trips)}</strong>
              </div>
              <div>
                Gross P&L: <strong>{String(replaySummary.gross_pnl_sol)} SOL</strong> | Fees & Price Impact Drag:{" "}
                <strong>{String(replaySummary.total_fees_and_impact_sol)} SOL</strong> | Net P&L:{" "}
                <strong>{String(replaySummary.net_pnl_sol)} SOL</strong>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

