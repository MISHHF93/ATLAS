import { AtlasTerminal } from "@/app/AtlasTerminal";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="risk" tab={tab} panels={{
        "account": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/risk-hud" />,
        "positions": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/trade/blotter" />,
        "limits": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/rulebook" />,
      }} />
  );
}
