"use client";

import { useEffect, useState } from "react";

type BarLock = {
  bars_in_lock?: number;
  bars_read?: number;
  method?: string;
  action?: string | null;
  stance?: string;
  invalidation_price?: number | null;
  objective_price?: number | null;
  feed_origin?: string;
  decision_timestamp?: string | null;
  execution_permission?: string;
  may_propose_order?: boolean;
  notice?: string;
};

type ReadBody = {
  active?: {
    feed_origin?: string;
    bar_lock?: BarLock;
  };
  execution_permission?: string;
};

function price(value: unknown): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function stamp(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toISOString().slice(0, 16).replace("T", " ") + "Z";
}

export function ChartLockRail({
  symbol,
  bucketSeconds,
  intervalLabel,
}: {
  symbol: string;
  bucketSeconds: number;
  intervalLabel: string;
}) {
  const [lock, setLock] = useState<BarLock | null>(null);
  const [feed, setFeed] = useState("unlabeled");
  const [phase, setPhase] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    let active = true;
    const pull = () => {
      void fetch(
        `/api/ml/chart-read?symbol=${encodeURIComponent(symbol)}&bucket_seconds=${bucketSeconds}`,
        { cache: "no-store" },
      )
        .then(async (response) => {
          if (!response.ok) throw new Error(`Chart read returned HTTP ${response.status}`);
          return (await response.json()) as ReadBody;
        })
        .then((body) => {
          if (!active) return;
          const next = body.active?.bar_lock ?? null;
          setLock(next);
          setFeed(next?.feed_origin ?? body.active?.feed_origin ?? "unlabeled");
          setPhase("ready");
        })
        .catch(() => {
          if (!active) return;
          setLock(null);
          setPhase("failed");
        });
    };
    setPhase("loading");
    pull();
    const timer = window.setInterval(pull, 4000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol, bucketSeconds]);

  const action = String(lock?.action ?? "").toUpperCase();
  const sideClass = action === "BUY" ? "is-buy" : action === "SELL" ? "is-sell" : "";
  const side = action === "BUY" || action === "SELL" ? action : "withheld";
  const bars = lock?.bars_in_lock ?? 0;
  const read = lock?.bars_read ?? 0;

  return (
    <aside className="chart-lock-rail" aria-label={`${symbol} ${intervalLabel} research lock beside the TradingView chart`}>
      {phase === "failed" ? (
        <p>The model read did not load beside this chart. Nothing was sent.</p>
      ) : phase === "loading" ? (
        <p>This model is dedicated to the TradingView chart for {symbol} {intervalLabel}. Nothing is sent while it loads.</p>
      ) : (
        <>
          <p>
            <strong>{symbol}</strong> {intervalLabel} · method {lock?.method === "causal_swing" ? "causal swing" : (lock?.method ?? "causal swing")}
            {" · "}
            <span className={sideClass}>{side}</span>
            {" · stance "}
            {lock?.stance ?? "abstain"}
            {" · "}
            {bars} bar{bars === 1 ? "" : "s"} in the lock
            {read > 0 ? ` of ${read}` : ""}
            {" · "}
            {feed}
          </p>
          {lock?.notice ? (
            <p>{lock.notice}</p>
          ) : (
            <>
              <p>
                Invalidation {price(lock?.invalidation_price)} · objective {price(lock?.objective_price)}
                {" · decision "}
                {stamp(lock?.decision_timestamp)}
                {" · execution_permission "}
                {lock?.execution_permission ?? "none"}
              </p>
              <p>
                Lock prices are from the public-candle path. The widget keeps its bars. Nothing was sent.
              </p>
            </>
          )}
        </>
      )}
    </aside>
  );
}
