import { RoleProvider } from "../src/context/RoleContext";
import { StreamlinedTradingStudio } from "../src/components/workbench/StreamlinedTradingStudio";

export default function Page() {
  return (
    <RoleProvider>
      <StreamlinedTradingStudio />
    </RoleProvider>
  );
}
