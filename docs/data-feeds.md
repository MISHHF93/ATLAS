# ATLAS data feed

There is one authoritative feed: `atlas.feeds`. Every consumer reads from the same point-in-time (PIT) SQLite store: the UDF/chart worker, training, setup/selector evidence and replay. Nothing fetches market data on its own. Paper and simulation only; live trading stays disabled.

```
providers (plugins + capability manifests) -> AtlasFeed (failover, rate limit, backoff, gap fill)
     -> FeedStore (PIT revisions, var/feeds/atlas_feed.sqlite, git-ignored) -> bars()/quality()/udf.history()
```

- **Records.** `FeedBar` (start, bar_end, OHLCV, confirmed, provider, receipt_time), plus `FeedTrade`, `FeedQuote` and `FeedObservation` (FRED, with vintages).
- **Point in time.** A revision is keyed by (provider, instrument, interval, event_time, receipt_time). Ingest is idempotent and never downgrades a confirmed bar. `bars(..., as_of=t)` returns only versions with receipt_time ≤ t.
- **Authoritative series.** Bars are merged by `Instrument.provider_priority`. Sanity providers are cross-check only and are never merged. For example, Coinbase BTC-USD is a USD proxy for BTCUSDT.
- **Quality flags.** `stale`, `gap`, `unconfirmed_last_bar`, `provider_disagreement`, `no_data`, `invalid_bar`. US equities use the XNYS session calendar, including early closes. `atlas.models.predict` abstains when `FeatureSnapshot.data_quality_flags` is non-empty, with reasons `data_quality` and `data_quality:<flag>`.
- **Streaming.** `AtlasFeed.run_stream` uses the websocket adapters with reconnect and full-jitter backoff, and aggregates 1m bars to 15m/1h.

## Python API (for the UDF worker)

```python
from atlas.feeds import get_feed, udf
feed = get_feed()                       # store path: ATLAS_FEED_DB or var/feeds/atlas_feed.sqlite
feed.bars("BTCUSDT", "15m", start, end, as_of=None, confirmed_only=True)   # list[FeedBar], priority-merged
feed.quality_flags("SPY", "1h")         # () when clean
feed.quality("SPY", "1h")               # Quality(flags, last_bar_end, age_s, gaps, ...)
feed.health()                           # providers snapshot + per-series freshness/flags
feed.cross_check("BTCUSDT", "1h", start, end)  # median/max bps vs sanity providers
udf.history("BTCUSDT", "15", frm, to)   # TradingView UDF {s, t, o, h, l, c, v} or {s:"no_data"}
udf.symbol_info("SPY")
```

The UDF route files belong to the UDF worker. This slice only provides the functions above.

## Backfill

```
PYTHONPATH=src python scripts/backfill_feeds.py --days 730 --intervals 15m,1h   # --health, --no-cross-check, --db PATH
```

Training, evidence and replay read the store: `load_datasets()` in `atlas.research.setup_evidence` reads it when the path ends in `.sqlite` or `ATLAS_EVIDENCE_SOURCE=feed` is set. `scripts/run_setup_evidence.py` and `run_selector_evidence.py` use `var/feeds/atlas_feed.sqlite` by default when it exists.

### Real backfill on 2026-10-23 (~22:07 UTC)

| Instrument | TF | Provider | Bars | Flags |
|---|---|---|---|---|
| BTCUSDT, ETHUSDT | 15m | binance (data-api.binance.vision) | 17,279 each (180 d) | ok |
| BTCUSDT, ETHUSDT | 1h | binance | 17,519 each (2 y) | ok |
| SPY, QQQ, IWM | 15m | yahoo (unofficial) | 1,093 each (~60 d, provider limit) | ok |
| SPY / QQQ / IWM | 1h | yahoo | 3,434 / 3,435 / 3,434 (from 2024-11-04) | ok |

Crypto cross-check over 7 days of 1h bars (median bps): okx ~0.5, kraken ~1–2.5, coinbase USD proxy ~12–13. A rerun was idempotent: 0 inserted, 1 revised (the forming bar became confirmed). Yahoo has two genuine provider holes in 1h data (2026-01-30 15:30 and 2026-02-02 14:30 UTC) that cannot be refilled without a keyed equity provider.

## Reachability from the box

- **Bybit:** geo-blocked (CloudFront 403).
- **api.binance.com:** returns 451. Failover goes to data-api.binance.vision; override with `ATLAS_BINANCE_REST_HOSTS`.
- **No keyless equity sanity source:** set the Alpaca keys to get IEX bars, a second ETF source and cross-checks.

## Providers

| Provider | Status | Assets | Env (names only) |
|---|---|---|---|
| [binance](data-providers/binance.md) | working | crypto | none (keyless) |
| [coinbase](data-providers/coinbase.md) | working | crypto | none (keyless) |
| [kraken](data-providers/kraken.md) | working | crypto | none (keyless) |
| [okx](data-providers/okx.md) | working | crypto | none (keyless) |
| [bybit](data-providers/bybit.md) | working | crypto | none (keyless) |
| [yahoo](data-providers/yahoo.md) | working (unofficial) | equity, etf, index, fx, crypto, future | none (keyless) |
| [fred](data-providers/fred.md) | interface_fixture_tested (endpoint reachable; needs key) | macro | `FRED_API_KEY` |
| [alpaca](data-providers/alpaca.md) | interface_fixture_tested | equity, etf | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` |
| [tiingo](data-providers/tiingo.md) | interface_fixture_tested | equity, etf, crypto, fx | `TIINGO_API_KEY` |
| [polygon](data-providers/polygon.md) | interface_fixture_tested | equity, etf, option, fx, crypto, index | `POLYGON_API_KEY` |
| [finnhub](data-providers/finnhub.md) | interface_fixture_tested | equity, etf, fx, crypto | `FINNHUB_API_KEY` |
| [twelvedata](data-providers/twelvedata.md) | interface_fixture_tested | equity, etf, fx, crypto, index | `TWELVEDATA_API_KEY` |
| [alphavantage](data-providers/alphavantage.md) | interface_fixture_tested | equity, etf, fx, crypto, macro | `ALPHAVANTAGE_API_KEY` |
| [databento](data-providers/databento.md) | interface_fixture_tested | equity, future, option | `DATABENTO_API_KEY` |
| [ibkr](data-providers/ibkr.md) | interface_fixture_tested | equity, etf, future, option, fx, index | `IBKR_CP_GATEWAY_URL` |
| [oanda](data-providers/oanda.md) | interface_fixture_tested | fx, cfd | `OANDA_API_TOKEN` |
| [questrade](data-providers/questrade.md) | interface_fixture_tested | equity, etf, option | `QUESTRADE_REFRESH_TOKEN` |
| [tradier](data-providers/tradier.md) | interface_fixture_tested | equity, etf, option | `TRADIER_ACCESS_TOKEN` |
| [cme](data-providers/cme.md) | documented_stub | future, option | none (keyless) |
| [tmx](data-providers/tmx.md) | documented_stub | equity, etf, future, option | none (keyless) |

Status meanings: `working` = live-tested keyless; `interface_fixture_tested` = adapter complete, unit-tested with labelled SYNTHETIC fixtures, activates only when its env vars are set; `documented_stub` = manifest + docs only. Unit tests (`tests/feeds`) never touch the network.
