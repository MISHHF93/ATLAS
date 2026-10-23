import { FounderShell } from "../../src/components/founder/FounderPanel";
import { PortalView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Money" title="Partner wallet" summary="What partners hold with the custodian: NAV, holdings, subscriptions, redemptions and payouts.">
      <PortalView />
    </FounderShell>
  );
}
