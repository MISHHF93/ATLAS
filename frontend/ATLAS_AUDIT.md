# ATLAS repository audit — 2026-10-21

The baseline was 121 passing backend tests and one failing subscription test. Frontend typecheck passed. Existing uncommitted catalog, API, workbench, stylesheet and test changes were preserved.

Read: `docs/ATLAS_MASTER_SPEC.md`, `UNIVERSAL_AI_ECOSYSTEM.md`, `RESEARCH_OPERATING_CONTRACT.md`, `CURRENT_STATE.md`, `DECISIONS.md`, the master roadmap and domain CSVs. Inspected control/rules, feature and market microstructure, streaming/WebSocket, SEC and MCP gates, calendars, regimes, challenger/evaluation/storage modules, API routes and frontend workbench/chart wiring.

The documents mix historical scaffold descriptions with newer implementation claims. “Implemented,” connection status, benchmark scores and permission labels are not evidence of production readiness.

## Changes

- Research no longer calls `submit_order` or mutates the control-plane training state. An AST regression test guards model imports and order dispatch calls.
- Signal intake rejects HOLD, inverted/missing brackets, invalid telemetry and unavailable instrument metadata before position mutation or connector calls. Bracket prices survive the decision and paper connector callback. Lot sizing rounds down, respects the track risk cap and consults `RemainingRoomReport`. Projected stop loss is checked against daily/drawdown room. Static drawdown uses initial equity.
- `process_strategy_signal` and `/api/control/strategy-signal` are the new strict intake. An unconfigured execution connector produces a rejection. The older control/connector API remains a paper simulation; it does not place live broker orders.
- Canonical OFI includes depleted bid/ask queues on price moves. The exponential feature delegates to that implementation. The correction follows [Cont, Kukanov and Stoikov](https://arxiv.org/abs/1011.6402).
- Streaming splits actual aggressor volume into fixed-volume buckets, computes rolling Kyle OLS using the canonical estimator, rejects malformed/future-receipt timestamps before changing feature state, and stops inventing opposite-side volume and OFI z-scores.
- Symbol subscriptions are reference counted. WebSockets send unsolicited updates through bounded queues, support JSON subscribe/unsubscribe, disconnect slow senders and release subscriptions. Provider retry scheduling does not imply a successful connection. An async source-factory hook consumes normalized provider streams with backoff.
- Synthetic gateway output requires explicit demo mode. Legacy integration tests opt into that mode. The production gateway waits for observed input.
- The workbench uses same-origin requests, displays backend account risk, checks HTTP/decision failures, accumulates observed ticks into candles, and uses responsive 20/55/25 desktop columns. Search retains empty results. The real pinned `lightweight-charts` package replaces the local substitute. Chart lifetime, resize handling and animation-frame updates are separated. Volume-profile levels use a contiguous 70% OHLCV approximation.

## Single-port operation

Run `npm run dev` in `frontend` (or from the repository root). Open `http://localhost:3000/workbench`. For production, run `npm run build`, then `npm start`.

`server.mjs` owns the sole TCP listener at `127.0.0.1:3000`, serves Next.js, and forwards `/api/*` and `/ws/market-stream` to `scripts/asgi_stdio.py`. Python runs ASGI over child-process stdio and opens no listening port. There is no automatic port fallback. Do not run a separate Uvicorn server.

## Limits that remain material

This is not a live-trading certification. Alpaca/CCXT/DXtrade classes in the existing repository are paper simulators; an IBKR live transport, venue credentials, account reconciliation and authenticated execution policy are not implemented by this patch. The new strict intake rejects without a configured connector.

The async feed hook needs an authenticated/entitled source adapter. It does not itself establish Databento/Polygon connectivity. Size-only depth updates are an imbalance proxy; full price-sensitive OFI requires priced L2 snapshots. No multi-thread lock-free guarantee or 60 FPS/HFT latency benchmark has been established. The deque is intended for event-loop-confined ingestion. Browser/network delivery is not a risk enforcement channel.

Legacy research/demo endpoints and catalog fixtures remain. Their synthetic benchmark statistics, auto-promotion claims and broader authentication/account-isolation behavior require a separate deeper audit before deployment. Exception classes and intentional abstract contracts are not unfinished production stubs. Close-only volatility proxies are not interchangeable with OHLC true-range ATR and were not blindly merged.

Minimum active days remains an evaluation-completion gate; making it an entry gate would prevent a new account from accumulating its first five trading days. No ledger, custody, signing-key or ownership behavior was changed.

## Verification

- Python 3.12.10: **132 passed**, including ten new boundary cases. The verbose suite used `-B`, disabled pytest's cache and placed temporary files under the permitted frontend directory.
- `npm run typecheck`: passed.
- `npm run build`: passed, **42 static pages generated**.
- Production-host smoke checks: `/api/health`, `/api/control/state`, `/workbench` returned HTTP 200 on port 3000. The same-port WebSocket returned `awaiting_data` and acknowledged a JSON subscription.
- `npm audit --omit=dev`: two dependency advisories remain (Next/PostCSS, one moderate and one high). npm proposes a major Next upgrade; that migration was not bundled into this change. No claim of a clean security audit is made.
