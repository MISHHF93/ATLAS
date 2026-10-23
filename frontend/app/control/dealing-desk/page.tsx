import { redirect } from "next/navigation";

export default function LegacyPage() {
  redirect("/trade/blotter");
}
