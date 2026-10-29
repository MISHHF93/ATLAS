"use client";

export type GuideIconName =
  | "desk"
  | "markets"
  | "trade"
  | "risk"
  | "research"
  | "data"
  | "pages"
  | "search"
  | "all"
  | "equity"
  | "crypto"
  | "futures"
  | "unlisted"
  | "competition"
  | "reserve";

const MARK_LABEL: Record<GuideIconName, string> = {
  desk: "Desk",
  markets: "Markets",
  trade: "Trade",
  risk: "Risk",
  research: "Research",
  data: "Data",
  pages: "Pages",
  search: "Search",
  all: "All",
  equity: "Listed",
  crypto: "Crypto",
  futures: "Futures",
  unlisted: "Not listed",
  competition: "Competition",
  reserve: "Reserve",
};

export function markLabel(name: GuideIconName): string {
  return MARK_LABEL[name];
}

export function markColor(name: GuideIconName): string | undefined {
  if (name === "equity") return "#00C8FF";
  if (name === "crypto" || name === "competition") return "#00F29D";
  if (name === "futures" || name === "reserve") return "#F4C460";
  if (name === "unlisted") return "#94A3B8";
  return undefined;
}

export function markForAsset(assetClass: string, exchange?: string): GuideIconName {
  if (exchange === "UNLISTED") return "unlisted";
  if (assetClass === "crypto_perps") return "crypto";
  if (assetClass === "futures") return "futures";
  return "equity";
}

export function markForSymbol(symbol: string): GuideIconName {
  const upper = symbol.toUpperCase();
  if (upper.endsWith("-USD")) return "crypto";
  if (["ES", "NQ", "YM", "RTY", "MES", "MNQ", "MYM", "M2K", "GC", "MGC", "SI", "CL", "MCL", "NG", "ZN", "ZB", "6E", "6J", "EUR_USD", "USD_CAD"].includes(upper)) return "futures";
  return "equity";
}

export function markForPage(pageId: string): GuideIconName {
  if (pageId === "listings") return "markets";
  if (pageId === "cockpit" || pageId === "depth" || pageId === "positions" || pageId === "journal") return "trade";
  if (pageId === "account" || pageId === "rulebook" || pageId === "audit" || pageId === "identity" || pageId === "exposure") return "risk";
  if (pageId === "chart-read" || pageId === "walk-forward" || pageId === "flow" || pageId === "training") return "research";
  if (pageId === "bars" || pageId === "connectors") return "data";
  if (pageId === "reserve") return "reserve";
  if (pageId === "capability" || pageId === "specs") return "pages";
  if (pageId === "money") return "reserve";
  if (pageId === "inbox") return "risk";
  return "desk";
}

export function markForGroup(groupId: string): GuideIconName {
  if (groupId === "trade") return "trade";
  if (groupId === "risk") return "risk";
  if (groupId === "research") return "research";
  if (groupId === "data") return "data";
  return "desk";
}

export const ASSET_MARKS: Array<{ name: GuideIconName; label: string }> = [
  { name: "equity", label: "Listed" },
  { name: "crypto", label: "Crypto" },
  { name: "futures", label: "Futures" },
  { name: "unlisted", label: "Not listed" },
];

function iconBody(name: GuideIconName) {
  switch (name) {
    case "desk":
      return <path d="M3 13V8.5M8 13V3.5M13 13V6.5" />;
    case "markets":
      return (
        <>
          <rect x="2" y="2" width="5" height="5" rx="1" />
          <rect x="9" y="2" width="5" height="5" rx="1" />
          <rect x="2" y="9" width="5" height="5" rx="1" />
          <rect x="9" y="9" width="5" height="5" rx="1" />
        </>
      );
    case "trade":
      return <path d="M4.5 2v12M4.5 5H7.2v5H4.5M11.5 2v12M8.8 6.5H11.5v5H8.8" />;
    case "risk":
      return <path d="M8 1.8 13.2 4v4.2c0 3.1-2.6 5-5.2 6.2C5.4 13.2 2.8 11.3 2.8 8.2V4L8 1.8z" />;
    case "research":
      return (
        <>
          <circle cx="4" cy="8" r="1.7" />
          <circle cx="12" cy="4.4" r="1.7" />
          <circle cx="12" cy="11.6" r="1.7" />
          <path d="M5.6 7.3 10.4 5.2M5.6 8.7l4.8 2.1" />
        </>
      );
    case "data":
      return <path d="M2 5.2 8 2.4l6 2.8L8 8 2 5.2zM2 8.2 8 11l6-2.8M2 11.2 8 14l6-2.8" />;
    case "pages":
      return <path d="M3 4h10M3 8h10M3 12h6" />;
    case "search":
      return (
        <>
          <circle cx="7" cy="7" r="4" />
          <path d="m10.2 10.2 3.3 3.3" />
        </>
      );
    case "all":
      return (
        <>
          <circle cx="5" cy="5" r="1.3" fill="currentColor" stroke="none" />
          <circle cx="11" cy="5" r="1.3" fill="currentColor" stroke="none" />
          <circle cx="5" cy="11" r="1.3" fill="currentColor" stroke="none" />
          <circle cx="11" cy="11" r="1.3" fill="currentColor" stroke="none" />
        </>
      );
    case "equity":
      return <path d="M2.8 14V6.5L8 3.2l5.2 3.3V14H2.8zM6.2 14V10h3.6v4" />;
    case "crypto":
      return (
        <>
          <circle cx="8" cy="8" r="5.2" />
          <path d="M8 5.2 10.3 8 8 10.8 5.7 8 8 5.2z" />
        </>
      );
    case "futures":
      return <path d="M4 2.5h6.2L13 5.2V13.5H4V2.5zM10 2.5V5.4H13" />;
    case "unlisted":
      return (
        <>
          <circle cx="8" cy="8" r="5.2" />
          <path d="M4.6 11.4 11.4 4.6" />
        </>
      );
    case "competition":
      return <path d="M4 14V2.5M4 2.5h7.2L9.6 5.2 11.2 8H4" />;
    case "reserve":
      return <path d="M3 6.5h10v7H3v-7zM6 6.5V4.2h4v2.3M8 9.2v2" />;
    default:
      return null;
  }
}

export function GuideIcon({
  name,
  size = 14,
  color,
}: {
  name: GuideIconName;
  size?: number;
  color?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ color, flex: "none", display: "block" }}
    >
      {iconBody(name)}
    </svg>
  );
}

export function AssetMarkLegend() {
  return (
    <div className="atlas-mark-legend" aria-label="How to read a symbol">
      {ASSET_MARKS.map((mark) => (
        <span key={mark.name}>
          <GuideIcon name={mark.name} color={markColor(mark.name)} />
          {mark.label}
        </span>
      ))}
    </div>
  );
}
