import { PageHeader } from "../../src/ui/primitives";
import { ApiKeysView } from "../../src/ui/pages/Console";

export default function Page() {
  return (
    <div className="ux-page">
      <PageHeader eyebrow="Settings" title="API keys" summary="Scoped, hashed, rate-limited keys for agents and the local MCP endpoint. No key can place a live order or move money." />
      <ApiKeysView />
    </div>
  );
}
