import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { InboxView } from "@/src/components/founder/views";
import { Overview } from "@/src/ui/pages/Overview";
import { Hub, tabParam, type HubProps } from "@/src/ui/Hub";

export default async function Page(props: HubProps) {
  const tab = await tabParam(props);
  return (
    <Hub id="overview" tab={tab}
      actions={<Link className="ux-btn" href="/trade">Open trading desk <ArrowRight size={14} aria-hidden /></Link>}
      panels={{ "overview": <Overview embedded />, "inbox": <InboxView /> }} />
  );
}
