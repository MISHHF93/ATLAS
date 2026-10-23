import { FounderShell } from "../../src/components/founder/FounderPanel";
import { PortalView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell title="Investor portal" summary="Read-only investor wallet: NAV, balances, subscriptions, redemptions and payouts.">
      <PortalView />
    </FounderShell>
  );
}
