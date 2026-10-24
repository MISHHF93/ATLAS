import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";
import { AssistantView, EvolutionView, FourBoxView, LabView, MemoryView, MicrostructureView, RegimesView } from "@/src/ui/pages/IntelViews";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="lab" tab={tab} panels={{
        "experiments": <LabView />,
        "regimes": <RegimesView />,
        "memory": <MemoryView />,
        "assistant": <AssistantView />,
        "microstructure": <MicrostructureView />,
        "fourbox": <FourBoxView />,
        "evolution": <EvolutionView />,
      }} />
  );
}
