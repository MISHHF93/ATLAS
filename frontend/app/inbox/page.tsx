import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function InboxPage() {
  return (
    <FounderShell title="Action needed" summary="Everything waiting on you: Safe stop, paper approvals, policy and venue checks.">
      <FounderPanel path="inbox" title="Action needed" />
      <FounderPanel path="approvals" title="Approval queue (decide with atlas-owner + step-up)" />
    </FounderShell>
  );
}
