import { ScanView } from "@/src/ui/pages/ExtViews";
import { AtlasTerminal } from "@/app/AtlasTerminal";
import { LevelsView } from "@/src/components/market/LevelsView";
import { PriceActionView } from "@/src/components/market/PriceActionView";
import { FourBoxView, MicrostructureView } from "@/src/ui/pages/IntelViews";
import { MultiAgentView } from "@/src/ui/pages/MultiAgentView";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="research" tab={tab} panels={{
        "chart": (
          <>
            <AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/central-node" />
            <MicrostructureView />
          </>
        ),
        "zones": (
          <>
            <PriceActionView />
            <FourBoxView />
          </>
        ),
        "levels": <LevelsView />,
        "forecasts": <AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/prediction-ledger" />,
        "scan": <ScanView />,
        "multi-agent": <MultiAgentView />,
      }} />
  );
}
