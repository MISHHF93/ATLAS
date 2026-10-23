import { FounderShell } from "../../src/components/founder/FounderPanel";
import { PaymentsView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Money" title="Payments" summary="Transfers, payees and manual transfer prep with two-person approval.">
      <PaymentsView />
    </FounderShell>
  );
}
