# ATLAS account awareness: letting the ML understand the broker account

Status: design plus **phase 1 implemented** (evo-13). Paper / practice / simulated endpoints only. ML `execution_permission` stays `none`.
`risk_policy.yaml` is unchanged and remains the only source of limits.

Evidence rules for this document: every external number below has a source in section 9. Anything marked **arithmetic** is my own
calculation from stated inputs (not data). Anything marked **hypothetical** is an illustrative input, not a forecast. Anything marked
**to verify** is not yet confirmed from an official page and must be checked before it drives code.

---

## 1. What the ML needs to know, and why

A model that only sees prices does not know whether the trade it likes can exist. The account decides that: cash, buying power,
what is already held or pending, the smallest order the venue takes, fees, whether the market is open, and which regulation applies.
Section 5 shows that on a tiny account these constraints, not the signal, decide the outcome.

| Group | Facts | Why it matters |
|---|---|---|
| Balances | cash, equity, buying power, settled cash, margin used / available, max leverage | upper bound on any order; cash vs margin changes risk |
| Holdings | positions, open orders | avoids doubling up; exposure and concentration features |
| Venue rules | minimum order (notional or units), fractional support, shorting, margin, settlement days, blocked flag | a policy-sized trade may be smaller than the minimum |
| Regulation | day-trade rule flag | see 3.3: the US PDT rule was retired 2026-06-04, but a broker may still carry a flag |
| Fees | commission per order / unit / min / cap, spread assumption, pass-through fees | fixed fees dominate small orders |
| Market state | open or closed, next open / close | no signal is actionable while closed |

## 2. Broker-agnostic `AccountSnapshot` (implemented: `src/atlas/broker_state/snapshot.py`)

Rules: unknown is `None`, never a guess; no secret and no full account number (masked to the last 4); `read_only=True` and
`execution_permission="none"` are forced in `__post_init__`; `environment` is one of `simulated | paper | practice` (live is not
representable); `status` is one of `ok | not_configured | needs_verification | verification_failed | refused_live | error`.

```
AccountSnapshot
  broker, environment, status, reason, as_of, currency, account_ref(masked), schema_version, read_only, execution_permission
  balances: cash, equity, buying_power, settled_cash, margin_used, margin_available, leverage_max
  positions[]: symbol, qty, side, avg_price, market_value, unrealized_pl, asset_class
  open_orders[]: order_id, symbol, side, qty, notional, order_type, status, submitted_at
  rules: min_order_notional, min_order_qty, fractional, shorting_allowed, margin_enabled, pdt_applies, pdt_note,
         settlement_days, trading_blocked, notes[]
  fees: commission_per_order, commission_per_unit, commission_min, commission_max_pct, spread_bps_assumed, notes[]
  market: is_open, next_open, next_close, source
  warnings[]
```

### 2.1 Field mapping per broker (official docs; paper/practice endpoints only)

| Snapshot | Alpaca paper (`paper-api.alpaca.markets`) | OANDA practice (`api-fxpractice.oanda.com`) | IBKR paper (phase 2) | Questrade (phase 2) |
|---|---|---|---|---|
| Account | `GET /v2/account`: `cash`, `equity`, `buying_power`, `multiplier`, `pattern_day_trader`, `trading_blocked`, `shorting_enabled`, `currency` | `GET /v3/accounts/{id}/summary`: `balance`, `NAV`, `marginUsed`, `marginAvailable`, `marginRate`, `currency` | `GET /portfolio/{accountId}/summary` (`availablefunds`, `buyingpower`, `-c` and `-s` variants) and `/ledger` (per-currency `cashbalance`, `settledcash`, `netliquidationvalue`); call `/portfolio/accounts` first | per-currency balances endpoint (cash, market value, buying power per currency) |
| Positions / orders | `/v2/positions`, `/v2/orders?status=open` | `/openPositions`, `/pendingOrders` | `/portfolio/{id}/positions`, live orders endpoint | positions and orders endpoints |
| Min order | $1 notional for fractional buys (docs); `GET /v2/assets` `fractionable` per symbol | `GET /instruments`: `minimumTradeSize`, `tradeUnitsPrecision`, per-instrument margin rate | per contract (to verify) | per symbol (to verify) |
| Market hours | `GET /v2/clock`, `GET /v2/calendar` | per-instrument `tradeable` in pricing (to verify in phase 2) | contract trading hours (to verify) | market status (to verify) |
| Paper guard | URL must be the paper host; account number must start `PA` (`execution/adapters/guards.py`) | `OANDA_ENV=live` refused; only the practice host is called | ports 4002 / 7497 only, account must start `DU` (guards.py, already in repo) | n/a: no paper environment confirmed here |

