import { FounderShell } from "../../src/components/founder/FounderPanel";
import { InboxView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Home" title="Inbox" summary="Everything waiting on you: paper approvals, payouts, policy and venue checks.">
      <InboxView />
    </FounderShell>
  );
}
