"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { AtlasLogo } from "./AtlasLogo";
import { GuideIcon, markForPage } from "./guideIcons";
import { PAGE_GROUPS, PAGES, pageForPath } from "./pagesMap";

export function AppNav() {
  const path = usePathname() || "/";
  const current = pageForPath(path);
  const groups = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const rail = groups.current;
    const link = rail?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!rail || !link || !window.matchMedia("(max-width: 700px)").matches) return;
    const bounds = rail.getBoundingClientRect();
    const active = link.getBoundingClientRect();
    if (active.left < bounds.left || active.right > bounds.right) {
      rail.scrollLeft += active.left - bounds.left;
    }
  }, [path]);

  return (
    <nav className="atlas-app-nav" aria-label="ATLAS">
      <div className="atlas-nav-primary">
        <a href="/" aria-label="ATLAS desk" className="atlas-nav-logo">
          <AtlasLogo size={26} wordmark />
        </a>
        <div ref={groups} className="atlas-nav-groups">
          {PAGE_GROUPS.map((group) => {
            const pages = PAGES.filter((page) => page.group === group.id);
            const groupOn = current.group === group.id;
            return (
              <div key={group.id} className={groupOn ? "atlas-nav-group is-current" : "atlas-nav-group"} aria-label={group.label}>
                {pages.map((page) => {
                  const on = page.href === current.href;
                  return (
                    <a
                      key={page.href}
                      href={page.href}
                      aria-current={on ? "page" : undefined}
                      className={[page.primary ? "is-primary" : "is-child", on ? "is-on" : ""].filter(Boolean).join(" ")}
                      title={page.summary}
                    >
                      {page.primary ? <GuideIcon name={markForPage(page.id)} /> : null}
                      {page.navLabel ?? page.label}
                    </a>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
