import { FounderShell } from "../../src/components/founder/FounderPanel";
import { MoneyView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell title="Money" summary="Founder P&amp;L, equity and drawdown, loss limits and the non-custodial ledgers.">
      <MoneyView />
    </FounderShell>
  );
}
