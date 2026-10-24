/**
 * Single route config consumer. `pagesMap.ts` is the one registry; the header, curtain menu, breadcrumbs, command
 * palette, hub headers and the 404 page are all derived from it here, so adding a page or tab there is the only step.
 */
import { PAGE_GROUPS, PAGES, pageForPath, redirectTarget, tabHref, type AtlasPage, type HubTab, type PageGroupId } from "../components/shell/pagesMap";

export type NavSection = { id: PageGroupId; label: string; href: string; pages: AtlasPage[] };

/** Main destinations by group (Advanced tools excluded). */
export const SECTIONS: NavSection[] = PAGE_GROUPS.map((group) => {
  const pages = PAGES.filter((p) => p.group === group.id && !p.advanced);
  return { id: group.id, label: group.label, href: pages[0]?.href ?? "/", pages };
}).filter((s) => s.pages.length);

/** Specialist tools, shown together in the curtain's "Advanced" group. */
export const ADVANCED: AtlasPage[] = PAGES.filter((p) => p.advanced);

/** The few destinations always visible in the header bar. Everything else is one click away in Menu or Cmd-K. */
export const HEADER_LINKS: Array<{ label: string; href: string; pageIds: string[] }> = [
  { label: "Trade", href: "/trade", pageIds: ["desk", "autopilot"] },
  { label: "Risk", href: "/control", pageIds: ["risk"] },
  { label: "Research", href: "/research", pageIds: ["research", "models", "data"] },
  { label: "Money", href: "/money", pageIds: ["money"] },
  { label: "Compliance", href: "/compliance", pageIds: ["compliance"] },
];

/** Exact page for a path (legacy addresses resolve to their hub), or null (the 404 case). */
export function findPage(path: string): AtlasPage | null {
  const clean = (path.split(/[?#]/)[0] || "/").replace(/\/+$/, "") || "/";
  if (redirectTarget(clean)) return pageForPath(clean);
  return PAGES.find((p) => p.href === clean) ?? null;
}

export function activeTab(page: AtlasPage, tab?: string | null): HubTab | null {
  if (!page.tabs) return null;
  return page.tabs.find((t) => t.id === tab) ?? page.tabs[0];
}

export function sectionFor(page: AtlasPage | null): NavSection | null {
  return page ? SECTIONS.find((s) => s.id === page.group) ?? null : null;
}

export type Crumb = { label: string; href?: string };
export function breadcrumbs(path: string, tab?: string | null): Crumb[] {
  const page = findPage(path);
  if (!page) return [{ label: "Home", href: "/" }, { label: "Not found" }];
  if (page.href === "/") return [{ label: "Home" }];
  const t = activeTab(page, tab);
  const crumbs: Crumb[] = [{ label: "Home", href: "/" }];
  if (t && t !== page.tabs![0]) crumbs.push({ label: page.label, href: page.href }, { label: t.label });
  else crumbs.push({ label: page.label });
  return crumbs;
}

export function pageTitle(page: AtlasPage, tab?: HubTab | null): string {
  return tab && page.tabs && tab !== page.tabs[0] ? `${tab.label} · ${page.label}` : page.label;
}

export type Command = { id: string; label: string; hint: string; group: string; href?: string; run?: () => void; keywords: string };
export function pageCommands(): Command[] {
  return PAGES.flatMap((p) => {
    const group = p.advanced ? "Advanced" : PAGE_GROUPS.find((g) => g.id === p.group)!.label;
    const hub: Command = {
      id: `page:${p.id}`, label: p.label, hint: p.summary, group, href: p.href,
      keywords: [p.label, p.navLabel, group, p.href, ...(p.aliases ?? [])].filter(Boolean).join(" ").toLowerCase(),
    };
    const tabs: Command[] = (p.tabs ?? []).slice(1).map((t) => ({
      id: `tab:${p.id}:${t.id}`, label: `${p.label} › ${t.label}`, hint: t.summary, group, href: tabHref(p, t.id),
      keywords: [t.label, p.label, group, ...(t.aliases ?? [])].join(" ").toLowerCase(),
    }));
    return [hub, ...tabs];
  });
}
