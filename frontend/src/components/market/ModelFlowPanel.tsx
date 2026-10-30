"use client";

import { useEffect, useRef, useState } from "react";
import { NavLink } from "../../nav/NavLink";

type Candle = { timestamp: string; open: number; high: number; low: number; close: number };
type FitRow = { symbol: string; status: string; bars: number; data_mode: string; promoted: boolean; gate_failures?: string[]; oos_sharpe_ratio?: number; oos_brier_score?: number; oos_max_drawdown_fraction?: number };
type Fit = { status?: string; cycle?: number; trained_at?: string; next_fit_at?: string; competition?: FitRow[]; open_market?: FitRow[]; model_notice?: string };
type ObserverMetrics = { samples_evaluated?: number; brier_score?: number; log_loss?: number; directional_accuracy?: number; baseline_brier_score?: number; baseline_log_loss?: number; scope?: string; validated?: boolean };
export type ModelRead = {
 as_of?: string;
 data_mode?: string;
 notice?: string;
 chart_track?: { picture?: string; follows?: string };
 active?: {
  symbol: string; bucket_seconds: number; bars_read: number; feed_origin: string; chart_source: string;
  online_observer?: { status: string; persistence?: string; warmup_remaining?: number; warmup_target?: number; samples_learned?: number; probability_up?: number; prediction_at?: string; feed_age_seconds?: number; notice?: string; horizon?: string; features_used?: string[]; rejected_bars?: number; feature_values?: number[]; weights?: number[]; metrics?: ObserverMetrics; recent_outcomes?: Array<{ predicted_at: string; resolved_at: string; probability_up: number; outcome: string }> };
  feed_health?: { connection?: string; receive_age_seconds?: number; trade_age_seconds?: number; exchange_to_receive_ms?: number; reconnects?: number; matches_received?: number; coverage?: string; delay_status?: string; delay_seconds?: number };
  notice?: string;
  direction: string; conviction?: number; model_id?: string; last_close?: number; last_bar_close?: string;
  stop_loss?: number; take_profit?: number; candles?: Candle[]; model_weights?: Record<string, number>;
  signal?: { telemetry?: Record<string, number | boolean | string> };
  bar_lock?: { window_timestamps?: string[]; invalidation_price?: number; objective_price?: number; average_true_range?: number };
  whale_moment?: { action?: string; scenario_id?: string; recommendation?: { stance?: string; summary?: string; reasons?: string[] } };
 };
};
const number = (value: unknown, digits = 4) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US", { maximumFractionDigits: digits }) : "—";
const time = (value?: string) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Not available";

function ModelCandles({ candles, locked }: { candles: Candle[]; locked: string[] }) {
 const [hover, setHover] = useState<number | null>(null);
 const container = useRef<HTMLDivElement>(null);
 const [width, setWidth] = useState(640);
 useEffect(() => {
  const element = container.current;
  if (!element) return;
  const observer = new ResizeObserver(entries => {
   const measured = entries[0]?.contentRect.width;
   if (measured) setWidth(Math.max(200, Math.floor(measured)));
  });
  observer.observe(element);
  return () => observer.disconnect();
 }, [candles.length > 0]);
 const plotWidth = width - 80;
 const bars = candles.slice(-Math.min(36, Math.max(8, Math.floor(plotWidth / 12))));
 if (!bars.length) return <p>No candles returned by the model.</p>;
 const low = Math.min(...bars.map(b => b.low));
 const high = Math.max(...bars.map(b => b.high));
 const span = Math.max(high - low, high * .0001);
 const y = (value: number) => 18 + (high - value) / span * 142;
 const selected = bars[Math.min(hover ?? bars.length - 1, bars.length - 1)];
 return <div ref={container} className="model-candles">
  <svg viewBox={`0 0 ${width} 190`} role="img" aria-label={`The latest ${bars.length} candles from the model input, sized to this panel. Highlighted columns belong to the causal swing.`}>
   {[0, .5, 1].map(v => <g key={v}><line x1="0" x2={plotWidth} y1={18 + v * 142} y2={18 + v * 142} stroke="#233244"/><text x={plotWidth + 4} y={22 + v * 142} fill="#94a3b8" fontSize="11">{number(high - v * span, 2)}</text></g>)}
   {bars.map((bar, index) => { const x = 8 + index * ((plotWidth - 16) / bars.length); const width = Math.max(3, (plotWidth - 16) / bars.length - 5); const color = bar.close >= bar.open ? "#00e6a0" : "#ff6c8d";
    return <g key={bar.timestamp} tabIndex={0} role="button" aria-label={`${time(bar.timestamp)} open ${bar.open} close ${bar.close}`} onMouseEnter={() => setHover(index)} onFocus={() => setHover(index)}>
     <title>{time(bar.timestamp)} · O {bar.open} H {bar.high} L {bar.low} C {bar.close}</title>
     <rect x={x - width / 2 - 2} y="8" width={width + 4} height="160" fill={locked.includes(bar.timestamp) ? "#174f51" : "transparent"}/>
     <line x1={x} x2={x} y1={y(bar.high)} y2={y(bar.low)} stroke={color}/>
     <rect x={x - width / 2} y={Math.min(y(bar.open), y(bar.close))} width={width} height={Math.max(1, Math.abs(y(bar.open) - y(bar.close)))} fill={color}/>
    </g>;
   })}
   <text x="0" y="185" fill="#94a3b8" fontSize="10">{new Date(bars[0].timestamp).toLocaleTimeString()}</text>
   <text x={plotWidth} y="185" textAnchor="end" fill="#94a3b8" fontSize="10">{new Date(bars[bars.length - 1].timestamp).toLocaleTimeString()}</text>
  </svg>
  <p className="model-muted">{time(selected.timestamp)} · O {number(selected.open)} · H {number(selected.high)} · L {number(selected.low)} · C {number(selected.close)}</p>
 </div>;
}

