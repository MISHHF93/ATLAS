"use client";

import React, { useEffect, useRef, useState } from "react";

/** Provenance badge. TradingView widgets render TradingView's own data inside their iframe;
 *  ATLAS cannot read it and it never feeds the model. */
export function TvProvenance({ kind }: { kind: "tradingview" | "atlas" }) {
  const tv = kind === "tradingview";
  return (
    <span
      data-provenance={kind}
      style={{
        display: "inline-block",
        fontSize: "10px",
        fontWeight: 700,
        letterSpacing: "0.02em",
        padding: "1px 6px",
        borderRadius: "4px",
        border: `1px solid ${tv ? "#E69F00" : "#56B4E9"}`,
        color: tv ? "#E69F00" : "#56B4E9",
      }}
    >
      {tv ? "TradingView display — not ATLAS data" : "ATLAS data"}
    </span>
  );
}

/** Lazy, timeout-guarded TradingView iframe with an offline fallback link. */
export function TvFrame({
  title,
  src,
  pageUrl,
  height,
  fill = false,
  timeoutMs = 20000,
  onLoaded,
  allowFullScreen = false,
}: {
  title: string;
  src: string;
  pageUrl: string;
  height: number | string;
  fill?: boolean;
  timeoutMs?: number;
  onLoaded?: () => void;
  allowFullScreen?: boolean;
}) {
  const [state, setState] = useState<"loading" | "loaded" | "timeout">("loading");
  const [online, setOnline] = useState(true);
  const loadedRef = useRef(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadedRef.current = false;
    setState("loading");
    setOnline(typeof navigator === "undefined" ? true : navigator.onLine);
    // The timeout only starts once the lazy frame is on screen, so off-screen frames are not flagged.
    let timer = 0;
    const arm = () => {
      if (timer) return;
      timer = window.setTimeout(() => {
        if (!loadedRef.current) setState("timeout");
      }, timeoutMs);
    };
    const seen = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) arm();
    });
    if (seen && boxRef.current) seen.observe(boxRef.current);
    else arm();
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.clearTimeout(timer);
      seen?.disconnect();
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, [src, timeoutMs]);

  if (!online) {
    return (
      <div role="status" style={{ minHeight: 60, color: "#94A3B8", fontSize: "12px", padding: "8px 2px" }}>
        Offline: the TradingView widget “{title}” needs a network connection. No substitute data is drawn.
      </div>
    );
  }
  return (
    <div ref={boxRef} style={{ position: "relative", height: fill ? "100%" : undefined, flex: fill ? 1 : undefined, minHeight: fill ? 0 : undefined }}>
      <iframe
        title={title}
        src={src}
        loading="lazy"
        referrerPolicy="strict-origin-when-cross-origin"
        scrolling="no"
        allowFullScreen={allowFullScreen}
        onLoad={() => {
          loadedRef.current = true;
          setState("loaded");
          onLoaded?.();
        }}
        style={{ width: "100%", height: fill ? "100%" : height, border: 0, borderRadius: "6px", background: "#0B0F17", display: "block" }}
      />
      {state === "timeout" ? (
        <div role="status" style={{ color: "#94A3B8", fontSize: "11px", marginTop: "4px" }}>
          TradingView did not finish loading “{title}”. It may be blocked by the network or an extension.{" "}
          <a href={pageUrl} target="_blank" rel="noopener nofollow" style={{ color: "#38bdf8" }}>Open on TradingView</a>
        </div>
      ) : null}
    </div>
  );
}

export default TvFrame;
