import type { ReactNode } from "react";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ATLAS | Autonomous Trading, Liquidity, Allocation & Strategy Intelligence",
  description:
    "Paper research desk for competition and open-market books. Charts from TradingView. Orders stay with the control plane.",
  applicationName: "ATLAS",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
