import { MoneyView, PaymentsView, PortalView, TaxView } from "@/src/components/founder/views";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="money" tab={tab} panels={{
        "overview": <MoneyView />,
        "payments": <PaymentsView />,
        "partners": <PortalView />,
        "tax": <TaxView />,
      }} />
  );
}
