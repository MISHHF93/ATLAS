import type { ReactNode } from "react";
import { PAGE_GROUPS, PAGES, tabHref } from "../components/shell/pagesMap";
import { activeTab } from "./nav";

/**
 * Standard page frame for every destination: eyebrow (section), plain-language title, one-line explanation,
 * optional primary actions, then the hub's tabs and a one-line description of the open tab.
 * Server component: only the selected tab's panel is rendered, so other tabs make no backend calls.
 */
export function Hub({ id, tab, panels, actions, compact, children }: { id: string; tab?: string; panels?: Record<string, ReactNode>; actions?: ReactNode; compact?: boolean; children?: ReactNode }) {
  const page = PAGES.find((p) => p.id === id);
  if (!page) throw new Error(`Unknown hub ${id}`);
  const current = activeTab(page, tab);
  const group = page.advanced ? "Advanced" : PAGE_GROUPS.find((g) => g.id === page.group)?.label;
  return (
    <div className="ux-page ux-hub" data-hub={page.id} data-tab={current?.id} data-compact={compact ? "true" : undefined}>
      <header className="ux-page-header">
        <div className="ux-page-header__text">
          <div className="ux-eyebrow">{group}</div>
          <h1 className="ux-h1">{page.label}</h1>
          <p className="ux-lede">{page.summary}</p>
        </div>
        {actions ? <div className="ux-page-header__actions">{actions}</div> : null}
      </header>
      {page.tabs && current ? (
        <>
          <nav className="ux-hubtabs" aria-label={`${page.label} views`}>
            <ul>
              {page.tabs.map((t) => (
                <li key={t.id}>
                  <a href={tabHref(page, t.id)} className="ux-hubtab" aria-current={t.id === current.id ? "page" : undefined}>{t.label}</a>
                </li>
              ))}
            </ul>
          </nav>
          <p className="ux-hubtab-desc">{current.summary}</p>
          <div className="ux-hub__panel" role="region" aria-label={current.label}>{panels?.[current.id]}</div>
        </>
      ) : children}
    </div>
  );
}

export type HubProps = { searchParams: Promise<{ tab?: string | string[] }> };
export async function tabParam(props: HubProps): Promise<string | undefined> {
  const t = (await props.searchParams).tab;
  return Array.isArray(t) ? t[0] : t;
}
