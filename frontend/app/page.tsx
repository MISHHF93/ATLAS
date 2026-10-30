import { ArrowRight } from "lucide-react";
import { NavLink } from "@/src/nav/NavLink";
import { HubPage, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  return (
    <HubPage page="home" tab={await tabParam(props)}
      actions={<NavLink className="ux-btn" to="markets">Open markets <ArrowRight size={14} aria-hidden /></NavLink>} />
  );
}
