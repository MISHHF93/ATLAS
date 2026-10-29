/**
 * The one page registry. Every top-level destination ("hub") is listed here with its tabs; the header, curtain menu,
 * breadcrumbs, command palette (Cmd-K), hub page headers, the 404 page and every legacy redirect are derived from it.
 * Older addresses are listed as `aliases` on the hub or tab that now holds their content.
 */
export type PageGroupId = "home" | "trade" | "research" | "money" | "settings";

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

export type HubTab = {
  id: string;
  label: string;
  /** One plain-language sentence shown under the tab bar. */
  summary: string;
  /** Desk workspace view this tab opens (used by desk buttons that jump between views). */
  workspaceRoute?: WorkspaceRoute;
  /** Older addresses that now open this tab. */
  aliases?: string[];
  /** Retired hub tabs (path?tab=id) whose content now lives in this tab. */
  tabAliases?: string[];
};

export type AtlasPage = {
  id: string;
  href: string;
  label: string;
  /** Short wording for the header bar when it differs from the label. */
  navLabel?: string;
  group: PageGroupId;
  summary: string;
  /** Tabs inside this hub. The first tab is the default and has no ?tab= in its address. */
  tabs?: HubTab[];
  workspaceRoute?: WorkspaceRoute;
  /** Older addresses that open this page (its first tab). */
  aliases?: string[];
  /** Specialist tools: listed under the curtain's "Advanced" group. */
  advanced?: boolean;
};

export const PAGE_GROUPS: Array<{ id: PageGroupId; label: string }> = [
  { id: "home", label: "Home" },
  { id: "trade", label: "Trade" },
  { id: "research", label: "Research" },
  { id: "money", label: "Money & compliance" },
  { id: "settings", label: "Settings, data & help" },
];

