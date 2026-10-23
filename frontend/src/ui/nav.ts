/**
 * Single route config consumer. `pagesMap.ts` is the one registry; the sidebar, breadcrumbs, command palette,
 * page headers and the 404 page are all derived from it here, so adding a page there is the only step.
 */
import { PAGE_GROUPS, PAGES, type AtlasPage, type PageGroupId } from "../components/shell/pagesMap";

export type NavSection = { id: PageGroupId; label: string; href: string; pages: AtlasPage[] };

export const SECTIONS: NavSection[] = PAGE_GROUPS.map((group) => {
  const pages = PAGES.filter((p) => p.group === group.id).sort((a, b) => Number(Boolean(b.primary)) - Number(Boolean(a.primary)));
  return { id: group.id, label: group.label, href: pages[0]?.href ?? "/", pages };
});

const ALIASES: Record<string, string> = Object.fromEntries(PAGES.flatMap((p) => (p.aliases ?? []).map((a) => [a, p.href])));

/** Exact page for a path, or null (the 404 case). Unlike pageForPath this never falls back to Home. */
export function findPage(path: string): AtlasPage | null {
  const clean = (path.split(/[?#]/)[0] || "/").replace(/\/+$/, "") || "/";
  const href = ALIASES[clean] ?? clean;
  return PAGES.find((p) => p.href === href) ?? null;
}

export function sectionFor(page: AtlasPage | null): NavSection | null {
  return page ? SECTIONS.find((s) => s.id === page.group) ?? null : null;
}

export type Crumb = { label: string; href?: string };
export function breadcrumbs(path: string): Crumb[] {
  const page = findPage(path);
  if (!page) return [{ label: "Home", href: "/" }, { label: "Not found" }];
  const section = sectionFor(page)!;
  if (page.href === "/") return [{ label: "Home" }];
  const crumbs: Crumb[] = [{ label: "Home", href: "/" }];
  if (section.href !== page.href) crumbs.push({ label: section.label, href: section.href });
  crumbs.push({ label: page.label });
  return crumbs;
}

export function pageTitle(page: AtlasPage): string {
  return page.label;
}

export type Command = { id: string; label: string; hint: string; group: string; href?: string; run?: () => void; keywords: string };
export function pageCommands(): Command[] {
  return SECTIONS.flatMap((s) =>
    s.pages.map((p) => ({
      id: `page:${p.id}`, label: p.label, hint: p.summary, group: s.label, href: p.href,
      keywords: [p.label, p.navLabel, s.label, p.href, ...(p.aliases ?? [])].filter(Boolean).join(" ").toLowerCase(),
    }))
  );
}
