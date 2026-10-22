export interface MarketBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MarketBarsResponse {
  symbol: string;
  track: string;
  bucket_seconds: number;
  bar_count: number;
  candles: MarketBar[];
  last_close: number;
  chart_source: string;
  feed_origin: string;
  catalog_found: boolean;
  notice: string;
  execution_permission: string;
}

export function bucketIso(epochMs: number, bucketSeconds: number): string {
  const bucketMs = Math.max(1, bucketSeconds) * 1000;
  return new Date(Math.floor(epochMs / bucketMs) * bucketMs).toISOString();
}

export function mapMarketBars(rows: Array<Partial<MarketBar>> | undefined): MarketBar[] {
  const bars: MarketBar[] = [];
  for (const row of rows ?? []) {
    const parsed = Date.parse(String(row.timestamp ?? ""));
    const open = Number(row.open);
    const high = Number(row.high);
    const low = Number(row.low);
    const close = Number(row.close);
    if (!Number.isFinite(parsed) || ![open, high, low, close].every(Number.isFinite)) continue;
    bars.push({
      timestamp: new Date(parsed).toISOString(),
      open,
      high,
      low,
      close,
      volume: Number.isFinite(Number(row.volume)) ? Number(row.volume) : 0,
    });
  }
  return bars;
}

export async function loadMarketBars(symbol: string, bucketSeconds: number, limit = 160): Promise<MarketBarsResponse> {
  const params = new URLSearchParams({
    symbol,
    bucket_seconds: String(bucketSeconds),
    limit: String(limit),
  });
  const response = await fetch(`/api/market/bars?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Bar history failed (HTTP ${response.status}).`);
  const body = (await response.json()) as MarketBarsResponse;
  return { ...body, candles: mapMarketBars(body.candles) };
}

export function mergeTickIntoBars(
  bars: MarketBar[],
  tick: { exchangeTimestamp: string; price: number; size: number },
  bucketSeconds: number,
): MarketBar[] {
  const parsed = Date.parse(tick.exchangeTimestamp);
  if (!Number.isFinite(parsed) || !Number.isFinite(tick.price) || tick.price <= 0) return bars;
  const bucketTs = bucketIso(parsed, bucketSeconds);
  const next = bars.slice();
  const last = next[next.length - 1];
  const size = Number.isFinite(tick.size) ? tick.size : 0;
  if (last && last.timestamp === bucketTs) {
    next[next.length - 1] = {
      ...last,
      high: Math.max(last.high, tick.price),
      low: Math.min(last.low, tick.price),
      close: tick.price,
      volume: last.volume + size,
    };
    return next;
  }
  if (last && bucketTs < last.timestamp) return next;
  next.push({
    timestamp: bucketTs,
    open: tick.price,
    high: tick.price,
    low: tick.price,
    close: tick.price,
    volume: size,
  });
  return next.slice(-180);
}
