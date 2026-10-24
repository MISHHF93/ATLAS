import { AtlasTerminal } from "@/app/AtlasTerminal";
import { ApiKeysView } from "@/src/ui/pages/Console";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="settings" tab={tab} panels={{
        "keys": <ApiKeysView />,
        "connectors": <AtlasTerminal initialSection="connectors" initialWorkspaceRoute="/data/pipelines" />,
      }} />
  );
}
