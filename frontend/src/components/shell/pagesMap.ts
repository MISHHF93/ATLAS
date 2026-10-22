export type PageGroupId = "desk" | "trade" | "risk" | "research" | "data";

export type WorkspaceRoute =
  | "/trade/cockpit"
  | "/trade/depth-dom"
  | "/trade/blotter"
  | "/trade/journal"
  | "/control/risk-hud"
  | "/control/rulebook"
  | "/control/surveillance"
  | "/control/proctoring"
  | "/control/dealing-desk"
  | "/research/central-node"
  | "/research/walk-forward"
  | "/research/microstructure"
  | "/research/registry"
  | "/data/lakehouse"
  | "/data/pipelines"
  | "/data/governance"
  | "/data/features-100";

export type AtlasPage = {
  id: string;
  href: string;
  label: string;
  /** Top-bar wording when it differs from the page label. */
  navLabel?: string;
  group: PageGroupId;
  summary: string;
  primary?: boolean;
  /** Shell route this address opens. The public href can be shorter. */
  workspaceRoute?: WorkspaceRoute;
  /** Older addresses that open this same page. */
  aliases?: string[];
};

export const PAGE_GROUPS: Array<{ id: PageGroupId; label: string }> = [
  { id: "desk", label: "Desk" },
  { id: "trade", label: "Trade" },
  { id: "risk", label: "Risk" },
  { id: "research", label: "Research" },
  { id: "data", label: "Data" },
];

export const PAGES: AtlasPage[] = [
  {
    id: "desk",
    href: "/",
    label: "Desk",
    group: "desk",
    primary: true,
    summary: "Symbol directory, the chart, and the paper ticket.",
    aliases: ["/workbench"],
  },
  {
    id: "listings",
    href: "/listings",
    label: "Listings",
    navLabel: "Markets",
    group: "desk",
    primary: true,
    summary: "Catalog search. Entries are fixture metadata, not a live listing session.",
  },
  {
    id: "cockpit",
    href: "/trade",
    label: "Cockpit",
    navLabel: "Trade",
    group: "trade",
    primary: true,
    workspaceRoute: "/trade/cockpit",
    summary: "Chart, watchlist, and the paper order ticket.",
    aliases: ["/trade/cockpit", "/market"],
  },
  {
    id: "depth",
    href: "/trade/depth-dom",
    label: "Depth ladder",
    group: "trade",
    workspaceRoute: "/trade/depth-dom",
    summary: "A reconstructed ladder from the last close and the catalog spread. Not an exchange book.",
  },
  {
    id: "positions",
    href: "/trade/blotter",
    label: "Positions",
    group: "trade",
    workspaceRoute: "/trade/blotter",
    summary: "Open control-plane positions and recorded decisions.",
  },
  {
    id: "journal",
    href: "/trade/journal",
    label: "Journal",
    group: "trade",
    workspaceRoute: "/trade/journal",
    summary: "Control-plane orders and audit lines.",
  },
  {
    id: "account",
    href: "/control",
    label: "Account risk",
    navLabel: "Risk",
    group: "risk",
    primary: true,
    workspaceRoute: "/control/risk-hud",
    summary: "The one paper account: equity, drawdown room, and open positions.",
    aliases: ["/control/risk-hud", "/profile"],
  },
  {
    id: "rulebook",
    href: "/control/rulebook",
    label: "Rulebook",
    group: "risk",
    workspaceRoute: "/control/rulebook",
    summary: "The printed limits, plus a check of the cockpit ticket against the live account.",
    aliases: ["/rules", "/settings", "/configurations"],
  },
  {
    id: "audit",
    href: "/control/surveillance",
    label: "Audit log",
    group: "risk",
    workspaceRoute: "/control/surveillance",
    summary: "Orders and audit lines the control plane recorded.",
  },
  {
    id: "identity",
    href: "/control/proctoring",
    label: "Identity checklist",
    group: "risk",
    workspaceRoute: "/control/proctoring",
    summary: "Send a typed example to the checklist. No camera is opened.",
  },
  {
    id: "exposure",
    href: "/control/dealing-desk",
    label: "Open positions",
    group: "risk",
    workspaceRoute: "/control/dealing-desk",
    summary: "Notional of positions the control plane still has open.",
  },
  {
    id: "chart-read",
    href: "/research",
    label: "Chart read",
    navLabel: "Research",
    group: "research",
    primary: true,
    workspaceRoute: "/research/central-node",
    summary: "Read closed public candles for the symbol on the desk. It cannot place an order.",
    aliases: ["/research/central-node"],
  },
  {
    id: "walk-forward",
    href: "/research/walk-forward",
    label: "Walk-forward",
    group: "research",
    workspaceRoute: "/research/walk-forward",
    summary: "Run the frozen benchmark study. A finished study is not a promotion.",
    aliases: ["/experiments"],
  },
  {
    id: "flow",
    href: "/research/microstructure",
    label: "Flow read",
    group: "research",
    workspaceRoute: "/research/microstructure",
    summary: "The same public-candle read. There is no live order book on this page.",
    aliases: ["/matrix"],
  },
  {
    id: "training",
    href: "/models",
    label: "Training status",
    group: "research",
    workspaceRoute: "/research/registry",
    summary: "Fit the air-gapped policy on desk candles. It cannot send an order.",
    aliases: ["/research/registry"],
  },
  {
    id: "bars",
    href: "/data",
    label: "Bar query",
    navLabel: "Data",
    group: "data",
    primary: true,
    workspaceRoute: "/data/lakehouse",
    summary: "Load closed bars for the symbol on the desk. This is not a SQL warehouse.",
    aliases: ["/data/lakehouse", "/warehouse"],
  },
  {
    id: "connectors",
    href: "/data/pipelines",
    label: "Connectors",
    group: "data",
    workspaceRoute: "/data/pipelines",
    summary: "Connector records on this process. A test writes an audit line and does not open a vendor socket.",
    aliases: ["/connectors", "/integrations", "/sync"],
  },
  {
    id: "reserve",
    href: "/governance",
    label: "Reserve sleeve",
    group: "data",
    workspaceRoute: "/data/governance",
    summary: "Load the paper reserve plan. It does not send an order.",
    aliases: ["/data/governance"],
  },
  {
    id: "capability",
    href: "/data/features-100",
    label: "Capability map",
    group: "data",
    workspaceRoute: "/data/features-100",
    summary: "A map of 100 desk ideas. Open a row to use the page that actually runs.",
    aliases: ["/roadmap"],
  },
  {
    id: "specs",
    href: "/docs",
    label: "Specifications",
    group: "data",
    summary: "The specification files this desk is built from. Reading them does not send an order.",
  },
];

const ALIAS_TO_HREF: Record<string, string> = Object.fromEntries(
  PAGES.flatMap((page) => (page.aliases ?? []).map((alias) => [alias, page.href]))
);

export function pageForPath(path: string): AtlasPage {
  const href = ALIAS_TO_HREF[path] ?? path;
  return PAGES.find((page) => page.href === href) ?? PAGES[0];
}