OANDA has no existing execution adapter in ATLAS, and phase 1 adds none (read-only). IBKR in the repo takes an injected client only.

### 2.2 Adapter interface (implemented: `src/atlas/broker_state/adapters.py`)

`BrokerStateAdapter.fetch(env) -> AccountSnapshot`. Shipped adapters:

* `PaperSimAdapter`: wraps ATLAS's `PaperBroker` (cash, positions, open orders, T+N settlement, flat commission + slippage). No network.
  The minimum order of 1.00 is an assumption mirroring Alpaca's $1; the snapshot says so.
* `AlpacaPaperStateAdapter` and `OandaPracticeStateAdapter`: **idle until Settings → Verify marks the key `verified`**
  (same secret-free store as the Verify button). Before that they return `needs_verification` and make **zero** requests. Only GET.
  Live host / live account / `OANDA_ENV=live` return `refused_live`. Errors become a snapshot with `status="error"`.
* No adapter has any write method (a test asserts it).

## 3. Rules that change what is possible

1. **Cash vs margin.** A cash account cannot spend unsettled proceeds; margin raises buying power but also loss. Alpaca exposes `multiplier`;
   OANDA exposes `marginRate` (leverage about 1/marginRate; per instrument). The snapshot carries `leverage_max`; the control plane never uses it to raise risk.
2. **Fractional and minimum size.** Alpaca: fractional orders, $1 minimum notional for buy entry orders, `day` time-in-force only, symbol must be `fractionable`.
   OANDA trades whole units (`minimumTradeSize`, `tradeUnitsPrecision`).
3. **Pattern day trader.** FINRA Regulatory Notice 26-10 replaced the PDT framework effective 2026-06-04 (no day-trade-count designation, no $25,000 minimum),
   replacing it with intraday-margin standards; firms may phase implementation until 2027-10-20. So `pdt_applies` is optional metadata: show it, do not hard-code the old $25k rule.
4. **Fees.** Alpaca: commission-free US equities; pass-through SEC fee (sells), FINRA TAF (sells), CAT fee (both) per its published schedule, accrued intraday,
   deducted end of day, rounded up to the cent (to verify whether the cent rounding is per order or per day). Questrade: $0 commission on online Canadian and US-listed stocks/ETFs;
   ECN fees can apply to certain US direct-routed or OTC trades. IBKR Pro Fixed: USD 0.005/share, **USD 1.00 minimum per order**, maximum 1% of trade value.
5. **Alpaca is not offered to Canadian residents** (user-reported); it is therefore an optional adapter. OANDA practice, IBKR paper and Questrade are the Canadian-relevant paths.

## 4. How the snapshot reaches the ML (read-only)

`features.snapshot_features(snapshot)` returns flat numbers/booleans (missing stays `None`; the model must handle missing, not 0):
equity, cash fraction, gross exposure, top-position fraction, buying-power ratio, margin utilisation, position and open-order counts,
fractional flag, minimum order and its percent of equity, how many minimum lots equity can buy, PDT flag, blocked flag, market open, and the sizing
feasibility triple from section 5. `features.context_text(snapshot)` gives one factual line for an agent context.
Both are served by `GET /api/account/snapshot` (query: `broker`, `sim_equity`, `risk_fraction`, `stop_distance`). The ML consumes them as inputs. Nothing flows back:
the output remains a proposal (direction, conviction, volatility forecast) that the control plane may shrink or reject, never enlarge.

## 5. Sizing math: the ML proposes, the control plane sizes

All sizing is **tighten-only** under `risk_policy.yaml` (current paper profile L1: daily 2%, weekly 4%, max drawdown 10%, max position 10% of bot capital; open-market
trades are risk-sized at 0.5% of equity per trade in the control plane). Order size is the **minimum** of every cap below, then rounded **down** to the broker step;
if the result is below the broker's minimum order the answer is **no trade** (never round up).

