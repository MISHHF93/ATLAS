import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function PaymentsPage() {
  return (
    <FounderShell title="Payments" summary="Founder treasury and subscription payments (sandbox rails, two-person + step-up approval in atlas-payments).">
      <FounderPanel path="ledgers" title="Payments ledger" hide={["ledgers"]} />
    </FounderShell>
  );
}
