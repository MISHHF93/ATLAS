# In-app wallet + payouts for a private fund/platform (Ontario): regulation, partners, architecture
_Written 2026-10-17. Research only, not legal advice. **[V]** = URL returned HTTP 200 and/or content checked on 2026-10-16/17. **[U]** = unverified (from general knowledge; confirm with the vendor or a lawyer). Fees change, so quote from vendor contracts._

## Bottom line
Do **not** build a wallet in which the platform holds user money. Three separate regimes would apply at once:
- **Bank of Canada payment service provider (PSP) supervision** under the Retail Payment Activities Act (RPAA).
- **Federal money-laundering law:** FINTRAC money services business (MSB) registration under the Proceeds of Crime (Money Laundering) and Terrorist Financing Act (PCMLTFA).
- **Ontario securities law:** investment fund manager (IFM), dealer and portfolio-manager registration, plus custody rules.

Investor money should sit with a **qualified custodian / fund administrator** under the fund's name. Non-fund payouts should go through a licensed payments partner holding money in trust. The app shows a **ledger "wallet" view** (balances read from the administrator or partner), not stored value. The biggest blocker is not payments. **Running an autonomous trading bot on other people's money in a pooled fund requires OSC registration (IFM + portfolio manager, plus an exempt market dealer or a registered dealer for distribution).** Do that first, with securities counsel.

## 1. Canadian regulation

**Retail Payment Activities Act (Bank of Canada).** The registration window opened 1–15 Nov 2024; risk-management and **safeguarding requirements have applied since 8 Sep 2025** [V]. If you hold end-user funds you must either keep them in trust, or keep them in a segregated account backed by insurance or a guarantee. You also need a dedicated safeguarding account, a written framework, reconciliation, and an independent review every 3 years [V]. Operating without having applied is a violation that can carry administrative penalties [V]. A new entrant must apply **before** operating; the national-security screening takes months [U on timing]. Exclusions include payment activities by banks and other prudentially regulated entities, and some activities incidental to another regulated service. Whether fund flows run by a registered securities firm are out of scope needs a legal opinion [U].
- https://www.bankofcanada.ca/regulatory-oversight/retail-payments/supervisory-framework/ [V]
- https://www.bankofcanada.ca/wp-content/uploads/2024/02/safeguarding-end-user-funds.pdf [V]
- https://www.bankofcanada.ca/regulatory-oversight/retail-payments/psp-registry/ [V]

**FINTRAC / PCMLTFA.** Transferring funds for others, or dealing in virtual currency, makes you an MSB. That means registration, a compliance program (officer, policies, risk assessment, training, a two-year effectiveness review), identity verification, record keeping, and reports: suspicious transactions, large cash and large virtual-currency transactions (≥$10k), and international EFTs (≥$10k). Securities dealers are separate reporting entities with similar duties [V for the MSB page; thresholds U].
- https://fintrac-canafe.canada.ca/msb-esm/msb-eng [V]
- KYC methods (government photo ID authenticated with document plus liveness technology, credit-file method, or dual-process): https://fintrac-canafe.canada.ca/guidance-directives/client-clientele/Guide11/11-eng [V]

