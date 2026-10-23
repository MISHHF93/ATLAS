import { FounderShell } from "../../src/components/founder/FounderPanel";
import { ComplianceView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell title="Compliance" summary="Sanctions hits, FINTRAC records, privacy and venue checks.">
      <ComplianceView />
    </FounderShell>
  );
}