export const PAGES: AtlasPage[] = [
  {
    id: "overview", href: "/", label: "Overview", group: "home",
    summary: "Your paper account at a glance: balance, room left before Safe stop, open positions and everything waiting on you.",
    tabs: [
      { id: "overview", label: "Summary", summary: "Today's paper results, room before Safe stop, open positions and the top items needing attention." },
      { id: "inbox", label: "Action needed", aliases: ["/inbox"], summary: "Everything waiting on you: paper approvals, payouts, policy and venue checks." },
    ],
  },
  {
    id: "desk", href: "/trade", label: "Trading desk", navLabel: "Trade", group: "trade",
    summary: "Pick a symbol, read the chart and send a paper order. Nothing here reaches a live market.",
    tabs: [
      { id: "chart", label: "Chart & ticket", workspaceRoute: "/trade/cockpit", aliases: ["/workbench", "/trade/cockpit", "/market"],
        summary: "The symbol list, the price chart and the paper order ticket." },
      { id: "markets", label: "Market list", aliases: ["/listings"], tabAliases: ["/trade?tab=pump"],
        summary: "Search the authentic instrument catalog: Gold & Silver, ETFs, CME Futures, FX, US Stocks and Liquid Crypto." },
      { id: "brief", label: "Daily brief",
        summary: "Yesterday's verified investments, today's AI market brief, portfolio attribution, multifactor ratings, ML forecasts and archive." },
      { id: "paper", label: "Paper account",
        summary: "Alpaca paper (optional) equity, cash, positions, orders and fills, reconciled. Read-only; live accounts are refused." },
      { id: "depth", label: "Order book estimate", workspaceRoute: "/trade/depth-dom", aliases: ["/trade/depth-dom"],
        summary: "An estimated order book built from the last close and the catalog spread. It is not a real exchange book." },
    ],
  },
  {
    id: "risk", href: "/control", label: "Risk & autopilot", navLabel: "Risk", group: "trade",
    summary: "How much room the paper account has, what is open right now, the limits that protect it, and the paper autopilot switch.",
    tabs: [
      { id: "account", label: "Account & positions", workspaceRoute: "/control/risk-hud",
        aliases: ["/control/risk-hud", "/profile", "/trade/blotter", "/control/dealing-desk"], tabAliases: ["/control?tab=positions"],
        summary: "Equity, drawdown room, total exposure, stop protection and every open position for the one paper account." },
      { id: "portfolio", label: "Portfolio risk", summary: "Exposure, correlation, VaR/CVaR and stress for the open paper book. Unpriced positions are listed, not guessed." },
      { id: "tracks", label: "Track rules", summary: "Competition and open-market rulebooks side by side, with probes showing each is enforced separately." },
      { id: "limits", label: "Limits & rules", workspaceRoute: "/control/rulebook", aliases: ["/control/rulebook", "/rules", "/configurations"],
        summary: "The trading limits in force, plus a risk check you can run on a paper ticket before sending it." },
      { id: "autopilot", label: "Autopilot", aliases: ["/autopilot"],
        summary: "Ask to switch the paper setup autopilot on (owner approves), switch it off instantly, and review what it saw." },
    ],
  },
  {
    id: "research", href: "/research", label: "Market research", navLabel: "Research", group: "research",
    summary: "Study price behaviour for the symbol on the desk. Research can never place an order.",
    tabs: [
      { id: "chart", label: "Chart read", workspaceRoute: "/research/central-node",
        aliases: ["/research/central-node", "/research/microstructure", "/research/drift-dashboard", "/matrix"],
        tabAliases: ["/research/lab?tab=microstructure"],
        summary: "Candle patterns, order-flow measurements and tier-gated microstructure metrics for the current symbol." },
      { id: "zones", label: "Price zones", aliases: ["/research/price-action"], tabAliases: ["/research/lab?tab=fourbox"],
        summary: "Opening ranges, breakout-and-retest setups, wick zones and the Four-Box summary. Setups are ideas, not trades." },
      { id: "levels", label: "Levels & sweeps", aliases: ["/research/levels"],
        summary: "Prior-day, session and swing levels, sweeps and reclaims, gold opening boxes, and the strategy switches. Research only." },
      { id: "scan", label: "Scan & Pine", summary: "Watchlist pivot/Fibonacci/zone crossings, VWAP and volume profile, and Pine v5 export with ATLAS replay statistics. Research only." },
      { id: "valuation", label: "Valuation", tabAliases: ["/research/lab?tab=valuation"],
        summary: "DCF (FCFF/FCFE), SEC filed fundamentals and investor-persona scores with a capped weight matrix. Research only." },
      { id: "options", label: "Options", tabAliases: ["/research/lab?tab=options"],
        summary: "Black-Scholes price, greeks and implied volatility. Live chains are unavailable without a licensed provider." },
      { id: "context", label: "Macro & news", summary: "Economic calendar, SEC filings, Federal Reserve / Bank of Canada / SEC releases and headlines from official, key-free sources. Context only." },
      { id: "news", label: "News & AI review", summary: "Your watchlist's SEC filings and headlines with hype/scam flags, plus the LLM Reviewer that can only veto or downgrade ML proposals. Advisory only: it never places an order." },
      { id: "agents", label: "Agents & dossier", tabAliases: ["/research?tab=multi-agent", "/research/lab?tab=agents"],
        summary: "Conviction 1–100 with named rules, plus parallel analysts, a bull/bear debate and a dry run. Research only: never submits an order." },
    ],
  },
  {
    id: "lab", href: "/research/lab", label: "Models & lab", navLabel: "Models", group: "research",
    summary: "Which models the autopilot may use, the tests behind them, and the lab that produces them. Research only: nothing here can place an order.",
    aliases: ["/research/evidence"],
    tabs: [
      { id: "evidence", label: "Approved models", tabAliases: ["/research/evidence?tab=evidence"], summary: "Registered setup models and the evidence files that back them." },
      { id: "ml", label: "ML meta-labels", tabAliases: ["/research/evidence?tab=ml"],
        summary: "Meta-label models trained on live feeds: gates, calibration, drift and cited explanations. Read-only." },
      { id: "forecasts", label: "Forecast ledger", workspaceRoute: "/research/prediction-ledger", aliases: ["/research/prediction-ledger"], tabAliases: ["/research?tab=forecasts"],
        summary: "Every recorded forecast, the data it used, and how it turned out." },
      { id: "walk-forward", label: "Back-tests", workspaceRoute: "/research/walk-forward", aliases: ["/research/walk-forward", "/experiments"], tabAliases: ["/research/evidence?tab=walk-forward"],
        summary: "Run the standard walk-forward test. Passing a test does not promote a model." },
      { id: "training", label: "Training", workspaceRoute: "/research/registry", aliases: ["/models", "/research/registry"], tabAliases: ["/research/evidence?tab=training"],
        summary: "Train the isolated research policy on desk candles. It cannot send an order." },
      { id: "experiments", label: "Experiments", summary: "Recorded variant experiments with deflated Sharpe, PBO, bootstrap intervals and cost sensitivity." },
      { id: "regimes", label: "Regimes", summary: "A causal trend/volatility regime label and how each strategy did in each regime." },
      { id: "memory", label: "Memory & governance", summary: "Where replay results came from, the closest past setups, and the model registry's promotion state." },
      { id: "evolution", label: "Model evolution", summary: "Generations of candidate models and bar types scored on the same walk-forward folds. Nothing is promoted to trading." },
      { id: "assistant", label: "Assistant", summary: "Ask a question; answers are quoted from docs and lab reports with evidence IDs." },
    ],
  },
  {
    id: "money", href: "/money", label: "Money & compliance", navLabel: "Money", group: "money",
    summary: "Profit and loss, payments, partner holdings, tax records, regulatory checks and the audit trail. Read-only: nothing here moves money.",
    tabs: [
      { id: "overview", label: "Summary", summary: "Paper P&L, room before Safe stop and the non-custodial ledgers." },
      { id: "payments", label: "Payments", aliases: ["/payments"], summary: "Transfers and payees. Any transfer needs two-person approval." },
      { id: "partners", label: "Partner wallet", aliases: ["/portal"], summary: "What partners hold with the custodian: value, holdings and statements." },
      { id: "tax", label: "Tax", aliases: ["/tax"], summary: "Canadian cost base (ACB), superficial losses, FX rates, T5008 and T1135." },
      { id: "regulatory", label: "Regulatory", aliases: ["/compliance"], tabAliases: ["/compliance?tab=overview"],
        summary: "Venue registration, sanctions screening, FINTRAC records and privacy." },
      { id: "audit", label: "Audit log", workspaceRoute: "/control/surveillance", aliases: ["/control/surveillance", "/trade/journal"], tabAliases: ["/compliance?tab=audit"],
        summary: "Every order and control-plane event, as recorded." },
      { id: "identity", label: "Identity check", workspaceRoute: "/control/proctoring", aliases: ["/control/proctoring"], tabAliases: ["/compliance?tab=identity"],
        summary: "Run a typed example through the identity checklist. No camera is opened." },
    ],
  },
  {
    id: "settings", href: "/settings", label: "Settings, data & help", navLabel: "Settings", group: "settings",
    summary: "Your account, step-by-step connector setup, access keys, data connectors and specialist data tools, plus the specifications this desk is built from.",
    tabs: [
      { id: "setup", label: "Setup", summary: "Step-by-step setup: add your free data, broker (paper only) and alert keys, then test each one. Keys are stored encrypted and only your account can use them." },
      { id: "profile", label: "Account", summary: "Your profile, password, signed-in devices and a log of every change to your account and keys." },
      { id: "billing", label: "Plan", summary: "Your plan and what it includes. Test mode with placeholder prices; ATLAS takes no commission on trades." },
      { id: "keys", label: "API keys", aliases: ["/keys"],
        summary: "Create read or research keys for agents, see each once, revoke any time. No key can trade live or move money." },
      { id: "connectors", label: "Connectors", workspaceRoute: "/data/pipelines", aliases: ["/data/pipelines", "/connectors", "/integrations", "/sync"],
        summary: "Data connector records. A test writes an audit line and does not open a vendor connection." },
      { id: "broker", label: "Broker & alerts", summary: "Integration status for every service, Alpaca paper status (live refused), alert channels (off by default) and the read-only agent tool list." },
      { id: "bars", label: "Bar query", workspaceRoute: "/data/lakehouse", aliases: ["/data", "/data/lakehouse", "/warehouse"], tabAliases: ["/data?tab=bars"],
        summary: "Load closed price bars for the symbol on the desk." },
      { id: "reserve", label: "Reserve plan", workspaceRoute: "/data/governance", aliases: ["/governance", "/data/governance"], tabAliases: ["/data?tab=reserve"],
        summary: "Load the paper reserve plan. It does not send an order." },
      { id: "capability", label: "Capability map", workspaceRoute: "/data/features-100", aliases: ["/data/features-100", "/roadmap"], tabAliases: ["/data?tab=capability"],
        summary: "A map of 100 desk ideas, each linked to the page that actually runs it." },
      { id: "docs", label: "Help & docs", aliases: ["/docs"], summary: "The specifications this desk is built from, in plain reading form." },
    ],
  },
];

