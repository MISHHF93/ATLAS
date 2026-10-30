/**
 * Panels for every route id in nav.config.ts. Each entry loads its views on demand, so only the open tab's modules are
 * evaluated (other tabs make no backend calls). `Record<RouteId, …>` makes a missing or misspelled route a compile error;
 * scripts/nav.test.mjs checks the same thing for the test run.
 */
import type { ReactNode } from "react";
import type { SectionId } from "@/app/AtlasTerminal";
import type { SubPageRouteId } from "@/src/components/shell/InstitutionalWorkspacesView";
import type { RouteId } from "./nav.config";

type Loader = () => Promise<ReactNode>;
/** A view of the specialist desk component (AtlasTerminal) opened at one workspace. */
const desk = (initialSection: SectionId, initialWorkspaceRoute: SubPageRouteId): Loader => async () => {
  const { AtlasTerminal } = await import("@/app/AtlasTerminal");
  return <AtlasTerminal initialSection={initialSection} initialWorkspaceRoute={initialWorkspaceRoute} />;
};

export const PANELS: Record<RouteId, Loader> = {
  // Home
  "home.overview": async () => { const { Overview } = await import("@/src/ui/pages/Overview"); return <Overview />; },
  "home.inbox": async () => { const { InboxView } = await import("@/src/components/founder/views"); return <InboxView />; },

  // Markets
  "markets.chart": async () => {
    const [{ RoleProvider }, { StreamlinedTradingStudio }] = await Promise.all([
      import("@/src/context/RoleContext"), import("@/src/components/workbench/StreamlinedTradingStudio"),
    ]);
    return <RoleProvider><div className="ux-fullbleed"><StreamlinedTradingStudio /></div></RoleProvider>;
  },
  "markets.list": async () => { const { Module02ListingsView } = await import("@/src/components/market/Module02ListingsView"); return <Module02ListingsView />; },
  "markets.depth": desk("market", "/trade/depth-dom"),
  "markets.read": async () => {
    const [{ AtlasTerminal }, { MicrostructureView }] = await Promise.all([import("@/app/AtlasTerminal"), import("@/src/ui/pages/IntelViews")]);
    return <><AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/central-node" /><MicrostructureView /></>;
  },
  "markets.zones": async () => {
    const [{ PriceActionView }, { LevelsView }, { FourBoxView }] = await Promise.all([
      import("@/src/components/market/PriceActionView"), import("@/src/components/market/LevelsView"), import("@/src/ui/pages/IntelViews"),
    ]);
    return <><PriceActionView /><FourBoxView /><LevelsView /></>;
  },
  "markets.scan": async () => { const { ScanView } = await import("@/src/ui/pages/ExtViews"); return <ScanView />; },
  "markets.valuation": async () => { const { ValuationView } = await import("@/src/ui/pages/ExtViews"); return <ValuationView />; },
  "markets.options": async () => { const { OptionsView } = await import("@/src/ui/pages/ExtViews"); return <OptionsView />; },

  // Predictions & ML
  "predictions.forecasts": desk("research", "/research/prediction-ledger"),
  "predictions.models": async () => {
    const [{ EvidenceView }, { MlModelsView }] = await Promise.all([import("@/src/ui/pages/Console"), import("@/src/ui/pages/MlModels")]);
    return <><EvidenceView /><MlModelsView /></>;
  },
  "predictions.walk-forward": desk("models", "/research/walk-forward"),
  "predictions.training": async () => {
    const [{ AtlasTerminal }, { EvolutionView }] = await Promise.all([import("@/app/AtlasTerminal"), import("@/src/ui/pages/IntelViews")]);
    return <><AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/registry" /><EvolutionView /></>;
  },
  "predictions.experiments": async () => { const { LabView, RegimesView } = await import("@/src/ui/pages/IntelViews"); return <><LabView /><RegimesView /></>; },
  "predictions.memory": async () => { const { MemoryView } = await import("@/src/ui/pages/IntelViews"); return <MemoryView />; },
  "predictions.assistant": async () => { const { AssistantView } = await import("@/src/ui/pages/IntelViews"); return <AssistantView />; },

  // News & AI
  "news.brief": async () => { const { AiDailyInvestmentBriefWorkspace } = await import("@/src/components/market/AiDailyInvestmentBriefPanel"); return <AiDailyInvestmentBriefWorkspace />; },
  "news.headlines": async () => { const { NewsFeedView } = await import("@/src/ui/pages/NewsViews"); return <NewsFeedView />; },
  "news.macro": async () => { const { ContextView } = await import("@/src/ui/pages/ContextViews"); return <ContextView />; },
  "news.agents": async () => {
    const [{ AgentsView }, { MultiAgentView }] = await Promise.all([import("@/src/ui/pages/ExtViews"), import("@/src/ui/pages/MultiAgentView")]);
    return <><AgentsView /><MultiAgentView /></>;
  },

  // Account & risk
  "account.positions": desk("rules", "/control/risk-hud"),
  "account.paper": async () => { const { PaperAccountView } = await import("@/src/ui/pages/IntegrationsViews"); return <PaperAccountView />; },
  "account.portfolio": async () => { const { PortfolioRiskView } = await import("@/src/ui/pages/IntelViews"); return <PortfolioRiskView />; },
  "account.limits": async () => {
    const [{ AtlasTerminal }, { TracksView }] = await Promise.all([import("@/app/AtlasTerminal"), import("@/src/ui/pages/IntelViews")]);
    return <><AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/rulebook" /><TracksView /></>;
  },
  "account.autopilot": async () => { const { AutopilotView } = await import("@/src/ui/pages/Console"); return <AutopilotView />; },

  // Money & compliance
  "money.overview": async () => { const { MoneyView } = await import("@/src/components/founder/views"); return <MoneyView />; },
  "money.payments": async () => { const { PaymentsView } = await import("@/src/components/founder/views"); return <PaymentsView />; },
  "money.partners": async () => { const { PortalView } = await import("@/src/components/founder/views"); return <PortalView />; },
  "money.tax": async () => { const { TaxView } = await import("@/src/components/founder/views"); return <TaxView />; },
  "money.regulatory": async () => { const { ComplianceView } = await import("@/src/components/founder/views"); return <ComplianceView />; },
  "money.audit": desk("matrix", "/control/surveillance"),
  "money.identity": desk("rules", "/control/proctoring"),

  // Data
  "data.providers": async () => {
    const [{ AtlasTerminal }, { CoverageCard }] = await Promise.all([import("@/app/AtlasTerminal"), import("@/src/ui/pages/IntegrationsViews")]);
    return <><CoverageCard /><AtlasTerminal initialSection="connectors" initialWorkspaceRoute="/data/pipelines" /></>;
  },
  "data.bars": desk("warehouse", "/data/lakehouse"),
  "data.broker": async () => { const { BrokerView } = await import("@/src/ui/pages/ExtViews"); return <BrokerView />; },
  "data.reserve": desk("governance", "/data/governance"),
  "data.capability": desk("roadmap", "/data/features-100"),

  // Health
  "health.feeds": async () => {
    const [{ LivePredictionsCard }, { FeedHealthPanel }] = await Promise.all([import("@/src/ui/pages/IntegrationsViews"), import("@/src/components/market/FeedHealthPanel")]);
    return <><LivePredictionsCard /><FeedHealthPanel /></>;
  },
  "health.predictions": async () => { const { PredictionHealthView } = await import("@/src/ui/pages/PredictionHealth"); return <PredictionHealthView />; },
  "health.integrations": async () => {
    const { GoLiveReadinessCard, IntegrationsStatusCard } = await import("@/src/ui/pages/IntegrationsViews");
    return <><IntegrationsStatusCard /><GoLiveReadinessCard /></>;
  },

  // Settings & help
  "settings.setup": async () => {
    const [{ SetupChecklistCard }, { SetupWizard }] = await Promise.all([import("@/src/ui/pages/IntegrationsViews"), import("@/src/ui/pages/AccountViews")]);
    return <><SetupChecklistCard /><SetupWizard /></>;
  },
  "settings.profile": async () => { const { ProfilePanel } = await import("@/src/ui/pages/AccountViews"); return <ProfilePanel />; },
  "settings.billing": async () => { const { BillingPanel } = await import("@/src/ui/pages/AccountViews"); return <BillingPanel />; },
  "settings.keys": async () => { const { ApiKeysView } = await import("@/src/ui/pages/Console"); return <ApiKeysView />; },
  "settings.docs": async () => { const { DocsReader } = await import("@/src/components/shell/DocsReader"); return <DocsReader />; },
};
