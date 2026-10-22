"use client";

import { useEffect, useRef, useState } from "react";

type LockCandle = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

type BarLock = {
  decision_timestamp?: string | null;
  window_timestamps?: string[];
  contributions?: Array<{ timestamp?: string; share?: number }>;
  action?: string | null;
  direction?: string;
  invalidation_price?: number | null;
  objective_price?: number | null;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  stance?: string;
  feed_origin?: string;
  notice?: string;
  execution_permission?: string;
};

type TapeBody = {
  candles?: LockCandle[];
  chart_source?: string;
  feed_origin?: string;
  last_close?: number | null;
  notice?: string;
  execution_permission?: string;
};

function epoch(value: string | null | undefined): number {
  if (!value) return Number.NaN;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

export function SecondBars({
  symbol,
  bucketSeconds,
  intervalLabel,
}: {
  symbol: string;
  bucketSeconds: number;
  intervalLabel: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [bars, setBars] = useState<LockCandle[]>([]);
  const [lock, setLock] = useState<BarLock | null>(null);
  const [note, setNote] = useState("Waiting for the next public trade.");

  useEffect(() => {
    let active = true;
    const pull = () => {
      void fetch(
        `/api/market/second-tape?symbol=${encodeURIComponent(symbol)}`,
        { cache: "no-store" },
      )
        .then(async (response) => {
          if (!response.ok) throw new Error(`Second tape returned HTTP ${response.status}`);
          return (await response.json()) as TapeBody;
        })
        .then((body) => {
          if (!active) return;
          const live = body.chart_source === "public_last_trade";
          const candles = live
            ? (body.candles ?? []).filter((bar) => [bar.open, bar.high, bar.low, bar.close].every(Number.isFinite))
            : [];
          setBars(candles);
          setLock(null);
          const price = body.last_close != null && Number.isFinite(body.last_close)
            ? ` · last ${body.last_close.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
            : "";
          setNote(
            `${intervalLabel}${price} · ${body.feed_origin ?? "none"} · ${candles.length} seconds. ${body.notice ?? "Nothing was sent."}`,
          );
        })
        .catch(() => {
          if (!active) return;
          setBars([]);
          setLock(null);
          setNote("The public last trade did not load. Nothing was drawn and nothing was sent.");
        });
    };
    pull();
    const timer = window.setInterval(pull, 400);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol, bucketSeconds, intervalLabel]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const draw = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const width = parent.clientWidth;
      const height = parent.clientHeight;
      if (width < 10 || height < 10) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.fillStyle = "#0B0F17";
      ctx.fillRect(0, 0, width, height);
      if (bars.length < 1) return;
      const pad = { left: 8, right: 72, top: 18, bottom: 16 };
      const plotWidth = width - pad.left - pad.right;
      const plotHeight = height - pad.top - pad.bottom;
      let low = Infinity;
      let high = -Infinity;
      for (const bar of bars) {
        low = Math.min(low, bar.low);
        high = Math.max(high, bar.high);
      }
      const invalidation = Number(lock?.invalidation_price);
      const objective = Number(lock?.objective_price);
      const levels = [invalidation, objective].filter((price) => Number.isFinite(price));
      for (const price of levels) {
        low = Math.min(low, price);
        high = Math.max(high, price);
      }
      if (!(high > low)) high = low + 1;
      const shares = new Map<number, number>();
      for (const row of lock?.contributions ?? []) {
        const stamp = epoch(row.timestamp);
        const share = Number(row.share);
        if (Number.isFinite(stamp) && Number.isFinite(share)) shares.set(stamp, share);
      }
      const decision = epoch(lock?.decision_timestamp);
      const slot = plotWidth / bars.length;
      const yOf = (price: number) => pad.top + ((high - price) / (high - low)) * plotHeight;
      bars.forEach((bar, index) => {
        const share = shares.get(epoch(bar.timestamp));
        if (share == null) return;
        ctx.fillStyle = `rgba(0, 200, 255, ${0.1 + 0.38 * Math.max(0, Math.min(1, share))})`;
        ctx.fillRect(pad.left + index * slot, pad.top, Math.max(1, slot), plotHeight);
      });
      bars.forEach((bar, index) => {
        const x = pad.left + index * slot + slot / 2;
        const rising = bar.close >= bar.open;
        ctx.strokeStyle = rising ? "#00F29D" : "#FF3B69";
        ctx.fillStyle = ctx.strokeStyle;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, yOf(bar.high));
        ctx.lineTo(x, yOf(bar.low));
        ctx.stroke();
        const top = yOf(Math.max(bar.open, bar.close));
        const bottom = yOf(Math.min(bar.open, bar.close));
        ctx.fillRect(x - Math.max(1, slot * 0.28), top, Math.max(2, slot * 0.56), Math.max(1, bottom - top));
        if (epoch(bar.timestamp) === decision) {
          ctx.strokeStyle = "#F8FAFC";
          ctx.strokeRect(pad.left + index * slot + 1, pad.top, Math.max(1, slot - 2), plotHeight);
          const action = String(lock?.action ?? "").toUpperCase();
          if (action === "BUY" || action === "SELL") {
            const buy = action === "BUY";
            ctx.fillStyle = buy ? "#00F29D" : "#FF3B69";
            const tip = buy ? yOf(bar.high) - 6 : yOf(bar.low) + 6;
            ctx.beginPath();
            if (buy) {
              ctx.moveTo(x, tip - 8);
              ctx.lineTo(x - 5, tip);
              ctx.lineTo(x + 5, tip);
            } else {
              ctx.moveTo(x, tip + 8);
              ctx.lineTo(x - 5, tip);
              ctx.lineTo(x + 5, tip);
            }
            ctx.closePath();
            ctx.fill();
          }
        }
      });
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      if (Number.isFinite(invalidation)) {
        ctx.strokeStyle = "#FF3B69";
        ctx.beginPath();
        ctx.moveTo(pad.left, yOf(invalidation));
        ctx.lineTo(width - pad.right, yOf(invalidation));
        ctx.stroke();
      }
      if (Number.isFinite(objective)) {
        ctx.strokeStyle = "#00F29D";
        ctx.beginPath();
        ctx.moveTo(pad.left, yOf(objective));
        ctx.lineTo(width - pad.right, yOf(objective));
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.fillStyle = "#94A3B8";
      ctx.font = "11px ui-monospace, monospace";
      ctx.fillText(high.toFixed(2), width - pad.right + 8, pad.top + 11);
      ctx.fillText(low.toFixed(2), width - pad.right + 8, pad.top + plotHeight);
    };
    draw();
    const observed = canvas.parentElement;
    const observer = new ResizeObserver(draw);
    if (observed) observer.observe(observed);
    return () => observer.disconnect();
  }, [bars, lock]);

  return (
    <div style={{ flex: 1, height: "100%", minHeight: 0, display: "flex", flexDirection: "column" }}>
      <div style={{ position: "relative", flex: 1, minHeight: 0 }}>
        <canvas ref={canvasRef} aria-label={`${symbol} ${intervalLabel} bars with the research lock`} />
      </div>
      <p style={{ margin: "6px 0 0", color: "#94A3B8", fontSize: "11px", lineHeight: 1.4 }}>{note}</p>
    </div>
  );
}