export function ModelFlowPanel({ symbol, bucketSeconds, intervalLabel, gap, snapshot, snapshotError = "", refreshSeconds }: { symbol: string; bucketSeconds: number; intervalLabel: string; gap?: string | null; snapshot?: ModelRead | null; snapshotError?: string; refreshSeconds?: number }) {
 const [polledRead, setRead] = useState<ModelRead | null>(null);
 const [fit, setFit] = useState<Fit | null>(null);
 const [pollError, setError] = useState("");
 const [busy, setBusy] = useState(false);
 const [expanded, setExpanded] = useState(false);
 const [capture, setCapture] = useState<Record<string, number> | null>(null);
 const externallyControlled = snapshot !== undefined;
 const read = externallyControlled ? snapshot : polledRead;
 const error = externallyControlled ? snapshotError : pollError;
 useEffect(() => {
  const controller = new AbortController(); let pending = false;
  setRead(null); setError("");
  if (gap || externallyControlled) return () => controller.abort();
  const pull = async () => {
   if (pending) return; pending = true;
   try {
    const response = await fetch(`/api/ml/chart-read?symbol=${encodeURIComponent(symbol)}&bucket_seconds=${bucketSeconds}`, { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Model read failed (${response.status})`);
    const body = await response.json() as ModelRead;
    if (!controller.signal.aborted) { setRead(body); setError(""); }
   } catch { if (!controller.signal.aborted) setError("Model read unavailable. The last snapshot is stale; retrying."); }
   finally { pending = false; }
  };
  void pull(); const timer = setInterval(pull, bucketSeconds === 1 ? 1000 : 4000);
  return () => { controller.abort(); clearInterval(timer); };
 }, [symbol, bucketSeconds, gap, externallyControlled]);
 useEffect(() => {
  if (externallyControlled) return;
  const controller = new AbortController();
  const pull = async () => {
   try { const response = await fetch("/api/ml/live-train/status", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(); const body = await response.json() as Fit;
    if (!controller.signal.aborted) setFit(body);
   } catch { if (!controller.signal.aborted) setFit(null); }
  };
  void pull(); const timer = setInterval(pull, 15000);
  return () => { controller.abort(); clearInterval(timer); };
 }, [externallyControlled]);
 useEffect(() => {
  if (bucketSeconds !== 1 && !externallyControlled) return;
  let active = true;
  const pull = async () => {
   try { const response = await fetch("/api/market/live-artifacts", { cache: "no-store" });
    if (!response.ok) throw new Error(); const body = await response.json() as { capture?: { counts?: Record<string, number> } };
    if (active) setCapture(body.capture?.counts ?? null);
   } catch { if (active) setCapture(null); }
  };
  void pull(); const timer = setInterval(pull, 5000);
  return () => { active = false; clearInterval(timer); };
 }, [bucketSeconds, externallyControlled]);
 const active = read?.active;
 const telemetry = active?.signal?.telemetry ?? {};
 const row = [...(fit?.competition ?? []), ...(fit?.open_market ?? [])].find(item => item.symbol === symbol);
 const recommendation = active?.whale_moment?.recommendation;
 const observer = active?.online_observer;
 const reportedDelay = active?.feed_health?.delay_seconds;
 const delayNotice = reportedDelay != null ? `provider-reported delay ${number(reportedDelay, 1)}s` : active?.feed_health?.delay_status === "provider_reported_delay" ? "provider reports a delay; duration unverified" : "provider delay unknown";
 if (bucketSeconds === 1 || externallyControlled) return <section className="model-flow-panel" aria-label="Model flow and learning">
  <header className="model-flow-header"><div><h3>What I see: {symbol}</h3><p>{bucketSeconds === 1 ? "1-second trade bars" : `${bucketSeconds / 60}-minute API candles`} / completed inputs / interpretation / later outcome</p></div><span className="model-flow-badge">{error ? "Read stale" : active?.chart_source === "public_last_trade" ? "Live trade input" : active?.chart_source === "public_market_candles" ? "Public minute input" : observer?.status ?? "Waiting"}</span></header>
  {error || gap ? <p role="status" className="model-flow-warning">{error || gap}</p> : null}
  <p className="model-live-status">Feed {active?.feed_health?.connection ?? "waiting"} / last received {number(active?.feed_health?.receive_age_seconds, 1)}s ago / model {observer?.status?.replaceAll("_", " ") ?? "waiting"}{bucketSeconds >= 60 ? ` / ${delayNotice}` : ""}</p>
  <ModelCandles candles={active?.candles ?? []} locked={[]}/>
  <p className="model-muted">Source: {active?.feed_origin ?? "Connecting to the market API"}. The chart and model share one received snapshot. The chart can include a forming candle; the model excludes forming candles and candles affected by known feed gaps.{bucketSeconds >= 60 ? ` These are 1-minute candles. Refreshing the API does not create second-by-second prices; ${delayNotice}.` : ""}</p>
  <p>Feed: {active?.feed_health?.connection ?? "Waiting for connection"} / last received {number(active?.feed_health?.receive_age_seconds, 2)}s ago{active?.feed_health?.exchange_to_receive_ms != null ? ` / exchange-to-server ${number(active.feed_health.exchange_to_receive_ms, 1)}ms` : ""}{active?.feed_health?.reconnects != null ? ` / reconnects ${active.feed_health.reconnects}` : ""}.</p>
  {active?.feed_health?.coverage === "gap_detected" ? <p className="model-flow-warning">A trade-ID gap was detected and recorded. Coverage is incomplete; no missing trades are invented.</p> : null}
  {(observer?.rejected_bars ?? 0) > 0 ? <p className="model-flow-warning">{observer?.rejected_bars} invalid or incomplete candles excluded from this model read.</p> : null}
  <p>Model: {observer?.status === "warming_up" ? `initializing${observer?.warmup_remaining == null ? "" : `, ${observer.warmup_remaining} labeled outcomes remaining`}` : observer?.status?.replaceAll("_", " ") ?? "waiting for completed bars"}. Model initialization is separate from live feed reception.</p>
  <div className="model-flow-heading"><strong>{active?.direction ?? "WAITING"}</strong><span>{active?.bars_read ?? 0} completed {bucketSeconds === 1 ? "trade bars" : "minute candles"} / feed age {number(observer?.feed_age_seconds, 1)}s</span></div>
  <p>{active?.notice ?? observer?.notice ?? "Waiting for real completed bars. Nothing is invented."}</p>
  <p>Next observed move: experimental P(up) {number(observer?.probability_up == null ? undefined : observer.probability_up * 100, 1)}% / prediction {time(observer?.prediction_at)}.</p>
  <p><strong>{observer?.samples_learned ?? 0} later outcomes learned.</strong> Each update waits for a later completed candle. Horizon: {observer?.horizon ?? "waiting for the model's resolution and horizon"}. Unchanged prices and long gaps do not train the fit.</p>
  <details><summary>Live prediction diagnostics</summary>{observer?.metrics ? <><p>{number(observer.metrics.samples_evaluated, 0)} scored outcomes / Brier {number(observer.metrics.brier_score)} / log loss {number(observer.metrics.log_loss)} / directional accuracy {number(observer.metrics.directional_accuracy == null ? undefined : observer.metrics.directional_accuracy * 100, 1)}%.</p><p>Equal-probability baseline: Brier {number(observer.metrics.baseline_brier_score)} / log loss {number(observer.metrics.baseline_log_loss)}. Lower loss is better.</p><p>{observer.metrics.scope === "prequential_before_update" ? "Each prediction is scored against its later outcome before updating the model." : `Scoring scope: ${observer.metrics.scope ?? "not reported"}.`} These online diagnostics are not independent validation or evidence of profitable trading.</p></> : <p>No live diagnostic scores have been reported.</p>}<NavLink to="predictions.training">View background observer health</NavLink></details>
  <details><summary>Why this interpretation?</summary><p>Online logistic regression uses the last return, the three-bar return (scaled by 1,000 and clipped between -3 and 3), and candle body divided by its range. It updates its coefficients after observing the next outcome.</p><p>Current inputs: {observer?.feature_values?.map(value => number(value)).join(" / ") ?? "Waiting"}. Learned coefficients: {observer?.weights?.map(value => number(value)).join(" / ") ?? "Not fitted"}.</p><p>During initialization{observer?.warmup_target == null ? "" : ` (the first ${observer.warmup_target} labeled outcomes)`}: OBSERVING. Afterwards: P(up) &gt; 55% means UP; below 45% means DOWN; otherwise UNCERTAIN. These are experimental thresholds, not evidence of accuracy.</p></details>
  <details><summary>Recent predictions and actual outcomes</summary>{observer?.recent_outcomes?.length ? observer.recent_outcomes.slice(-6).reverse().map(row => <p key={row.predicted_at}>{time(row.predicted_at)} / predicted P(up) {number(row.probability_up * 100, 1)}% / actual {row.outcome} at {time(row.resolved_at)}</p>) : <p>No prediction has a later outcome yet.</p>}</details>
  <p>Artifacts: {capture ? `${capture.raw_match ?? 0} raw matches / ${capture.candle_snapshot ?? 0} API candle snapshots / ${capture.bar ?? 0} bars / ${capture.prediction ?? 0} predictions / ${capture.outcome ?? 0} outcomes / ${capture.gap ?? 0} detected gaps` : "Capture status unavailable"}. <a href="/api/market/live-artifacts/export" download>Download captured artifacts</a></p>
  <p className="model-muted">Last read {time(read?.as_of)} / display refresh every {refreshSeconds ?? 1}s. Inputs, predictions, outcomes and learned state are saved locally; model initialization does not repeat after a normal restart. Experimental only: no orders, no promotion, no calibrated probabilities. The daily policy model is unchanged.</p>
 </section>;
 const publicData = active?.chart_source === "public_market_candles";
 const aligned = read?.chart_track?.follows === "same_symbol_and_interval";
 return <section className="model-flow-panel" aria-label="Model flow and learning">
  <header className="model-flow-header"><div><h3>Inside the model</h3><p>{symbol} · {intervalLabel} · {active?.model_id ?? "Waiting for model"}</p></div><span className={`model-flow-badge ${publicData && !error ? "is-public" : ""}`}>{error ? "Read stale" : publicData ? "Public candles" : active ? "Fixture / fallback" : "Loading"}</span></header>
  <div className="model-flow-path"><span>{bucketSeconds === 1 ? "Real-time trade display" : "TradingView display"}<br/><b>{bucketSeconds === 1 ? symbol : read?.chart_track?.picture ?? symbol}</b></span><span>Separate model feed<br/><b>{active?.feed_origin ?? "Waiting"}</b></span><span>Research score<br/><b>{active?.direction ?? "—"} · {number(telemetry.raw_score)}</b></span><span>Decision<br/><b>{recommendation?.stance ?? "abstain"}</b></span></div>
  <p className="model-muted">{bucketSeconds === 1 ? "Real time displays sampled public crypto trades in one-second bars. This is an ATLAS view; its trade tape and the model input shown below are separate." : `${aligned ? "Symbol and interval match the requested chart." : "The model series does not currently match the requested chart resolution."} TradingView widget candles are not exported to the model. Prices can differ. Change the symbol and interval using the Desk controls.`}</p>
  {gap || error ? <p role="status" className="model-flow-warning">{gap || error}</p> : null}
  <div className="model-flow-heading"><strong>What the model actually sees</strong><span>{active?.bars_read ?? 0} bars · {active?.bucket_seconds ?? bucketSeconds}s</span></div>
  {active ? <ModelCandles candles={active.candles ?? []} locked={active.bar_lock?.window_timestamps ?? []}/> : <p>Loading the model’s candle snapshot…</p>}
  <p className="model-muted">Last bar closes {time(active?.last_bar_close)} · Last read {time(read?.as_of)} · polls every 4s. Public candles exclude the forming bar. Shading marks the causal swing; hover or focus a candle to inspect it.</p>
  <div className="model-flow-grid"><div><strong>Techniques in this score</strong><dl><dt>ATR · trailing volatility</dt><dd>{number(telemetry.atr_14)}</dd><dt>VPIN · candle-derived proxy</dt><dd>{number(telemetry.vpin)}</dd><dt>Kyle’s lambda · candle-derived proxy</dt><dd>{number(telemetry.kyles_lambda, 6)} · diagnostic only</dd><dt>Order flow / Hawkes / spread</dt><dd>{telemetry.ofi_observed === true ? "Flow observed" : "Flow unobserved"} · {telemetry.hawkes_observed === true ? "Hawkes observed" : "Hawkes unobserved"} · {telemetry.spread_observed === true ? "Spread observed" : "Spread unobserved"}</dd></dl></div>
   <div><strong>Rules behind the label</strong><p>{recommendation?.summary ?? "Waiting for evidence. No order is authorized."}</p><p>Factor label: {active?.whale_moment?.scenario_id ?? "Withheld"} {active?.whale_moment?.action ?? ""}. This may disagree with the policy direction.</p><p>Swing invalidation {number(active?.bar_lock?.invalidation_price)} · objective {number(active?.bar_lock?.objective_price)}.</p><p>Policy stop {number(active?.stop_loss)} · target {number(active?.take_profit)}. These are research levels.</p></div></div>
  <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>Inspect scoring formula and risk rules</summary><p>Score = wOFI × OFI + wVPIN × (VPIN − 0.25) × 3.2 × side + wHawkes × Hawkes × side. Unobserved flow and Hawkes terms contribute zero. Side follows observed OFI, otherwise the latest candle momentum.</p><p>Weights: OFI {number(active?.model_weights?.ofi_z)} · VPIN {number(active?.model_weights?.vpin)} · Hawkes {number(active?.model_weights?.hawkes_ratio)}. Kyle’s lambda has no term in this score.</p><p>HOLD when flow is unobserved or |OFI| &lt; 0.20, and VPIN &lt; 0.22. Otherwise nonnegative score → BUY; negative → SELL. Conviction is a heuristic transform, not a calibrated probability.</p><p>Stop distance = max(0.3% of price, 1 × ATR). Target distance = max(1.5 × stop distance, 1.5 × ATR). The swing rule walks backward through agreeing candle bodies and uses a 0.25 × ATR cushion. It is separate from the policy stop.</p></details>
  <div className="model-learning"><div><strong>Learning status · {fit?.status ?? "Unavailable"}</strong><p>Daily candle refit every 15 minutes · cycle {fit?.cycle ?? 0}. This is not tick-by-tick learning.</p><p>Last fit {time(fit?.trained_at)} · next {time(fit?.next_fit_at)}</p><p>{row ? `${row.symbol}: ${row.bars} bars · ${row.data_mode} · ${row.promoted ? "gate passed" : "not promoted"}` : "No training result for this symbol."}</p><p>Served model: candle-retuned heuristic. Walk-forward tests fit a separate logistic model; its learned coefficients are not served.</p><p>Gate: Sharpe &gt; 1.80 / actual {number(row?.oos_sharpe_ratio)} · drawdown &lt; 3.2% / actual {number(row?.oos_max_drawdown_fraction == null ? undefined : row.oos_max_drawdown_fraction * 100, 2)}% · Brier &lt; 0.180 / actual {number(row?.oos_brier_score)}.</p></div><button type="button" className="btn btn-outline btn-sm" disabled={busy} onClick={async () => {
   setBusy(true); try { const response = await fetch("/api/ml/live-train", { method: "POST" }); if (!response.ok) throw new Error(); setFit(await response.json() as Fit); } catch { setError("Refit failed. The last model remains loaded."); } finally { setBusy(false); }
  }}>{busy ? "Refitting…" : "Refit daily history"}</button></div>
  <p className="model-muted">Research only · no order authority. Watching a chart does not train the model or prove predictive accuracy.</p>
 </section>;
}
