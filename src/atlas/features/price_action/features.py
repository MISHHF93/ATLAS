"""Per-bar indicator context, computed either streaming or in batch (parity-tested)."""
from __future__ import annotations

from typing import Any, Sequence

from atlas.features.price_action import indicators as ind
from atlas.features.price_action.bars import Bar

BAND_A = ("close", 20, 2.0)
BAND_B = ("open", 4, 4.0)


class StreamingFeatures:
    def __init__(self, atr_n: int = 14, band_a=BAND_A, band_b=BAND_B):
        self.atr = ind.WilderATR(atr_n)
        self.ba_src, self.bb_src = band_a[0], band_b[0]
        self.ba, self.bb = ind.Bollinger(band_a[1], band_a[2]), ind.Bollinger(band_b[1], band_b[2])
        self.prev: dict[str, Any] | None = None

    def update(self, bar: Bar) -> dict[str, Any]:
        ctx = {"atr": self.atr.update(bar.high, bar.low, bar.close),
               "band_a": self.ba.update(getattr(bar, self.ba_src)),
               "band_b": self.bb.update(getattr(bar, self.bb_src))}
        ctx["prev_band_a"] = self.prev["band_a"] if self.prev else None
        ctx["prev_band_b"] = self.prev["band_b"] if self.prev else None
        ctx["prev_atr"] = self.prev["atr"] if self.prev else None
        self.prev = ctx
        return ctx


def batch_features(bars: Sequence[Bar], atr_n: int = 14, band_a=BAND_A, band_b=BAND_B) -> list[dict[str, Any]]:
    h, l, c = [b.high for b in bars], [b.low for b in bars], [b.close for b in bars]
    atr = ind.atr_batch(h, l, c, atr_n)
    ba = ind.bollinger_batch([getattr(b, band_a[0]) for b in bars], band_a[1], band_a[2])
    bb = ind.bollinger_batch([getattr(b, band_b[0]) for b in bars], band_b[1], band_b[2])
    return [{"atr": atr[i], "band_a": ba[i], "band_b": bb[i],
             "prev_band_a": ba[i - 1] if i else None, "prev_band_b": bb[i - 1] if i else None,
             "prev_atr": atr[i - 1] if i else None} for i in range(len(bars))]
