"use client";

import { useState } from "react";

/** The only way to release Safe stop: the owner runs this locally with step-up (passphrase + TOTP). */
export const SAFE_STOP_RELEASE_CLI = "atlas-owner reset";

/**
 * Shown in place of a "Release Safe stop" button. HTTP release is refused (403) by the API,
 * so the UI only offers to copy the owner CLI command.
 */
export function SafeStopReleaseCli({ compact = false }: { compact?: boolean }) {
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(SAFE_STOP_RELEASE_CLI);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
  };
  return (
    <span className="safe-stop-release-cli" style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span style={{ fontSize: compact ? "11px" : "12px", color: "var(--c-muted)" }}>
        Safe stop is on. Release: <code>{SAFE_STOP_RELEASE_CLI}</code> (owner, step-up)
      </span>
      <button
        type="button"
        className="btn btn-sm btn-outline"
        onClick={() => void copy()}
        title="Copy the owner CLI command. Safe stop cannot be released from the browser."
        aria-label="Copy Safe stop release command"
      >
        {copied === "copied" ? "Copied" : copied === "failed" ? "Copy failed: select the command" : "Copy release command"}
      </button>
    </span>
  );
}
