import type { ReactNode } from "react";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ATLAS | Autonomous Trading, Liquidity, Allocation & Strategy Intelligence",
  description: "Actionable regime-aware research, forecasting, self-training, and deterministic control-plane execution platform.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
