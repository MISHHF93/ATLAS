"use client";

import { BookOpen, ChevronDown, ChevronRight, CircleUser, Menu, Moon, Search, Sun, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AtlasLogo } from "../components/shell/AtlasLogo";
import type { AtlasPage, PageGroupId } from "../components/shell/pagesMap";
import { SECTION_ICONS, pageIcon } from "./icons";
import { ADVANCED, SECTIONS, breadcrumbs, findPage, pageCommands, type Command } from "./nav";
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

type CurtainView = PageGroupId | "all";

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname() || "/";
  const page = findPage(path);
  const crumbs = breadcrumbs(path);
  const [theme, toggleTheme] = useTheme();
  const [curtain, setCurtain] = useState<CurtainView | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const safeStop = useSafeStopSource();
  const health = useApi<{ status?: string }>("/api/health", 15000);
  const [online, setOnline] = useState(true);
  const headerRef = useRef<HTMLElement>(null);
  const curtainRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const hoverOpen = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeSection = page?.group ?? null;

  const clearTimer = () => { if (timer.current) { clearTimeout(timer.current); timer.current = null; } };
  const close = useCallback((restoreFocus = false) => {
    clearTimer(); hoverOpen.current = false; setCurtain(null);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);
  const open = (view: CurtainView, trigger: HTMLButtonElement | null, byHover = false) => {
    clearTimer(); triggerRef.current = trigger; hoverOpen.current = byHover; setCurtain(view);
  };

  useEffect(() => { close(); }, [path, close]);
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
    document.title = page ? `${page.label} · ATLAS` : "Not found · ATLAS";
  }, [page]);

  const backendDown = health.status === 0 || (health.status !== null && health.status >= 500);
  const canHover = () => typeof window !== "undefined" && window.matchMedia("(hover: hover) and (min-width: 1100px)").matches;
  const leave = () => { if (hoverOpen.current) { clearTimer(); timer.current = setTimeout(() => close(), 220); } };

  return (
    <SafeStopContext.Provider value={safeStop}>
      <a className="ux-skip" href="#ux-main">Skip to content</a>
      <div className="ux-shell" data-curtain={curtain ? "open" : "closed"}>
        <header className="ux-header" ref={headerRef} onMouseLeave={leave} onMouseEnter={() => { if (hoverOpen.current) clearTimer(); }}>
          <button type="button" className="ux-menu-btn" aria-expanded={curtain === "all"} aria-controls="ux-curtain"
            aria-label={curtain === "all" ? "Close menu" : "Open menu"}
            onClick={(e) => (curtain === "all" ? close() : open("all", e.currentTarget))}>
            {curtain === "all" ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
            <span className="ux-menu-btn__text">Menu</span>
          </button>
          <a href="/" className="ux-brand" aria-label="ATLAS home">
            <AtlasLogo size={24} wordmark />
          </a>
          <span className="ux-paper" title="Paper trading only. No order on this platform reaches a live venue.">PAPER</span>
          <nav className="ux-tabs" aria-label="Sections">
            <ul>
              {SECTIONS.map((s, i) => {
                const Icon = SECTION_ICONS[s.id];
                return (
                  <li key={s.id}>
                    <button type="button" className="ux-tab" data-active={s.id === activeSection ? "true" : "false"} data-section={s.id}
                      aria-expanded={curtain === s.id} aria-controls="ux-curtain"
                      onClick={(e) => (curtain === s.id && !hoverOpen.current ? close() : open(s.id, e.currentTarget))}
                      onMouseEnter={(e) => {
                        if (!canHover()) return;
                        const el = e.currentTarget;
                        clearTimer();
                        timer.current = setTimeout(() => { if (!curtain || hoverOpen.current) open(s.id, el, true); }, curtain ? 60 : 140);
                      }}
                      onKeyDown={(e) => {
                        const tabs = [...(headerRef.current?.querySelectorAll<HTMLButtonElement>(".ux-tab") ?? [])];
                        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                          e.preventDefault();
                          const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
                          next?.focus(); if (curtain) open(SECTIONS[tabs.indexOf(next)].id, next);
                        }
                        if (e.key === "ArrowDown") {
                          e.preventDefault(); open(s.id, e.currentTarget);
                          setTimeout(() => curtainRef.current?.querySelector<HTMLAnchorElement>("a")?.focus(), 0);
                        }
                      }}>
                      <Icon size={15} aria-hidden />
                      <span>{s.label}</span>
                      {s.id === activeSection ? <span className="ux-sr">(current section)</span> : null}
                      <ChevronDown size={13} aria-hidden className="ux-tab__chev" />
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <button type="button" className="ux-search" onClick={() => { close(); setPaletteOpen(true); }} aria-label="Search pages and actions (Ctrl+K)">
            <Search size={15} aria-hidden />
            <span className="ux-search__text">Search…</span>
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

        <Curtain view={curtain} refEl={curtainRef} activeHref={page?.href ?? null} onClose={close} onSwitch={(v) => setCurtain(v)}
          onMouseEnter={() => { if (hoverOpen.current) clearTimer(); }} onMouseLeave={leave} />
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

/* --------------------------------------------------------------- curtain */

function Curtain({ view, refEl, activeHref, onClose, onSwitch, onMouseEnter, onMouseLeave }: {
  view: CurtainView | null; refEl: React.RefObject<HTMLDivElement | null>; activeHref: string | null;
  onClose: (restore?: boolean) => void; onSwitch: (v: CurtainView) => void; onMouseEnter: () => void; onMouseLeave: () => void;
}) {
  const isAll = view === "all";
  const section = view && view !== "all" ? SECTIONS.find((s) => s.id === view) ?? null : null;
  useEffect(() => {
    if (!isAll) return;
    const t = setTimeout(() => refEl.current?.querySelector<HTMLElement>("a, button")?.focus(), 0);
    return () => clearTimeout(t);
  }, [isAll, refEl]);
  const trap = (e: React.KeyboardEvent) => {
    if (!isAll || e.key !== "Tab" || !refEl.current) return;
    const f = [...refEl.current.querySelectorAll<HTMLElement>("a, button")];
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  const label = isAll ? "All pages" : section ? `${section.label} pages` : "Navigation";
  return (
    <div id="ux-curtain" ref={refEl} className="ux-curtain" data-open={view ? "true" : "false"} data-mode={isAll ? "all" : "section"}
      hidden={!view} role={isAll ? "dialog" : "region"} aria-modal={isAll ? true : undefined} aria-label={label}
      onKeyDown={trap} onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <div className="ux-curtain__inner">
        <div className="ux-curtain__top">
          <h2 className="ux-curtain__title">{label}</h2>
          <button type="button" className="ux-icon-btn" aria-label="Close menu" onClick={() => onClose(true)}><X size={18} aria-hidden /></button>
        </div>
        {isAll ? (
          <div className="ux-curtain__all">
            {SECTIONS.map((s) => s.main.length ? (
              <section key={s.id} className="ux-curtain__group" aria-labelledby={`cg-${s.id}`}>
                <h3 id={`cg-${s.id}`} className="ux-curtain__gh"><button type="button" className="ux-link-btn" onClick={() => onSwitch(s.id)}>{s.label}</button></h3>
                <Tiles pages={s.main} activeHref={activeHref} compact />
              </section>
            ) : null)}
            {ADVANCED.length ? (
              <section className="ux-curtain__group" data-advanced aria-labelledby="cg-adv">
                <h3 id="cg-adv" className="ux-curtain__gh">Advanced</h3>
                <Tiles pages={ADVANCED} activeHref={activeHref} compact />
              </section>
            ) : null}
          </div>
        ) : section ? (
          <div className="ux-curtain__section">
            <Tiles pages={section.main} activeHref={activeHref} />
            {section.advanced.length ? (
              <section className="ux-curtain__adv" aria-labelledby="cg-sec-adv">
                <h3 id="cg-sec-adv" className="ux-curtain__gh">Advanced</h3>
                <Tiles pages={section.advanced} activeHref={activeHref} compact />
              </section>
            ) : null}
            <button type="button" className="ux-link-btn ux-curtain__more" onClick={() => onSwitch("all")}>See all sections</button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Tiles({ pages, activeHref, compact }: { pages: AtlasPage[]; activeHref: string | null; compact?: boolean }) {
  return (
    <ul className="ux-ctiles" data-compact={compact ? "true" : "false"}>
      {pages.map((p) => {
        const Icon = pageIcon(p.id);
        return (
          <li key={p.href}>
            <a href={p.href} className="ux-ctile" aria-current={p.href === activeHref ? "page" : undefined}>
              <span className="ux-ctile__icon" aria-hidden><Icon size={compact ? 16 : 18} /></span>
              <span className="ux-ctile__text">
                <span className="ux-ctile__label">{p.label}</span>
                <span className="ux-ctile__desc" title={p.summary}>{p.summary}</span>
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