**Travel rule:** originator and beneficiary information must travel with EFTs and virtual-currency transfers of $1,000 or more. Unhosted-wallet transfers need extra steps [U; FINTRAC's "travel rule" URL moved, so search fintrac-canafe.canada.ca].

**Sanctions:** screen every user and counterparty, at onboarding and continuously, against the lists under the Special Economic Measures Act, the Justice for Victims of Corrupt Foreign Officials Act (Magnitsky) and the Criminal Code terrorist listings (Global Affairs Canada consolidated list [U: the gc.ca page timed out from the box]). Also screen for politically exposed persons and heads of international organizations (PEP/HIO), and check beneficial ownership for corporate investors. Partners such as Stripe or Zum Rails screen their own customers, but that **does not** discharge the platform's duties if the platform is itself a reporting entity [U].

**Securities (Ontario / National Instruments):**
- Managing a pooled fund requires **IFM registration** (OSC; NI 31-103) [V instrument page]. Making the trading decisions requires **portfolio manager (adviser)** registration, and an algorithm doesn't remove that requirement. Selling units requires an **exempt market dealer** (or another dealer) using NI 45-106 exemptions: accredited investor, offering memorandum, or minimum amount. A Form 45-106F1 report is due within 10 days of each distribution [U].
- **Custody:** NI 31-103 Part 14 Division 3 requires client and fund assets to be held by a **qualified custodian** (a Canadian bank or trust company, or a qualified dealer), separate from the registrant's own assets [U on section numbers]. https://www.osc.ca/en/securities-law/instruments-rules-policies/3/31-103 [V]
- Subscription money must go to the fund (or to the dealer's or administrator's trust account), never to an app operator's general account.
- Crypto: if the app holds crypto for users, it becomes a crypto trading platform needing CSA/CIRO registration (CSA Staff Notice 21-327 and the pre-registration undertaking regime) [U]. Keep crypto inside the fund's custodial accounts at Kraken or Coinbase.
- **Ontario specifics:** the OSC is the regulator (https://www.osc.ca/en [V]). The OM exemption has been available in Ontario since 2016 with investment caps for non-eligible investors [U]. An Ontario corporation also brings payroll and tax registrations. FSRA is not relevant unless you add insurance or mortgage products [V for the site].

## 2. Partner options

| Partner | What it does | Canada? | Who holds funds | KYC included | APIs / fees | Fit |
|---|---|---|---|---|---|---|
| **Stripe Connect** | Marketplace payments with payouts to connected accounts | Yes, CAD payouts [V docs] | Stripe (its licensed entity) | Yes, for connected accounts | Connect API; fees on the pricing page [V] | **Poor.** Stripe's restricted-businesses list puts "Investment and brokerage services", "money transmitters… and other MSBs", "peer-to-peer money transmission", escrow and third-party stored value behind sales approval or prohibition [V, checked 2026-10-17]. Fine for platform subscription fees, not investor money. https://stripe.com/legal/restricted-businesses |
| **Wise Platform / Business API** | Multi-currency accounts, FX, payouts | Yes [V site] | Wise (an MSB, safeguarded) | Wise does KYC on its own customers | REST API; https://wise.com/ca/pricing/business [V] | Good for **the business's own** FX and payouts. Embedding it for end users needs a partnership agreement; investment use is likely restricted [U]. |
| **Adyen for Platforms** | Platform payments and accounts | Available in CA [U for full balance-platform support] | Adyen (licensed in the EU and UK; acquiring licence in Canada [U]) | Yes | https://docs.adyen.com/platforms/ [V]; sales-led and enterprise-sized | Overkill. Investment use needs approval [U]. |
| **Zum Rails** | EFT, Interac e-Transfer, card, and wallet "funding" via API; KYC add-on | Canadian [V site] | Zum Rails in trust/FBO at a sponsor bank [U] | Optional ID verification [U] | https://docs.zumrails.com/ [V]; pricing not public [U] | **Strong** for non-fund payouts and collections. Confirm it will service investment flows. |
| **VoPay** | EFT, Interac e-Transfer, RTR-ready, virtual accounts | Canadian [V] | VoPay in trust at its banking partner [U] | Via partners | https://docs.vopay.com/ [V]; https://vopay.com/pricing/ [V] | Strong; similar to Zum Rails. |
| **Rotessa** | Pre-authorized debit (PAD) collection | Canada/US [V] | Rotessa then settles to you | Light | https://www.rotessa.com/pricing/ [V] | Collections only (e.g., recurring subscriptions into the fund's trust account). Not for payouts or wallets. |
| **Peoples Group / Peoples Trust** | Sponsor bank (trust company) for fintechs: EFT, Interac, BIN sponsorship | Yes [V] | Peoples Trust (CDIC member) | Bank-grade, via the program | https://www.peoplestrust.com/en/business/ [V] | Sits behind many fintechs; you'd only go direct at scale. |
| **Paytrie** | CAD↔stablecoin (USDC/USDT) on/off-ramp | Canadian MSB [U] | Paytrie | Yes | https://paytrie.com/ [V] | Only for crypto ramps. High regulatory sensitivity; avoid for investor money. |
| **Plaid / Flinks** | Bank account verification (account and transit number, ownership, balance) | Plaid and Flinks both cover CA banks [V sites] | Don't hold funds | Account ownership only | https://plaid.com/docs/auth/ [V], https://flinks.com/ [V] | **Use one** to verify the payout account belongs to the KYC'd investor (anti-fraud, travel-rule data). |
| **Interac e-Transfer for Business** | Bulk send and request-money | Through participating FIs or processors (Zum Rails, VoPay) [U] | The FI | The FI | https://www.interac.ca/en/business/ [V] | Fast payouts up to per-transaction limits (often $10k–$25k [U]). |
| **Payments Canada Real-Time Rail (RTR)** | 24/7 ISO 20022 instant payments | **Launch Q4 2026** with first direct participants; Interac migration Q1–Q2 2027; full capacity Q3 2027 [V, Payments Canada and BetaKit Oct 2026]. Big banks likely not in phase 1 [V BetaKit] | — | — | Access via a participant or processor | Plan for 2027; don't depend on it now. https://www.payments.ca/systems-services/payment-systems/real-time-rail-payment-system/testing-and-launch |
| **Fund administrator + custodian** (SGGG Fund Services, CIBC Mellon; others: SS&C, Citco, NAV, Apex [U]) | Investor register, KYC/AML on subscribers, NAV calculation, subscriptions and redemptions, trust bank accounts, Fundserv | SGGG is a Toronto emerging-manager specialist [V site]; CIBC Mellon is institutional with high minimums [V site] | **The fund's custodian / administrator trust account** | Yes (investor AML is typically delegated to the administrator) | Pricing not public; basis points of AUM plus minimums [U] | **Core of the solution** for investor money. https://www.sggg.com/ , https://www.cibcmellon.com/ , https://www.fundserv.com/ [V] |

## 3. Recommended architecture

**Principle:** the operating company never holds client money. Each money pool has a regulated holder:
- Fund capital: the fund's custodian bank and broker accounts (IBKR, Kraken/Coinbase institutional accounts in the fund's name).
- Subscription and redemption cash in transit: the administrator's or dealer's trust account.
- Any non-investment user balances (e.g., referral rewards): a PSP partner's trust/FBO account.

**Flows**
1. **Onboarding:**
   - App collects the data.
   - Dealer or administrator performs KYC, the accredited-investor or OM eligibility check, the suitability/KYP assessment (a dealer duty), sanctions/PEP screening and beneficial ownership.
   - Plaid or Flinks verifies the bank account in the investor's name.
2. **Deposit / subscription:**
   - The investor sends an EFT, wire or PAD (Rotessa or the administrator's own) directly to the **fund's subscription trust account**, with a reference ID.
   - The administrator matches the payment, issues units at the next NAV and sends a confirmation. The dealer files the 45-106F1.
   - The app shows "pending → units issued" by reading the administrator's API or files.
3. **Investing:** the custodian moves cash to the fund's broker accounts. The trading bot only ever has *trading* permissions there, never withdrawal rights.
4. **Redemption:**
   - The investor submits a request in the app, which is forwarded to the administrator. Apply notice periods, gates and lockups from the OM.
   - The administrator calculates NAV, deducts fees and withholdings, and pays **only to the verified bank account in the investor's name** (no third-party payouts). Payment goes by EFT or wire now, Interac or RTR later.
5. **Non-fund payouts** (if any): a Zum Rails or VoPay payout from the partner's trust account. The partner is the PSP/MSB; contract terms must allow your use case.

**Reconciliation (daily; build this):**
- **Three-way match:** internal ledger ↔ administrator investor register / NAV ↔ custodian bank and broker statements. Add partner payout reports where used.
- Use a double-entry ledger with immutable entries, idempotency keys and alerts on breaks.
- Daily "units × NAV" against the investor statements; monthly independent check by the auditor.

**Build vs partner**
- *Partner provides:* KYC/AML on investors, custody, trust accounts, NAV, unit register, tax slips (T3/T5013 and NR4, depending on fund structure [U]), payment rails, sanctions screening.
- *App builds:*
  - UX and the read-only wallet view.
  - Secure document exchange.
  - Request workflows (subscribe, redeem, change bank account, with step-up authentication).
  - The internal ledger and reconciliation.
  - Audit logs and role-based access (no human or bot can move money alone; two-person approval).
  - Communications archive.
  - Integration with the administrator (often SFTP/CSV rather than API [U]).
- *Do not build:* stored-value balances, peer-to-peer transfers, pooled omnibus accounts in the operating company, internal crypto custody.

## Next steps
1. Securities counsel: fund structure (LP vs trust), IFM/PM/EMD registration, or partnering with an existing registered manager as a sub-adviser or platform (fastest route [U]).
2. RFPs to fund administrators (SGGG and 1–2 others): request pricing, API/file specs and AML delegation terms.
3. Only if non-fund payouts are needed: Zum Rails or VoPay compliance review. Ask explicitly whether they will support investment-adjacent flows.
4. Legal opinion on RPAA and FINTRAC scope for whatever the app ends up touching.
