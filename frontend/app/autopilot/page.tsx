import { PageHeader } from "../../src/ui/primitives";
import { AutopilotView } from "../../src/ui/pages/Console";

export default function Page() {
  return (
    <div className="ux-page">
      <PageHeader eyebrow="Trade" title="Setup autopilot" summary="Paper only. Request it on, switch it off instantly, and review what it saw." />
      <AutopilotView />
    </div>
  );
}
