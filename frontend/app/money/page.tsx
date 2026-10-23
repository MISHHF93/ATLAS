import { FounderPanel, FounderShell } from "../../src/components/founder/FounderPanel";

export default function MoneyPage() {
  return (
    <FounderShell title="Money" summary="The 8 non-custodial money ledgers and read-only balances.">
      <FounderPanel path="ledgers" title="Non-custodial ledgers" />
      <FounderPanel path="state" title="Founder capital track (2% daily-loss Safe stop)" />
    </FounderShell>
  );
}
