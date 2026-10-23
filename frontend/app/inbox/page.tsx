import { FounderShell } from "../../src/components/founder/FounderPanel";
import { InboxView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell title="Action needed" summary="Everything waiting on you: Safe stop, paper approvals, payouts, policy and venue checks.">
      <InboxView />
    </FounderShell>
  );
}
