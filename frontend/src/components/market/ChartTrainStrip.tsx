"use client";

import { useEffect, useState } from "react";

type TrackCount = {
  symbols?: number;
  trained?: number;
  public?: number;
  fixture?: number;
};

type TrainingLink = {
  status?: string;
  cycle?: number;
  trained_at?: string | null;
  next_fit_at?: string | null;
  cadence_seconds?: number;
  path_id?: string;
  orders_submitted?: number;
  execution_permission?: string;
  notice?: string;
  autonomous?: boolean;
  tracks?: {
    competition?: TrackCount;
    open_market?: TrackCount;
  };
};

type ChartTrack = {
  picture?: string | null;
  interval?: string | null;
  follows?: string;
  bars_from_tradingview?: boolean;
  notice?: string;
  execution_permission?: string;
};

type ChartRead = {
  active?: {
    symbol?: string;
    direction?: string;
    bars_read?: number;
    feed_origin?: string;
    model_id?: string;
  };
  training?: TrainingLink;
  chart_track?: ChartTrack;
  execution_permission?: string;
};

function clock(value: string | null | undefined): string {
  if (!value) return "not yet";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "not yet";
  return `${new Date(parsed).toISOString().slice(11, 16)} UTC`;
}

function book(name: string, row: TrackCount | undefined): string {
  return `${name} ${row?.trained ?? 0}/${row?.symbols ?? 0} trained, ${row?.public ?? 0} public`;
}

function fitLine(link: TrainingLink | undefined, symbol: string, direction: string): string {
  const minutes = Math.round((link?.cadence_seconds ?? 900) / 60);
  const rhythm = link?.autonomous === false
    ? "This process is not refitting"
    : `Refits on its own about every ${minutes} min`;
  const tracks = `${book("competition", link?.tracks?.competition)} · ${book("open market", link?.tracks?.open_market)}`;
  return `${link?.path_id ?? "desk fit"} · ${rhythm} · cycle ${link?.cycle ?? 0} · ${tracks} · ${symbol} ${direction} · last ${clock(link?.trained_at)} · next ${clock(link?.next_fit_at)} · orders ${link?.orders_submitted ?? 0} · execution_permission ${link?.execution_permission ?? "none"}`;
}

export function ChartTrainStrip({
  symbol,
  bucketSeconds,
  intervalLabel,
  gap,
  onOpenMinute,
}: {
  symbol: string;
  bucketSeconds: number;
  intervalLabel: string;
  gap?: string | null;
  onOpenMinute?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [track, setTrack] = useState<ChartTrack | null>(null);
  const [readLine, setReadLine] = useState("Chart read loading");
  const [fitLineText, setFitLineText] = useState("The desk refits both books on its own. No order is sent.");
  const [ledgerLine, setLedgerLine] = useState("Daily trend ledger loading. It cannot send an order.");
  const minuteChart = bucketSeconds >= 60;

  useEffect(() => {
    if (gap) {
      setTrack(null);
      setReadLine(gap);
      setFitLineText("This symbol has no model series. Nothing is trained from it and nothing is sent.");
      return;
    }
    let active = true;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/ml/chart-read?symbol=${encodeURIComponent(symbol)}&bucket_seconds=${bucketSeconds}`,
          { cache: "no-store" }
        );
        if (!response.ok) throw new Error("chart read unavailable");
        const body = (await response.json()) as ChartRead;
        if (!active) return;
        const row = body.active;
        setTrack(body.chart_track ?? null);
        setReadLine(
          `${row?.symbol ?? symbol} · ${row?.model_id ?? "book"} · ${row?.direction ?? "—"} · ${row?.bars_read ?? 0} bars · ${row?.feed_origin ?? "unlabeled"} · execution_permission ${body.execution_permission ?? "none"}`
        );
        setFitLineText(fitLine(body.training, row?.symbol ?? symbol, row?.direction ?? "—"));
      } catch {
        if (active) setReadLine("Chart read loading");
      }
    };
    void pull();
    const timer = setInterval(pull, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [symbol, bucketSeconds, gap]);

  useEffect(() => {
    let active = true;
    const pull = () => {
      void fetch("/api/research/outcome-ledger", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw new Error("ledger unavailable");
          return response.json() as Promise<{
            tracks?: {
              competition?: { judgment?: string; public_resolved_stances?: number; required_resolved_stances?: number };
              open_market?: { judgment?: string; public_resolved_stances?: number; required_resolved_stances?: number };
            };
            execution_permission?: string;
          }>;
        })
        .then((body) => {
          if (!active) return;
          const line = (name: string, row: { judgment?: string; public_resolved_stances?: number; required_resolved_stances?: number } | undefined) =>
            `${name} ${row?.judgment ?? "too_few_to_judge"} ${row?.public_resolved_stances ?? 0}/${row?.required_resolved_stances ?? 60}`;
          setLedgerLine(
            `Daily trend ledger · ${line("competition", body.tracks?.competition)} · ${line("open market", body.tracks?.open_market)} · abstentions are not wins · execution_permission ${body.execution_permission ?? "none"}`
          );
        })
        .catch(() => {
          if (active) setLedgerLine("Daily trend ledger did not load. Nothing was sent.");
        });
    };
    pull();
    const timer = window.setInterval(pull, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const tracking = minuteChart && track?.follows === "same_symbol_and_interval" && Boolean(track.picture);
  const label = gap
    ? "No model series"
    : !minuteChart
      ? "Track on the 1m chart"
      : tracking
        ? `Tracking ${track?.picture} · ${intervalLabel}`
        : track?.follows === "picture_only" && track.picture
          ? `Chart only · ${track.picture}`
          : track
            ? "No TradingView chart"
            : "Track this chart";
  const note = gap
    ? gap
    : !minuteChart
      ? "The 1-second view is our canvas. This opens the TradingView chart at 1 minute and the model follows it."
      : track?.notice
        ?? "The model follows this chart's symbol and interval. Nothing is sent while the listing is checked.";

  return (
    <div className="chart-track">
      <button
        type="button"
        className={`chart-train-btn${tracking ? " is-tracking" : ""}`}
        aria-pressed={open}
        onClick={() => {
          if (!minuteChart) {
            onOpenMinute?.();
            return;
          }
          setOpen((value) => !value);
        }}
      >
        {label}
      </button>
      <p className="chart-track-note">{note}</p>
      {open ? (
        <div className="chart-train-copy">
          <div className="chart-train-kicker">Model on this chart</div>
          <div className="chart-train-line">{readLine}</div>
          <div className="chart-train-sub">{fitLineText}</div>
          <div className="chart-train-sub">{ledgerLine}</div>
        </div>
      ) : null}
    </div>
  );
}
