"use client";

import { useEffect, useState } from "react";

type LockedOpportunity = {
  opportunity_locked?: boolean;
  scenario_id?: string;
  scenario_name?: string;
  action?: string;
  conviction?: number;
  entry_price?: number;
  stop_loss_price?: number;
  take_profit_price?: number;
  trigger_summary?: string;
  execution_permission?: string;
};

type LivePrediction = {
  symbol?: string;
  status?: string;
  data_mode?: string;
  notice?: string;
  as_of?: string;
  feed_source?: string;
  spot_price?: number;
  model_id?: string;
  direction?: string;
  calibrated_probability?: number;
  locked_whale_opportunity?: LockedOpportunity;
  live_microstructure?: { vpin?: number; ofi?: number; latency_ms?: number; ring_buffer_size?: number };
  execution_permission?: string;
};

type ObserverRow = {
  symbol?: string;
  status?: string;
  model_status?: string;
  feed_status?: string;
  feed_origin?: string;
  bucket_seconds?: number;
  bars_read?: number;
  samples_learned?: number;
  last_bar_close?: string;
  last_checked_at?: string;
  feed_age_seconds?: number;
  direction?: string;
  probability_up?: number | null;
  prediction_at?: string | null;
  warmup_remaining?: number | null;
  notice?: string;
};

type ObserverStatus = {
  state?: string;
  coverage_status?: string;
  sampling_enabled?: boolean;
  last_cycle_at?: string;
  symbols?: ObserverRow[];
};

type TrainingStatus = {
  status?: string;
  cycle?: number;
  trained_at?: string;
  next_fit_at?: string;
  execution_permission?: string;
};

const number = (value: number | undefined, digits = 2) =>
  value == null || !Number.isFinite(value) ? "Unavailable" : value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });

const stamped = (value: string | undefined) => (value ? new Date(value).toLocaleString() : "Not yet");

