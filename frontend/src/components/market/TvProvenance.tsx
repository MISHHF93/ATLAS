"use client";


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
      {tv ? "TradingView: display only, not ATLAS data" : "ATLAS data"}
    </span>
  );
}
