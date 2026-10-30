import { AtlasTerminal } from "@/app/AtlasTerminal";
import { EvidenceView } from "@/src/ui/pages/Console";
import { MlModelsView } from "@/src/ui/pages/MlModels";
import { PredictionHealthView } from "@/src/ui/pages/PredictionHealth";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";
import { AssistantView, EvolutionView, LabView, MemoryView, RegimesView } from "@/src/ui/pages/IntelViews";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="lab" tab={tab} panels={{
        "evidence": <EvidenceView />,
        "ml": <MlModelsView />,
        "forecasts": <AtlasTerminal initialSection="research" initialWorkspaceRoute="/research/prediction-ledger" />,
        "walk-forward": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/walk-forward" />,
        "training": <AtlasTerminal initialSection="models" initialWorkspaceRoute="/research/registry" />,
        "predictions": <PredictionHealthView />,
        "experiments": <LabView />,
        "regimes": <RegimesView />,
        "memory": <MemoryView />,
        "evolution": <EvolutionView />,
        "assistant": <AssistantView />,
      }} />
  );
}
