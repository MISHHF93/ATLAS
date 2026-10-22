# Range garden — paper harvest of a proven range

Path id: `range-garden:v1`. Strategy id: `STRAT_RANGE_GARDEN`.

This is the trading mechanism for both books. The desk watches as fast as the print is real. It buys the lower rail and sells the upper rail. It does not turn every second into an order. A second with no rail touch is a watch. Revenue is the sum of completed paper round trips after cost.

The control plane is the only component that can open or close a paper bracket. This path does not open a broker, prop-firm, Polygon, Databento, or IBKR session. A promoted research model is not an input to the order. FRED is not an input.

## Objective

Maximize realized paper P&L from range harvests:

```
revenue = sum over closed harvests of (directional move in dollars) − round-trip cost
```

Round-trip cost is two fees plus the spread. Turnover is not the objective. A buy and a sell in the same second, inside the spread, has negative expectancy before any forecast is right.

Constraints, all of them binding:

1. One garden bracket per symbol. The fixture seed position `pos-001` is not a garden position and is never closed by this path.
2. A new bracket only when the last public print is inside a rail zone of a range that has already been touched on both sides.
3. The distance from the entry print to the target must clear the round-trip cost. If the box is thinner than that, the action is `stand_down` / `range_does_not_pay`.
4. The stop sits outside the rail by at least the track minimum: 25 bps on `competition`, 30 bps on `open_market`.
5. After a harvest closes, the next entry waits until price has returned through the middle of the bed.
6. Competition prints older than 500 ms are not tradable. Open-market prints older than 2000 ms are not tradable. Those are the same staleness checks `submit_order` already enforces.
7. A labeled fixture tick, a demo orbit, or a missing timestamp is not a market. Geometry may still be computed for the desk. No order is sent.
8. The kill switch blocks new brackets. A close of a garden bracket the engine still shows as open is a risk reduction and remains allowed.
9. `execution_permission` on the signal and on this report stays `none`. Authorization is the control-plane decision, and the fill mode is `paper`.

## Fundamentals the bot is built on

| Idea | What the garden does with it |
| --- | --- |
| Expectancy | Prefer fewer harvests whose target clears cost over a toggle on every print. |
| Cost | Competition assumes 6 bps fee per side and 2 bps half-spread, unless the Coinbase bid/ask is tighter and still under 40 bps wide. Open market assumes 1 bp fee per side and 1 bp half-spread. A book wider than 40 bps is `spread_too_wide`. |
| Inventory | Flat, long one bracket, or short one bracket. A second signal on the same symbol does not add size. |
| Range versus trend | Two or more lows at the lower rail and two or more highs at the upper rail, measured on the last 90 one-minute public bars (at least 40). A print 10 bps through either rail is `range_broken`. No fade. |
| Payoff | Target the opposite rail when the full width clears cost plus the minimum stop. Otherwise target the midline when half the width clears that hurdle. |
| Time | The 1-second loop is a tender: mark the stop, mark the target, refresh the print. It is not a signal to trade. |
| Authority | Opens go through `ingest_whale_policy_signal` with the measured print age and `require_connector=False`. Closes go through `close_position`. Neither call is a venue fill. |
| Honesty of the tape | Crypto last trades come from Coinbase's public ticker (`coinbase_exchange_public`, `public_last_trade`). Rails come from public 1-minute candles. Equities and ETFs have Yahoo minute bars only. Those bars are older than 2000 ms, so the open-market book can show a blocked harvest and must not paper it until a print that fresh exists. |

## Mechanism

Rails are the 15th percentile of lows and the 85th percentile of highs on the minute bars. The midline is the midpoint of those rails. The rail zone is the outer 18% of the bed on each side.

| Observed state | Action |
| --- | --- |
| Fewer than 40 printed minute bars | `stand_down` / `not_enough_printed_bars` |
| Range broken by 10 bps | `stand_down` / `range_broken` |
| Fewer than two touches on either rail | `watch` / `range_unproven` |
| Width does not clear cost and the minimum stop | `stand_down` / `range_does_not_pay` |
| Flat, print in the lower zone, box pays, print fresh and public | `harvest_buy` |
| Flat, print in the upper zone, box pays, print fresh and public | `harvest_sell` |
| Flat, print in a zone, but the print is stale, synthetic, or unlabeled | `stand_down`, with `blocked_action` naming the harvest that was withheld |
| Waiting for a return to the midline after a close | `watch` / `waiting_for_midline` |
| Inside the bed, no bracket | `watch` / `inside_bed` |
| Bracket open, print through the stop | `close_long` or `close_short` / `stop` |
| Bracket open, print through the target | `close_long` or `close_short` / `target` |
| Bracket open, print still inside the bracket | `watch` / `tending_open_bracket` |
| Kill switch engaged and the action would open | `stand_down` / `kill_switch_engaged` |
| Control plane rejects the open | `stand_down` / `control_plane_rejected` |

The open-market names are SPY, NVDA, AAPL, MSFT, QQQ, and TSLA. The competition names are BTC-USD, ETH-USD, and SOL-USD. Same universe as the training path. Other catalog symbols stay on labeled fixture bars and are not garden names.

Paper P&L is booked only when a garden position closes. The fee charged at the close is the round-trip cost in bps times the sized notional. Equity, gross notional, and the correlated and sector adders move with that close. The seed book's notional is left in place.

## What this pass builds

| Piece | Where |
| --- | --- |
| This document | `docs/roadmap/range_garden.md` |
| Rail math and the air-gapped signal | `src/atlas/strategies/range_garden.py` |
| Public last trade for crypto | `fetch_public_ticker` in `src/atlas/marketdata/public_quotes.py` |
| Paper close | `ActionableControlPlaneEngine.close_position` |
| One-second tender | Startup task beside the universe pump. Off under pytest and when `ATLAS_DISABLE_RANGE_GARDEN=1`. |
| Status | `GET /api/strategies/range-garden` and `POST /api/strategies/range-garden/cycle` |
| Desk line | The studio prints path, the selected symbol's action, orders opened, harvests closed, and `execution_permission`. |

`POST` runs one tender on the public tape. It does not accept a caller-supplied price. Named roles that cannot `submit_bracket_order` receive 403. An omitted role keeps the operator-console behavior used by the rest of the desk.

## Still outside this path

A broker or prop-firm session, a certified live route, a second-resolution equity print, and any claim that a harvest won a competition or maximized live revenue. Those wait on a real session and on the same control-plane gate. Until an equity print is younger than 2000 ms, that book is a watch.
