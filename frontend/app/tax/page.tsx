import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function TaxPage() {
  return (
    <FounderShell title="Tax (Canada)" summary="ACB, superficial-loss guard, Bank of Canada FX, T5008 and T1135 records.">
      <FounderPanel path="tax" title="Tax summary" />
    </FounderShell>
  );
}
