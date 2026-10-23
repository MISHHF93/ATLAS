export type PageGroupId = "home" | "trade" | "money" | "research" | "compliance" | "settings";

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
  | "/research/prediction-ledger"
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
  { id: "home", label: "Home" },
  { id: "trade", label: "Trade" },
  { id: "money", label: "Money" },
  { id: "research", label: "Research" },
  { id: "compliance", label: "Compliance" },
  { id: "settings", label: "Settings" },
];

export const PAGES: AtlasPage[] = [
  {
    id: "overview",
    href: "/",
    label: "Overview",
    group: "home",
    primary: true,
    summary: "Paper account, Safe stop room, open positions and what needs you today.",
  },
  {
    id: "desk",
    href: "/trade",
    label: "Trading desk",
    navLabel: "Desk",
    group: "trade",
    primary: true,
    summary: "Symbol directory, the chart, and the paper ticket.",
    workspaceRoute: "/trade/cockpit",
    aliases: ["/workbench", "/trade/cockpit", "/market"],
  },
  {
    id: "listings",
    href: "/listings",
    label: "Listings",
    navLabel: "Markets",
    group: "trade",
    summary: "Catalog search. Entries are fixture metadata, not a live listing session.",
  },
  {
    id: "depth",
    href: "/trade/depth-dom",
    label: "Estimated depth",
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
    summary: "Open positions, total exposure, and stop protection from the control plane.",
    aliases: ["/control/dealing-desk"],
  },
  {
    id: "account",
    href: "/control",
    label: "Account risk",
    navLabel: "Risk",
    group: "trade",
    workspaceRoute: "/control/risk-hud",
    summary: "The one paper account: equity, drawdown room, and open positions.",
    aliases: ["/control/risk-hud", "/profile"],
  },
  {
    id: "rulebook",
    href: "/control/rulebook",
    label: "Rulebook",
    group: "settings",
    primary: true,
    workspaceRoute: "/control/rulebook",
    summary: "Trading limits and a paper ticket risk check against the account.",
    aliases: ["/rules", "/settings", "/configurations"],
  },
  {
    id: "audit",
    href: "/control/surveillance",
    label: "Audit log",
    group: "compliance",
    workspaceRoute: "/control/surveillance",
    summary: "Order history and audit lines recorded by the control plane.",
    aliases: ["/trade/journal"],
  },
  {
    id: "identity",
    href: "/control/proctoring",
    label: "Identity checklist",
    group: "compliance",
    workspaceRoute: "/control/proctoring",
    summary: "Send a typed example to the checklist. No camera is opened.",
  },
  {
    id: "chart-read",
    href: "/research",
    label: "Chart read",
    navLabel: "Chart read",
    group: "research",
    primary: true,
    workspaceRoute: "/research/central-node",
    summary: "Candle research and flow measurements for the symbol on the desk. It cannot place an order.",
    aliases: ["/research/central-node", "/research/microstructure", "/research/drift-dashboard", "/matrix"],
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
    id: "training",
    href: "/models",
    label: "Training status",
    group: "research",
    workspaceRoute: "/research/registry",
    summary: "Fit the air-gapped policy on desk candles. It cannot send an order.",
    aliases: ["/research/registry"],
  },
  {
    id: "prediction-ledger",
    href: "/research/prediction-ledger",
    label: "Prediction ledger",
    group: "research",
    workspaceRoute: "/research/prediction-ledger",
    summary: "Persistent PIT forecasts, walk-forward evidence, model inputs, outcomes, and paper authorizations.",
  },
  {
    id: "bars",
    href: "/data",
    label: "Bar query",
    group: "research",
    workspaceRoute: "/data/lakehouse",
    summary: "Load closed bars for the symbol on the desk. This is not a SQL warehouse.",
    aliases: ["/data/lakehouse", "/warehouse"],
  },
  {
    id: "connectors",
    href: "/data/pipelines",
    label: "Connectors",
    group: "settings",
    workspaceRoute: "/data/pipelines",
    summary: "Connector records on this process. A test writes an audit line and does not open a vendor socket.",
    aliases: ["/connectors", "/integrations", "/sync"],
  },
  {
    id: "reserve",
    href: "/governance",
    label: "Reserve sleeve",
    group: "research",
    workspaceRoute: "/data/governance",
    summary: "Load the paper reserve plan. It does not send an order.",
    aliases: ["/data/governance"],
  },
  {
    id: "capability",
    href: "/data/features-100",
    label: "Capability map",
    group: "settings",
    workspaceRoute: "/data/features-100",
    summary: "A map of 100 desk ideas. Open a row to use the page that actually runs.",
    aliases: ["/roadmap"],
  },
  {
    id: "specs",
    href: "/docs",
    label: "Specifications",
    navLabel: "Docs",
    group: "settings",
    summary: "The specification files this desk is built from. Reading them does not send an order.",
  },
  {
    id: "inbox",
    href: "/inbox",
    label: "Action needed",
    navLabel: "Inbox",
    group: "home",
    summary: "Safe stop, paper approvals and checks waiting on you.",
  },
  {
    id: "money",
    href: "/money",
    label: "Money",
    navLabel: "Overview",
    group: "money",
    primary: true,
    summary: "The 8 non-custodial money ledgers and read-only balances.",
  },
  {
    id: "payments",
    href: "/payments",
    label: "Payments",
    group: "money",
    summary: "Founder treasury and subscription payments (sandbox).",
  },
  {
    id: "portal",
    href: "/portal",
    label: "Partner wallet",
    group: "money",
    summary: "Investor wallet and fund statements, read-only.",
  },
  {
    id: "tax",
    href: "/tax",
    label: "Tax",
    group: "money",
    summary: "Canadian ACB, superficial loss, BoC FX, T5008 and T1135.",
  },
  {
    id: "compliance",
    href: "/compliance",
    label: "Compliance overview",
    navLabel: "Overview",
    group: "compliance",
    primary: true,
    summary: "FINTRAC records, sanctions, privacy and Canadian venues.",
  },
];

const ALIAS_TO_HREF: Record<string, string> = Object.fromEntries(
  PAGES.flatMap((page) => (page.aliases ?? []).map((alias) => [alias, page.href]))
);

export function pageForPath(path: string): AtlasPage {
  const href = ALIAS_TO_HREF[path] ?? path;
  return PAGES.find((page) => page.href === href) ?? PAGES[0];
}

/** Canonical URL for shell buttons and older workspace destinations. */
export function hrefForWorkspace(route: WorkspaceRoute): string {
  return pageForPath(route).href;
}