1. **Risk-per-trade cap (exists today).** `notional_risk = E · r / s`, with equity `E`, per-trade risk fraction `r` (0.5%), stop distance `s` (fraction of price).
2. **Fractional Kelly cap (phase 3).** For a lognormal asset with excess drift `μ-r_f` and volatility `σ`, Kelly fraction `f* = (μ-r_f)/σ²` (Kelly 1956; Thorp). Betting a fraction
   `c` of Kelly gives long-run growth `g = r_f + (c − c²/2)·S²` where `S` is the Sharpe ratio (MacLean, Thorp, Ziemba). Full Kelly maximises growth but prescribes large short-term-risky bets;
   fractional Kelly trades growth for security. Because `μ` and `σ` are estimated, use `c ≤ 0.5` (a policy choice). **Arithmetic, hypothetical S = 0.5:** full Kelly grows 12.5%/yr over
   the risk-free rate at 50%/yr portfolio volatility; half Kelly grows 9.4%/yr (75% of the growth) at 25% volatility.
3. **Volatility target cap (phase 3).** exposure `= min(cap, σ_target / σ̂)`; scale down when forecast volatility rises. Moreira and Muir (2017) report that volatility-managed
   portfolios raise Sharpe ratios and alphas in their samples; treat as supportive evidence, not a guarantee, and test it net of costs here.
4. **Drawdown governor (phase 3).** Grossman and Zhou (1993): to keep wealth above a fraction `α` of its running peak `M`, risky exposure is proportional to the surplus
   `W − α·M`. Implementation: `exposure = m · (W − α·M) / W`, with `α = 1 − 10%` to match the policy drawdown, so exposure shrinks automatically near the limit. Gaps can still jump through a floor.
5. **Diversification across few lots (phase 3).** Equal-risk-contribution weights (Maillard, Roncalli, Teïletche 2010) sit between minimum-variance and equal-weight in volatility. On a small
   account the number of lots is bounded by `floor(E / min_order)` (feature `acct_max_distinct_min_lots`), so diversification is capped by the account, not by the model.
6. **Feasibility gate (implemented: `features.sizing_feasibility`).** Compare ideal notional `E·r/s` with the venue minimum. If smaller, the only trade that fits risks `min_order·s/E`, more than policy.
   Minimum equity for a policy-sized trade is `min_order·s/r`. **Arithmetic** with min order $1, `r = 0.5%`, `s = 2%`: ideal notional at E = $1 is $0.25 (infeasible); the $1 minimum would risk 2%
   (4× policy); policy becomes feasible at E ≥ $4. At E = $1 the account is also fully invested by a single minimum order, so there is no diversification at all.

## 6. Realistic small-account analysis

**There is no zero-risk, steadily compounding strategy.** The only near-riskless return is the risk-free rate (bank/T-bill type products), whatever it is today; anything above it
carries risk of loss, and risk controls reduce the size of losses but do not remove them (gaps, halts, correlated moves, estimation error in `μ` and `σ`).
Controls change the shape of risk, not the existence of it.

What the sources and arithmetic say:

