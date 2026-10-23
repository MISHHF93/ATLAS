import { FounderShell } from "../../src/components/founder/FounderPanel";
import { MoneyView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Money" title="Money overview" summary="Paper P&amp;L, room left before Safe stop, equity and drawdown, and the non-custodial ledgers.">
      <MoneyView />
    </FounderShell>
  );
}
