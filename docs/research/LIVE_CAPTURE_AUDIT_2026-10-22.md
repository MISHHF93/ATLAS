# Live capture, freshness and retained learning — October 22, 2026

This supersedes the session-only and REST-sampling limitations of the earlier
Real time observer implementation. The daily heuristic policy remains separate.

## Changed data path

- Coinbase Exchange public `matches` and `heartbeat` WebSocket channels replace
  serial REST last-trade polling for the Real time chart and observer.
- BTC-USD, ETH-USD and SOL-USD stay subscribed while the process runs. Up to three
  recently viewed crypto symbols are additionally eligible for subscriptions.
- Received matches form one-second bars; seconds without trades stay empty.
  The chart displays forming bars. The observer uses only completed bars.
- A background observer checks completed bars every 250 ms, independently of
  browser requests. Its screen refreshes once per second with overlapping fetches
  suppressed. This is not a hard real-time latency guarantee.
- The display separates feed connection/freshness from the initial eight labeled
  outcomes needed by the experimental model. Unchanged prices and long gaps do
  not produce labels. Initialization is not proof of model quality.

## Artifacts and restart behavior

`.atlas/live_capture.sqlite` stores received trade and heartbeat messages with
exchange and receipt timestamps, derived bar states, prediction inputs and model
version, outcomes, skipped labels, detected trade-ID gaps, connection gaps, and
observer checkpoints. Each artifact payload has a SHA-256 digest. Local capture
files are excluded from Git. This implementation has no automatic archive purge;
the database grows as capture runs.

Checkpointed coefficients, bias, counts, pending prediction and recent outcomes
restore on restart. A process restart is recorded as a capture discontinuity.
Old bars remain subject to the stale-data gate; restoration does not pretend
that disconnected time was observed.

`GET /api/market/live-artifacts` reports counts and feed health.
`GET /api/market/live-artifacts/export` downloads a consistent ZIP containing a
standalone SQLite snapshot and manifest with its SHA-256. The Real time panel
links to this download.

## Verified

- Production WebSocket subscription returned subscriptions, historical last-match
  context, heartbeat and live match messages.
- A live restart check retained the observer's learned count: 31 before restart,
  51 after restart and subsequent background observation, with no repeated warm-up.
- A live check captured 853 raw matches, 256 heartbeats, 167 bars, 155 predictions,
  107 outcomes, 45 skipped outcomes and one process-restart gap. Counts continue
  increasing. The exported database and SHA-256 were verified.
- A captured BTC trade reached the server approximately 727 ms after its exchange
  timestamp. Clock alignment, network conditions and processing affect that value;
  it is an observation, not an SLA. Completed-bar and display delays are additional.
- 204 backend tests passed. Additional capture checks cover same-timestamp trade
  IDs, duplicate suppression, gap recording, checkpoint restoration, and export
  integrity. Type checking, route checks and production build passed. Desktop and
  mobile browser checks reported no page errors or document horizontal overflow.

## Documentation and remaining boundaries

[TradingView's widget data FAQ](https://www.tradingview.com/widget-docs/faq/data/)
states that widget data cannot be downloaded/exported, that widgets have no data
API for this use, and that website stock widgets can be delayed. Purchasing a
TradingView account plan does not change embedded stock-feed entitlements.
The model's feed therefore remains separate from the TradingView iframe.

[Coinbase's public WebSocket overview](https://docs.cdp.coinbase.com/exchange/websocket-feed/overview)
describes the unauthenticated public endpoint. Its
[channel documentation](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels)
warns that match messages can be dropped. This capture records known trade-ID and
heartbeat discontinuities, but does not automatically REST-backfill them. Initial
subscription boundaries are not full historical coverage.

The archive covers received subscribed data, not all exchanges, stocks, order-book
updates, news or filings. No absent artifacts are invented. It cannot capture while
the process or network is down. No entitled live stock feed or profitable model
has been established. The observer remains experimental with no order authority.
