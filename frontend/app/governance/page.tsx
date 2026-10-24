import { redirect } from "next/navigation";

/** Former address, kept working: opens the hub tab that now holds this content. */
export default function LegacyPage() {
  redirect("/data?tab=reserve");
}
