import Link from "next/link";
import type { ComponentProps } from "react";
import { href, type PageId, type RouteId } from "./nav.config";

/**
 * The only way application code links to an internal page. `to` is a page id ("markets") or a route id ("markets.depth");
 * the address comes from the config, so a renamed URL needs no edits here.
 */
export function NavLink({ to, ...rest }: { to: PageId | RouteId } & Omit<ComponentProps<typeof Link>, "href">) {
  return <Link href={href(to)} {...rest} />;
}
