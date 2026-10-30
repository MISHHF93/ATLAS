import type { ReactNode } from "react";
import { notFound } from "next/navigation";
import { PAGES, activeTab, type PageId, type RouteId } from "../nav/nav.config";
import { NavLink } from "../nav/NavLink";
import { PANELS } from "../nav/panels";

/**
 * Standard page frame for every destination, one row: the page title and its tabs (plus optional actions) in a single
 * strip, then the open tab's panel. The tab summary is kept as the tab's tooltip and as a screen-reader description.
 * Server component: only the open tab's panel is loaded, so other tabs make no backend calls.
 */
export async function HubPage({ page: pageId, tab, actions }: { page: PageId; tab?: string; actions?: ReactNode }) {
  const page = PAGES.find((p) => p.id === pageId);
  if (!page) notFound();
  const current = activeTab(page, tab);
  const route = `${page.id}.${current.id}` as RouteId;
  const panel = await PANELS[route]();
  const descId = `hubdesc-${page.id}`;
  return (
    <div className="ux-page ux-hub" data-hub={page.id} data-tab={current.id}>
      <header className="ux-hubbar">
        <h1 className="ux-hubbar__title">{page.label}</h1>
        <nav className="ux-hubtabs" aria-label={`${page.label} views`}>
          <ul>
            {page.tabs.map((t) => (
              <li key={t.id}>
                <NavLink to={`${page.id}.${t.id}` as RouteId} className="ux-hubtab" title={t.summary} aria-current={t.id === current.id ? "page" : undefined}>{t.label}</NavLink>
              </li>
            ))}
          </ul>
        </nav>
        {actions ? <div className="ux-hubbar__actions">{actions}</div> : null}
      </header>
      <p id={descId} className="ux-sr-only">{current.summary}</p>
      <div key={current.id} className="ux-hub__panel" role="region" aria-label={current.label} aria-describedby={descId}>{panel}</div>
    </div>
  );
}

export type HubProps = { searchParams: Promise<{ tab?: string | string[] }> };
export async function tabParam(props: HubProps): Promise<string | undefined> {
  const t = (await props.searchParams).tab;
  return Array.isArray(t) ? t[0] : t;
}
