"use client";

import { useId } from "react";

const TAGLINE = "Autonomous Trading, Liquidity, Allocation & Strategy Intelligence";

export function AtlasLogo({
  size = 28,
  wordmark = false,
  subtitle,
}: {
  size?: number;
  wordmark?: boolean;
  subtitle?: string;
}) {
  const gradientId = `atlasMark${useId().replace(/:/g, "")}`;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "8px", minWidth: 0 }}>
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="4" y1="2" x2="28" y2="30" gradientUnits="userSpaceOnUse">
            <stop stopColor="#00F29D" />
            <stop offset="1" stopColor="#00C8FF" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="8" fill="#070A0F" />
        <rect x="1.2" y="1.2" width="29.6" height="29.6" rx="7" fill="none" stroke={`url(#${gradientId})`} strokeWidth="1.4" />
        <path
          d="M16 6.2 24.6 25.2M16 6.2 7.4 25.2"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <path d="M10.8 18.2h10.4" fill="none" stroke={`url(#${gradientId})`} strokeWidth="2.4" strokeLinecap="round" />
      </svg>
      {wordmark ? (
        <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <span style={{ fontWeight: 800, letterSpacing: "0.12em", fontSize: "13px", color: "#F8FAFC", lineHeight: 1.1 }}>
            ATLAS
          </span>
          {subtitle ? (
            <span
              style={{
                marginTop: "3px",
                fontSize: "10px",
                color: "#94A3B8",
                letterSpacing: "0.02em",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {subtitle}
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}

export const ATLAS_TAGLINE = TAGLINE;

export default AtlasLogo;