* **Fees and minimums decide tiny accounts (arithmetic).** A flat $1 fee per order (ATLAS paper default; also IBKR Fixed's minimum) on a $10 round trip costs $2 = 20%. On $1000 it is 0.2%.
  A $1 account with a $1 minimum order is 100% invested in one position at once.
* **Retail trading evidence is poor.** Barber and Odean (2000), 66,465 US households, 1991-96: the most active traders earned 11.4%/yr versus 17.9% for the market; the average household
  earned 16.4% net after costs, gross returns were near the market, and the shortfall is attributed to trading costs and overconfidence. Chague, De-Losso, Giovannetti (2019): of 1,551 Brazilian
  futures day traders who persisted at least 300 days, 97% lost money net of fees, 0.4% earned more than a bank teller, and the authors find no evidence of learning. These are not forecasts for ATLAS;
  they are the base rate an automated system must beat net of costs before it is trusted.
* **Compounding arithmetic (hypothetical rates).** $1 at 10%/yr is about $2.59 after 10 years; at 20%/yr about $6.19. Absolute gains on tiny balances are cents; regular contributions dominate
  growth until the balance is large (e.g. $50/month for 10 years is $6,000 of contributions before any return). Volatility drag lowers compound growth by about `σ²/2` below the average return, and a 50% loss needs a 100% gain to recover.
* **Kelly bounds the ambition.** Section 5.2: even with a true Sharpe of 0.5 (itself optimistic for most retail strategies; hypothetical) the best long-run excess growth is 12.5%/yr at full Kelly with 50% volatility.

What ATLAS can honestly do for a small account, in order of value: (1) refuse trades whose size or fee drag makes them unprofitable in expectation (feasibility gate + fee drag feature);
(2) keep the core in a low-cost diversified ETF sleeve (policy core 60%); (3) take only risk the account can size to the minimum lot; (4) prove edge in paper first: the policy ladder already requires
60 paper days, Sharpe ≥ 1.0, max drawdown ≤ 10% and profit factor ≥ 1.3 before level 2; (5) report results net of costs against a buy-and-hold ETF benchmark. Live trading stays locked.

## 7. Phased build plan

| Phase | Scope | Exit criteria |
|---|---|---|
| 1 (done, evo-13) | `AccountSnapshot`; adapter interface; paper-sim, Alpaca-paper, OANDA-practice adapters (idle until verified); `GET /api/account/snapshot`; UI card (Trade → Paper account); 18 tests | tests green; zero requests before Verify; live refused |
| 2 | IBKR paper adapter (CP Web API read; DU/port guards); Questrade balances/positions; market calendar and hours; per-instrument rules (Alpaca `/v2/assets`, OANDA `/instruments` cache); snapshot history in `var/` | each adapter fixture-tested against official response shapes; every "to verify" item confirmed from official docs |
| 3 | `sizing` module: tighten-only caps (fractional Kelly, vol target, drawdown governor, feasibility gate) called from the control plane before `submit_order`; property tests: result ≤ policy cap, ≤ buying power, never below broker minimum | for 10^5 random inputs size never exceeds `risk_policy.yaml` |
| 4 | ML features: wire `snapshot_features` as read-only inputs; cost-aware labels (net of fee/spread); calibrate the fee model from real paper fills | out-of-sample net-of-cost improvement vs the same model without account features, or it is not shipped |
| 5 | Paper evidence run against the autonomy gates, net-of-cost reporting vs ETF benchmark | gates in `risk_policy.yaml` met; live remains owner-signed, separate decision |

## 8. Safety invariants (tested or structural)

* Read-only: adapters expose no write method; only GET; `execution_permission="none"` forced in the schema and in the API response.
* Paper/practice only: Alpaca live host and non-`PA` account refused; OANDA live refused without a request; `live` is not a valid `environment`.
* No keys set by ATLAS: adapters are idle until the owner enters a key and presses Verify; snapshots hold masked account refs only.
* Unknown stays unknown (`None`); the UI says "unknown", not 0.

## 9. Sources

* Kelly, J. L. (1956). A New Interpretation of Information Rate. Bell System Technical Journal 35(4), 917-926.
* Thorp, E. O. (2006). The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market. Handbook of Asset and Liability Management.
* MacLean, Thorp, Ziemba. Good and Bad Properties of the Kelly Criterion. Wilmott 3 (2010 reprint). https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf
* Grossman, S. J. and Zhou, Z. (1993). Optimal Investment Strategies for Controlling Drawdowns. Mathematical Finance 3(3), 241-276. https://doi.org/10.1111/j.1467-9965.1993.tb00044.x
* Maillard, S., Roncalli, T., Teïletche, J. (2010). The Properties of Equally Weighted Risk Contribution Portfolios. J. Portfolio Management 36(4), 60-70. https://doi.org/10.3905/jpm.2010.36.4.060
* Moreira, A. and Muir, T. (2017). Volatility-Managed Portfolios. Journal of Finance 72(4), 1611-1644. https://doi.org/10.1111/jofi.12513
* Barber, B. and Odean, T. (2000). Trading Is Hazardous to Your Wealth. Journal of Finance. https://doi.org/10.1111/0022-1082.00226
* Chague, F., De-Losso, R., Giovannetti, B. (2019). Day Trading for a Living? https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
* FINRA Regulatory Notice 26-10 (PDT replaced, effective 2026-06-04). https://www.finra.org/rules-guidance/notices/26-10 and 26-11.
* Alpaca fractional trading: https://docs.alpaca.markets/us/docs/fractional-trading ; $1 notional: https://alpaca.markets/support/can-we-submit-orders-smaller-than-1-usd-in-notional-value ;
  regulatory fees: https://docs.alpaca.markets/us/docs/regulatory-fees ; commission-free: https://alpaca.markets/algotrading
* OANDA v20 account definitions: https://developer.oanda.com/rest-live-v20/account-df/ ; development guide: https://developer.oanda.com/rest-live-v20/development-guide/
* IBKR Web API: https://www.interactivebrokers.com/docs/web-api/v1/endpoints/portfolio/portfolio-summary.md and `.../portfolio-ledger.md`; commissions: https://www.interactivebrokers.com/en/pricing/commissions-stocks.php
* Questrade fees: https://www.questrade.com/pricing/self-directed-commissions-plans-fees/transaction
* Repo: `config/founder/risk_policy.yaml`, `src/atlas/execution/adapters/guards.py`, `docs-research/broker_apis.md`.
