import { RoleProvider } from "../../src/context/RoleContext";
import { StreamlinedTradingStudio } from "../../src/components/workbench/StreamlinedTradingStudio";

export default function TradePage() {
  return (
    <RoleProvider>
      <div className="ux-fullbleed">
        <StreamlinedTradingStudio />
      </div>
    </RoleProvider>
  );
}
