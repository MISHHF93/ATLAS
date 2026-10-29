import type { ReactNode } from "react";
import type { Metadata, Viewport } from "next";
import "./globals.css";
import "../src/ui/tokens.css";
import { AppShell } from "../src/ui/AppShell";

// Pages are rendered per request so Next can stamp the per-request CSP nonce (set in server.mjs) on its inline scripts.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ATLAS",
  description: "ATLAS: Canadian quant trading intelligence. Paper trading only; orders stay with the control plane.",
  applicationName: "ATLAS",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0D1117" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-CA" data-theme="dark" suppressHydrationWarning>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
