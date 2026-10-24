import { RoleProvider } from "@/src/context/RoleContext";
import { StreamlinedTradingStudio } from "@/src/components/workbench/StreamlinedTradingStudio";
import { Module02ListingsView } from "@/src/components/market/Module02ListingsView";
import { AtlasTerminal } from "@/app/AtlasTerminal";
import { PaperAccountView } from "@/src/ui/pages/IntegrationsViews";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="desk" tab={tab} compact panels={{
        "chart": <RoleProvider><div className="ux-fullbleed"><StreamlinedTradingStudio /></div></RoleProvider>,
        "markets": <Module02ListingsView />,
        "paper": <PaperAccountView />,
        "depth": <AtlasTerminal initialSection="market" initialWorkspaceRoute="/trade/depth-dom" />,
      }} />
  );
}
