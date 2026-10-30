/**
 * The one navigation config. Pages, tabs, their addresses, header placement and every retired address (`legacy`) are
 * declared here, once, as typed data. The header, menu, command palette, page frame, 404 page and the
 * next.config redirects are all derived from it, and `panels.tsx` must supply a panel for every route id below
 * (checked by the compiler and by scripts/nav.test.mjs).
 *
 * Keep this file import-free: tests and scripts load it directly.
 *
 * Address rules: the first tab of a page is the bare address (`/markets`); other tabs are `/markets?tab=depth`.
 * Retired addresses go in `legacy` as either a path (`/trade`) or a path with a tab (`/trade?tab=paper`).
 */

export type SectionId = "work" | "account" | "system";
export type Placement = "logo" | "header" | "menu";

/** Desk workspace views that older code and the specialist desk component still name; each maps to the tab that shows it. */
export type WorkspaceRoute =
  | "/trade/cockpit" | "/trade/depth-dom" | "/trade/blotter" | "/trade/journal"
  | "/control/risk-hud" | "/control/rulebook" | "/control/surveillance" | "/control/proctoring" | "/control/dealing-desk"
  | "/research/central-node" | "/research/walk-forward" | "/research/microstructure" | "/research/registry" | "/research/prediction-ledger"
  | "/data/lakehouse" | "/data/pipelines" | "/data/governance" | "/data/features-100";

type TabDef = {
  readonly id: string;
  readonly label: string;
  /** One plain-language sentence shown under the tabs. */
  readonly summary: string;
  readonly workspace?: WorkspaceRoute;
  /** Retired addresses (path, or path?tab=id) that now open this tab. */
  readonly legacy?: readonly string[];
};
type PageDef = {
  readonly id: string;
  readonly href: string;
  readonly label: string;
  /** Short wording for the header bar. */
  readonly navLabel: string;
  readonly section: SectionId;
  /** logo = the brand mark links here; header = a header item; menu = reachable from the account menu, Menu and Cmd-K only. */
  readonly placement: Placement;
  readonly summary: string;
  readonly tabs: readonly TabDef[];
};

export const NAV_SECTIONS = [
  { id: "work", label: "Markets & research" },
  { id: "account", label: "Account & money" },
  { id: "system", label: "Data & system" },
] as const satisfies ReadonlyArray<{ id: SectionId; label: string }>;

