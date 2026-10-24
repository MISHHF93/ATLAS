"use client";

import { BookOpen, ChevronRight, CircleUser, Inbox, KeyRound, Menu, Moon, Search, Sun, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AtlasLogo } from "../components/shell/AtlasLogo";
import type { AtlasPage } from "../components/shell/pagesMap";
import { pageIcon } from "./icons";
import { ADVANCED, HEADER_LINKS, SECTIONS, activeTab, breadcrumbs, findPage, pageCommands, pageTitle, type Command } from "./nav";
import { useApi } from "./primitives";


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
  const [tab, setTab] = useState<string | null>(null);
  const page = findPage(path);
  const crumbs = breadcrumbs(path, tab);
  const [theme, toggleTheme] = useTheme();
  const [curtain, setCurtain] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const safeStop = useSafeStopSource();
  const health = useApi<{ status?: string }>("/api/health", 15000);
  const [online, setOnline] = useState(true);
  const headerRef = useRef<HTMLElement>(null);
  const curtainRef = useRef<HTMLDivElement>(null);
  const menuBtn = useRef<HTMLButtonElement | null>(null);

  const close = useCallback((restoreFocus = false) => {
    setCurtain(false);
    if (restoreFocus) menuBtn.current?.focus();
  }, []);

  useEffect(() => { close(); setTab(new URLSearchParams(window.location.search).get("tab")); }, [path, close]);
  useEffect(() => {
    const on = () => setOnline(navigator.onLine);
    on();
    window.addEventListener("online", on); window.addEventListener("offline", on);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", on); };
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); close(); setPaletteOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);
  useEffect(() => {
    if (!curtain) return;
    const down = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!curtainRef.current?.contains(t) && !headerRef.current?.contains(t)) close();
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); close(true); } };
    document.addEventListener("mousedown", down); document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", esc); };
  }, [curtain, close]);
  useEffect(() => {
    document.title = page ? `${pageTitle(page, activeTab(page, tab))} · ATLAS` : "Not found · ATLAS";
  }, [page, tab]);

  const backendDown = health.status === 0 || (health.status !== null && health.status >= 500);

  return (
    <SafeStopContext.Provider value={safeStop}>
      <a className="ux-skip" href="#ux-main">Skip to content</a>
      <div className="ux-shell" data-curtain={curtain ? "open" : "closed"}>
        <header className="ux-header" ref={headerRef}>
          <div className="ux-header__left">
            <button type="button" ref={menuBtn} className="ux-menu-btn" aria-expanded={curtain} aria-controls="ux-curtain"
              aria-label={curtain ? "Close menu" : "Open menu: all pages"}
              onClick={() => (curtain ? close() : setCurtain(true))}>
              {curtain ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
              <span className="ux-menu-btn__text">Menu</span>
            </button>
            <a href="/" className="ux-brand" aria-label="ATLAS overview">
              <AtlasLogo size={22} wordmark />
            </a>
            <span className="ux-paper" title="Paper trading only. No order on this platform reaches a live venue.">PAPER</span>
          </div>
          <nav className="ux-tabs" aria-label="Main sections">
            <ul>
              {HEADER_LINKS.map((l) => {
                const active = Boolean(page && l.pageIds.includes(page.id));
                return (
                  <li key={l.href}>
                    <a href={l.href} className="ux-tab" data-active={active ? "true" : "false"} aria-current={active ? "page" : undefined}>{l.label}</a>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="ux-header__right">
            <button type="button" className="ux-search" onClick={() => { close(); setPaletteOpen(true); }} aria-label="Search pages and actions (Ctrl+K)">
              <Search size={15} aria-hidden />
              <span className="ux-search__text">Search</span>
              <kbd className="ux-kbd">⌘K</kbd>
            </button>
            <a href="/inbox" className="ux-icon-btn" aria-label="Action needed (inbox)" title="Action needed" data-active={page?.id === "inbox" ? "true" : undefined}>
              <Inbox size={17} aria-hidden />
            </a>
            <SafeStopPill />
            <AccountMenu onTheme={toggleTheme} theme={theme} />
          </div>
        </header>

        <Curtain open={curtain} refEl={curtainRef} activeHref={page?.href ?? null} onClose={close} />
        {curtain ? <div className="ux-curtain-scrim" aria-hidden onMouseDown={() => close()} /> : null}

        <div className="ux-main-col">
          {!online || backendDown ? (
            <div className="ux-banner" data-tone="bad" role="alert">
              {!online ? "You are offline." : "ATLAS backend is not responding."} Figures below may be stale.
              <button type="button" className="ux-link-btn" onClick={health.reload}>Retry</button>
            </div>
          ) : null}
          {safeStop.engaged ? (
            <div className="ux-banner" data-tone="warn" role="status">
              <strong>Safe stop active.</strong> New paper orders are rejected{safeStop.reason ? ` (${safeStop.reason.replaceAll("_", " ")})` : ""}. Release is owner CLI only:
              <code className="ux-code">atlas-owner reset-kill-switch</code>
            </div>
          ) : null}
          {crumbs.length > 2 ? (
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

/* --------------------------------------------------------------- curtain */

function Curtain({ open, refEl, activeHref, onClose }: {
  open: boolean; refEl: React.RefObject<HTMLDivElement | null>; activeHref: string | null; onClose: (restore?: boolean) => void;
}) {
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => refEl.current?.querySelector<HTMLElement>("a")?.focus(), 0);
    return () => clearTimeout(t);
  }, [open, refEl]);
  const trap = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab" || !refEl.current) return;
    const f = [...refEl.current.querySelectorAll<HTMLElement>("a, button")];
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  return (
    <div id="ux-curtain" ref={refEl} className="ux-curtain" data-open={open ? "true" : "false"} data-mode="all"
      hidden={!open} role="dialog" aria-modal={true} aria-label="All pages" onKeyDown={trap}>
      <div className="ux-curtain__inner">
        <div className="ux-curtain__top">
          <h2 className="ux-curtain__title">All pages</h2>
          <span className="ux-curtain__hint">Tip: press <kbd className="ux-kbd">⌘K</kbd> to jump anywhere</span>
          <button type="button" className="ux-icon-btn" aria-label="Close menu" onClick={() => onClose(true)}><X size={18} aria-hidden /></button>
        </div>
        <div className="ux-curtain__all">
          {SECTIONS.map((s) => (
            <section key={s.id} className="ux-curtain__group" aria-labelledby={`cg-${s.id}`}>
              <h3 id={`cg-${s.id}`} className="ux-curtain__gh">{s.label}</h3>
              <Tiles pages={s.pages} activeHref={activeHref} />
            </section>
          ))}
          {ADVANCED.length ? (
            <section className="ux-curtain__group" data-advanced aria-labelledby="cg-adv">
              <h3 id="cg-adv" className="ux-curtain__gh">Advanced</h3>
              <Tiles pages={ADVANCED} activeHref={activeHref} />
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Tiles({ pages, activeHref }: { pages: AtlasPage[]; activeHref: string | null }) {
  return (
    <ul className="ux-ctiles" data-compact="true">
      {pages.map((p) => {
        const Icon = pageIcon(p.id);
        return (
          <li key={p.href}>
            <a href={p.href} className="ux-ctile" aria-current={p.href === activeHref ? "page" : undefined}>
              <span className="ux-ctile__icon" aria-hidden><Icon size={16} /></span>
              <span className="ux-ctile__text">
                <span className="ux-ctile__label">{p.label}</span>
                <span className="ux-ctile__desc" title={p.summary}>{p.summary}</span>
                {p.tabs ? <span className="ux-ctile__tabs">{p.tabs.map((t) => t.label).join(" · ")}</span> : null}
              </span>
            </a>
          </li>
        );
      })}
    </ul>
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
          <a role="menuitem" href="/control?tab=limits">Limits &amp; rules</a>
          <a role="menuitem" href="/settings"><KeyRound size={14} aria-hidden /> Settings &amp; API keys</a>
          <a role="menuitem" href="/docs"><BookOpen size={14} aria-hidden /> Help &amp; docs</a>
          <button role="menuitem" type="button" onClick={() => { onTheme(); setOpen(false); }}>
            {theme === "dark" ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />} {theme === "dark" ? "Light theme" : "Dark theme"}
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
    { id: "act:safestop", label: "Safe stop status", hint: "Open Risk & positions", group: "Actions", href: "/control", keywords: "safe stop halt risk kill" },
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