/** Address of a hub tab. The first tab is the bare hub address. */
export function tabHref(page: AtlasPage, tabId?: string): string {
  if (!tabId || !page.tabs || page.tabs[0].id === tabId) return page.href;
  return `${page.href}?tab=${tabId}`;
}

const ALIAS_TARGET: Record<string, { page: AtlasPage; href: string }> = Object.fromEntries(
  PAGES.flatMap((page) => [
    ...(page.aliases ?? []).map((a) => [a, { page, href: page.href }] as const),
    ...(page.tabs ?? []).flatMap((t) => (t.aliases ?? []).map((a) => [a, { page, href: tabHref(page, t.id) }] as const)),
  ])
);

/** Every retired hub tab ("/hub?tab=old") and the exact URL it now opens. */
const TAB_ALIAS_TARGET: Record<string, string> = Object.fromEntries(
  PAGES.flatMap((page) => (page.tabs ?? []).flatMap((t) => (t.tabAliases ?? []).map((a) => [a, tabHref(page, t.id)] as const)))
);
/** Same targets with an explicit ?tab= so Next's redirect cannot carry the retired tab id through (which would loop). */
const TAB_ALIAS_EXPLICIT: Record<string, string> = Object.fromEntries(
  PAGES.flatMap((page) => (page.tabs ?? []).flatMap((t) => (t.tabAliases ?? []).map((a) => [a, `${page.href}?tab=${t.id}`] as const)))
);