export const NAV_PAGES = [
  {
    id: "home", href: "/", label: "Home", navLabel: "Home", section: "work", placement: "logo",
    summary: "Your paper account at a glance: balance, room left before Safe stop, open positions and everything waiting on you.",
    tabs: [
      { id: "overview", label: "Summary",
        summary: "Today's paper results, room before Safe stop, open positions and the top items needing attention." },
      { id: "inbox", label: "Action needed", legacy: ["/inbox"],
        summary: "Everything waiting on you: paper approvals, payouts, policy and venue checks." },
    ],
  },
  {
    id: "markets", href: "/markets", label: "Markets", navLabel: "Markets", section: "work", placement: "header",
    summary: "Chart and paper ticket, market list, order-book estimate, chart read, price zones, scans, valuation and options.",
    tabs: [
      { id: "chart", label: "Chart & ticket", workspace: "/trade/cockpit", legacy: ["/market","/trade","/trade/cockpit","/trade?tab=chart","/workbench"],
        summary: "The symbol list, the price chart and the paper order ticket." },
      { id: "list", label: "Market list", legacy: ["/listings","/trade?tab=markets","/trade?tab=pump"],
        summary: "Search the authentic instrument catalog: Gold & Silver, ETFs, CME Futures, FX, US Stocks and Liquid Crypto." },
      { id: "depth", label: "Order book estimate", workspace: "/trade/depth-dom", legacy: ["/trade/depth-dom","/trade?tab=depth"],
        summary: "An estimated order book built from the last close and the catalog spread. It is not a real exchange book." },
      { id: "read", label: "Chart read", workspace: "/research/central-node", legacy: ["/matrix","/research","/research/central-node","/research/drift-dashboard","/research/lab?tab=microstructure","/research/microstructure","/research?tab=chart"],
        summary: "Candle patterns, order-flow measurements and tier-gated microstructure metrics for the current symbol." },
      { id: "zones", label: "Zones & levels", legacy: ["/research/lab?tab=fourbox","/research/levels","/research/price-action","/research?tab=levels","/research?tab=zones"],
        summary: "Price zones, four-box read, levels and sweeps for the symbol on the desk. Context for you, not signals." },
      { id: "scan", label: "Scan & Pine", legacy: ["/research?tab=scan"],
        summary: "Watchlist pivot/Fibonacci/zone crossings, VWAP and volume profile, and Pine v5 export with ATLAS replay statistics. Research only." },
      { id: "valuation", label: "Valuation", legacy: ["/research/lab?tab=valuation","/research?tab=valuation"],
        summary: "DCF (FCFF/FCFE), SEC filed fundamentals and investor-persona scores with a capped weight matrix. Research only." },
      { id: "options", label: "Options", legacy: ["/research/lab?tab=options","/research?tab=options"],
        summary: "Black-Scholes price, greeks and implied volatility. Live chains are unavailable without a licensed provider." },
    ],
  },
  {
    id: "predictions", href: "/predictions", label: "Predictions & ML", navLabel: "Predictions", section: "work", placement: "header",
    summary: "Forecasts, model evidence, back-tests, training and the experiments behind them. Research display only; models never place orders.",
    tabs: [
      { id: "forecasts", label: "Forecasts", workspace: "/research/prediction-ledger", legacy: ["/research/lab?tab=forecasts","/research/prediction-ledger","/research?tab=forecasts"],
        summary: "Every recorded forecast, the data it used, and how it turned out." },
      { id: "models", label: "Models", legacy: ["/research/evidence","/research/evidence?tab=evidence","/research/evidence?tab=ml","/research/lab","/research/lab?tab=evidence","/research/lab?tab=ml"],
        summary: "Approved models with their evidence, plus ML meta-labels. Research display only." },
      { id: "walk-forward", label: "Back-tests", workspace: "/research/walk-forward", legacy: ["/experiments","/research/evidence?tab=walk-forward","/research/lab?tab=walk-forward","/research/walk-forward"],
        summary: "Run the standard walk-forward test. Passing a test does not promote a model." },
      { id: "training", label: "Training & evolution", workspace: "/research/registry", legacy: ["/models","/research/evidence?tab=training","/research/lab?tab=evolution","/research/lab?tab=training","/research/registry"],
        summary: "Model training runs and registry, plus how the models evolve over time." },
      { id: "experiments", label: "Experiments & regimes", legacy: ["/research/lab?tab=experiments","/research/lab?tab=regimes"],
        summary: "Experiments and the market regimes they were run in." },
      { id: "memory", label: "Memory & governance", legacy: ["/research/lab?tab=memory"],
        summary: "Where replay results came from, the closest past setups, and the model registry's promotion state." },
      { id: "assistant", label: "Assistant", legacy: ["/research/lab?tab=assistant"],
        summary: "Ask a question; answers are quoted from docs and lab reports with evidence IDs." },
    ],
  },
  {
    id: "news", href: "/news", label: "News & AI", navLabel: "News & AI", section: "work", placement: "header",
    summary: "Your daily brief, headlines with AI review, the macro calendar and the agents' dossier. Advisory only.",
    tabs: [
      { id: "brief", label: "Daily brief", legacy: ["/trade?tab=brief"],
        summary: "Yesterday's verified investments, today's AI market brief, portfolio attribution, multifactor ratings, ML forecasts and archive." },
      { id: "headlines", label: "Headlines & AI review", legacy: ["/research?tab=news"],
        summary: "Watchlist SEC filings and headlines with hype/scam flags, plus an LLM Reviewer that can only veto or downgrade ML proposals. Advisory only." },
      { id: "macro", label: "Macro & calendar", legacy: ["/research?tab=context"],
        summary: "Economic calendar, SEC filings, Federal Reserve / Bank of Canada / SEC releases and headlines from official, key-free sources. Context only." },
      { id: "agents", label: "Agents & dossier", legacy: ["/research/lab?tab=agents","/research?tab=agents","/research?tab=multi-agent"],
        summary: "Conviction 1–100 with named rules, plus parallel analysts, a bull/bear debate and a dry run. Research only: never submits an order." },
    ],
  },
  {
    id: "account", href: "/account", label: "Account & risk", navLabel: "Account", section: "account", placement: "header",
    summary: "Paper positions and account, portfolio risk, limits, track rules and autopilot. Safe stop status is always in the header.",
    tabs: [
      { id: "positions", label: "Positions", workspace: "/control/risk-hud", legacy: ["/control","/control/dealing-desk","/control/risk-hud","/control?tab=account","/control?tab=positions","/profile","/trade/blotter"],
        summary: "Equity, drawdown room, total exposure, stop protection and every open position for the one paper account." },
      { id: "paper", label: "Paper account", legacy: ["/trade?tab=paper"],
        summary: "Alpaca paper (optional) equity, cash, positions, orders and fills, reconciled. Read-only; live accounts are refused." },
      { id: "portfolio", label: "Portfolio risk", legacy: ["/control?tab=portfolio"],
        summary: "Exposure, correlation, VaR/CVaR and stress for the open paper book. Unpriced positions are listed, not guessed." },
      { id: "limits", label: "Limits & tracks", workspace: "/control/rulebook", legacy: ["/configurations","/control/rulebook","/control?tab=limits","/control?tab=tracks","/rules"],
        summary: "Your limits and rules, plus the rules each track (equities, competition) applies." },
      { id: "autopilot", label: "Autopilot & Safe stop", legacy: ["/autopilot","/control?tab=autopilot"],
        summary: "Engage the Safe stop, switch the paper autopilot off, ask to turn it on (owner approves) and review what it saw." },
    ],
  },
  {
    id: "money", href: "/money", label: "Money & compliance", navLabel: "Money", section: "account", placement: "header",
    summary: "Profit and loss, payments, partner holdings, tax records, regulatory checks and the audit trail. Read-only: nothing here moves money.",
    tabs: [
      { id: "overview", label: "Summary",
        summary: "Paper P&L, room before Safe stop and the non-custodial ledgers." },
      { id: "payments", label: "Payments", legacy: ["/payments"],
        summary: "Transfers and payees. Any transfer needs two-person approval." },
      { id: "partners", label: "Partner wallet", legacy: ["/portal"],
        summary: "What partners hold with the custodian: value, holdings and statements." },
      { id: "tax", label: "Tax", legacy: ["/tax"],
        summary: "Canadian cost base (ACB), superficial losses, FX rates, T5008 and T1135." },
      { id: "regulatory", label: "Regulatory", legacy: ["/compliance","/compliance?tab=overview"],
        summary: "Venue registration, sanctions screening, FINTRAC records and privacy." },
      { id: "audit", label: "Audit log", workspace: "/control/surveillance", legacy: ["/compliance?tab=audit","/control/surveillance","/trade/journal"],
        summary: "Every order and control-plane event, as recorded." },
      { id: "identity", label: "Identity check", workspace: "/control/proctoring", legacy: ["/compliance?tab=identity","/control/proctoring"],
        summary: "Run a typed example through the identity checklist. No camera is opened." },
    ],
  },
  {
    id: "data", href: "/data", label: "Data", navLabel: "Data", section: "system", placement: "header",
    summary: "Data providers, closed-bar queries, broker and alert integrations, the reserve plan and the capability map.",
    tabs: [
      { id: "providers", label: "Providers & connectors", workspace: "/data/pipelines", legacy: ["/connectors","/data/pipelines","/integrations","/settings?tab=connectors","/sync"],
        summary: "Data connector records. A test writes an audit line and does not open a vendor connection." },
      { id: "bars", label: "Bar query", workspace: "/data/lakehouse", legacy: ["/data/lakehouse","/settings?tab=bars","/warehouse"],
        summary: "Load closed price bars for the symbol on the desk." },
      { id: "broker", label: "Broker & alerts", legacy: ["/settings?tab=broker"],
        summary: "Integration status for every service, Alpaca paper status (live refused), alert channels (off by default) and the read-only agent tool list." },
      { id: "reserve", label: "Reserve plan", workspace: "/data/governance", legacy: ["/data/governance","/governance","/settings?tab=reserve"],
        summary: "Load the paper reserve plan. It does not send an order." },
      { id: "capability", label: "Capability map", workspace: "/data/features-100", legacy: ["/data/features-100","/roadmap","/settings?tab=capability"],
        summary: "A map of 100 desk ideas, each linked to the page that actually runs it." },
    ],
  },
  {
    id: "health", href: "/health", label: "Health", navLabel: "Health", section: "system", placement: "header",
    summary: "Whether the data and predictions feeding the desk are fresh, and whether each integration is ready.",
    tabs: [
      { id: "feeds", label: "Feeds & freshness",
        summary: "Live prediction status and data-feed freshness for every catalog asset." },
      { id: "predictions", label: "Prediction health", legacy: ["/research/lab?tab=predictions"],
        summary: "Every catalog asset: last real data, last prediction, model version and why there is none. Research display only." },
      { id: "integrations", label: "Integrations & go-live",
        summary: "Status of every integration and what is still needed before go-live. Paper only; live is refused." },
    ],
  },
  {
    id: "settings", href: "/settings", label: "Settings & help", navLabel: "Settings", section: "system", placement: "menu",
    summary: "Your account and plan, step-by-step setup, access keys and the specifications this desk is built from.",
    tabs: [
      { id: "setup", label: "Setup",
        summary: "Step-by-step setup: add your free data, broker (paper only) and alert keys, then test each one. Keys are stored encrypted and only your account can use them." },
      { id: "profile", label: "Profile",
        summary: "Your profile, password, signed-in devices and a log of every change to your account and keys." },
      { id: "billing", label: "Plan",
        summary: "Your plan and what it includes. Test mode with placeholder prices; ATLAS takes no commission on trades." },
      { id: "keys", label: "API keys", legacy: ["/keys"],
        summary: "Create read or research keys for agents, see each once, revoke any time. No key can trade live or move money." },
      { id: "docs", label: "Help & docs", legacy: ["/docs"],
        summary: "The specifications this desk is built from, in plain reading form." },
    ],
  },
] as const satisfies readonly PageDef[];

