# ATLAS Price Action Framework Specifications

This document defines the quantitative specifications for the Price Action Zone Engine and the Snapback Entry strategy.

## 1. Price Action Zone Engine

The Zone Engine identifies high-probability reaction areas (Zones of Interest) based on market structure and volatility.

### 1.1 Opening Box
**Definition:** The high and low range of the first completed 1-hour candle of a specific trading session.
- **Standard Sessions (UTC):**
    - **Asian:** 00:00 - 01:00
    - **European:** 08:00 - 09:00
    - **U.S.:** 13:30 - 14:30
- **Boundaries:** $\text{Zone}_{High} = \max(\text{Wick Highs})$, $\text{Zone}_{Low} = \min(\text{Wick Lows})$.
- **Logic:** Establishes the session's baseline range.

### 1.2 Breakout Box
**Definition:** A zone created by a volatility expansion event piercing a double Bollinger Band filter.
- **Filter 1 (Core):** Length 20, StdDev 2, Source: Close.
- **Filter 2 (Extreme):** Length 4, StdDev 4, Source: Open.
- **Trigger:** A candle must pierce both the Upper (Bullish) or Lower (Bearish) bands of both filters and close beyond the outermost band.
- **Boundaries:** The high/low of the triggering candle.

### 1.3 Anchor Box
**Definition:** A zone created at a swing extreme followed by a structural reversal.
- **Detection:** 
    - **Bullish:** Swing low $\rightarrow$ Bullish reversal candle.
    - **Bearish:** Swing high $\rightarrow$ Bearish reversal candle.
- **Boundaries:** From the extreme wick to the close of the reversal candle.

### 1.4 Event Box
**Definition:** The range of the 1-hour candle coinciding with a high-impact economic event.
- **Triggers:** Verified timestamps for CPI, FOMC, NFP, etc.
- **Boundaries:** High and low of the 1-hour candle encompassing the release time.

---

## 2. Snapback Entry Strategy

A deterministic state-machine for identifying breakout-and-retest opportunities.

### 2.1 State Transitions
1. **RANGE_ESTABLISHED:** Opening Box is closed.
2. **BREAKOUT:** A candle closes outside the Opening Box.
3. **RETEST:** Price returns to touch the boundary of the Opening Box.
4. **CONFIRMATION:** A candle closes back outside the box in the original breakout direction.
5. **QUALIFIED:** Signal passed to ML for probability scoring.

### 2.2 Trade Management
- **Stop Loss (SL):** 
    - Primary: $2 \times \text{Opening Box Height}$ from entry.
    - Secondary: Structural invalidation (opposite side of the box).
- **Take Profit (TP):**
    - Target 1: $1:1$ Risk/Reward.
    - Target 2: Opposing Price Action Zone.
- **Risk Control:** Stop moved to breakeven after $1:1$ realized.

---

## 3. ML Intelligence Integration

### 3.1 Feature Set
- $\text{Zone\_Type} \in \{\text{Opening, Breakout, Anchor, Event}\}$
- $\text{Retest\_Count}$: Number of touches before confirmation.
- $\text{Regime}$: VPIN/OFI derived state (Compression vs Expansion).
- $\text{Overlap}$: Boolean indicating coincidence of multiple zone types.
- $\text{Confirmation\_Strength}$: Volume/Range of the confirmation candle.

### 3.2 Success Metric
A trade is successful if it reaches TP before SL. The primary objective is to prove $\text{P}(\text{Success} | \text{Snapback}) > \text{P}(\text{Success} | \text{Simple Breakout})$.
