import { SECTIONS } from "../src/ui/nav";

export default function NotFound() {
  return (
    <div className="ux-page">
      <header className="ux-page-header">
        <div className="ux-page-header__text">
          <div className="ux-eyebrow">404</div>
          <h1 className="ux-h1">That page isn’t in ATLAS</h1>
          <p className="ux-lede">The address may be mistyped or retired. Former addresses redirect to the page that now holds their data. Pick a section, or press ⌘K / Ctrl+K to search.</p>
        </div>
      </header>
      <div className="ux-tiles">
        {SECTIONS.map((s) => (
          <a key={s.id} className="ux-tile-link" href={s.href}>
            <strong>{s.label}</strong>
            <span>{s.pages.map((p) => p.navLabel ?? p.label).join(" · ")}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
