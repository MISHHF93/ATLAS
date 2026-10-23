import { FounderShell } from "../../../src/components/founder/FounderPanel";
import { PriceActionView } from "../../../src/components/market/PriceActionView";

export default function Page() {
  return (
    <FounderShell title="Price-action zones" summary="Backend-computed zones and setups on closed bars. A detected pattern is not a trade; the control plane decides.">
      <PriceActionView />
    </FounderShell>
  );
}