export function LiveModelLockPanel({ symbol = "BTC-USD" }: { symbol?: string }) {
  const [prediction, setPrediction] = useState<LivePrediction | null>(null);
  const [observer, setObserver] = useState<ObserverStatus | null>(null);
  const [training, setTraining] = useState<TrainingStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let predictionTimer = 0;
    let observerTimer = 0;
    let trainingTimer = 0;

    const pullPrediction = async () => {
      try {
        const response = await fetch(`/api/market/live-ai-prediction?symbol=${encodeURIComponent(symbol)}&allow_network=true`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Live prediction returned ${response.status}`);
        const body = (await response.json()) as LivePrediction;
        if (!controller.signal.aborted) {
          setPrediction(body);
          setError("");
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Live prediction unavailable.");
      } finally {
        if (!controller.signal.aborted) predictionTimer = window.setTimeout(pullPrediction, 5000);
      }
    };

    const pullObserver = async () => {
      try {
        const response = await fetch("/api/ml/live-observer/status", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`Observer status returned ${response.status}`);
        const body = (await response.json()) as ObserverStatus;
        if (!controller.signal.aborted) setObserver(body);
      } catch {
        if (!controller.signal.aborted) setObserver(null);
      } finally {
        if (!controller.signal.aborted) observerTimer = window.setTimeout(pullObserver, 5000);
      }
    };

    const pullTraining = async () => {
      try {
        const response = await fetch("/api/ml/live-train/status", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`Training status returned ${response.status}`);
        const body = (await response.json()) as TrainingStatus;
        if (!controller.signal.aborted) setTraining(body);
      } catch {
        if (!controller.signal.aborted) setTraining(null);
      } finally {
        if (!controller.signal.aborted) trainingTimer = window.setTimeout(pullTraining, 15000);
      }
    };

    void pullPrediction();
    void pullObserver();
    void pullTraining();
    return () => {
      controller.abort();
      window.clearTimeout(predictionTimer);
      window.clearTimeout(observerTimer);
      window.clearTimeout(trainingTimer);
    };
  }, [symbol]);

  const row = observer?.symbols?.find((item) => item.symbol?.toUpperCase() === symbol.toUpperCase());
  const locked = prediction?.locked_whale_opportunity;
  const source = prediction?.feed_source ?? row?.feed_origin ?? "Waiting for the public feed";
  const modelState = row?.model_status ?? row?.status ?? "waiting";
  const feedState = row?.feed_status ?? "waiting";
  const permission = prediction?.execution_permission ?? locked?.execution_permission ?? "none";

  return (
    <section className="clean-card" aria-label="Live model lock">
      <div className="clean-card-header">
        <div>
          <h2 className="clean-card-title">Live model lock · {symbol}</h2>
          <p className="clean-card-subtitle">
            The model reads authorized public market data in real time. TradingView is a display layer only; its candles are not exported into the model.
          </p>
        </div>
        <span className={`badge ${prediction?.data_mode === "synthetic" ? "badge-danger" : row?.status === "observing" || modelState === "learning" ? "badge-emerald" : "badge-slate"}`}>
          {error ? "Feed error" : prediction?.data_mode === "synthetic" ? "Synthetic fixture" : feedState}
        </span>
      </div>

      {error ? <p role="status" className="model-flow-warning">{error} Showing the last successful read.</p> : null}
      {prediction?.data_mode === "synthetic" ? (
        <p role="status" className="model-flow-warning">
          {prediction.notice ?? "This is a labeled offline fixture, not observed live market data."}
        </p>
      ) : null}

      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Model price (15m candles)</span>
          <span className="clean-kpi-value">{number(prediction?.spot_price)}</span>
          <span className="clean-kpi-sub">{source}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Model direction</span>
          <span className="clean-kpi-value">{prediction?.direction ?? "Waiting"}</span>
          <span className="clean-kpi-sub">P(up) {number(prediction?.calibrated_probability == null ? undefined : prediction.calibrated_probability * 100, 1)}% · {prediction?.model_id ?? "model loading"}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Locked scenario</span>
          <span className="clean-kpi-value">{locked?.opportunity_locked ? locked.action ?? "LOCKED" : "No lock"}</span>
          <span className="clean-kpi-sub">{locked?.scenario_id ?? "Waiting for a qualifying setup"} {locked?.scenario_name ? `· ${locked.scenario_name}` : ""}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Real-time observer</span>
          <span className="clean-kpi-value">{row?.direction ?? "Waiting"}</span>
          <span className="clean-kpi-sub">P(up) {number(row?.probability_up == null ? undefined : row.probability_up * 100, 1)}% · {row?.samples_learned ?? 0} outcomes · {row?.bars_read ?? 0} completed bars</span>
        </div>
      </div>

      <div className="clean-kpi-row">
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Entry / stop / target</span>
          <span className="clean-kpi-value" style={{ fontSize: "15px" }}>
            {number(locked?.entry_price)} / {number(locked?.stop_loss_price)} / {number(locked?.take_profit_price)}
          </span>
          <span className="clean-kpi-sub">Research levels only</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Feed</span>
          <span className="clean-kpi-value" style={{ fontSize: "15px" }}>{feedState}</span>
          <span className="clean-kpi-sub">{row?.feed_origin ?? "public source"} · {row?.bucket_seconds != null ? `${row.bucket_seconds}s bars` : "resolution pending"} · age {row?.feed_age_seconds == null ? "unknown" : `${number(row.feed_age_seconds, 1)}s`}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Desk fit</span>
          <span className="clean-kpi-value" style={{ fontSize: "15px" }}>{training?.status ?? "waiting"}</span>
          <span className="clean-kpi-sub">cycle {training?.cycle ?? 0} · trained {stamped(training?.trained_at)}</span>
        </div>
        <div className="clean-kpi-card">
          <span className="clean-kpi-label">Execution permission</span>
          <span className="clean-kpi-value" style={{ fontSize: "16px" }}>{permission}</span>
          <span className="clean-kpi-sub">Control plane remains the only order authority</span>
        </div>
      </div>

      <p className="clean-card-subtitle" style={{ margin: 0 }}>
        Latest read {stamped(prediction?.as_of)} · observer cycle {stamped(observer?.last_cycle_at)} · last bar close {stamped(row?.last_bar_close)}. {locked?.trigger_summary ?? "No locked trigger has been returned."}
      </p>
      <p className="clean-card-subtitle" style={{ margin: "6px 0 0" }}>
        Crypto uses the public Coinbase trade stream; equities use public Yahoo minute candles. A closed market or provider delay pauses learning instead of inventing data.
      </p>
    </section>
  );
}
