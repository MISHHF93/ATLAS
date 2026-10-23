# Trader Kim Strategy Framework: Specifications & Hypotheses

This document formalizes the "Four-Box" and "Snapback Entry" methodologies for integration into ATLAS. These are treated as **hypotheses** to be scientifically validated through walk-forward backtesting and ML-augmented filtering.

## 1. The Four-Box Price Action Framework

The goal of the Four-Box framework is to identify **Zones of Interest (ZOI)** where price is likely to react.

### 1.1 Opening Box (The Session Anchor)
**Definition:** The high and low range of the first completed 1-hour candle of a specific trading session.
- **Sessions:**
    - **Asian:** 00:00 - 01:00 UTC (Adjustable)
    - **European:** 08:00 - 09:00 UTC (Adjustable)
    - **U.S.:** 13:30 - 14:30 UTC (Adjustable)
- **Boundaries:** Include wicks. $\text{Box}_{High} = \max(\text{Highs})$, $\text{Box}_{Low} = \min(\text{Lows})$.
- **Hypothesis:** Breakouts of the Opening Box establish the directional bias for the remainder of the session.

### 1.2 Breakout Box (The Momentum Signal)
**Definition:** A zone created when price "pierces" a double Bollinger Band filter.
- **Filter 1 (Core):** Length 20, StdDev 2, Source: Close.
- **Filter 2 (Extreme):** Length 4, StdDev 4, Source: Open.
- **Trigger Condition:** A candle must:
    1. Pierce both the Upper BB1 and Upper BB2 (for bullish) or both Lower BB1 and Lower BB2 (for bearish).
    2. Close outside the outermost band.
- **Zone Creation:** The high/low of the triggering candle forms the "Breakout Box".
- **Hypothesis:** Double-band piercing indicates a volatility expansion that is more likely to result in a trend than a mean-reversion.

### 1.3 Anchor Box (The Structural Pivot)
**Definition:** A zone created at a swing extreme that is immediately rejected.
- **Detection:**
    - **Bullish Anchor:** A swing low is established by a wick, followed by a bullish reversal candle (e.g., Hammer or Bullish Engulfing).
    - **Bearish Anchor:** A swing high is established by a wick, followed by a bearish reversal candle.
- **Boundaries:** The zone spans from the extreme of the wick to the close of the reversal candle.
- **Hypothesis:** Anchor boxes represent "institutional footprints" and provide high-probability retest levels.

### 1.4 Event Box (The Catalyst Range)
**Definition:** The range of the 1-hour candle coinciding with a high-impact economic event.
- **Triggers:** CPI, FOMC, NFP, etc. (sourced from verified economic calendars).
- **Boundaries:** High and low of the 1-hour candle surrounding the release time.
- **Hypothesis:** Event boxes encapsulate the initial "market shock" and define the boundaries of the news-driven regime.

---

## 2. The Snapback Entry Strategy

A deterministic setup combining the Opening Box with a confirmed retest.

### 2.1 The Sequence (State Machine)
1. **STATE: RANGE_ESTABLISHED** $\rightarrow$ 1-hour Opening Box is closed.
2. **STATE: BREAKOUT** $\rightarrow$ A subsequent candle closes outside the Opening Box.
3. **STATE: RETEST** $\rightarrow$ Price returns to touch the boundary of the Opening Box.
4. **STATE: CONFIRMATION** $\rightarrow$ A candle closes back outside the box in the original breakout direction.
5. **STATE: QUALIFIED** $\rightarrow$ Signal is sent to ML Intelligence for probability scoring.

### 2.2 Trade Management Rules (Research Assumptions)
Since the source material is ambiguous, the following defaults are assumed for testing:
- **Stop Loss (SL):** 
    - Option A: $2 \times \text{Opening Box Height}$ from entry.
    - Option B: Beyond the opposite side of the Opening Box (Structural Invalidation).
- **Take Profit (TP):**
    - Target 1: $1:1$ Risk/Reward.
    - Target 2: The opposing Price Action Zone (e.g., an Anchor Box on the opposite side).
    - Target 3: The high/low of the previous session's Opening Box.
- **Exit:** Move SL to breakeven after $1:1$ is reached.

---

## 3. ML Integration & Evaluation

### 3.1 Features for ML
The model will receive:
- $\text{Zone\_Type} \in \{\text{Opening, Breakout, Anchor, Event}\}$
- $\text{Retest\_Count}$: Number of times the zone was touched before the Snapback.
- $\text{Regime}$: (Compression vs Expansion) via VPIN/OFI.
- $\text{Overlap}$: Whether multiple box types coincide in the same price area.
- $\text{Confirmation\_Strength}$: Size/Volume of the confirmation candle.

### 3.2 Success Metrics
A setup is "Successful" if it hits TP before SL.
**Primary Goal:** Determine if $\text{P}(\text{Success} | \text{Snapback}) > \text{P}(\text{Success} | \text{Simple Breakout})$.
