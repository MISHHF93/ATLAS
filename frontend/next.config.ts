import type { NextConfig } from "next";
import { legacyRedirects } from "./src/components/shell/pagesMap";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Every former address is a permanent (308) redirect generated from the one page registry (pagesMap.ts),
  // so bookmarks keep working and no stub page files are needed.
  async redirects() {
    return legacyRedirects();
  },
};

export default nextConfig;
