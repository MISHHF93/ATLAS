"use client";

import {
  BookOpen, ChevronDown, ChevronRight, CircleUser, FlaskConical, Home, Landmark, Menu, Moon, PanelLeftClose, PanelLeftOpen,
  Search, Settings, ShieldCheck, Sun, TrendingUp, X,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AtlasLogo } from "../components/shell/AtlasLogo";
import type { PageGroupId } from "../components/shell/pagesMap";
import { SECTIONS, breadcrumbs, findPage, pageCommands, type Command } from "./nav";
import { useApi } from "./primitives";

const ICONS: Record<PageGroupId, typeof Home> = {
  home: Home, trade: TrendingUp, money: Landmark, research: FlaskConical, compliance: ShieldCheck, settings: Settings,
};

/* ------------------------------------------------------------ Safe stop */

type SafeStop = { engaged: boolean | null; reason: string | null; since: string | null; error: string; reload: () => void };
const SafeStopContext = createContext<SafeStop>({ engaged: null, reason: null, since: null, error: "", reload: () => {} });
export const useSafeStop = () => useContext(SafeStopContext);

function useSafeStopSource(): SafeStop {
  const founder = useApi<{ engaged?: boolean; reason?: string | null; engaged_at?: string | null }>("/api/founder/safe-stop", 10000);
  const control = useApi<{ kill_switch_engaged?: boolean }>("/api/control/state", 10000);
  const known = founder.data !== null || control.data !== null;
  const engaged = known ? Boolean(founder.data?.engaged) || Boolean(control.data?.kill_switch_engaged) : null;
  return {
    engaged,
    reason: founder.data?.reason ?? (control.data?.kill_switch_engaged ? "Control plane halted paper trading" : null),
    since: founder.data?.engaged_at ?? null,
    error: founder.error && control.error ? founder.error : "",
    reload: () => { founder.reload(); control.reload(); },
  };
}

/* ---------------------------------------------------------------- theme */

