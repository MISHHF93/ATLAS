import { FounderShell } from "../../src/components/founder/FounderPanel";
import { ComplianceView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Compliance" title="Compliance overview" summary="Venue registration, sanctions screening, FINTRAC records and privacy policy.">
      <ComplianceView />
    </FounderShell>
  );
}
