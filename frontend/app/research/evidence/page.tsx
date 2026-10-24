import { AtlasTerminal } from "@/app/AtlasTerminal";
import { EvidenceView } from "@/src/ui/pages/Console";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="models" tab={tab} panels={{
        "evidence": <EvidenceView />,
        "walk-forward": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/walk-forward" />,
        "training": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/registry" />,
      }} />
  );
}
