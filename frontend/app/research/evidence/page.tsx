import { AtlasTerminal } from "@/app/AtlasTerminal";
import { EvidenceView } from "@/src/ui/pages/Console";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";
import { MlModelsView } from "@/src/ui/pages/MlModels";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="models" tab={tab} panels={{
        "evidence": <EvidenceView />,
        "ml": <MlModelsView />,
        "walk-forward": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/walk-forward" />,
        "training": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/registry" />,
      }} />
  );
}
