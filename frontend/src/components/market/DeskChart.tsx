"use client";

import type { ReactNode } from "react";
import { ChartLockRail } from "./ChartLockRail";
import { ChartTrainStrip } from "./ChartTrainStrip";
import { SecondBars } from "./SecondBars";
import { TradingViewChart } from "./TradingViewChart";

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
  children,
}: {
  symbol: string;
  timeframe: string;
  frameClassName: string;
  gap?: string | null;
  onOpenMinute?: () => void;
  children?: ReactNode;
}) {
  const bucketSeconds = BUCKETS[timeframe] ?? 60;
  const widgetPicture = timeframe !== "1s";
  return (
    <div className={frameClassName}>
      <TradingViewChart symbol={symbol} timeframe="1m" showTape showChart={false} quiet />
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
            <ChartLockRail symbol={symbol} bucketSeconds={bucketSeconds} intervalLabel={timeframe} />
          </>
        ) : (
          <SecondBars symbol={symbol} bucketSeconds={bucketSeconds} intervalLabel={timeframe} />
        )}
        {children}
        <ChartTrainStrip
          symbol={symbol}
          bucketSeconds={bucketSeconds}
          intervalLabel={timeframe}
          gap={gap}
          onOpenMinute={onOpenMinute}
        />
      </div>
    </div>
  );
}
