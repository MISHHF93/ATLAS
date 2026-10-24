# Indicator & math catalog (library.py / indicators.py)

All batch functions: output[i] uses inputs[0..i] of confirmed bars only; warmup → `None`.

| Name | Formula | Params | Warmup | Data tier | Missing data |
|---|---|---|---|---|---|
| SMA | (1/n)ΣP_{t-i} | n | n−1 | OHLCV | None if window has NaN |
| EMA (existing) | αP+(1−α)EMA, α=2/(n+1) | n | n−1 (SMA seed) | OHLCV | — |
| slope | (x_t−x_{t−k})/k | k | k | derived | None propagates |
| MACD | EMA12−EMA26; signal EMA9; hist | 12/26/9 | 25 / 33 | OHLCV | |
| ADX/DMI | Wilder smoothing of TR, +DM, −DM; DX=100|+DI−−DI|/(+DI+−DI) | n=14 | DI n, ADX 2n−1 | OHLCV | |
| RSI, ATR, BB, VWAP | existing `indicators.py` (Wilder) | | | OHLCV | |
| ROC / momentum | 100(P_t/P_{t−n}−1) / P_t−P_{t−n} | n | n | OHLCV | |
| log return | ln(P_t/P_{t−1}) | — | 1 | OHLCV | |
| realized vol | sample std (ddof=1) of n log returns ×√A | n, A | n | OHLCV | |
| Donchian | max H / min L over n incl. t | n | n−1 | OHLCV | |
| AVWAP | Σ(TP·V)/ΣV from anchor, TP=(H+L+C)/3 | anchor | anchor | OHLCV+vol | None if ΣV=0 |
| RVOL | V_t / mean(V_{t−n..t−1}) (current bar excluded) | n | n | volume | None if baseline 0 |
| candle anatomy / doji / engulfing / displacement | body, wicks, ratios; displacement range≥k·ATR & body≥0.6 range | k | — | OHLC | |
| trend band | EMA(n) ± k·ATR(n), sticky state ±1 (transparent, not a proprietary clone) | n,k | n−1 | OHLC | |
| HTF→LTF mapping | uses only HTF bars with end ≤ LTF bar end | — | — | — | None before first HTF |
| overlap / overlap ratio | max(0,min(H1,H2)−max(L1,L2)) / max(ε,min(R1,R2)) | ε | — | — | |
| normalized distance | (P−Level)/max(ATR,ε) | | ATR warmup | | None without ATR |
| OBI | (Bid−Ask)/(Bid+Ask+ε) | | | **L2 required** | never from OHLCV |
| trade imbalance | (Buy−Sell)/(Total+ε) | | | **aggressor trades** | None if missing |
| Kyle λ | OLS ΔP=α+λQ+ε, returns λ, se | — | ≥10 obs | signed volume | None |
| Hawkes λ(t) | μ+Σα e^{−β(t−t_i)} (research; params from a fit) | μ,α,β | | event times | |
| VPIN | mean |V_b−V_s|/(V_b+V_s) over volume buckets | window | window | classified volume | None |
| EV / p_BE | pG−(1−p)L−C ; (L+C)/(G+L) | | | | |
| sizing | floor(Risk/(stop·value)/lot)·lot, capped (research; control plane decides) | | | spec | 0 if invalid |
| portfolio | wᵀμ, wᵀΣw | | | | |
| VaR/CVaR | historical, positive loss, ≥20 obs | α | | returns | None |
| Brier / log loss / reliability | standard | bins | | | |
| implementation shortfall | Perold: execution + opportunity + fees | | | fills | |
| Almgren–Chriss | existing `execution/scheduling.py` | | | | |
