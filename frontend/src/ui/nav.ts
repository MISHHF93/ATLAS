/**
 * Navigation derived from the one config (`src/nav/nav.config.ts`): header items, menu sections, page titles, the command
 * palette and the 404 page. To add a page or tab, edit the config (and `src/nav/panels.tsx`) and nothing else.
 */
import {
  NAV_SECTIONS, PAGES, activeTab, href, pageForPath, redirectTarget, tabHref,
  type AtlasPage, type HubTab, type PageId, type SectionId,
} from "../nav/nav.config";

export { activeTab };

export type NavSection = { id: SectionId; label: string; href: string; pages: AtlasPage[] };

/** Menu / 404 sections: every page (the logo's Home page included) grouped by the config's sections. */
export const SECTIONS: NavSection[] = NAV_SECTIONS.map((s) => {
  const pages = PAGES.filter((p) => p.section === s.id);
  return { id: s.id, label: s.label, href: pages[0]?.href ?? href("home"), pages };
}).filter((s) => s.pages.length);

export function curtainSections(): NavSection[] {
  return SECTIONS;
}

export type HeaderLink = { label: string; href: string; pageId: PageId };
/** The destinations always visible in the header bar (the config's `placement: "header"` pages). Home is the logo. */
export const HEADER_LINKS: HeaderLink[] = PAGES.filter((p) => p.placement === "header").map((p) => ({ label: p.navLabel, href: p.href, pageId: p.id }));

/** Exact page for a path (retired addresses resolve to the page that absorbed them), or null (the 404 case). */
export function findPage(path: string): AtlasPage | null {
  const clean = (path.split(/[?#]/)[0] || "/").replace(/\/+$/, "") || "/";
  const own = PAGES.find((p) => p.href === clean);
  if (own) return own;
  return redirectTarget(clean) ? pageForPath(clean) : null;
}

export function pageTitle(page: AtlasPage, tab?: HubTab | null): string {
  return tab && tab !== page.tabs[0] ? `${tab.label} · ${page.label}` : page.label;
}

export type Command = { id: string; label: string; hint: string; group: string; href?: string; run?: () => void; keywords: string };
export function pageCommands(): Command[] {
  return PAGES.flatMap((p) => {
    const group = SECTIONS.find((s) => s.id === p.section)?.label ?? "Pages";
    const hub: Command = {
      id: `page:${p.id}`, label: p.label, hint: p.summary, group, href: p.href,
      keywords: [p.label, p.navLabel, group, p.href].join(" ").toLowerCase(),
    };
    const tabs: Command[] = p.tabs.slice(1).map((t) => ({
      id: `tab:${p.id}:${t.id}`, label: `${p.label} › ${t.label}`, hint: t.summary, group, href: tabHref(p, t.id),
      keywords: [t.label, p.label, group, ...(t.legacy ?? [])].join(" ").toLowerCase(),
    }));
    return [hub, ...tabs];
  });
}
