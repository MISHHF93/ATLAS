import { PageHeader } from "../../../src/ui/primitives";
import { EvidenceView } from "../../../src/ui/pages/Console";

export default function Page() {
  return (
    <div className="ux-page">
      <PageHeader eyebrow="Research" title="Models & evidence" summary="What the autopilot is allowed to use, and the studies behind it." />
      <EvidenceView />
    </div>
  );
}
