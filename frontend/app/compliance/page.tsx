import { AtlasTerminal } from "@/app/AtlasTerminal";
import { ComplianceView } from "@/src/components/founder/views";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="compliance" tab={tab} panels={{
        "overview": <ComplianceView />,
        "audit": <AtlasTerminal initialSection="matrix" initialWorkspaceRoute="/control/surveillance" />,
        "identity": <AtlasTerminal initialSection="rules" initialWorkspaceRoute="/control/proctoring" />,
      }} />
  );
}
