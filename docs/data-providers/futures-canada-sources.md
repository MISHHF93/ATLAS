# Canada-eligible sources for the 18 Yahoo-only futures (research, 2026-10-29)

Scope: ES, NQ, YM, RTY, MES, MNQ, MYM, M2K, CL, MCL, GC, MGC, SI, NG, ZN, ZB, 6E, 6J.
Rule: an adapter is added only where the published terms allow it. No key is set anywhere; every key below is **needs verification**.
Yahoo stays excluded from trade series (unofficial terms). Nothing here changes `execution_permission` (none) or the paper-only risk policy.

| Source | Terms (from the provider's own pages) | Covers | Use in ATLAS | Status |
|---|---|---|---|---|
| OANDA Canada practice v20 (`api-fxpractice.oanda.com`) | Personal practice token + account id; CFDs are enabled for OANDA Canada clients; M1..M candles, 5000 per page. | SPX500_USD, NAS100_USD, US30_USD, US2000_USD, WTICO_USD, BCO_USD, NATGAS_USD, XAU_USD, XAG_USD, USB10Y_USD, USB30Y_USD, EUR_USD, USD_JPY (see `feeds/oanda_proxies.py`) | **Labelled proxy** CFD intraday series; nowcast anchor only after `OANDA_API_TOKEN` is verified. Never a futures price. | Mapped, **inactive**. No token given. Confirm each instrument with `GET /v3/instruments`. |
| EIA Open Data API v2 | Free key. US-government work, public domain; reuse with attribution. | WTI spot (RWTC), Brent (RBRTE), Henry Hub spot (RNGWHHD), daily | Display/context for CL, MCL, NG. Spot benchmark, **not** the futures contract, daily only. | Not wired. `EIA_API_KEY` **needs verification** (user must register). |
| Bank of Canada Valet | No key. Indicative daily rates, statistical use, cache and respect limits. | USD/CAD, EUR/CAD, JPY/CAD (EUR/USD, USD/JPY only as derived crosses) | EOD context for 6E, 6J. Not a trade series. | Existing note in `boc_valet.md`; not a futures bar source. |
| FRED (keyed) | Terms prohibit AI training/archival. | DCOILWTICO, DHHNGSP, DGS10, DGS30 | Display/risk-context only. **Never enters ML training.** | Existing `macro_risk` layer; key unchanged. |
| Stooq | Personal non-commercial use, no redistribution, CAPTCHA key and daily quota. | most of the list | **Do not add.** | Rejected. |
| CME / ICE delayed or historical | Licensed; redistribution restricted. Needs a CME-recognised vendor agreement. | all | No adapter. | Rejected (licence). |
| Yahoo | Unofficial, no terms for this use. | all | Excluded from trade series. | Rejected. |

Equity-index and rates contracts (ES/NQ/YM/RTY and micros, ZN/ZB) have **no free official source for futures prices in Canada**. The honest options are
the OANDA CFD proxy (labelled proxy, once the user verifies a token), or a paid licensed vendor chosen by the user. Gaps stay visible as
"no feed bars"; the dashed nowcast covers the chart meanwhile and is never stored as bars.
