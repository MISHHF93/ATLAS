"use client";

import { useEffect, useRef, useState } from "react";
import { ModelFlowPanel, type ModelRead } from "./ModelFlowPanel";
import { SecondBars, type Tape } from "./SecondBars";

export type LiveSnapshot = ModelRead & Tape & {
  symbol: string;
  status: string;
  bucket_seconds: number;
  refresh_seconds: number;
};

/** A single response supplies both the native chart and the completed model inputs. */
export function LiveMarketViewer({ symbol, onOpenMinute, onSnapshot }: { symbol: string; onOpenMinute?: () => void; onSnapshot?: (snapshot: LiveSnapshot) => void }) {
  const [state, setState] = useState<{ requestedSymbol: string; snapshot: LiveSnapshot } | null>(null);
  const [failure, setFailure] = useState<{ symbol: string; message: string } | null>(null);
  const snapshot = state?.requestedSymbol === symbol ? state.snapshot : null;
  const error = failure?.symbol === symbol ? failure.message : "";
  const snapshotListener = useRef(onSnapshot);
  snapshotListener.current = onSnapshot;

  useEffect(() => {
    const controller = new AbortController();
    let timer = 0;
    let refreshSeconds = 1;
    setState(null);
    setFailure(null);
    const poll = async () => {
      try {
        const response = await fetch(`/api/market/live-view?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`Market API returned ${response.status}`);
        const body = await response.json() as LiveSnapshot;
        if (controller.signal.aborted) return;
        if (typeof body.symbol !== "string" || body.symbol.toUpperCase() !== symbol.toUpperCase()
          || (body.active?.symbol != null && body.active.symbol.toUpperCase() !== symbol.toUpperCase())
          || !Array.isArray(body.candles) || !Number.isFinite(body.bucket_seconds)) throw new Error("Market API returned an invalid candle snapshot for this symbol");
        refreshSeconds = Number.isFinite(body.refresh_seconds) ? Math.max(0.4, body.refresh_seconds) : 10;
        setState({ requestedSymbol: symbol, snapshot: body });
        setFailure(null);
        snapshotListener.current?.(body);
      } catch (cause) {
        if (controller.signal.aborted) return;
        setFailure({ symbol, message: `${cause instanceof Error ? cause.message : "Market feed unavailable"}. Retrying; any displayed snapshot is stale.` });
        refreshSeconds = Math.max(2, refreshSeconds);
      } finally {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void poll(), refreshSeconds * 1000);
      }
    };
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [symbol]);

  const bucketSeconds = snapshot?.bucket_seconds ?? 1;
  return <>
    <SecondBars symbol={symbol} bucketSeconds={bucketSeconds} intervalLabel={bucketSeconds === 1 ? "Real time" : "Live view, 1-minute candles"} snapshot={snapshot} snapshotError={error} onOpenMinute={onOpenMinute} />
    <ModelFlowPanel symbol={symbol} bucketSeconds={bucketSeconds} intervalLabel="Real time" snapshot={snapshot} snapshotError={error} refreshSeconds={snapshot?.refresh_seconds} />
  </>;
}
