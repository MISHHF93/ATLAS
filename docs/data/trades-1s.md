# 1-second crypto trade bars

Source: Kraken v2 `trade` and Coinbase `matches` websocket channels (both public, both reachable from Canada; probed 2026-10-30).
Code: `src/atlas/feeds/trades1s.py`, wired into `LiveIngest` (`src/atlas/feeds/live.py`).

| Table (`var/feeds/atlas_1s.sqlite`) | Grain | Retention | Notes |
|---|---|---|---|
| `bars_1s` | venue x instrument x traded second | 7 days (`ATLAS_1S_RETAIN_DAYS`) | OHLC, volume, taker buy/sell volume, trade count, price*qty sum (vwap numerator) |
| `flow_1m` | venue x instrument x minute | 90 days (`ATLAS_FLOW_RETAIN_DAYS`) | Roll-up of the same trades, built before the 1s rows are pruned; `active_s` = seconds with a trade |

Rules
* Real trades only. A second with no trade has **no row**; nothing is forward-filled or interpolated.
* One row per venue: Kraken and Coinbase are never mixed.
* `taker_side` is the aggressor. Kraken's `side` is already the taker; Coinbase's `side` is the maker order, so it is inverted.
* A trade arriving after its second was written is dropped and counted (`late_dropped`), not merged. Duplicate trade ids are dropped.
* History starts when the service starts; there is no backfill (neither venue offers public historical trades at 1s through these channels).
* Disk budget `ATLAS_1S_MAX_MB` (default 2048): over budget, the 1s window is halved until it fits. Estimated cost is 70-100 MB/day.
* The 1s store is separate from the point-in-time feed store (`bar_revisions`); no 1s data is written there.
* Research input only. `execution_permission` is `none`; nothing places an order.
