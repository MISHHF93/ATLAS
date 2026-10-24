import { BrokerView } from "@/src/ui/pages/ExtViews";
import { IntegrationsStatusCard } from "@/src/ui/pages/IntegrationsViews";
import { AtlasTerminal } from "@/app/AtlasTerminal";
import { FeedHealthPanel } from "@/src/components/market/FeedHealthPanel";
import { ApiKeysView } from "@/src/ui/pages/Console";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="settings" tab={tab} panels={{
        "keys": <ApiKeysView />,
        "connectors": (
          <>
            <FeedHealthPanel />
            <AtlasTerminal initialSection="connectors" initialWorkspaceRoute="/data/pipelines" />
          </>
        ),
        "broker": <><IntegrationsStatusCard /><BrokerView /></>,
      }} />
  );
}
