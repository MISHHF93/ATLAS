import { AppNav } from "../src/components/shell/AppNav";

export default function NotFound() {
  return (
    <main style={{ minHeight: "100vh", background: "#070A0F", color: "#F8FAFC" }}>
      <AppNav />
      <div style={{ padding: "48px", fontFamily: "Segoe UI, sans-serif" }}>
        <h1>That page is not in ATLAS</h1>
        <p>Use Desk, Markets, Trade, Risk, Research, or Data. Every former alias still redirects to the page that holds its data.</p>
      </div>
    </main>
  );
}
