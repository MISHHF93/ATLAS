"use client";

import React, { useCallback, useEffect, useState } from "react";
import { loadMarketBars, type MarketBar, type MarketBarsResponse } from "../../lib/marketBars";
import { LiveModelLockPanel } from "../market/LiveModelLockPanel";
import { ObserverHealthPanel } from "../market/ObserverHealthPanel";
import { FeedHealthPanel } from "../market/FeedHealthPanel";

type PositionRow = {
  position_id: string;
  instrument_id: string;
  side: string;
  notional_usd: string;
  stop_distance_bps: string;
  status: string;
  track: string;
};

type OrderRow = {
  order_id: string;
  instrument_id: string;
  side: string;
  notional_usd: string;
  control_plane_decision: string;
  evaluated_at?: string;
  violations?: string[];
};

function num(value: unknown, digits = 4): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

function dig(source: unknown, path: string[]): unknown {
  let current = source;
  for (const key of path) {
    if (!current || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

export function AccountRiskPage({
  ready,
  equityLabel,
  hwmLabel,
  profitLabel,
  dailyLabel,
  trailingLabel,
  consistencyLabel,
  positions,
  busy,
  onFlatten,
  showTable = true,
}: {
  ready: boolean;
  equityLabel: string;
  hwmLabel: string;
  profitLabel: string;
  dailyLabel: string;
  trailingLabel: string;
  consistencyLabel: string;
  positions: PositionRow[];
  busy: boolean;
  onFlatten: () => void;
  /** Off when the caller renders the richer open-positions table itself. */
  showTable?: boolean;
}) {
  return (
    <>
      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">The one paper account</h2>
            <p className="clean-card-subtitle">These figures come from the control plane. There are no other accounts on this desk.</p>
          </div>
          <button type="button" className="btn btn-danger btn-sm" disabled={busy || !ready} onClick={onFlatten}>
            Flatten open positions
          </button>
        </div>
        <div className="clean-kpi-row">
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Equity</span>
            <span className="clean-kpi-value">{ready ? equityLabel : "—"}</span>
            <span className="clean-kpi-sub">{ready ? profitLabel : "Waiting for the control plane"}</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">High-water mark</span>
            <span className="clean-kpi-value">{ready ? hwmLabel : "—"}</span>
            <span className="clean-kpi-sub">{ready ? dailyLabel : "Daily room waits on the account"}</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Drawdown room</span>
            <span className="clean-kpi-value" style={{ fontSize: "18px" }}>{ready ? trailingLabel : "—"}</span>
            <span className="clean-kpi-sub">{ready ? consistencyLabel : "Consistency waits on the account"}</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Open positions</span>
            <span className="clean-kpi-value">{positions.length}</span>
            <span className="clean-kpi-sub">Flatten sends one request to the control plane</span>
          </div>
        </div>
      </div>
      {showTable ? (
      <div className="clean-card">
        <table className="clean-table">
          <thead>
            <tr>
              <th>Position</th>
              <th>Instrument</th>
              <th>Side</th>
              <th>Notional</th>
              <th>Stop</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={6}>No open positions.</td>
              </tr>
            ) : (
              positions.map((position) => (
                <tr key={position.position_id}>
                  <td className="mono-cell">{position.position_id}</td>
                  <td className="mono-cell">{position.instrument_id}</td>
                  <td>{position.side}</td>
                  <td className="mono-cell">{position.notional_usd}</td>
                  <td className="mono-cell">{position.stop_distance_bps} bps</td>
                  <td>{position.status} · {position.track}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      ) : null}
    </>
  );
}

export function AuditLogPage({ orders, audit }: { orders: OrderRow[]; audit: string[] }) {
  const lines = audit.length ? audit.slice(-12).reverse() : [];
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">What the control plane recorded</h2>
          <p className="clean-card-subtitle">Orders and audit lines from this process. No copy-bot detector is connected.</p>
        </div>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Instrument</th>
            <th>Side</th>
            <th>Notional</th>
            <th>Decision</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 ? (
            <tr>
              <td colSpan={6}>No orders recorded yet.</td>
            </tr>
          ) : (
            orders.slice(-8).reverse().map((order) => (
              <tr key={order.order_id}>
                <td className="mono-cell">{order.evaluated_at ?? "—"}</td>
                <td className="mono-cell">{order.instrument_id}</td>
                <td>{order.side}</td>
                <td className="mono-cell">{order.notional_usd}</td>
                <td>{order.control_plane_decision}</td>
                <td>{order.violations?.length ? order.violations.join(", ") : order.order_id}</td>
              </tr>
            ))
          )}
          {lines.map((line, index) => (
            <tr key={`audit-${index}`}>
              <td className="mono-cell" colSpan={6}>{line}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExposurePage({ positions }: { positions: PositionRow[] }) {
  const open = positions.filter((position) => position.status === "open");
  const total = open.reduce((sum, position) => sum + Number(position.notional_usd || 0), 0);
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Open paper exposure</h2>
          <p className="clean-card-subtitle">Notional of positions the control plane still has open. No A-book or B-book router is connected.</p>
        </div>
      </div>
      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Open positions</span>
          <span className="clean-kpi-value">{open.length}</span>
          <span className="clean-kpi-sub">Combined notional ${total.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
        </div>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Position</th>
            <th>Instrument</th>
            <th>Side</th>
            <th>Notional</th>
            <th>Track</th>
          </tr>
        </thead>
        <tbody>
          {open.length === 0 ? (
            <tr>
              <td colSpan={5}>Nothing is open.</td>
            </tr>
          ) : (
            open.map((position) => (
              <tr key={position.position_id}>
                <td className="mono-cell">{position.position_id}</td>
                <td className="mono-cell">{position.instrument_id}</td>
                <td>{position.side}</td>
                <td className="mono-cell">{position.notional_usd}</td>
                <td>{position.track}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function ChartReadPage({
  symbol,
  heading = "Chart read",
  blurb = "Press Read chart. The result cannot place an order.",
}: {
  symbol: string;
  heading?: string;
  blurb?: string;
}) {
  const [note, setNote] = useState(blurb);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async () => {
    setBusy(true);
    try {
      const response = await fetch(`/api/ml/chart-read?symbol=${encodeURIComponent(symbol)}&bucket_seconds=60`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Chart read returned HTTP ${response.status}`);
      const body = (await response.json()) as {
        active?: Record<string, unknown>;
        execution_permission?: string;
        training?: { cycle?: number; status?: string };
      };
      const active = body.active ?? {};
      setRows([active]);
      const cycle = body.training?.cycle ?? 0;
      setNote(`${symbol} · ${String(active.feed_origin ?? "unlabeled")} · ${String(active.bars_read ?? 0)} bars · fit cycle ${cycle} · permission ${body.execution_permission ?? "none"}`);
    } catch (error) {
      setRows([]);
      setNote(error instanceof Error ? error.message : "Chart read failed.");
    } finally {
      setBusy(false);
    }
  }, [symbol]);

  useEffect(() => {
    void run();
    const timer = window.setInterval(() => void run(), 15000);
    return () => window.clearInterval(timer);
  }, [run]);

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">{heading}: {symbol}</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Reading…" : "Read chart"}
        </button>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Bars</th>
            <th>Last</th>
            <th>Direction</th>
            <th>Whale moment</th>
            <th>Feed</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={6}>No read yet.</td>
            </tr>
          ) : (
            rows.map((row) => {
              const moment = row.whale_moment as { status?: string; action?: string; scenario_id?: string } | undefined;
              const momentLabel = moment?.status === "locked"
                ? `${String(moment.action ?? "—")} · ${String(moment.scenario_id ?? "—")}`
                : "withheld";
              return (
                <tr key={String(row.symbol)}>
                  <td className="mono-cell">{String(row.symbol ?? symbol)}</td>
                  <td className="mono-cell">{String(row.bars_read ?? "—")}</td>
                  <td className="mono-cell">{String(row.last_close ?? "—")}</td>
                  <td>{String(row.direction ?? "—")}</td>
                  <td className="mono-cell">{momentLabel}</td>
                  <td>{String(row.feed_origin ?? "—")}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

type LedgerReliability = {
  direction_hits?: number;
  direction_attempts?: number;
  direction_hit_rate?: number | null;
  confidence?: string;
  brier_score?: number | null;
  calibration_rows?: number;
  required_calibration_rows?: number;
  execution?: string;
  notice?: string;
};

type LedgerTrack = {
  judgment?: string;
  public_resolved_stances?: number;
  required_resolved_stances?: number;
  abstentions?: number;
  mean_net_return?: number | null;
  notice?: string;
  reliability?: LedgerReliability;
};

type LedgerReport = {
  hypothesis?: string;
  filter?: string;
  notice?: string;
  execution_permission?: string;
  orders_submitted?: number;
  tracks?: { competition?: LedgerTrack; open_market?: LedgerTrack };
  open_forecasts?: Array<{
    symbol?: string;
    track?: string;
    stance?: string;
    primary_side?: string;
    abstain_reason?: string | null;
    filter_probability?: number | null;
    data_mode?: string;
  }>;
};

function ledgerJudgment(row: LedgerTrack | undefined): string {
  const seen = row?.public_resolved_stances ?? 0;
  const need = row?.required_resolved_stances ?? 60;
  return `${row?.judgment ?? "too_few_to_judge"} · ${seen}/${need} public stances · ${row?.abstentions ?? 0} abstentions`;
}

function reliabilityLine(row: LedgerTrack | undefined): string {
  const reliability = row?.reliability;
  const attempts = reliability?.direction_attempts ?? 0;
  const hits = reliability?.direction_hits ?? 0;
  const direction = attempts > 0 ? `${hits}/${attempts} direction hits` : "no taken stance";
  const net = row?.mean_net_return;
  const trade = net == null ? "no costed mean" : `costed mean ${(net * 100).toFixed(2)}%`;
  const confidence = reliability?.confidence === "scored"
    ? `confidence Brier ${reliability.brier_score ?? "—"} on ${reliability.calibration_rows ?? 0}`
    : `confidence ${reliability?.confidence ?? "too_few_to_calibrate"} ${reliability?.calibration_rows ?? 0}/${reliability?.required_calibration_rows ?? 30}`;
  return `${direction} · ${trade} · ${confidence} · execution ${reliability?.execution ?? "not_attempted"}`;
}

export function OutcomeLedgerPanel() {
  const [report, setReport] = useState<LedgerReport | null>(null);
  const [note, setNote] = useState("Loading the daily trend ledger.");

  useEffect(() => {
    let live = true;
    const pull = () => {
      void fetch("/api/research/outcome-ledger", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw new Error(`Outcome ledger returned HTTP ${response.status}`);
          return (await response.json()) as LedgerReport;
        })
        .then((body) => {
          if (!live) return;
          setReport(body);
          setNote(body.notice ?? "The ledger is loaded. It cannot send an order.");
        })
        .catch((error: unknown) => {
          if (live) setNote(error instanceof Error ? error.message : "The ledger did not load.");
        });
    };
    pull();
    const timer = window.setInterval(pull, 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const opens = report?.open_forecasts ?? [];
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Daily trend ledger</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
      </div>
      <p style={{ margin: "0 0 8px", fontSize: "12px", color: "#94A3B8", lineHeight: 1.45 }}>
        {report?.hypothesis} {report?.filter}
      </p>
      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Competition</span>
          <span className="clean-kpi-value" style={{ fontSize: "14px" }}>{ledgerJudgment(report?.tracks?.competition)}</span>
          <span className="clean-kpi-sub">{reliabilityLine(report?.tracks?.competition)}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Open market</span>
          <span className="clean-kpi-value" style={{ fontSize: "14px" }}>{ledgerJudgment(report?.tracks?.open_market)}</span>
          <span className="clean-kpi-sub">{reliabilityLine(report?.tracks?.open_market)}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Permission</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{report?.execution_permission ?? "none"}</span>
          <span className="clean-kpi-sub">Orders {report?.orders_submitted ?? 0}. Abstentions are not wins.</span>
        </div>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Track</th>
            <th>Open stance</th>
            <th>Side</th>
            <th>Filter</th>
            <th>Data</th>
          </tr>
        </thead>
        <tbody>
          {opens.length === 0 ? (
            <tr><td colSpan={6}>No open daily forecast yet.</td></tr>
          ) : opens.map((row) => (
            <tr key={String(row.symbol)}>
              <td className="mono-cell">{row.symbol}</td>
              <td>{row.track}</td>
              <td>{row.stance}{row.abstain_reason ? ` · ${row.abstain_reason}` : ""}</td>
              <td>{row.primary_side}</td>
              <td className="mono-cell">{row.filter_probability ?? "—"}</td>
              <td>{row.data_mode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ReadinessCheck = { id?: string; status?: string; detail?: string };

type TrialRow = {
  track?: string;
  judgment?: string;
  mean_net_return?: number | null;
  brier_score?: number | null;
  execution?: string;
};

type TrialLog = {
  count?: number;
  kept_misses?: number;
  notice?: string;
  latest?: TrialRow[];
};

type ReadinessReport = {
  light?: string;
  live_money?: string;
  trading?: string;
  notice?: string;
  official?: { notice?: string; paper_broker?: string; live_endpoint?: string };
  execution_permission?: string;
  orders_submitted?: number;
  checks?: ReadinessCheck[];
  trials?: TrialLog;
};

function trialLine(row: TrialRow): string {
  const net = row.mean_net_return == null ? "no costed mean" : `costed mean ${(row.mean_net_return * 100).toFixed(2)}%`;
  const brier = row.brier_score == null ? "no Brier" : `Brier ${row.brier_score.toFixed(3)}`;
  return `${row.track ?? "track"} · ${row.judgment ?? "unavailable"} · ${net} · ${brier} · execution ${row.execution ?? "not_attempted"}`;
}

export function TradeReadinessPanel() {
  const [report, setReport] = useState<ReadinessReport | null>(null);
  const [note, setNote] = useState("Loading the trade readiness checks.");

  useEffect(() => {
    let live = true;
    const pull = () => {
      void fetch("/api/control/trade-readiness", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw new Error(`Trade readiness returned HTTP ${response.status}`);
          return (await response.json()) as ReadinessReport;
        })
        .then((body) => {
          if (!live) return;
          setReport(body);
          setNote(body.notice ?? "Live money stays off.");
        })
        .catch((error: unknown) => {
          if (live) setNote(error instanceof Error ? error.message : "Trade readiness did not load.");
        });
    };
    pull();
    const timer = window.setInterval(pull, 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const checks = report?.checks ?? [];
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Trade readiness</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
      </div>
      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Research light</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{report?.light ?? "withheld"}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Live money</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{report?.live_money ?? "disabled"}</span>
          <span className="clean-kpi-sub">Trading {report?.trading ?? "disabled"}. Orders {report?.orders_submitted ?? 0}.</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Misses kept</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{report?.trials?.kept_misses ?? "—"}</span>
          <span className="clean-kpi-sub">{report?.trials?.count ?? 0} recorded verdicts.</span>
        </div>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Check</th>
            <th>Status</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {checks.length === 0 ? (
            <tr><td colSpan={3}>No readiness check yet.</td></tr>
          ) : checks.map((row) => (
            <tr key={String(row.id)}>
              <td className="mono-cell">{row.id}</td>
              <td>{row.status}</td>
              <td>{row.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="clean-card-subtitle" style={{ marginTop: "12px" }}>
        {report?.official?.notice ?? "Official feeds have not loaded."} Broker {report?.official?.paper_broker ?? "internal_simulator"}. Live endpoint {report?.official?.live_endpoint ?? "refused"}.
      </p>
      <p className="clean-card-subtitle" style={{ marginTop: "12px" }}>
        {report?.trials?.notice ?? "The trial log has not loaded."}
      </p>
      {(report?.trials?.latest ?? []).length === 0 ? (
        <p className="clean-card-subtitle">No verdict recorded yet.</p>
      ) : (report?.trials?.latest ?? []).map((row) => (
        <p key={row.track ?? trialLine(row)} className="clean-card-subtitle">{trialLine(row)}</p>
      ))}
    </div>
  );
}

export function WalkForwardPage({ track }: { track: "competition" | "open_market" }) {
  const [note, setNote] = useState("Runs the frozen benchmark study for the selected track. It does not promote a model or send an order.");
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setNote("Running the walk-forward study…");
    try {
      const response = await fetch("/api/research/walk-forward", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track, cost_bps: 4, purge_bars: 1, embargo_bars: 1 }),
      });
      if (!response.ok) throw new Error(`Walk-forward returned HTTP ${response.status}`);
      const body = (await response.json()) as { study?: Record<string, unknown> };
      setReport(body.study ?? null);
      setNote(body.study ? `Study finished for ${track}. Permission stays none.` : "The study returned no report.");
    } catch (error) {
      setReport(null);
      setNote(error instanceof Error ? error.message : "Walk-forward failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Walk-forward on the {track === "competition" ? "competition" : "open-market"} book</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Running…" : "Run study"}
        </button>
      </div>
      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Challenger MAE</span>
          <span className="clean-kpi-value">{report ? num(dig(report, ["overall_report", "mae"])) : "—"}</span>
          <span className="clean-kpi-sub">Baseline MAE {report ? num(dig(report, ["linear_baseline_report", "mae"])) : "—"}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Directional accuracy</span>
          <span className="clean-kpi-value">{report ? num(dig(report, ["overall_report", "directional_accuracy"]), 3) : "—"}</span>
          <span className="clean-kpi-sub">Samples {report ? String(dig(report, ["overall_report", "samples"]) ?? "—") : "—"}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Purge / embargo</span>
          <span className="clean-kpi-value">{report ? `${String(report.purge_bars)} / ${String(report.embargo_bars)}` : "—"}</span>
          <span className="clean-kpi-sub">{report ? String(report.dataset_id ?? "") : "Run the study to fill this"}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Permission</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{report ? String(report.execution_permission ?? "none") : "none"}</span>
          <span className="clean-kpi-sub">A finished study is not a promotion</span>
        </div>
      </div>
    </div>
  );
}

export function TrainingStatusPage({ symbol = "BTC-USD" }: { symbol?: string }) {
  const [note, setNote] = useState("This process refits both books on its own about every 15 minutes. A fit cannot send an order.");
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const response = await fetch("/api/ml/live-train/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`Training status returned HTTP ${response.status}`);
    const body = (await response.json()) as Record<string, unknown>;
    setStatus(body);
    setNote(String(body.notice ?? "The desk fit is linked to chart reads. Permission stays none."));
  }, []);

  useEffect(() => {
    let live = true;
    const pull = () => {
      void load().catch((error: unknown) => {
        if (live) setNote(error instanceof Error ? error.message : "Status failed.");
      });
    };
    pull();
    const timer = window.setInterval(pull, 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [load]);

  const run = async () => {
    setBusy(true);
    setNote("Fitting once more. This still cannot send an order.");
    try {
      const response = await fetch("/api/ml/live-train", { method: "POST" });
      if (!response.ok) throw new Error(`Training returned HTTP ${response.status}`);
      const body = (await response.json()) as Record<string, unknown>;
      setStatus(body);
      setNote(String(body.notice ?? "Fit finished. Permission stays none."));
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Training failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
    <LiveModelLockPanel symbol={symbol} />
    <ObserverHealthPanel />
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Desk candle fit</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-outline btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Fitting…" : "Fit once more"}
        </button>
      </div>
      <p className="mono-cell" style={{ margin: 0, fontSize: "12.5px", color: "#CBD5E1" }}>
        {status
          ? `Status ${String(status.status ?? "unknown")} · cycle ${String(status.cycle ?? 0)} · autonomous ${String(status.autonomous ?? false)} · orders ${String(status.orders_submitted ?? 0)} · permission ${String(status.execution_permission ?? "none")}`
          : "Waiting for the desk fit."}
      </p>
    </div>
    </>
  );
}

type RulebookView = {
  rulebook_id?: string;
  revision?: string;
  max_position_notional_usd?: string;
  max_daily_loss_fraction?: string;
  drawdown_mode?: string;
  max_drawdown_fraction?: string;
  max_per_trade_risk_fraction?: string;
  min_stop_distance_bps?: string;
  max_data_age_seconds?: number;
  min_trading_days?: number;
  max_single_day_profit_share?: string | null;
  allowed_sessions?: string[];
  execution_permission?: string;
};

function moneyLimit(value: string | undefined): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return parsed.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

function percentLimit(value: string | null | undefined): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return `${(parsed * 100).toFixed(2)}%`;
}

export function RulebookBoards() {
  const [notice, setNotice] = useState("Loading the paper rulebooks from this process.");
  const [openBook, setOpenBook] = useState<RulebookView | null>(null);
  const [compBook, setCompBook] = useState<RulebookView | null>(null);

  useEffect(() => {
    let live = true;
    const pull = async () => {
      try {
        const response = await fetch("/api/control/rulebooks", { cache: "no-store" });
        if (!response.ok) throw new Error(`Rulebooks returned HTTP ${response.status}`);
        const body = (await response.json()) as {
          notice?: string;
          trading?: string;
          execution_permission?: string;
          open_market?: RulebookView;
          competition?: RulebookView;
        };
        if (!live) return;
        if (body.trading !== "disabled" || body.execution_permission !== "none") {
          throw new Error("Rulebook payload is not a paper configuration.");
        }
        setOpenBook(body.open_market ?? null);
        setCompBook(body.competition ?? null);
        setNotice(body.notice ?? "Loaded paper rulebooks. They are not edited here.");
      } catch (error) {
        if (!live) return;
        setOpenBook(null);
        setCompBook(null);
        setNotice(error instanceof Error ? error.message : "Rulebooks did not load.");
      }
    };
    void pull();
    return () => {
      live = false;
    };
  }, []);

  const card = (title: string, subtitle: string, book: RulebookView | null, badge: string) => (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">{title}</h2>
          <p className="clean-card-subtitle">{book ? `${book.rulebook_id ?? "—"} · revision ${book.revision ?? "—"}` : subtitle}</p>
        </div>
        <span className={`badge ${badge}`}>PAPER LIMITS</span>
      </div>
      <table className="clean-table">
        <tbody>
          <tr><td>Max position notional</td><td className="mono-cell">{moneyLimit(book?.max_position_notional_usd)}</td></tr>
          <tr><td>Daily loss limit</td><td className="mono-cell">{percentLimit(book?.max_daily_loss_fraction)}</td></tr>
          <tr><td>Drawdown</td><td className="mono-cell">{book ? `${book.drawdown_mode ?? "—"} ${percentLimit(book.max_drawdown_fraction)}` : "—"}</td></tr>
          <tr><td>Per-trade risk cap</td><td className="mono-cell">{percentLimit(book?.max_per_trade_risk_fraction)}</td></tr>
          <tr><td>Minimum stop</td><td className="mono-cell">{book?.min_stop_distance_bps ? `${book.min_stop_distance_bps} bps` : "—"}</td></tr>
          <tr><td>Rulebook max data age</td><td className="mono-cell">{book?.max_data_age_seconds ?? "—"} s</td></tr>
          <tr><td>Minimum trading days</td><td className="mono-cell">{book?.min_trading_days ?? "—"}</td></tr>
          <tr><td>Single-day profit share</td><td className="mono-cell">{book?.max_single_day_profit_share ? percentLimit(book.max_single_day_profit_share) : "—"}</td></tr>
          <tr><td>Sessions</td><td className="mono-cell">{book?.allowed_sessions?.join(", ") || "—"}</td></tr>
          <tr><td>Permission</td><td className="mono-cell">{book?.execution_permission ?? "none"}</td></tr>
        </tbody>
      </table>
    </div>
  );

  return (
    <>
      <p className="clean-card-subtitle" style={{ margin: 0 }}>{notice}</p>
      <div className="clean-grid-2">
        {card("Open-Market Equities Rulebook", "Waiting for the open-market rulebook.", openBook, "badge-blue")}
        {card("Prop Competition Rulebook", "Waiting for the competition rulebook.", compBook, "badge-emerald")}
      </div>
    </>
  );
}

export function BarQueryPage({ symbol }: { symbol: string }) {
  const [body, setBody] = useState<MarketBarsResponse | null>(null);
  const [rows, setRows] = useState<MarketBar[]>([]);
  const [note, setNote] = useState(`Loads closed bars for ${symbol}. This is not a SQL warehouse and not a SIP session.`);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const loaded = await loadMarketBars(symbol, 3600, 12);
      setBody(loaded);
      setRows(loaded.candles.slice(-8));
      setNote(`${loaded.symbol} · ${loaded.feed_origin} · ${loaded.bar_count} bars · ${loaded.notice}`);
    } catch (error) {
      setBody(null);
      setRows([]);
      setNote(error instanceof Error ? error.message : "Bar query failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Bars for {symbol}</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Loading…" : "Load bars"}
        </button>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Open</th>
            <th>High</th>
            <th>Low</th>
            <th>Close</th>
            <th>Volume</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={6}>{body ? "The response had no closed bars." : "Press Load bars."}</td>
            </tr>
          ) : (
            rows.map((bar) => (
              <tr key={bar.timestamp}>
                <td className="mono-cell">{bar.timestamp}</td>
                <td className="mono-cell">{bar.open}</td>
                <td className="mono-cell">{bar.high}</td>
                <td className="mono-cell">{bar.low}</td>
                <td className="mono-cell">{bar.close}</td>
                <td className="mono-cell">{bar.volume}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

type ConnectorRecord = {
  connector_id?: string;
  name?: string;
  category?: string;
  status?: string;
  enabled?: boolean;
  execution_permission?: string;
};

type PipelineStage = {
  id: string;
  name: string;
  state: "ready" | "watching" | "blocked" | "withheld" | string;
  detail: string;
};

function connectorLabel(row: ConnectorRecord): string {
  if (row.category === "quarantined" || row.status === "blocked") return "blocked";
  if (row.enabled === false || row.status === "standby") return "off";
  return "record";
}

export function PipelinePath() {
  const [stages, setStages] = useState<PipelineStage[]>([]);
  const [note, setNote] = useState("Loading the data path on this process.");
  const [summary, setSummary] = useState("");

  useEffect(() => {
    let active = true;
    void fetch("/api/data/pipelines", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Data path returned HTTP ${response.status}`);
        return response.json() as Promise<{
          stages?: PipelineStage[];
          notice?: string;
          trading?: string;
          execution_permission?: string;
          catalog?: { total_assets?: number };
          public_candle_pages?: unknown[];
        }>;
      })
      .then((body) => {
        if (!active) return;
        setStages(Array.isArray(body.stages) ? body.stages : []);
        const cached = Array.isArray(body.public_candle_pages) ? body.public_candle_pages.length : 0;
        const directory = body.catalog?.total_assets;
        setSummary(
          `Directory ${directory == null ? "—" : directory.toLocaleString()} · cached public pages ${cached} · trading ${body.trading ?? "—"} · permission ${body.execution_permission ?? "none"}`,
        );
        setNote(typeof body.notice === "string" ? body.notice : "Data path loaded.");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setStages([]);
        setNote(error instanceof Error ? error.message : "Data path failed.");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div>
      <p className="clean-card-subtitle">{note}</p>
      {summary ? (
        <p className="mono-cell" style={{ fontSize: "11px", color: "#94A3B8", margin: "6px 0 10px" }}>
          {summary}
        </p>
      ) : null}
      <div className="pipeline-board">
        {stages.length === 0 ? (
          <div className="clean-catalog-empty">The data path has not loaded.</div>
        ) : (
          stages.map((stage, index) => (
            <div key={stage.id} className="pipeline-stage">
              <div className="pipeline-rail" aria-hidden="true">
                <span className="pipeline-letter">{stage.id}</span>
                {index < stages.length - 1 ? <span className="pipeline-stem" /> : null}
              </div>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "center" }}>
                  <strong style={{ fontSize: "13px", color: "#F8FAFC" }}>{stage.name}</strong>
                  <span className={`pipeline-state ${stage.state}`}>{stage.state}</span>
                </div>
                <div style={{ fontSize: "12px", color: "#94A3B8", lineHeight: 1.45, marginTop: "4px" }}>{stage.detail}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function ConnectorsPage() {
  const [rows, setRows] = useState<ConnectorRecord[]>([]);
  const [note, setNote] = useState("Loading connector records on this process.");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const response = await fetch("/api/connectors", { cache: "no-store" });
      if (!response.ok) throw new Error(`Connectors returned HTTP ${response.status}`);
      const body = (await response.json()) as { connectors?: ConnectorRecord[] };
      setRows(Array.isArray(body.connectors) ? body.connectors : []);
      setNote("Records loaded. Test writes a control-plane audit line. It does not open a vendor socket.");
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Connector load failed.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const test = async (connectorId: string) => {
    setBusy(true);
    try {
      const response = await fetch("/api/connectors/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connector_id: connectorId, action: "test_connection" }),
      });
      const body = (await response.json()) as { status?: string; message?: string };
      setNote(
        body.status === "blocked_by_policy"
          ? body.message || "Blocked by policy."
          : "Audit line written. The record flag is not a live vendor session.",
      );
      await load();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Test failed.");
      setBusy(false);
    }
  };

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Data path</h2>
          <p className="clean-card-subtitle">Each letter is a stage on this process, from the catalog through the paper desk.</p>
        </div>
      </div>
      <PipelinePath />
      <FeedHealthPanel />
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Connector records</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-outline btn-sm" disabled={busy} onClick={() => void load()}>
          {busy ? "Working…" : "Reload records"}
        </button>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Category</th>
            <th>Status</th>
            <th>Permission</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={5}>{busy ? "Loading records…" : "No connector records on this process."}</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.connector_id}>
                <td>{row.name}</td>
                <td className="mono-cell">{row.category}</td>
                <td>{connectorLabel(row)}</td>
                <td className="mono-cell">{row.execution_permission ?? "none"}</td>
                <td>
                  <button type="button" className="btn btn-outline btn-sm" disabled={busy || !row.connector_id} onClick={() => void test(String(row.connector_id))}>
                    Test record
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function ReservePage() {
  const [note, setNote] = useState("Loads the paper reserve plan from distributable profit. It does not send an order.");
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);

  const load = async () => {
    try {
      const response = await fetch("/api/strategies/reserve-yield", { cache: "no-store" });
      if (!response.ok) throw new Error(`Reserve plan returned HTTP ${response.status}`);
      const body = (await response.json()) as Record<string, unknown>;
      setPlan(body);
      setNote(
        `Distributable ${String(body.distributable_usd ?? "0")}. ${String(body.withheld_reason ?? "No withhold reason.")} Permission ${String(body.execution_permission ?? "none")}. Orders submitted ${String(body.orders_submitted ?? 0)}.`,
      );
    } catch (error) {
      setPlan(null);
      setNote(error instanceof Error ? error.message : "Reserve plan failed.");
    }
  };

  const sleeves = Array.isArray(plan?.sleeves) ? (plan?.sleeves as Array<Record<string, unknown>>) : [];
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Reserve sleeve</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void load()}>
          Load reserve plan
        </button>
      </div>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Sleeve</th>
            <th>Weight</th>
            <th>Dollars</th>
          </tr>
        </thead>
        <tbody>
          {sleeves.length === 0 ? (
            <tr>
              <td colSpan={3}>Press Load reserve plan.</td>
            </tr>
          ) : (
            sleeves.map((sleeve) => (
              <tr key={String(sleeve.id ?? sleeve.sleeve_id ?? sleeve.name)}>
                <td>{String(sleeve.id ?? sleeve.name ?? sleeve.sleeve_id ?? "sleeve")}</td>
                <td className="mono-cell">{String(sleeve.weight ?? "—")}</td>
                <td className="mono-cell">{String(sleeve.target_usd ?? sleeve.dollars ?? sleeve.notional_usd ?? "—")}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

type MeasurementRow = {
  id?: string;
  name?: string;
  value?: string;
  status?: string;
};

export function MeasurementsPanel({ symbol }: { symbol: string }) {
  const [note, setNote] = useState(`Reading QM-01 through QM-08 for ${symbol}.`);
  const [rows, setRows] = useState<MeasurementRow[]>([]);
  const [feed, setFeed] = useState("unlabeled");

  useEffect(() => {
    let live = true;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/measurements/institutional?symbol=${encodeURIComponent(symbol)}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error(`Measurements returned HTTP ${response.status}`);
        const body = (await response.json()) as {
          measurements?: MeasurementRow[];
          candle_feed_source?: string;
          bars_read?: number;
          execution_permission?: string;
        };
        if (!live) return;
        setRows(body.measurements ?? []);
        setFeed(String(body.candle_feed_source ?? "unlabeled"));
        setNote(
          `${symbol} · ${body.bars_read ?? 0} bars · ${body.candle_feed_source ?? "unlabeled"} · permission ${body.execution_permission ?? "none"}`
        );
      } catch (error) {
        if (!live) return;
        setRows([]);
        setNote(error instanceof Error ? error.message : "Measurements failed.");
      }
    };
    void pull();
    return () => {
      live = false;
    };
  }, [symbol]);

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Candle measurements</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
      </div>
      <p className="clean-card-subtitle" style={{ margin: 0 }}>
        Feed {feed}. Funding, filings, and tick-to-trade latency stay unobserved on this call. Nothing here sends an order.
      </p>
      <table className="clean-table">
        <thead>
          <tr>
            <th>Id</th>
            <th>Measurement</th>
            <th>Value</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4}>Waiting for the measurement read.</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={String(row.id)}>
                <td className="mono-cell">{String(row.id ?? "—")}</td>
                <td>{String(row.name ?? "—")}</td>
                <td className="mono-cell">{String(row.value ?? "—")}</td>
                <td>{String(row.status ?? "—")}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function IdentityChecklist({
  traderId,
  cameraDriver,
  hardwareGuid,
  faceCount,
  biometricSimilarity,
  blinkPassed,
  headYawDeg,
  gazeOffScreenSec,
  concurrentOrderId,
  mobileRoomScan,
}: {
  traderId: string;
  cameraDriver: string;
  hardwareGuid: string;
  faceCount: number;
  biometricSimilarity: number;
  blinkPassed: boolean;
  headYawDeg: number;
  gazeOffScreenSec: number;
  concurrentOrderId: string;
  mobileRoomScan: boolean;
}) {
  const [note, setNote] = useState("This sends the checklist you picked. No camera is opened.");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      const response = await fetch("/api/proctoring/evaluate-frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trader_id: traderId,
          camera_driver: cameraDriver,
          hardware_guid: hardwareGuid,
          face_count: faceCount,
          biometric_match_score: biometricSimilarity,
          eye_blink_detected: blinkPassed,
          head_yaw_degrees: headYawDeg,
          gaze_off_screen_pct: Math.min(1, gazeOffScreenSec / 10),
          concurrent_order_id: concurrentOrderId,
          dual_camera_mobile_active: mobileRoomScan,
        }),
      });
      if (!response.ok) throw new Error(`Checklist returned HTTP ${response.status}`);
      const body = (await response.json()) as { evaluation?: { proctoring_status?: string; violations?: string[] } };
      const status = body.evaluation?.proctoring_status ?? "no status";
      const violations = body.evaluation?.violations ?? [];
      setNote(`${status}${violations.length ? ` · ${violations.join(", ")}` : ""}`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Checklist failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Identity checklist</h2>
          <p className="clean-card-subtitle">{note}</p>
        </div>
        <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void run()}>
          {busy ? "Checking…" : "Run checklist"}
        </button>
      </div>
    </div>
  );
}

export function TicketCheck({
  ready,
  compliant,
  detail,
}: {
  ready: boolean;
  compliant: boolean;
  detail: string;
}) {
  return (
    <div className="clean-card">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Would this ticket pass?</h2>
          <p className="clean-card-subtitle">Uses the order ticket on the cockpit and the control-plane account. Changing a toggle here does not rewrite the rulebook.</p>
        </div>
        <span className={`badge ${!ready ? "badge-amber" : compliant ? "badge-emerald" : "badge-danger"}`}>
          {!ready ? "WAITING" : compliant ? "PASSES" : "BLOCKED"}
        </span>
      </div>
      <p style={{ margin: 0, color: "#CBD5E1", fontSize: "13px" }}>{detail}</p>
    </div>
  );
}

type SliceForecast = {
  forecast_id: string;
  symbol: string;
  track: string;
  decision_time: string;
  target_time: string;
  action: string;
  predicted_class: string;
  confidence: number;
  edge: number;
  probabilities?: Record<string, number>;
  interval_low?: number | null;
  interval_high?: number | null;
  realized_return?: number | null;
  realized_class?: string | null;
  brier_score?: number | null;
  status: string;
  cost_bps: number;
  execution_permission: string;
};

type SliceTrade = {
  trade_id: string;
  forecast_id: string;
  symbol: string;
  side: string;
  created_at: string;
  requested_notional_usd: number;
  authorized_notional_usd?: number | null;
  control_plane_decision: string;
  violations_json?: string;
  status: string;
  realized_pnl_usd?: number | null;
  execution_permission: string;
};

type SliceLuckyMoment = {
  forecast_id: string;
  symbol: string;
  decision_time: string;
  action: string;
  confidence: number;
  realized_return: number;
  signed_gross_return: number;
  reason: string;
  caution: string;
};

type SliceChartBar = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type SliceChartMarker = {
  forecast_id: string;
  time: string;
  target_time: string;
  price: number;
  action: string;
  predicted_class: string;
  confidence: number;
  interval_low?: number | null;
  interval_high?: number | null;
};

type SliceChartPayload = {
  symbol: string;
  status?: string;
  bars: SliceChartBar[];
  markers: SliceChartMarker[];
  notice?: string;
  reason?: string;
  execution_permission: string;
};

type SliceScheduler = {
  running: boolean;
  symbols: string[];
  bucket_seconds: number;
  horizons?: number[];
  poll_seconds: number;
  initial_delay_seconds: number;
  last_check_at?: string | null;
  last_bar_at?: string | null;
  last_run_at?: string | null;
  runs: number;
  resolutions: number;
  skips: number;
  errors: number;
  last_error?: string | null;
  execution_permission: string;
};

type SliceStatus = {
  path_id: string;
  runs: number;
  forecasts: { total: number; open: number; resolved: number };
  resolved_direction_accuracy?: number | null;
  resolved_taken: number;
  mean_brier_score?: number | null;
  paper_trades: {
    proposed: number;
    authorized: number;
    rejected_or_not_proposed: number;
    resolved: number;
    net_pnl_usd?: number | null;
    wins: number;
    losses: number;
  };
  latest_run?: Record<string, unknown> | null;
  research_inputs?: {
    feature_names: string[];
    classes: string[];
    optional_challengers: Array<Record<string, unknown>>;
  };
  scheduler?: SliceScheduler;
  paper_account?: {
    status: string;
    current_equity_usd?: number;
    high_water_mark_usd?: number;
    starting_equity_usd?: number;
    open_positions?: number;
    gross_notional_usd?: number;
    correlated_exposure_usd?: number;
    sector_exposure_usd?: number;
    kill_switch_engaged?: boolean;
    books?: Record<string, { current_equity_usd?: number; open_positions?: number }>;
    restored_from_disk?: boolean;
    execution_permission: string;
  };
  execution_permission: string;
};

type SliceEvaluationRow = {
  symbol: string;
  horizon_steps: number;
  status?: string;
  bars?: number;
  selected_model_family?: string;
  walk_forward_status?: string;
  brier_score?: number | null;
  log_loss?: number | null;
  accuracy?: number | null;
  coverage?: number | null;
  rows?: number;
  taken?: number;
  direction_accuracy?: number | null;
  frequency_brier_score?: number | null;
  challenger_status?: string;
  challenger_brier_score?: number | null;
  baseline_selected?: boolean;
  reason?: string;
  execution_permission?: string;
};

type SliceEvaluation = {
  status: string;
  bucket_seconds: number;
  symbols: string[];
  horizons: number[];
  rows: SliceEvaluationRow[];
  scored_cells: number;
  cells: number;
  notice?: string;
  execution_permission: string;
};

type SliceRegimeMetrics = {
  status: string;
  rows: number;
  metrics?: {
    brier_score?: number | null;
    log_loss?: number | null;
    accuracy?: number | null;
  };
  notice?: string;
  execution_permission: string;
};

type SliceAblationRow = {
  family: string;
  status: string;
  removed_features: string[];
  metrics?: {
    brier_score?: number | null;
    log_loss?: number | null;
    accuracy?: number | null;
  };
  delta_brier_removed?: number;
  delta_log_loss_removed?: number;
  delta_accuracy_removed?: number;
  evidence?: string;
  regime_metrics?: Record<string, SliceRegimeMetrics>;
  execution_permission?: string;
};

type SliceAblation = {
  status: string;
  symbol: string;
  bars?: number;
  baseline?: {
    primary_model_family?: string | null;
    softmax_metrics?: SliceAblationRow["metrics"] | null;
    regime_metrics?: Record<string, SliceRegimeMetrics>;
  };
  ablations: SliceAblationRow[];
  notice?: string;
  execution_permission: string;
};

type SliceAblationMultiRow = {
  symbol: string;
  horizon_steps: number;
  status: string;
  bars?: number;
  baseline?: SliceAblation["baseline"];
  ablations?: SliceAblationRow[];
  supported_families?: string[];
  negative_families?: string[];
  inconclusive_families?: string[];
  execution_permission: string;
};

type SliceAblationMulti = {
  status: string;
  symbols: string[];
  horizons: number[];
  rows: SliceAblationMultiRow[];
  scored_cells: number;
  cells: number;
  notice?: string;
  execution_permission: string;
};

function sliceNumber(value: unknown, digits = 4): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

function slicePercent(value: unknown, digits = 2): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—";
}

function sliceTime(value: unknown): string {
  if (typeof value !== "string") return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

function SliceChartPanel({ chart }: { chart: SliceChartPayload | null }) {
  const bars = chart?.bars ?? [];
  if (bars.length === 0) {
    return (
      <p className="clean-card-subtitle" style={{ margin: 0 }}>
        {chart?.reason ?? "No authorized bars have been recorded for this symbol yet. Run the slice to populate the chart."}
      </p>
    );
  }
  const width = 960;
  const height = 280;
  const padTop = 18;
  const padBottom = 28;
  const padLeft = 10;
  const padRight = 76;
  const lows = bars.map((bar) => bar.low);
  const highs = bars.map((bar) => bar.high);
  const marker = chart?.markers?.[0];
  const intervalLowPrice = marker?.interval_low == null ? null : marker.price * (1 + marker.interval_low);
  const intervalHighPrice = marker?.interval_high == null ? null : marker.price * (1 + marker.interval_high);
  const candidates = [Math.min(...lows), Math.max(...highs), intervalLowPrice ?? Infinity, intervalHighPrice ?? -Infinity]
    .filter((value) => Number.isFinite(value));
  const floor = Math.min(...candidates);
  const ceiling = Math.max(...candidates);
  const span = Math.max(ceiling - floor, 1e-9);
  const y = (value: number) => padTop + ((ceiling - value) / span) * (height - padTop - padBottom);
  const step = (width - padLeft - padRight) / bars.length;
  const markerIndex = marker
    ? Math.max(0, bars.findIndex((bar) => bar.time === marker.time))
    : -1;
  const markerX = markerIndex >= 0 ? padLeft + step * (markerIndex + 0.5) : width - padRight;
  const markerColor = marker?.action === "long" ? "#34d399" : marker?.action === "short" ? "#f87171" : "#fbbf24";

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${chart?.symbol ?? "instrument"} authorized candles with recorded forecast marker`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        <line x1={padLeft} x2={width - padRight} y1={height - padBottom} y2={height - padBottom} stroke="#334155" strokeWidth="1" />
        {intervalLowPrice != null && intervalHighPrice != null ? (
          <rect
            x={Math.max(padLeft, markerX - step * 0.8)}
            y={y(Math.max(intervalLowPrice, intervalHighPrice))}
            width={step * 1.6}
            height={Math.max(2, Math.abs(y(intervalLowPrice) - y(intervalHighPrice)))}
            fill={markerColor}
            opacity="0.12"
          />
        ) : null}
        {bars.map((bar, index) => {
          const x = padLeft + step * (index + 0.5);
          const bullish = bar.close >= bar.open;
          const color = bullish ? "#34d399" : "#f87171";
          const bodyTop = y(Math.max(bar.open, bar.close));
          const bodyBottom = y(Math.min(bar.open, bar.close));
          return (
            <g key={bar.time}>
              <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} stroke={color} strokeWidth="1" opacity="0.8" />
              <rect
                x={x - Math.max(1, step * 0.26)}
                y={bodyTop}
                width={Math.max(2, step * 0.52)}
                height={Math.max(1, bodyBottom - bodyTop)}
                fill={color}
                opacity="0.85"
              />
            </g>
          );
        })}
        {marker ? (
          <>
            <line x1={markerX} x2={markerX} y1={padTop} y2={height - padBottom} stroke={markerColor} strokeWidth="1.5" strokeDasharray="5 4" />
            <circle cx={markerX} cy={y(marker.price)} r="5" fill={markerColor} stroke="#0f172a" strokeWidth="2" />
            <text x={Math.min(markerX + 8, width - padRight + 4)} y={Math.max(padTop + 10, y(marker.price) - 8)} fill={markerColor} fontSize="11">
              {marker.action.toUpperCase()} {slicePercent(marker.confidence, 1)}
            </text>
          </>
        ) : null}
        <text x={padLeft} y={height - 8} fill="#94a3b8" fontSize="10">{sliceTime(bars[0]?.time)}</text>
        <text x={width - padRight} y={height - 8} fill="#94a3b8" fontSize="10" textAnchor="end">{sliceTime(bars[bars.length - 1]?.time)}</text>
        <text x={width - padRight + 6} y={y(ceiling)} fill="#94a3b8" fontSize="10">{sliceNumber(ceiling, 2)}</text>
        <text x={width - padRight + 6} y={y(floor)} fill="#94a3b8" fontSize="10">{sliceNumber(floor, 2)}</text>
      </svg>
      <p className="clean-card-subtitle" style={{ margin: "8px 0 0" }}>
        {chart?.notice ?? "Bars are authorized observations; the marker is the recorded forecast decision."}
      </p>
    </div>
  );
}

export function PredictionLedgerPage({ symbol }: { symbol: string }) {
  const [status, setStatus] = useState<SliceStatus | null>(null);
  const [forecasts, setForecasts] = useState<SliceForecast[]>([]);
  const [trades, setTrades] = useState<SliceTrade[]>([]);
  const [lucky, setLucky] = useState<SliceLuckyMoment[]>([]);
  const [chart, setChart] = useState<SliceChartPayload | null>(null);
  const [evaluation, setEvaluation] = useState<SliceEvaluation | null>(null);
  const [ablation, setAblation] = useState<SliceAblation | null>(null);
  const [ablationMatrix, setAblationMatrix] = useState<SliceAblationMulti | null>(null);
  const [scheduler, setScheduler] = useState<SliceScheduler | null>(null);
  const [note, setNote] = useState("Loading persistent forecasts. No order is sent by this page.");
  const [busy, setBusy] = useState<"run" | "resolve" | "evaluate" | "ablate" | "ablate-matrix" | null>(null);

  const load = useCallback(async () => {
    const [statusResponse, forecastResponse, tradeResponse, luckyResponse, chartResponse] = await Promise.all([
      fetch("/api/research/vertical-slice/status", { cache: "no-store" }),
      fetch("/api/research/vertical-slice/forecasts?limit=30", { cache: "no-store" }),
      fetch("/api/research/vertical-slice/paper-trades?limit=30", { cache: "no-store" }),
      fetch("/api/research/vertical-slice/lucky-moments?limit=12", { cache: "no-store" }),
      fetch(`/api/research/vertical-slice/chart?symbol=${encodeURIComponent(symbol)}&limit=160`, { cache: "no-store" }),
    ]);
    if (!statusResponse.ok) throw new Error(`Ledger status returned HTTP ${statusResponse.status}`);
    const statusBody = (await statusResponse.json()) as SliceStatus;
    const forecastBody = forecastResponse.ok
      ? ((await forecastResponse.json()) as { forecasts?: SliceForecast[] })
      : { forecasts: [] };
    const tradeBody = tradeResponse.ok
      ? ((await tradeResponse.json()) as { paper_trades?: SliceTrade[] })
      : { paper_trades: [] };
    const luckyBody = luckyResponse.ok
      ? ((await luckyResponse.json()) as { lucky_moments?: SliceLuckyMoment[] })
      : { lucky_moments: [] };
    const chartBody = chartResponse.ok
      ? ((await chartResponse.json()) as SliceChartPayload)
      : null;
    setStatus(statusBody);
    if (statusBody.scheduler) setScheduler(statusBody.scheduler);
    setForecasts(forecastBody.forecasts ?? []);
    setTrades(tradeBody.paper_trades ?? []);
    setLucky(luckyBody.lucky_moments ?? []);
    setChart(chartBody);
    setNote(String(statusBody.latest_run ? "Ledger loaded from SQLite. Forecast and paper P&L are separate." : "No run has been recorded yet. Run the slice to fetch authorized public candles."));
  }, [symbol]);

  useEffect(() => {
    void load().catch((error: unknown) => setNote(error instanceof Error ? error.message : "Ledger failed to load."));
  }, [load]);

  useEffect(() => {
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch("/api/research/vertical-slice/scheduler", { cache: "no-store" });
        if (response.ok && active) setScheduler((await response.json()) as SliceScheduler);
      } catch {
        // Keep the last known scheduler status; the research ledger is unchanged.
      }
    };
    void pull();
    const timer = setInterval(pull, 15_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  const run = async () => {
    setBusy("run");
    setNote(`Fetching authorized public candles for ${symbol} and recording a point-in-time forecast…`);
    try {
      const response = await fetch("/api/research/vertical-slice/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: [symbol], bucket_seconds: 86400, horizon_steps: 1 }),
      });
      if (!response.ok) throw new Error(`Run returned HTTP ${response.status}`);
      const body = (await response.json()) as { symbols?: Array<Record<string, unknown>> };
      const first = body.symbols?.[0];
      setNote(first?.status === "forecast_recorded" ? "Forecast recorded. Paper authorization is shown below." : `Run status: ${String(first?.status ?? "unknown")}.`);
      await load();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Run failed.");
    } finally {
      setBusy(null);
    }
  };

  const resolve = async () => {
    setBusy("resolve");
    setNote(`Resolving open forecasts for ${symbol} with the latest public close…`);
    try {
      const response = await fetch("/api/research/vertical-slice/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: [symbol] }),
      });
      if (!response.ok) throw new Error(`Resolve returned HTTP ${response.status}`);
      const body = (await response.json()) as { count?: number };
      setNote(`${body.count ?? 0} forecast(s) resolved. Paper accounting remains separate from forecast accuracy.`);
      await load();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Resolve failed.");
    } finally {
      setBusy(null);
    }
  };

  const evaluate = async () => {
    setBusy("evaluate");
    setNote(`Evaluating purged walk-forward evidence for ${symbol} across horizons 1, 5, and 20. This creates no paper trades.`);
    try {
      const response = await fetch("/api/research/vertical-slice/evaluate-multi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: [symbol], bucket_seconds: 86400, horizon_steps: [1, 5, 20] }),
      });
      if (!response.ok) throw new Error(`Evaluation returned HTTP ${response.status}`);
      const body = (await response.json()) as SliceEvaluation;
      setEvaluation(body);
      setNote(`${body.scored_cells} of ${body.cells} symbol/horizon cells scored. Evaluation-only; the production ledger was not changed.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Evaluation failed.");
    } finally {
      setBusy(null);
    }
  };

  const ablate = async () => {
    setBusy("ablate");
    setNote(`Ablating feature families for ${symbol}. Each family is removed and retrained on the same purged folds; no forecasts or trades are created.`);
    try {
      const response = await fetch("/api/research/vertical-slice/feature-ablation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, bucket_seconds: 86400, horizon_steps: 1 }),
      });
      if (!response.ok) throw new Error(`Ablation returned HTTP ${response.status}`);
      const body = (await response.json()) as SliceAblation & { status?: string; reason?: string };
      if (!Array.isArray(body.ablations)) {
        setAblation(null);
        setNote(`Ablation not run: ${String(body.reason ?? body.status ?? "no result").replaceAll("_", " ")}. Nothing was changed.`);
        return;
      }
      setAblation(body);
      setNote(`${body.ablations.length} feature families measured. Ablation is read-only; the forecast ledger was not changed.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Feature ablation failed.");
    } finally {
      setBusy(null);
    }
  };

  const ablateMatrix = async () => {
    setBusy("ablate-matrix");
    setNote(`Ablating feature families across ${symbol}, ETH-USD, and SPY at horizons 1 and 5. Every cell is read-only and uses purged walk-forward evidence.`);
    try {
      const response = await fetch("/api/research/vertical-slice/feature-ablation-multi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbols: [symbol, "ETH-USD", "SPY"], bucket_seconds: 86400, horizon_steps: [1, 5], include_session: true, include_cross_asset: true }),
      });
      if (!response.ok) throw new Error(`Ablation matrix returned HTTP ${response.status}`);
      const body = (await response.json()) as SliceAblationMulti & { status?: string; reason?: string };
      if (!Array.isArray(body.rows)) {
        setAblationMatrix(null);
        setNote(`Ablation matrix not run: ${String(body.reason ?? body.status ?? "no result").replaceAll("_", " ")}. Nothing was changed.`);
        return;
      }
      setAblationMatrix(body);
      setNote(`${body.scored_cells} of ${body.cells} symbol/horizon cells scored. No forecasts, trades, or order permission were created.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Ablation matrix failed.");
    } finally {
      setBusy(null);
    }
  };

  const latestRun = status?.latest_run;
  const runSymbols = Array.isArray(latestRun?.symbols) ? (latestRun.symbols as Array<Record<string, unknown>>) : [];
  const symbolRun = runSymbols.find((row) => row.symbol === symbol) ?? runSymbols[0];
  const latestForecast = symbolRun?.forecast as Record<string, unknown> | undefined;
  const latestFeatures = latestForecast?.features as Record<string, number> | undefined;
  const contributions = Array.isArray(latestForecast?.feature_contributions)
    ? (latestForecast.feature_contributions as Array<Record<string, unknown>>)
    : [];
  const latestProbabilities = latestForecast?.probabilities as Record<string, number> | undefined;
  const walkForward = symbolRun?.walk_forward as Record<string, unknown> | undefined;
  const modelMetrics = walkForward?.model as Record<string, unknown> | undefined;
  const modelReport = symbolRun?.model as Record<string, unknown> | undefined;
  const modelFamily = String(modelReport?.model_family ?? walkForward?.selected_model_family ?? "not recorded");
  const challengerReport = walkForward?.xgboost_challenger as Record<string, unknown> | undefined;
  const challengerMetrics = challengerReport?.model as Record<string, unknown> | undefined;
  const limitations = Array.isArray(latestRun?.limitations) ? (latestRun.limitations as string[]) : [];
  const challengers = Array.isArray(latestRun?.optional_challengers)
    ? (latestRun.optional_challengers as Array<Record<string, unknown>>)
    : status?.research_inputs?.optional_challengers ?? [];

  return (
    <div className="clean-stack">
      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Prediction ledger · {symbol}</h2>
            <p className="clean-card-subtitle">{note}</p>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy !== null} onClick={() => void run()}>
              {busy === "run" ? "Running…" : "Run forecast"}
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={busy !== null} onClick={() => void resolve()}>
              {busy === "resolve" ? "Resolving…" : "Resolve open"}
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={busy !== null} onClick={() => void evaluate()}>
              {busy === "evaluate" ? "Evaluating…" : "Evaluate horizons"}
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={busy !== null} onClick={() => void ablate()}>
              {busy === "ablate" ? "Ablating…" : "Ablate features"}
            </button>
            <button type="button" className="btn btn-outline btn-sm" disabled={busy !== null} onClick={() => void ablateMatrix()}>
              {busy === "ablate-matrix" ? "Ablating matrix…" : "Ablate matrix"}
            </button>
          </div>
        </div>
        <div className="clean-kpi-row">
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Forecasts</span>
            <span className="clean-kpi-value">{status?.forecasts.total ?? 0}</span>
            <span className="clean-kpi-sub">{status?.forecasts.open ?? 0} open · {status?.forecasts.resolved ?? 0} resolved</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Mean Brier</span>
            <span className="clean-kpi-value">{sliceNumber(status?.mean_brier_score, 5)}</span>
            <span className="clean-kpi-sub">Multi-class probability score, lower is better</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Direction accuracy</span>
            <span className="clean-kpi-value">{status?.resolved_direction_accuracy == null ? "—" : slicePercent(status.resolved_direction_accuracy, 1)}</span>
            <span className="clean-kpi-sub">{status?.resolved_taken ?? 0} taken forecasts resolved</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Paper P&amp;L</span>
            <span className="clean-kpi-value">{status?.paper_trades.net_pnl_usd == null ? "—" : `$${sliceNumber(status.paper_trades.net_pnl_usd, 2)}`}</span>
            <span className="clean-kpi-sub">{status?.paper_trades.authorized ?? 0} authorized · {status?.paper_trades.rejected_or_not_proposed ?? 0} blocked/abstained</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Paper equity</span>
            <span className="clean-kpi-value">${sliceNumber(status?.paper_account?.current_equity_usd, 2)}</span>
            <span className="clean-kpi-sub">
              {status?.paper_account?.open_positions ?? 0} open / {status?.paper_account?.restored_from_disk ? "restored" : "fresh"} / gross ${sliceNumber(status?.paper_account?.gross_notional_usd, 2)}
              {status?.paper_account?.books ? ` / ${Object.keys(status.paper_account.books).length} horizon books` : ""}
            </span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Permission</span>
            <span className="clean-kpi-value" style={{ fontSize: "15px" }}>{status?.execution_permission ?? "none"}</span>
            <span className="clean-kpi-sub">Research only. Control plane is the sole order gate.</span>
          </div>
        </div>
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Multi-horizon evidence</h2>
            <p className="clean-card-subtitle">
              {evaluation
                ? evaluation.notice ?? "Evaluation-only matrix. No paper trades or order permission were created."
                : "Evaluate the same symbol across 1, 5, and 20 completed bars. This uses an isolated in-memory ledger and does not create paper trades."}
            </p>
          </div>
          {evaluation ? (
            <span className="badge badge-slate">{evaluation.scored_cells} / {evaluation.cells} scored</span>
          ) : null}
        </div>
        {!evaluation ? (
          <p className="clean-card-subtitle" style={{ margin: 0 }}>Select Evaluate horizons to compare purged walk-forward evidence against frequency and uniform baselines.</p>
        ) : (
          <table className="clean-table">
            <thead>
              <tr>
                <th>Horizon</th><th>Status</th><th>Selected</th><th>Brier</th><th>Log loss</th>
                <th>Accuracy</th><th>Freq. baseline</th><th>XGBoost</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.rows.map((row) => (
                <tr key={`${row.symbol}-${row.horizon_steps}`}>
                  <td>{row.horizon_steps} bar{row.horizon_steps === 1 ? "" : "s"}</td>
                  <td>{row.walk_forward_status ?? row.status ?? "unavailable"}</td>
                  <td>
                    <span className={`badge ${row.baseline_selected ? "badge-amber" : "badge-emerald"}`}>
                      {row.selected_model_family ?? "not scored"}
                    </span>
                  </td>
                  <td>{sliceNumber(row.brier_score, 5)}</td>
                  <td>{sliceNumber(row.log_loss, 5)}</td>
                  <td>{slicePercent(row.accuracy, 1)}</td>
                  <td>{sliceNumber(row.frequency_brier_score, 5)}</td>
                  <td>{row.challenger_status === "scored" ? sliceNumber(row.challenger_brier_score, 5) : row.challenger_status ?? "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Feature-family ablation</h2>
            <p className="clean-card-subtitle">
              {ablation
                ? ablation.notice ?? "Read-only ablation evidence."
                : "Remove one feature family at a time and retrain on the same purged walk-forward folds. Positive delta Brier means the family helped out of sample; small deltas are inconclusive."}
            </p>
          </div>
          {ablation ? (
            <span className="badge badge-slate">{ablation.ablations.length} families</span>
          ) : null}
        </div>
        {!ablation ? (
          <p className="clean-card-subtitle" style={{ margin: 0 }}>
            Select Ablate features to compare momentum, trend, volatility, positioning, and volume families. This creates no forecasts, trades, or order permission.
          </p>
        ) : (
          <table className="clean-table">
            <thead>
              <tr>
                <th>Family</th><th>Removed</th><th>Status</th><th>Brier</th>
                <th>Δ Brier when removed</th><th>Δ Log loss</th><th>Δ Accuracy</th><th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {ablation.ablations.map((row) => (
                <tr key={row.family}>
                  <td>{row.family}</td>
                  <td>{row.removed_features.join(", ")}</td>
                  <td>{row.status}</td>
                  <td>{sliceNumber(row.metrics?.brier_score, 5)}</td>
                  <td>{sliceNumber(row.delta_brier_removed, 5)}</td>
                  <td>{sliceNumber(row.delta_log_loss_removed, 5)}</td>
                  <td>{slicePercent(row.delta_accuracy_removed, 1)}</td>
                  <td>{row.evidence ?? "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Cross-symbol ablation matrix</h2>
            <p className="clean-card-subtitle">
              {ablationMatrix
                ? ablationMatrix.notice ?? "Read-only matrix. No forecasts or trades were created."
                : "Run the same feature-family ablation across selected symbols and horizons. Each cell uses purged walk-forward evidence and is read-only."}
            </p>
          </div>
          {ablationMatrix ? (
            <span className="badge badge-slate">{ablationMatrix.scored_cells} / {ablationMatrix.cells} scored</span>
          ) : null}
        </div>
        {!ablationMatrix ? (
          <p className="clean-card-subtitle" style={{ margin: 0 }}>
            Select Ablate matrix to compare {symbol}, ETH-USD, and SPY at 1 and 5 bars, including session and cross-asset research features. Small deltas stay inconclusive and do not change the production feature set.
          </p>
        ) : (
          <table className="clean-table">
            <thead>
              <tr>
                <th>Symbol</th><th>Horizon</th><th>Status</th><th>Baseline</th><th>Regimes</th>
                <th>Supported families</th><th>Negative</th><th>Inconclusive</th>
              </tr>
            </thead>
            <tbody>
              {ablationMatrix.rows.map((row) => (
                <tr key={`${row.symbol}-${row.horizon_steps}`}>
                  <td>{row.symbol}</td>
                  <td>{row.horizon_steps} bar{row.horizon_steps === 1 ? "" : "s"}</td>
                  <td>{row.status}</td>
                  <td>{row.baseline?.primary_model_family ?? "not scored"}</td>
                  <td>{Object.keys(row.baseline?.regime_metrics ?? {}).length}</td>
                  <td>{row.supported_families?.join(", ") || "none"}</td>
                  <td>{row.negative_families?.join(", ") || "none"}</td>
                  <td>{row.inconclusive_families?.join(", ") || "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Autonomous scheduler</h2>
            <p className="clean-card-subtitle">
              Checks completed bars, runs the slice at most once per bar, and resolves due forecasts. It never authorizes an order.
            </p>
          </div>
          <span className={`badge ${scheduler?.running ? "badge-emerald" : "badge-slate"}`}>
            {scheduler?.running ? "running" : "stopped"}
          </span>
        </div>
        <div className="clean-kpi-row">
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Last check</span>
            <span className="clean-kpi-value" style={{ fontSize: "13px" }}>{sliceTime(scheduler?.last_check_at)}</span>
            <span className="clean-kpi-sub">Every {scheduler?.poll_seconds ?? "?"}s / {scheduler?.bucket_seconds ?? "?"}s bars / horizons {scheduler?.horizons?.join(", ") ?? "1"}</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Last completed bar</span>
            <span className="clean-kpi-value" style={{ fontSize: "13px" }}>{sliceTime(scheduler?.last_bar_at)}</span>
            <span className="clean-kpi-sub">Last run {sliceTime(scheduler?.last_run_at)}</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Runs / resolutions</span>
            <span className="clean-kpi-value">{scheduler?.runs ?? 0} / {scheduler?.resolutions ?? 0}</span>
            <span className="clean-kpi-sub">{scheduler?.skips ?? 0} already-processed skips</span>
          </div>
          <div className="clean-kpi-card">
            <span className="clean-kpi-label">Errors</span>
            <span className="clean-kpi-value">{scheduler?.errors ?? 0}</span>
            <span className="clean-kpi-sub">{scheduler?.last_error ?? "No scheduler error recorded"}</span>
          </div>
        </div>
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Synchronized observations and forecast marker</h2>
            <p className="clean-card-subtitle">Authorized bars are plotted with the recorded decision time and conditional 5–95% interval. The marker is not a TradingView-native annotation.</p>
          </div>
        </div>
        <SliceChartPanel chart={chart} />
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">What the model sees right now</h2>
            <p className="clean-card-subtitle">
              Latest recorded feature vector and the selected model&apos;s contribution to the chosen class. Selected: {modelFamily}. Contributions are not causal effects.
            </p>
          </div>
          <span className={`badge ${latestForecast?.action === "long" ? "badge-emerald" : latestForecast?.action === "short" ? "badge-danger" : "badge-amber"}`}>
            {String(latestForecast?.action ?? "no forecast").toUpperCase()}
          </span>
        </div>
        {!latestFeatures ? (
          <p className="clean-card-subtitle" style={{ margin: 0 }}>Run the slice to populate the point-in-time feature snapshot. Missing data is not replaced with a synthetic vector.</p>
        ) : (
          <>
            <div className="clean-kpi-row">
              <div className="clean-kpi-card">
                <span className="clean-kpi-label">Decision / target</span>
                <span className="clean-kpi-value" style={{ fontSize: "14px" }}>{sliceTime(latestForecast?.decision_time)}</span>
                <span className="clean-kpi-sub">Target {sliceTime(latestForecast?.target_time)}</span>
              </div>
              <div className="clean-kpi-card">
                <span className="clean-kpi-label">P(down) / P(neutral) / P(up)</span>
                <span className="clean-kpi-value" style={{ fontSize: "15px" }}>
                  {slicePercent(latestProbabilities?.down, 1)} / {slicePercent(latestProbabilities?.neutral, 1)} / {slicePercent(latestProbabilities?.up, 1)}
                </span>
                <span className="clean-kpi-sub">Confidence {slicePercent(latestForecast?.confidence, 1)} · edge {sliceNumber(latestForecast?.edge, 3)}</span>
              </div>
              <div className="clean-kpi-card">
                <span className="clean-kpi-label">Empirical 5–95% interval</span>
                <span className="clean-kpi-value" style={{ fontSize: "15px" }}>{slicePercent(latestForecast?.interval_low, 2)} to {slicePercent(latestForecast?.interval_high, 2)}</span>
                <span className="clean-kpi-sub">Conditional return quantiles, not a guarantee</span>
              </div>
              <div className="clean-kpi-card">
                <span className="clean-kpi-label">Walk-forward Brier</span>
                <span className="clean-kpi-value">{sliceNumber(modelMetrics?.brier_score, 5)}</span>
                <span className="clean-kpi-sub">{String(walkForward?.status ?? "not scored")} · {String(modelMetrics?.rows ?? "—")} out-of-sample rows</span>
              </div>
              <div className="clean-kpi-card">
                <span className="clean-kpi-label">XGBoost Brier</span>
                <span className="clean-kpi-value">{challengerMetrics ? sliceNumber(challengerMetrics.brier_score, 5) : "n/a"}</span>
                <span className="clean-kpi-sub">{String(challengerReport?.status ?? "not recorded")} / {String(challengerMetrics?.rows ?? "n/a")} rows</span>
              </div>
            </div>
            <table className="clean-table">
              <thead>
                <tr><th>Feature</th><th>Value</th><th>Contribution</th><th>Method</th></tr>
              </thead>
              <tbody>
                {contributions.length === 0
                  ? Object.entries(latestFeatures).map(([name, value]) => (
                      <tr key={name}><td>{name}</td><td>{sliceNumber(value, 6)}</td><td>—</td><td>—</td></tr>
                    ))
                  : contributions.map((row) => (
                      <tr key={String(row.feature)}>
                        <td>{String(row.feature)}</td>
                        <td>{sliceNumber(row.value, 6)}</td>
                        <td>{sliceNumber(row.contribution, 6)}</td>
                        <td>{String(row.method ?? "linear_logit")}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </>
        )}
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Forecast ledger</h2>
            <p className="clean-card-subtitle">Every row is persisted before resolution. Forecast error and paper execution are separate.</p>
          </div>
        </div>
        <table className="clean-table">
          <thead>
            <tr><th>Decision</th><th>Symbol</th><th>Action</th><th>Confidence</th><th>Up / down</th><th>Interval</th><th>Realized</th><th>Brier</th><th>Status</th></tr>
          </thead>
          <tbody>
            {forecasts.length === 0 ? (
              <tr><td colSpan={9}>No forecasts recorded.</td></tr>
            ) : forecasts.map((row) => (
              <tr key={row.forecast_id}>
                <td>{sliceTime(row.decision_time)}</td>
                <td>{row.symbol} · {row.track}</td>
                <td>{row.action}</td>
                <td>{slicePercent(row.confidence, 1)}</td>
                <td>{slicePercent(row.probabilities?.up, 1)} / {slicePercent(row.probabilities?.down, 1)}</td>
                <td>{slicePercent(row.interval_low, 2)} to {slicePercent(row.interval_high, 2)}</td>
                <td>{slicePercent(row.realized_return, 2)}</td>
                <td>{sliceNumber(row.brier_score, 5)}</td>
                <td>{row.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Paper authorizations</h2>
            <p className="clean-card-subtitle">Only ActionableControlPlaneEngine can authorize. A rejected proposal is recorded, not executed.</p>
          </div>
        </div>
        <table className="clean-table">
          <thead>
            <tr><th>Created</th><th>Symbol</th><th>Side</th><th>Requested</th><th>Authorized</th><th>Decision</th><th>Status</th><th>Paper P&amp;L</th></tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={8}>No paper authorizations recorded.</td></tr>
            ) : trades.map((row) => (
              <tr key={row.trade_id}>
                <td>{sliceTime(row.created_at)}</td>
                <td>{row.symbol}</td>
                <td>{row.side}</td>
                <td>${sliceNumber(row.requested_notional_usd, 2)}</td>
                <td>{row.authorized_notional_usd == null ? "—" : `$${sliceNumber(row.authorized_notional_usd, 2)}`}</td>
                <td>{row.control_plane_decision}</td>
                <td>{row.status}</td>
                <td>{row.realized_pnl_usd == null ? "—" : `$${sliceNumber(row.realized_pnl_usd, 2)}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Lucky moments</h2>
            <p className="clean-card-subtitle">Favorable outcomes with weak confidence or moves outside the expected interval. These may be luck, not repeatable skill.</p>
          </div>
        </div>
        {lucky.length === 0 ? (
          <p className="clean-card-subtitle" style={{ margin: 0 }}>No low-confidence wins or out-of-interval wins have resolved yet.</p>
        ) : (
          <table className="clean-table">
            <thead><tr><th>Decision</th><th>Symbol</th><th>Action</th><th>Confidence</th><th>Signed return</th><th>Reason</th><th>Caveat</th></tr></thead>
            <tbody>
              {lucky.map((row) => (
                <tr key={row.forecast_id}>
                  <td>{sliceTime(row.decision_time)}</td>
                  <td>{row.symbol}</td>
                  <td>{row.action}</td>
                  <td>{slicePercent(row.confidence, 1)}</td>
                  <td>{slicePercent(row.signed_gross_return, 2)}</td>
                  <td>{row.reason}</td>
                  <td>{row.caution}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="clean-card">
        <div className="clean-card-header">
          <div>
            <h2 className="clean-card-title">Evidence limits and challengers</h2>
            <p className="clean-card-subtitle">Optional packages are reported as unavailable rather than replaced with invented metrics.</p>
          </div>
        </div>
        <ul style={{ margin: "0 0 12px 18px", color: "#CBD5E1", fontSize: "13px" }}>
          {limitations.map((line) => <li key={line}>{line}</li>)}
          {limitations.length === 0 ? <li>Run the slice to record measured limitations.</li> : null}
        </ul>
        <table className="clean-table">
          <thead><tr><th>Challenger</th><th>Status</th><th>Version</th><th>Reason</th></tr></thead>
          <tbody>
            {challengers.length === 0 ? (
              <tr><td colSpan={4}>No optional challenger status recorded.</td></tr>
            ) : challengers.map((row) => (
              <tr key={String(row.name)}>
                <td>{String(row.name)}</td>
                <td>{String(row.status)}</td>
                <td>{String(row.version ?? "—")}</td>
                <td>{String(row.reason ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
