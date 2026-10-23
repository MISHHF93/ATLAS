# Addendum: Venue, Data & Regulatory Compatibility for a Canadian Resident / Canadian Entity
*Prepared 2026-10-16 (ET). Companion to `review.md`. Not legal or tax advice. Confirm with the venue, a securities lawyer and a CPA before going live.*

Legend: ✅ verified from a cited source on 2026-10-16 · ⚠️ partly verified or inferred · ❓ not verified (general knowledge or vendor docs that don't address Canada).

## 1. Compatibility table

| Venue | Individual | Corporation | Private fund | Asset classes / markets | API | Regulator status (Canada) | Notes |
|---|---|---|---|---|---|---|---|
| **Interactive Brokers Canada** | ✅ Yes | ✅ Yes (institution accounts) | ✅ Yes (Hedge Fund / Multiple Hedge Fund / Allocation; needs an HFA/FM master account first) | Global equities, ETFs, options, futures, FX, bonds; crypto via Paxos/Zero Hash ⚠️ | ✅ Full trading (TWS/IB Gateway API, Client Portal Web API ❓ by name) | CIRO member, CIPF ✅ | **Recommended primary broker** for every structure. Canadian advisors must prove provincial registration. [1][2][3][4] Crypto eligibility for IBKR **Canada** clients, as opposed to IBKR LLC, ⚠️ needs confirming per account. [5] |
| **Alpaca** | ❌ Live no; paper only | ❌ | ❌ | US equities/crypto (for US/intl clients) | Paper API only for Canadians | Not registered in Canada | "Residents of Canada are not currently eligible." Market-data subscriptions aren't offered to Canadians. Alpaca staff said on Aug 14, 2026 that they are targeting regulatory approval around Nov 2026 for individual accounts (**not launched**). [6][7] |
| **Questrade** | ✅ | ✅ ❓ (corp accounts exist, not verified here) | ❓ | CA/US equities, ETFs, options | ⚠️ Read-only for customers. Order execution is limited to partner developers. The Questrade MCP drafts orders but each one needs push approval on your phone. | CIRO/CIPF ❓ (not re-checked) | Can't be used for autonomous execution. Good for data or reconciliation only. [8][9] |
| **Wealthsimple** | ✅ | ❓ | ❌ ❓ | CA/US equities, crypto | ❌ No official API (SnapTrade is a third-party aggregator) | Crypto: Investment Dealer ✅ | Not suitable for a bot. [10][12] |
| **Moomoo Canada** | ✅ ❓ | ❓ | ❓ | CA/US equities, ETFs | ✅ OpenAPI documents Canadian stocks/ETFs and order placement | ❓ | Possible secondary broker. Verify account types and order permissions. [11] |
| **Webull Canada** | ✅ ❓ | ❓ | ❓ | Equities; crypto (Webull Canada Crypto) | ⚠️ Official API docs cover the US. Canada coverage isn't confirmed. | Crypto entity: Investment Dealer (Jun 17, 2026) ✅ | [12][13] |
| **Coinbase Canada** | ✅ | ⚠️ Yes (business accounts; Ontario not explicitly confirmed) | ⚠️ Coinbase Exchange / Prime are institutional. Coinbase International Exchange is for non-US institutions in eligible jurisdictions, by application ❓ for Canada. | Spot crypto (derivatives restricted for Canadians ❓) | ✅ Advanced Trade REST/WebSocket; Exchange FIX/REST | Restricted Dealer, all provinces. Interim relief extended Apr 1, 2026 while the CIRO membership application continues ✅ | Usable for the crypto sleeve. Status is interim, so monitor the OSC page. [14][15][16][17] |
| **Kraken (Payward Canada)** | ✅ | ✅ (corporate verification; API keys scoped per account) ⚠️ | ⚠️ Corporate path likely. Fund-specific onboarding not verified. | Spot crypto only. **No margin, no derivatives** for Canadian residents. Long restricted list including USDT, USDC-family (USDG), DAI, WBTC, XMR. | ✅ REST, WebSocket, FIX (spot) | Restricted Dealer (OSC + all provinces; amended decision Aug 18, 2026), FINTRAC MSB M19343731 ✅ | **Registration is now confirmed, so the `kraken.enabled: false` "until CSA confirmed" gate can be lifted** (owner decision). The software must enforce Kraken's Canada asset blocklist. [14][18][19] |
| Other CSA-authorized crypto platforms: Coinsquare/Bitbuy (Investment Dealer), NDAX (ID), Shakepay (ID), Newton (RD), Netcoins (RD), Crypto.com/Foris DAX (RD), Fidelity Digital Assets (ID), Satstreet (RD) | ✅ registered | ❓ | ❓ | Spot crypto | ❓ API quality varies (NDAX has a public API ❓) | As listed ✅ | Only CSA-authorized platforms should be used. Unregistered offshore exchanges (Binance, Bybit, OKX, etc.) are **out of scope**. [14][20][21] |
| **Massive (formerly Polygon.io)** (data) | ✅ (non-pro individual plans) | ⚠️ needs a Business plan | ⚠️ needs a Business plan | **US only** (equities, ETFs, OTC, options/crypto ❓). **No TSX quotes.** The TMX partnership covers corporate events only. | REST/WebSocket | n/a | A corp or fund using it is commercial use, so personal plans don't apply. [22] |
| **Databento** (data) | ✅ ❓ | ✅ ❓ | ✅ ❓ | US venues. TSX is "accepted" on the roadmap but **not released**. | API | n/a | [23] |
| **TMX Datalinx / TMX Information Services** (data) | ✅ | ✅ | ✅ | TSX, TSXV, Alpha: real-time L1/L2, historical back to 1998 | Feeds / licensed | n/a | The authoritative Canadian equity data source. Expect professional-subscriber fees for a corp or fund. [24] |
| **Finnhub** (data) | ❓ | ❓ | ❓ | Global fundamentals/news | REST | n/a | Not re-verified. Check commercial licence terms for the corp/fund. |
| **IBKR market data** | ✅ | ✅ | ✅ | Global, through exchange subscriptions | Via the API | n/a | Corp and fund users are usually classified "professional", which costs much more ❓. [4] |

### Markets reachable from Canada (via IBKR Canada)
TSX/TSXV/Cboe Canada and the Montréal Exchange (CA equities, options, futures); US (NYSE/Nasdaq/options/CME futures); Europe, UK, Asia-Pacific; FX. ✅ IBKR is CIRO-regulated and offers global access [1]. Per-exchange permissions for Canadian clients ❓ must be checked in Client Portal. Crypto: use CSA-registered platforms. Spot only at Kraken; derivatives generally unavailable to Canadian retail.

## 2. Regulatory notes by structure
**Personal account (Ontario resident)**
- Use only CIRO dealers and CSA-registered crypto platforms. Unregistered offshore venues are a compliance and counterparty risk. [14]
- CSA crypto rules (⚠️ summarized): retail purchase limits apply on non-"specified" crypto, and there's an appropriateness assessment. Stablecoin restrictions (e.g., USDT) are reflected in Kraken's blocklist. [18]

**Canadian corporation (holdco trading its own money)**
- No securities registration is needed to trade the corporation's own capital ⚠️ (dealer/adviser registration is triggered by doing it for others).
- Requires corporate KYC: articles, resolution, directors, ≥10% owners. [3]

**Private fund (pooled outside money)**
- In Ontario, whoever directs the fund's business usually needs **Investment Fund Manager** registration. Whoever makes investment decisions needs **Portfolio Manager (adviser)** registration. Whoever distributes units needs **Exempt Market Dealer** registration (or an exemption). All under NI 31-103. [25][26]
- Units are sold under NI 45-106 prospectus exemptions (accredited investor, minimum amount, offering memorandum where available). Ontario has its own specifics and Form 45-106F1 reports of exempt distribution ⚠️. [27][28]
- A narrow private investment club exemption exists (few members, no paid adviser) ⚠️. [26]
- Broker side: IBKR requires the HFA/FM master account to exist first, and cash sent to the HFA account can't be used to trade the fund. [3]
- **Implication for the bot:** running it for outside investors makes it a regulated portfolio-management tool. Expect audit-trail, KYC/suitability, best-execution, trade-allocation fairness and record-retention obligations (⚠️ 7 years typical under NI 31-103).

## 3. Canadian tax notes
- Capital gains inclusion rate is **50%** for 2026. Business income is 100% taxable. ✅ [29]
- **Business vs. capital:** CRA uses no bright-line test. Frequent, short-term, systematic trading with expertise and time spent points to business income, and **an automated bot strongly suggests business treatment** ⚠️. The same goes inside a TFSA, where business income is taxable. [29][30]
- **Superficial loss:** a loss is denied if you or an affiliated person (spouse, controlled corp, RRSP/TFSA) buys an identical property within 30 days before or after and still holds it on day 30. The denied loss is added to the ACB. This applies to crypto too. [31] Affiliation means a personal account and a holdco must be tracked **together**.
- **ACB:** Canada uses average cost per identical property across all accounts of the same taxpayer. Not FIFO.
- **Crypto:** crypto-to-crypto trades are taxable dispositions. Staking and rewards are income. [30]
- **Foreign property:** T1135 is required if the cost of specified foreign property is over CAD 100k at any time in the year (US shares count even when held at a Canadian broker; crypto on foreign platforms ❓ also likely counts).
- **US withholding:** file a W-8BEN (individual) or W-8BEN-E (corp/fund). The treaty rate is 15% on US dividends, and the foreign tax credit is claimed in Canada ❓.
- **Corporation:** passive investment income is taxed at high refundable rates (RDTOH), and AAII over $50k erodes the small business limit ❓. If trading is a business, active rates may apply ⚠️.
- **Fund:** usually a trust or LP. Mutual fund trust status, T3/T5013 and investor reporting ❓. Get specialist advice.
- Brokers issue T5008 slips. Crypto platforms' reporting varies, and CARF crypto reporting is coming ❓.

## 4. What the software must track
1. **Per-taxpayer, cross-venue ACB** (average cost, CAD) per identical property, covering personal + spouse + controlled corp + registered accounts.
2. **Superficial-loss engine:** a ±30-day window across all affiliated accounts. Optionally a pre-trade block or warning.
3. **CAD FX for every fill:** Bank of Canada daily rate (or the transaction-date rate), with the source stored.
4. **Venue/jurisdiction eligibility config:** per-venue allowed account types, asset blocklists (e.g., Kraken's Canada list), "no margin/derivatives" flags, and registration status with a last-verified date. Fail closed when status is stale (>90 days).
5. **Entity separation:** distinct ledgers per individual, corp and fund. For funds, trade allocation records (pre-trade allocation, fairness) and NAV per unit.
6. **Business-vs-capital evidence log:** holding periods and turnover, used for a CPA decision. TFSA trading flagged.
7. **Foreign property cost tracker** for the T1135 threshold. Withholding tax per dividend.
8. **Crypto events:** crypto-to-crypto swaps, fees paid in crypto, staking income, wallet transfers (non-taxable but must be linked).
9. **Immutable audit trail** (order → signal → risk decision → fill), retained ≥7 years. Exports in T5008/Schedule 3-compatible form.
10. **Data-licence classification** (pro vs. non-pro) per entity, so corp/fund use doesn't violate personal data plans (Massive, IBKR, TMX).

## 5. Actions for the existing plan (`review.md`)
- Keep IBKR as the live broker for everything. Alpaca stays paper-only. Re-check Alpaca after Nov 2026.
- Kraken: registration is verified, so it can be enabled behind an asset blocklist with spot-only flags. Fix the UI inconsistency either way.
- Coinbase: allowed, but flag its "interim relief" status.
- TSX data: Massive and Databento don't cover the TSX. Use IBKR feeds or TMX.
- A private fund requires registrations before taking outside money. Treat it as a separate phase that needs legal counsel.

## Sources
1. https://www.interactivebrokers.ca/en/accounts/account-guide.php
2. https://www.interactivebrokers.ca/en/accounts/hedge-fund.php
3. https://www.interactivebrokers.ca/en/accounts/hedge-fund-onboarding.php ; https://www.interactivebrokers.ca/en/general/what-you-need-adv.php
4. https://www.interactivebrokers.ca/en/accounts/trading-and-market-data.php
5. https://www.interactivebrokers.com/en/trading/products-cryptocurrencies.php
6. https://alpaca.markets/learn/live-trading-account-non-us
7. https://forum.alpaca.markets/t/is-the-market-data-subscription-available-in-canada/19519
8. https://www.questrade.com/api/
9. https://www.questrade.com/learning/using-questrade/connect-your-questrade-account-to-ai
10. https://snaptrade.com/brokerage-integrations/wealthsimple-api
11. https://open.moomoo.com/api/overview/api-reference
12. https://fcnb.ca/en/investing/high-risk-investments/crypto-assets-and-cryptocurrency/registered-crypto-asset-trading-platforms
13. https://developer.webull.com/apis/docs/
14. https://www.osc.ca/en/industry/registration-and-compliance/crypto-businesses
15. https://www.osc.ca/en/securities-law/orders-rulings-decisions/coinbase-canada-inc-and-coinbase-inc-0
16. https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/introduction
17. https://www.coinbase.com/en-ca/international-exchange
18. https://support.kraken.com/articles/where-is-kraken-licensed-or-regulated (updated Sep 30, 2026)
19. https://support.kraken.com/ca/articles/organizations-api-keys
20. https://lautorite.qc.ca/en/general-public/registers/cryptoasset-trading-platforms
21. https://www.autorites-valeurs-mobilieres.ca/plateformes-de-cryptoactifs-mesures-reglementaires-et-dapplication-de-la-loi/plateformes-de-cryptoactifs-autorisees-a-faire-affaire-avec-les-canadiens/
22. https://massive.com/knowledge-base/article/does-massive-offer-international-data
23. https://databento.com/equities ; https://roadmap.databento.com/b/n0o5prm6/feature-ideas/canadian-exchange-tsx-data
24. https://www.tmxinfoservices.com/market-data/real-time-data?lang=en
25. https://www.osc.ca/en/securities-law/instruments-rules-policies/3/31-103/unofficial-consolidation-companion-policy-31-103cp-registration-requirements-exemptions-and
26. https://www.asc.ca/-/media/ASC-Documents-part-1/Regulatory-Instruments/2026/01/6258976--31-103--NI-Consolidation-Eff-January-1-2026.pdf
27. https://www.osc.ca/sites/default/files/2025-12/ni_20251204_45-106_unofficial-consolidation.pdf
28. https://www.osc.ca/en/industry/companies/selling-securities-ontario/exempt-market
29. https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/t4037/capital-gains.html
30. https://www.canada.ca/en/revenue-agency/programs/about-canada-revenue-agency-cra/compliance/cryptocurrency-guide/income-crypto-transactions.html
31. https://www.canada.ca/en/revenue-agency/services/tax/individuals/topics/about-your-tax-return/tax-return/completing-a-tax-return/personal-income/line-12700-capital-gains/capital-losses-deductions.html