export type LegacyRedirect = { source: string; destination: string; permanent: true; has?: Array<{ type: "query"; key: "tab"; value: string }> };

/** Permanent (308) redirects for next.config: every older address, then every retired tab. */
export function legacyRedirects(): LegacyRedirect[] {
  const paths = Object.entries(ALIAS_TARGET).map(([source, t]) => ({ source, destination: t.href, permanent: true as const }));
  const tabs = Object.entries(TAB_ALIAS_EXPLICIT).map(([from, destination]) => {
    const [source, query] = from.split("?");
    const value = new URLSearchParams(query).get("tab")!;
    return { source, destination, permanent: true as const, has: [{ type: "query" as const, key: "tab" as const, value }] };
  });
  // Retired-tab rules (they carry a `has` query match) go first so they win over the bare path rule of the same source.
  return [...tabs, ...paths];
}

/** Every older address and the exact URL (hub + tab) it redirects to. */
export function redirectTarget(path: string): string | null {
  return ALIAS_TARGET[path]?.href ?? TAB_ALIAS_TARGET[path] ?? null;
}

export function pageForPath(path: string): AtlasPage {
  const clean = path.split(/[?#]/)[0];
  return ALIAS_TARGET[clean]?.page ?? PAGES.find((page) => page.href === clean) ?? PAGES[0];
}

/** Flat list of desk workspace views with the tab that owns each one. */
export const WORKSPACE_VIEWS: Array<{ route: WorkspaceRoute; title: string; summary: string; href: string }> = PAGES.flatMap((page) =>
  (page.tabs ?? []).filter((t) => t.workspaceRoute).map((t) => ({ route: t.workspaceRoute!, title: t.label, summary: t.summary, href: tabHref(page, t.id) }))
);

/** Canonical URL for desk buttons and older workspace destinations. */
export function hrefForWorkspace(route: WorkspaceRoute): string {
  return WORKSPACE_VIEWS.find((v) => v.route === route)?.href ?? redirectTarget(route) ?? pageForPath(route).href;
}
