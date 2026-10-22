"use client";

import { useEffect, useState } from "react";

type WhaleMoment = {
  status?: string;
  reason?: string;
  scenario_id?: string;
  action?: string;
  trigger_summary?: string;
  stop_loss_price?: number;
  take_profit_price?: number;
  execution_permission?: string;
  recommendation?: {
    stance?: string;
    summary?: string;
    may_propose_order?: boolean;
  };
};

type ActiveRead = {
  symbol?: string;
  last_close?: number;
  feed_origin?: string;
  bars_read?: number;
  whale_moment?: WhaleMoment;
};

type TrainingLink = {
  status?: string;
  cycle?: number;
  served_model_id?: string;
  execution_permission?: string;
};

type ChartRead = { active?: ActiveRead; training?: TrainingLink };

type WhaleCall = {
  title: string;
  detail: string;
  abstain: string;
  side: "BUY" | "SELL" | "HOLD";
  stop?: number;
  target?: number;
};

function money(value: number | undefined): string {
  if (value == null || !Number.isFinite(value) || value <= 0) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function whaleCall(active: ActiveRead): WhaleCall {
  const moment = active.whale_moment;
  const action = String(moment?.action ?? "").toUpperCase();
  const scenario = String(moment?.scenario_id ?? "");
  const locked = moment?.status === "locked" && (action === "BUY" || action === "SELL") && scenario.startsWith("WSDM-");
  if (!locked || moment?.execution_permission !== "none") {
    const reason = moment?.reason === "no_quote"
      ? "This name has no quote. No price series is invented. Nothing was sent."
      : moment?.status === "withheld"
      ? "The factor lock needs four bars. Nothing was sent."
      : "This read has no whale lock yet. Nothing was sent.";
    return {
      title: "Whale moment withheld",
      detail: reason,
      abstain: moment?.recommendation?.summary ?? "Must not trade. Nothing was sent.",
      side: "HOLD",
    };
  }
  const verb = action === "SELL" ? "sell" : "buy";
  const recommendation = moment?.recommendation;
  const abstain = recommendation?.may_propose_order === true
    ? "Must not trade. A chart read cannot propose an order."
    : recommendation?.summary ?? "Must not trade. This read cannot send an order.";
  return {
    title: `Research label · ${verb} · ${scenario}`,
    detail: moment?.trigger_summary ?? "The factor lock named this label.",
    abstain,
    side: action === "SELL" ? "SELL" : "BUY",
    stop: moment?.stop_loss_price,
    target: moment?.take_profit_price,
  };
}

export function WhaleOnChart({
  symbol,
  bucketSeconds,
  gap,
}: {
  symbol: string;
  bucketSeconds: number;
  gap?: string | null;
}) {
  const [active, setActive] = useState<ActiveRead | null>(null);
  const [training, setTraining] = useState<TrainingLink | null>(null);
  const [waiting, setWaiting] = useState(true);

  useEffect(() => {
    if (gap) return;
    let live = true;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/ml/chart-read?symbol=${encodeURIComponent(symbol)}&bucket_seconds=${bucketSeconds}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("chart read unavailable");
        const body = (await response.json()) as ChartRead;
        if (!live) return;
        setActive(body.active ?? null);
        setTraining(body.training ?? null);
        setWaiting(false);
      } catch {
        if (live) setWaiting(true);
      }
    };
    void pull();
    const timer = setInterval(pull, 4000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [symbol, bucketSeconds, gap]);

  const call = active ? whaleCall(active) : null;
  const side = call?.side ?? "HOLD";

  return (
    <div className="whale-on-chart" aria-live="polite">
      <div className="whale-on-chart-kicker">Whale read on this chart</div>
      {gap ? (
        <div className="whale-on-chart-title">No model series</div>
      ) : waiting || !call ? (
        <div className="whale-on-chart-title">Reading price for a whale moment</div>
      ) : (
        <>
          <div className={`whale-on-chart-title is-${side === "SELL" ? "sell" : side === "BUY" ? "buy" : "hold"}`}>
            {call.title}
          </div>
          <div className="whale-on-chart-price">
            {active?.symbol ?? symbol} {money(active?.last_close)} · {active?.bars_read ?? 0} bars · {active?.feed_origin ?? "unlabeled"}
          </div>
          <div className="whale-on-chart-detail">{call.abstain}</div>
          <div className="whale-on-chart-detail">{call.detail}</div>
          <div className="whale-on-chart-levels">
            Moment stop {money(call.stop)} · moment target {money(call.target)}
          </div>
          <div className="whale-on-chart-detail">
            {training?.status === "ok"
              ? `Linked to desk fit ${training.cycle ?? 0}. ${training.served_model_id ?? "book loaded"}. execution_permission ${training.execution_permission ?? "none"}`
              : "The desk fit has not finished a cycle yet. This card cannot send an order."}
          </div>
        </>
      )}
      {gap ? <div className="whale-on-chart-detail">{gap}</div> : null}
    </div>
  );
}
