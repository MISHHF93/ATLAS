"use client";

import { ModelFlowPanel } from "./ModelFlowPanel";
import { LiveMarketViewer, type LiveSnapshot } from "./LiveMarketViewer";
import { TradingViewChart } from "./TradingViewChart";
import { useLayoutEffect, useRef } from "react";

const BUCKETS: Record<string, number> = {
  "1s": 1,
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
  "1D": 86400,
};

export function DeskChart({
  symbol,
  timeframe,
  frameClassName,
  gap,
  onOpenMinute,
  modelSymbol,
  onSnapshot,
}: {
  symbol: string;
  timeframe: string;
  frameClassName: string;
  gap?: string | null;
  onOpenMinute?: () => void;
  modelSymbol?: string;
  onSnapshot?: (snapshot: LiveSnapshot) => void;
}) {
  const bucketSeconds = BUCKETS[timeframe] ?? 60;
  const widgetPicture = timeframe !== "1s";
  const frame = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = frame.current;
    if (!element || widgetPicture) return;
    const main = element.closest("main");
    if (!main) return;
    let scheduled = 0;
    const measure = () => {
      cancelAnimationFrame(scheduled);
      scheduled = requestAnimationFrame(() => {
        const style = getComputedStyle(main);
        const flowing = window.matchMedia("(max-width: 1100px)").matches;
        const available = flowing ? (window.visualViewport?.height ?? window.innerHeight) : main.clientHeight;
        const offset = element.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
        const footer = main.lastElementChild?.getBoundingClientRect().height ?? 0;
        const gap = parseFloat(style.rowGap) || 0;
        const fontSize = parseFloat(style.fontSize) || 12;
        const height = Math.max(fontSize * 24, available - offset - footer - gap * 2);
        element.style.setProperty("--viewer-available-height", `${Math.floor(height)}px`);
      });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(main);
    if (element.parentElement) observer.observe(element.parentElement);
    if (main.firstElementChild) observer.observe(main.firstElementChild);
    if (main.lastElementChild) observer.observe(main.lastElementChild);
    window.addEventListener("resize", measure);
    window.visualViewport?.addEventListener("resize", measure);
    measure();
    return () => {
      observer.disconnect(); cancelAnimationFrame(scheduled);
      window.removeEventListener("resize", measure);
      window.visualViewport?.removeEventListener("resize", measure);
    };
  }, [widgetPicture]);
  return (
    <div ref={frame} className={`${frameClassName}${widgetPicture ? "" : " is-realtime"}`}>
      {widgetPicture ? <TradingViewChart symbol={symbol} timeframe="1m" showTape showChart={false} quiet /> : null}
      <div className="desk-chart-stage">
        {widgetPicture ? (
          <>
            <div className="desk-tv-picture">
              <TradingViewChart
                symbol={symbol}
                timeframe={timeframe}
                showChart
                showTape={false}
                showCompanions={false}
                quiet
                fill
              />
            </div>
          </>
        ) : (
          <LiveMarketViewer symbol={modelSymbol ?? symbol} onOpenMinute={onOpenMinute} onSnapshot={onSnapshot} />
        )}
        {widgetPicture && <ModelFlowPanel
          symbol={modelSymbol ?? symbol}
          bucketSeconds={bucketSeconds}
          intervalLabel={widgetPicture ? timeframe : "Real time"}
          gap={gap}
        />}
      </div>
    </div>
  );
}