// ---------------------------------------------------------------------------------------------------------------------
// Derived types
// ---------------------------------------------------------------------------------------------------------------------
type Pages = typeof NAV_PAGES;
export type PageId = Pages[number]["id"];
export type TabIdOf<P extends PageId> = Extract<Pages[number], { id: P }>["tabs"][number]["id"];
/** Every addressable view as "page.tab", e.g. "markets.depth". The compiler checks panels and links against this. */
export type RouteId = { [P in PageId]: `${P}.${TabIdOf<P>}` }[PageId];

export type NavTab = {
  id: string; label: string; summary: string; workspace?: WorkspaceRoute; legacy?: readonly string[];
};
export type AtlasPage = {
  id: PageId; href: string; label: string; navLabel: string; section: SectionId; placement: Placement; summary: string; tabs: readonly NavTab[];
};
export type HubTab = NavTab;
export const PAGES: readonly AtlasPage[] = NAV_PAGES;

export function splitRoute(route: RouteId): { page: PageId; tab: string } {
  const [page, tab] = route.split(".");
  return { page: page as PageId, tab };
}

export function pageById(id: string): AtlasPage | undefined {
  return PAGES.find((p) => p.id === id);
}

/** Address of a tab. The first tab is the bare page address. */
export function tabHref(page: AtlasPage, tabId?: string): string {
  if (!tabId || page.tabs[0].id === tabId || !page.tabs.some((t) => t.id === tabId)) return page.href;
  return `${page.href}?tab=${tabId}`;
}

