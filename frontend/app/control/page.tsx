import { AtlasTerminal } from "@/app/AtlasTerminal";
import { PortfolioRiskView, TracksView } from "@/src/ui/pages/IntelViews";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="risk" tab={tab} panels={{
        "account": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/risk-hud" />,
        "portfolio": <PortfolioRiskView />,
        "tracks": <TracksView />,
        "limits": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/rulebook" />,
      }} />
  );
}
