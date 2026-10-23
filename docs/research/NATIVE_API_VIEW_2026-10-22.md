# Native API chart and model viewer

The reported error, "No public 1-second print for this name", came from the non-crypto guard in `second_tape.snapshot`. It was a source-selection limitation, not an inability to draw API data. The old one-second endpoint remains a trade-only endpoint; Real time mode now uses `/api/market/live-view` instead.

## Data path

- Supported Coinbase products retain the received WebSocket trade stream and one-second candles.
- Other listings request available public one-minute API candles. Yahoo symbol mappings cover dotted stock names and supported futures roots. The native chart draws these candles directly, without an iframe. Refreshing every ten seconds does not turn them into second-by-second prices.
- One response supplies both the chart and the observer. The chart may show a forming candle; the observer sees only completed candles from that response. Real time mode no longer runs the Desk's legacy bar/model polls or merges its fixture socket into the viewer.
- Failed refreshes retain original data timestamps. Missing symbols stay empty. Old candles remain inspectable, while stale inputs pause learning. Provider delay remains unknown unless reported; undocumented provider delay units are preserved without guessing a duration.

## Learning and capture

The experimental online logistic observer supports the actual candle duration. It waits for a later completed outcome; merely revisiting a snapshot does not train it. One-second observations retain the ten-second maximum outcome gap; minute observations use a two-minute maximum gap. State is isolated by symbol, source and resolution. Minute observation progresses while the viewer requests snapshots; existing core crypto background observation continues independently.

Minute API snapshots, prediction inputs, outcomes and checkpoints join the existing local capture archive. Historical minute candles are not replayed as successful live training. The observer remains experimental and has no order authority.

## Verification

- Production build and TypeScript check passed; 231 backend tests and three navigation checks passed. The 25 new live-view tests cover shared inputs, causal minute learning, state isolation, failed refreshes, missing data, validation, endpoint behavior, and symbol mappings.
- Live requests returned native API candles for NVDA, BRK.B and ES. NVDA and BRK.B were fresh; older ES data correctly reported stale and withheld learning.
- Browser checks verified NVDA on Desk and Markets, BTC on Desk, and Desk at 1440x900, 390x844 and 844x390. Both chart and model rendered; no browser errors or horizontal document overflow occurred. Network inspection confirmed no legacy one-second chart-read or second-tape requests in Real time mode.
- Screenshots and request evidence are under `.test-runs/visual-audit/native-api/`.

No authenticated equities tick feed is configured. This implementation provides real public API candles at their available resolution; it does not grant tick-level stock coverage or complete coverage of the asset directory.
