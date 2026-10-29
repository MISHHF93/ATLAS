import { BrokerView } from "@/src/ui/pages/ExtViews";
import { CoverageCard, GoLiveReadinessCard, IntegrationsStatusCard, LivePredictionsCard, SetupChecklistCard } from "@/src/ui/pages/IntegrationsViews";
import { AtlasTerminal } from "@/app/AtlasTerminal";
import { FeedHealthPanel } from "@/src/components/market/FeedHealthPanel";
import { DocsReader } from "@/src/components/shell/DocsReader";
import { ApiKeysView } from "@/src/ui/pages/Console";
import { BillingPanel, ProfilePanel, SetupWizard } from "@/src/ui/pages/AccountViews";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="settings" tab={tab} panels={{
        "setup": <><SetupChecklistCard /><GoLiveReadinessCard /><SetupWizard /></>,
        "profile": <ProfilePanel />,
        "billing": <BillingPanel />,
        "keys": <ApiKeysView />,
        "connectors": (
          <>
            <LivePredictionsCard />
            <CoverageCard />
            <FeedHealthPanel />
            <AtlasTerminal initialSection="connectors" initialWorkspaceRoute="/data/pipelines" />
          </>
        ),
        "broker": <><GoLiveReadinessCard /><IntegrationsStatusCard /><BrokerView /></>,
        "bars": <AtlasTerminal initialSection="warehouse" initialWorkspaceRoute="/data/lakehouse" />,
        "reserve": <AtlasTerminal initialSection="governance" initialWorkspaceRoute="/data/governance" />,
        "capability": <AtlasTerminal initialSection="roadmap" initialWorkspaceRoute="/data/features-100" />,
        "docs": <DocsReader />,
      }} />
  );
}
