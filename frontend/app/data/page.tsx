import { AtlasTerminal } from "@/app/AtlasTerminal";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="data" tab={tab} panels={{
        "bars": <AtlasTerminal initialSection="warehouse" initialWorkspaceRoute="/data/lakehouse" />,
        "reserve": <AtlasTerminal initialSection="governance" initialWorkspaceRoute="/data/governance" />,
        "capability": <AtlasTerminal initialSection="roadmap" initialWorkspaceRoute="/data/features-100" />,
      }} />
  );
}