type Theme = "dark" | "light";
function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>("dark");
  useEffect(() => {
    const saved = (localStorage.getItem("atlas-theme") as Theme | null) ?? "dark";
    setTheme(saved);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const toggle = useCallback(() => setTheme((t) => {
    const next = t === "dark" ? "light" : "dark";
    localStorage.setItem("atlas-theme", next);
    return next;
  }), []);
  return [theme, toggle];
}

/* ----------------------------------------------------------- the shell */

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const page = findPage(path);
  const crumbs = breadcrumbs(path);
  const [theme, toggleTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const safeStop = useSafeStopSource();
  const health = useApi<{ status?: string }>("/api/health", 15000);
  const [online, setOnline] = useState(true);

  useEffect(() => { setCollapsed(localStorage.getItem("atlas-sidebar") === "collapsed"); }, []);
  useEffect(() => { setMobileOpen(false); }, [path]);
  useEffect(() => {
    const on = () => setOnline(navigator.onLine);
    on();
    window.addEventListener("online", on); window.addEventListener("offline", on);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", on); };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen((o) => !o); }
      if (e.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    document.title = page ? `${page.label} · ATLAS` : "Not found · ATLAS";
  }, [page]);

  const toggleCollapsed = () => setCollapsed((c) => { localStorage.setItem("atlas-sidebar", c ? "open" : "collapsed"); return !c; });
  const backendDown = health.status === 0 || (health.status !== null && health.status >= 500);

  return (
    <SafeStopContext.Provider value={safeStop}>
      <a className="ux-skip" href="#ux-main">Skip to content</a>
      <div className="ux-shell" data-collapsed={collapsed ? "true" : "false"} data-mobile-open={mobileOpen ? "true" : "false"}>
        <header className="ux-header">
          <button type="button" className="ux-icon-btn ux-only-mobile" aria-label={mobileOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={mobileOpen} aria-controls="ux-sidebar" onClick={() => setMobileOpen((o) => !o)}>
            {mobileOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <a href="/" className="ux-brand" aria-label="ATLAS home">
            <AtlasLogo size={24} wordmark />
          </a>
          <span className="ux-paper" title="Paper trading only. No order on this platform reaches a live venue.">PAPER</span>
          <button type="button" className="ux-search" onClick={() => setPaletteOpen(true)} aria-label="Search pages and actions (Ctrl+K)">
            <Search size={15} aria-hidden />
            <span className="ux-search__text">Search pages and actions…</span>
            <kbd className="ux-kbd">⌘K</kbd>
          </button>
          <div className="ux-header__right">
            <SafeStopPill />
            <button type="button" className="ux-icon-btn" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <AccountMenu onTheme={toggleTheme} theme={theme} />
          </div>
        </header>

        <aside id="ux-sidebar" className="ux-sidebar" aria-label="Main navigation">
          <nav>
            {SECTIONS.map((s) => <SidebarSection key={s.id} section={s} activeHref={page?.href ?? null} collapsed={collapsed} />)}
          </nav>
          <button type="button" className="ux-collapse ux-only-desktop" onClick={toggleCollapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <PanelLeftOpen size={16} /> : <><PanelLeftClose size={16} /> <span>Collapse</span></>}
          </button>
        </aside>
        {mobileOpen ? <button type="button" className="ux-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}

        <div className="ux-main-col">
          {!online || backendDown ? (
            <div className="ux-banner" data-tone="bad" role="alert">
              {!online ? "You are offline." : "ATLAS backend is not responding."} Figures below may be stale.
              <button type="button" className="ux-link-btn" onClick={health.reload}>Retry</button>
            </div>
          ) : null}
          {safeStop.engaged ? (
            <div className="ux-banner" data-tone="warn" role="status">
              <strong>Safe stop active.</strong> New paper orders are rejected{safeStop.reason ? ` (${safeStop.reason.replaceAll("_", " ")})` : ""}. Reset is owner CLI only:
              <code className="ux-code">atlas-owner reset-kill-switch</code>
            </div>
          ) : null}
          {crumbs.length > 1 ? (
            <nav className="ux-crumbs" aria-label="Breadcrumb">
              <ol>
                {crumbs.map((c, i) => (
                  <li key={i}>
                    {c.href ? <a href={c.href}>{c.label}</a> : <span aria-current="page">{c.label}</span>}
                    {i < crumbs.length - 1 ? <ChevronRight size={12} aria-hidden /> : null}
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}
          <main id="ux-main" className="ux-main" tabIndex={-1}>{children}</main>
        </div>
      </div>
      {paletteOpen ? <CommandPalette onClose={() => setPaletteOpen(false)} onTheme={toggleTheme} /> : null}
    </SafeStopContext.Provider>
  );
}

function SidebarSection({ section, activeHref, collapsed }: { section: (typeof SECTIONS)[number]; activeHref: string | null; collapsed: boolean }) {
  const Icon = ICONS[section.id];
  const inSection = section.pages.some((p) => p.href === activeHref);
  const [open, setOpen] = useState(inSection);
  useEffect(() => { if (inSection) setOpen(true); }, [inSection]);
  const single = section.pages.length === 1;
  return (
    <div className="ux-nav-section" data-active={inSection ? "true" : "false"}>
      <div className="ux-nav-row">
        <a href={section.href} className="ux-nav-top" aria-current={section.href === activeHref ? "page" : undefined} title={collapsed ? section.label : undefined}>
          <Icon size={17} aria-hidden />
          <span className="ux-nav-label">{section.label}</span>
        </a>
        {!single ? (
          <button type="button" className="ux-nav-toggle" aria-expanded={open} aria-label={`${open ? "Hide" : "Show"} ${section.label} pages`} onClick={() => setOpen((o) => !o)}>
            <ChevronDown size={14} aria-hidden style={{ transform: open ? "none" : "rotate(-90deg)" }} />
          </button>
        ) : null}
      </div>
      {!single && open ? (
        <ul className="ux-nav-sub">
          {section.pages.map((p) => (
            <li key={p.href}>
              <a href={p.href} aria-current={p.href === activeHref ? "page" : undefined} title={p.summary}>{p.navLabel ?? p.label}</a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function SafeStopPill() {
  const s = useSafeStop();
  const tone = s.engaged === null ? "neutral" : s.engaged ? "bad" : "good";
  const label = s.engaged === null ? "Safe stop: unknown" : s.engaged ? "Safe stop active" : "Safe stop armed";
  return (
    <a href="/control" className="ux-pill" data-tone={tone}
      title={s.engaged === null ? "Safe stop status unavailable" : s.engaged ? "New paper orders are rejected" : "2% daily-loss Safe stop is armed and not triggered"}>
      <span className="ux-dot" aria-hidden />
      <span className="ux-pill__text">{label}</span>
    </a>
  );
}

function AccountMenu({ onTheme, theme }: { onTheme: () => void; theme: Theme }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="ux-menu" ref={ref}>
      <button type="button" className="ux-icon-btn" aria-haspopup="menu" aria-expanded={open} aria-label="Account menu" onClick={() => setOpen((o) => !o)}>
        <CircleUser size={18} />
      </button>
      {open ? (
        <div className="ux-menu__list" role="menu">
          <div className="ux-menu__head">Owner · paper account<br /><span className="ux-muted">Writes need atlas-owner + step-up</span></div>
          <a role="menuitem" href="/control">Account risk</a>
          <a role="menuitem" href="/control/rulebook">Rulebook &amp; limits</a>
          <a role="menuitem" href="/docs"><BookOpen size={14} aria-hidden /> Specifications</a>
          <button role="menuitem" type="button" onClick={() => { onTheme(); setOpen(false); }}>
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function CommandPalette({ onClose, onTheme }: { onClose: () => void; onTheme: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const all = useMemo<Command[]>(() => [
    ...pageCommands(),
    { id: "act:theme", label: "Toggle light / dark theme", hint: "Appearance", group: "Actions", run: onTheme, keywords: "theme dark light appearance" },
    { id: "act:safestop", label: "Safe stop status", hint: "Open account risk", group: "Actions", href: "/control", keywords: "safe stop halt risk kill" },
  ], [onTheme]);
  const results = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    return all.filter((c) => terms.every((t) => c.keywords.includes(t) || c.label.toLowerCase().includes(t))).slice(0, 12);
  }, [all, q]);
  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => { setActive(0); }, [q]);
  const go = (c: Command | undefined) => {
    if (!c) return;
    onClose();
    if (c.run) c.run(); else if (c.href) router.push(c.href);
  };
  return (
    <div className="ux-palette-scrim" onMouseDown={onClose}>
      <div className="ux-palette" role="dialog" aria-modal="true" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ux-palette__input">
          <Search size={16} aria-hidden />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Go to page or run action…"
            role="combobox" aria-expanded="true" aria-controls="ux-palette-list" aria-activedescendant={results[active] ? `cmd-${results[active].id}` : undefined}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(results.length - 1, a + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
              if (e.key === "Enter") { e.preventDefault(); go(results[active]); }
              if (e.key === "Escape") onClose();
            }} />
          <kbd className="ux-kbd">Esc</kbd>
        </div>
        <ul id="ux-palette-list" role="listbox" className="ux-palette__list">
          {results.length ? results.map((c, i) => (
            <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === active} onMouseEnter={() => setActive(i)} onClick={() => go(c)}>
              <span className="ux-palette__label">{c.label}</span>
              <span className="ux-palette__group">{c.group}</span>
              <span className="ux-palette__hint">{c.hint}</span>
            </li>
          )) : <li className="ux-palette__none">No page or action matches “{q}”.</li>}
        </ul>
      </div>
    </div>
  );
}
