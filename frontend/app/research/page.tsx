import { AtlasTerminal } from "@/app/AtlasTerminal";
import { PriceActionView } from "@/src/components/market/PriceActionView";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="research" tab={tab} panels={{
        "chart": <AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/central-node" />,
        "zones": <PriceActionView />,
        "forecasts": <AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/prediction-ledger" />,
      }} />
  );
}