/** Address of a page (its first tab) or of a "page.tab" route. The only way application code should build an internal link. */
export function href(target: PageId | RouteId): string {
  if (target.includes(".")) {
    const { page, tab } = splitRoute(target as RouteId);
    return tabHref(pageById(page)!, tab);
  }
  return pageById(target)!.href;
}

export function activeTab(page: AtlasPage, tab?: string | null): NavTab {
  return page.tabs.find((t) => t.id === tab) ?? page.tabs[0];
}

// ---------------------------------------------------------------------------------------------------------------------
// Legacy addresses -> redirects
// ---------------------------------------------------------------------------------------------------------------------
type LegacyEntry = { source: string; tab?: string; page: AtlasPage; tabDef: NavTab; destination: string };

const LEGACY: readonly LegacyEntry[] = PAGES.flatMap((page) =>
  page.tabs.flatMap((tabDef) =>
    (tabDef.legacy ?? []).map((from) => {
      const [source, query] = from.split("?");
      const tab = query ? new URLSearchParams(query).get("tab") ?? undefined : undefined;
      // Always an explicit ?tab=, even for a first tab: Next carries the request's query through a redirect, so a retired
      // tab id would otherwise ride along to the destination.
      const destination = `${page.href}?tab=${tabDef.id}`;
      return { source, tab, page, tabDef, destination };
    })
  )
);

