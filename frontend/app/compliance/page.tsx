import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function CompliancePage() {
  return (
    <FounderShell title="Compliance" summary="FINTRAC records, sanctions screening, privacy and Canadian venue registration.">
      <FounderPanel path="compliance" title="Compliance overview" />
      <FounderPanel path="venues" title="Canadian venues and broker restrictions" />
    </FounderShell>
  );
}
