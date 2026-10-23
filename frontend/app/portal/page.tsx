import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function PortalPage() {
  return (
    <FounderShell title="Investor portal" summary="Investor wallet and fund statements (read-only, non-custodial).">
      <FounderPanel path="ledgers" title="Investor wallet and fund ledgers" hide={["payments"]} />
    </FounderShell>
  );
}