export type LegacyRedirect = { source: string; destination: string; permanent: true; has?: Array<{ type: "query"; key: "tab"; value: string }> };

/** Permanent (308) redirects for next.config: retired tabs first (they carry a query match), then retired paths. */
export function legacyRedirects(): LegacyRedirect[] {
  const tabs = LEGACY.filter((e) => e.tab).map((e) => ({
    source: e.source, destination: e.destination, permanent: true as const, has: [{ type: "query" as const, key: "tab" as const, value: e.tab! }],
  }));
  const paths = LEGACY.filter((e) => !e.tab).map((e) => ({
    source: e.source, destination: e.tabDef === e.page.tabs[0] ? e.page.href : e.destination, permanent: true as const,
  }));
  return [...tabs, ...paths];
}

/** Where a retired address ("/trade", "/trade?tab=paper") now lives, or null when it is not a retired address. */
export function redirectTarget(address: string): string | null {
  const hit = LEGACY.find((e) => e.source + (e.tab ? `?tab=${e.tab}` : "") === address);
  return hit ? tabHref(hit.page, hit.tabDef.id) : null;
}

/** The page that owns a path: canonical pages first, then retired paths (which resolve to the page that absorbed them). */
export function pageForPath(path: string): AtlasPage {
  const clean = path.split(/[?#]/)[0];
  return PAGES.find((p) => p.href === clean) ?? LEGACY.find((e) => e.source === clean)?.page ?? PAGES[0];
}

/** Flat list of desk workspace views with the tab that owns each one. */
export const WORKSPACE_VIEWS: ReadonlyArray<{ route: WorkspaceRoute; title: string; summary: string; href: string }> = PAGES.flatMap((page) =>
  page.tabs.filter((t) => t.workspace).map((t) => ({ route: t.workspace!, title: t.label, summary: t.summary, href: tabHref(page, t.id) }))
);

/** Canonical URL for desk buttons and older workspace destinations. */
export function hrefForWorkspace(route: WorkspaceRoute): string {
  return WORKSPACE_VIEWS.find((v) => v.route === route)?.href ?? redirectTarget(route) ?? pageForPath(route).href;
}
