"use client";

import { useEffect, useState } from "react";
import { ModelFlowPanel } from "./ModelFlowPanel";
import type { LiveSnapshot } from "./liveTypes";
import { AtlasChart } from "./AtlasChart";

const BUCKETS: Record<string, number> = { "1s": 1, "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1D": 86400 };

/** The desk's one chart. Real time is a timeframe ("Live") INSIDE AtlasChart, not a second chart (chart-2). */
export function DeskChart({ symbol, timeframe, frameClassName, gap, modelSymbol, onSnapshot, onTimeframe }: {
  symbol: string;
  timeframe: string;
  frameClassName: string;
  gap?: string | null;
  /** @deprecated kept for call-site compatibility; the Live timeframe has its own empty state. */
  onOpenMinute?: () => void;
  modelSymbol?: string;
  onSnapshot?: (snapshot: LiveSnapshot) => void;
  onTimeframe?: (tf: string) => void;
}) {
  const live = timeframe === "1s";
  // Chart height follows the viewport (about half of it, clamped) so it fits at 1366x768 and 1920x1080 without a fixed 480px stage.
  const [chartH, setChartH] = useState(420);
  useEffect(() => {
    const fit = () => setChartH(Math.min(640, Math.max(300, Math.round(window.innerHeight * 0.5))));
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);
  const sym = modelSymbol ?? symbol;
  return (
    <div className={frameClassName}>
      <div className="desk-chart-stage">
        <div className="desk-atlas-picture">
          <AtlasChart symbol={sym} timeframe={timeframe} height={chartH} onTimeframe={onTimeframe} onLiveSnapshot={onSnapshot}
            liveExtras={(snap, err) => <ModelFlowPanel symbol={sym} bucketSeconds={snap?.bucket_seconds ?? 1} intervalLabel="Real time"
              snapshot={snap} snapshotError={err} refreshSeconds={snap?.refresh_seconds} />} />
        </div>
        {!live && <ModelFlowPanel symbol={sym} bucketSeconds={BUCKETS[timeframe] ?? 60} intervalLabel={timeframe} gap={gap} />}
      </div>
    </div>
  );
}
