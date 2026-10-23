"""8. Crypto factors inside the 10% high_risk sleeve (Liu-Tsyvinski 2021; Liu-Tsyvinski-Wu 2022):
time-series momentum, cross-sectional momentum, and on-chain adoption/flow factors (active-address
growth, exchange net inflow as a negative). Vol-targeted (crypto alone can draw down 50%+) and
MAKER-ONLY: every order is a non-marketable limit at/inside the passive side, never crossing the spread
(Kraken/Coinbase retail taker fees 0.25-0.6%)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def _z(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd and sd > 0 else s * 0


@dataclass
class CryptoFactorModel:
    ts_lookback: int = 28
    xs_lookback: int = 21
    w_ts: float = 0.4
    w_xs: float = 0.3
    w_onchain: float = 0.3
    target_vol: float = 0.40
    max_names: int = 3

    def scores(self, close: pd.DataFrame, onchain: pd.DataFrame | None = None) -> pd.Series:
        """onchain columns per symbol: f"{sym}:active_addr", f"{sym}:netflow" (daily; optional)."""
        ts = np.sign(close.iloc[-1] / close.iloc[-1 - self.ts_lookback] - 1)
        xs = _z(close.iloc[-1] / close.iloc[-1 - self.xs_lookback] - 1)
        oc = pd.Series(0.0, index=close.columns)
        if onchain is not None and len(onchain) > 30:
            for s in close.columns:
                a, n = f"{s}:active_addr", f"{s}:netflow"
                g = onchain[a].iloc[-1] / onchain[a].iloc[-31] - 1 if a in onchain else 0.0
                f = -onchain[n].iloc[-7:].sum() if n in onchain else 0.0
                oc[s] = g + np.sign(f) * 0.1
            oc = _z(oc)
        return self.w_ts * ts + self.w_xs * xs + self.w_onchain * oc

    def weights(self, close: pd.DataFrame, onchain: pd.DataFrame | None = None) -> pd.Series:
        sc = self.scores(close, onchain)
        longs = sc[sc > 0].nlargest(self.max_names).index      # long-only: negative score -> cash
        w = pd.Series(0.0, index=close.columns)
        if len(longs) == 0:
            return w
        rv = np.log(close[longs]).diff().iloc[-30:].std() * np.sqrt(365)
        inv = 1 / rv.replace(0, np.nan)
        w[longs] = (inv / inv.sum()).fillna(0)
        port_vol = float(np.sqrt((w[longs] ** 2 * rv ** 2).sum()))
        return w * min(1.0, self.target_vol / port_vol) if port_vol > 0 else w   # scale down only

    def backtest(self, close: pd.DataFrame, rebalance: int = 7, maker_fee_bps: float = 16.0) -> pd.Series:
        r = close.pct_change().fillna(0); w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
        cur = pd.Series(0.0, index=close.columns)
        start = max(self.ts_lookback, self.xs_lookback) + 31
        for i in range(start, len(close)):
            if (i - start) % rebalance == 0:
                cur = self.weights(close.iloc[: i + 1])
            w.iloc[i] = cur
        wl = w.shift(1).fillna(0)
        return (wl * r).sum(1) - w.diff().abs().sum(1).fillna(0) * maker_fee_bps / 1e4


def maker_only_limit(side: str, bid: float, ask: float, tick: float = 0.01) -> float:
    """Passive price that cannot take liquidity: buy at the bid (or one tick inside if spread allows)."""
    if bid <= 0 or ask <= bid:
        raise ValueError("bad quote")
    if side == "buy":
        p = min(bid + tick, ask - tick) if ask - bid > 2 * tick else bid
        assert p < ask
    else:
        p = max(ask - tick, bid + tick) if ask - bid > 2 * tick else ask
        assert p > bid
    return round(p, 8)


def is_maker(side: str, limit: float, bid: float, ask: float) -> bool:
    return limit < ask if side == "buy" else limit > bid
