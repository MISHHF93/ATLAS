import type { NextConfig } from "next";
import { legacyRedirects } from "./src/nav/nav.config";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Every former address is a permanent (308) redirect generated from the one navigation config (src/nav/nav.config.ts),
  // so bookmarks keep working and no stub page files are needed.
  poweredByHeader: false,
  // Baseline headers for anything Next serves without server.mjs (`next start`). server.mjs adds the nonce CSP (Next would override it if set here) and HSTS per request.
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "no-referrer" },
    ] }];
  },
  async redirects() {
    return legacyRedirects();
  },
};

export default nextConfig;
