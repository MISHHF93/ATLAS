# Reserve yield — `reserve-yield:v1`

The third book is a paper sweep of realized trading profit into liquid cash-flow assets. It does not place a venue order, and it does not touch the competition seed position `pos-001`.

## What gets the profit

Distributable profit is the control plane's cumulative paper profit when that number is above zero. Open competition notional is not swept.

| Sleeve | Weight | Holdings |
| --- | --- | --- |
| Federal tax-exempt munis | 40% | `MUB`, `VTEB`, `TFI`, `HYMB`, `CMF`, `NYF`, split evenly |
| T-bills | 30% | `SGOV`, `BIL`, split evenly |
| Broad equities | 20% | `VOO`, `QQQ`, split evenly |
| Real estate | 10% | `VNQ`, `CPT`, split evenly |

`SHY`, `IEF`, and `TLT` stay on the treasury ladder at a zero sweep weight. `SPG`, `HST`, and `VICI` stay in the real-asset list at a zero sweep weight. The named rule allocates the 30% to T-bills and the 10% to `VNQ` and `CPT`.

## Tax-equivalent yield

For a muni distribution yield `y` and a federal marginal rate `t`:

`TEY = y / (1 - t)`

`t` must sit in `[0, 1)`. The desk assumes `t = 0.37`, the top statutory federal ordinary rate, and labels that assumption. A treasury yield is taxable, so it is not run through this formula. `y` is filled only when a public distribution yield is observed. Until then TEY stays unobserved. A historical 4.0%–4.5% muni range is the reason the sleeve exists. It is not stamped on today's book.

## What is connected

Prices for these tickers use the same public-candle path as the other equities: Yahoo when the body is real, and the labeled fixture otherwise. TradingView charts them from the primary listing: `SGOV` is `NYSE:SGOV`, `MUB` is `AMEX:MUB`, `SHY` is `NASDAQ:SHY`.

MSRB EMMA, FINRA TRACE, and the IBKR bond scanner are not connected. No order is submitted. Equity and ETF prints from the public chart are older than the open-market freshness rule, so the sweep remains a target plan.

`GET /api/strategies/reserve-yield` returns the plan with `orders_submitted: 0` and `execution_permission: "none"`.
