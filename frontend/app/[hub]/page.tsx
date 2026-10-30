import { notFound } from "next/navigation";
import { PAGES } from "@/src/nav/nav.config";
import { HubPage, tabParam, type HubProps } from "@/src/ui/Hub";

/** One route serves every page except Home (app/page.tsx); the page, its tabs and their panels all come from src/nav. */
export default async function Page(props: HubProps & { params: Promise<{ hub: string }> }) {
  const { hub } = await props.params;
  const page = PAGES.find((p) => p.id !== "home" && p.href === `/${hub}`);
  if (!page) notFound();
  return <HubPage page={page.id} tab={await tabParam(props)} />;
}
