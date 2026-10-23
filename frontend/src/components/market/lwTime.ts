/** Shared Lightweight Charts options: America/Toronto time axis and TradingView attribution.
 *  Lightweight Charts treats UTCTimestamp values as UTC and renders them in UTC unless
 *  formatters are supplied, so bars from ATLAS (UTC seconds) are relabelled here.
 *  Apache-2.0 NOTICE requires crediting TradingView with a link; `attributionLogo` does that on-chart. */
import type { DeepPartial, ChartOptions, Time } from "lightweight-charts";

export const DESK_TIME_ZONE = "America/Toronto";

const seconds = (time: Time): number => {
  if (typeof time === "number") return time;
  if (typeof time === "string") return Date.parse(`${time}T00:00:00Z`) / 1000;
  return Date.UTC(time.year, time.month - 1, time.day) / 1000;
};

const fmt = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("en-CA", { timeZone: DESK_TIME_ZONE, hour12: false, ...options });
const full = fmt({ year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
const hm = fmt({ hour: "2-digit", minute: "2-digit" });
const md = fmt({ month: "short", day: "numeric" });
const ym = fmt({ year: "numeric", month: "short" });
const y = fmt({ year: "numeric" });

export function formatDeskTime(unixSeconds: number): string {
  return `${full.format(new Date(unixSeconds * 1000))} ET`;
}

export const deskTimeOptions: DeepPartial<ChartOptions> = {
  layout: { attributionLogo: true },
  localization: { timeFormatter: (time: Time) => formatDeskTime(seconds(time)) },
  timeScale: {
    timeVisible: true,
    // TickMarkType: 0 Year, 1 Month, 2 DayOfMonth, 3 Time, 4 TimeWithSeconds
    tickMarkFormatter: (time: Time, type: number) => {
      const date = new Date(seconds(time) * 1000);
      if (type === 0) return y.format(date);
      if (type === 1) return ym.format(date);
      if (type === 2) return md.format(date);
      return hm.format(date);
    },
  },
};

/** Freshness of the newest bar: close time = open + bucket. */
export function freshness(lastOpenUnix: number | null | undefined, bucketSeconds: number, nowMs = Date.now()) {
  if (!lastOpenUnix) return { label: "no bars", stale: true };
  const close = lastOpenUnix + bucketSeconds;
  const age = Math.max(0, Math.floor(nowMs / 1000) - close);
  const stale = age > Math.max(2 * bucketSeconds, 300);
  const ageText = age < 120 ? `${age}s` : age < 7200 ? `${Math.round(age / 60)}m` : `${Math.round(age / 3600)}h`;
  return { label: `last bar closed ${formatDeskTime(close)} (${ageText} ago)`, stale };
}
