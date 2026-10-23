import { FounderShell } from "../../src/components/founder/FounderPanel";
import { TaxView } from "../../src/components/founder/views";

export default function Page() {
  return (
    <FounderShell eyebrow="Money" title="Tax" summary="Canadian ACB, superficial loss, T5008 and T1135 summaries.">
      <TaxView />
    </FounderShell>
  );
}
