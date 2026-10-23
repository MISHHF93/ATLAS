# Investor wallet vs Canadian and global banking standards: gap analysis and build plan

*Research date: 2026-10-17. Scope: `/workspace/trading-bot-app` (payments/ and the wallet in `payments/src/tradingbot_payments/wallet/`, plus console `wallet_api.py`). This is not legal, regulatory or tax advice; confirm scope with counsel and the partners.*

## Bottom line

**Architecture: aligned.** The wallet's architecture is already the one the rules favour: the platform never holds money. Subscriptions go to the fund administrator's trust account. Assets sit with the custodian and brokers in the fund's name. Payouts are released by the administrator, or by a payout-rail partner from its own trust account, after two approvals.

**Which regimes apply to us:**
- Most banking-system regimes (Payments Canada membership, Lynx/RTR participation, SWIFT, RPAA safeguarding, MSB registration) apply **to our partners, not to us**. That holds only if we keep it this way.
- What applies **directly**:
  - privacy law (PIPEDA, Quebec Law 25);
  - sanctions law (SEMA, JVCFOA, UN Act, Criminal Code). Every person in Canada must not deal with listed persons;
  - FINTRAC-grade record keeping where we act for a reporting entity (the dealer/EMD or the administrator);
  - security expectations that partners will impose (SOC 2 / ISO 27001-style controls, OSFI B-10/B-13 flow-down if a partner is federally regulated).

**What the code is missing is plumbing, not architecture:**
- Canadian account-number validation.
- A CAD business-day and holiday calendar. NAV and dealing dates currently fall on weekends and holidays.
- ISO 20022 statement parsing and payment-file generation (camt.053/054, pain.001/002).
- CPA-005 export.
- Sanctions-list screening of our own (currently a demo name set).
- FINTRAC record and report templates (LCTR, EFTR, Listed Person Property Report).
- Retention and deletion rules.
- Structured addresses (ISO 20022 / travel-rule ready).
- A data-residency and transfer register (Law 25).

**Top recommendations:**
1. A CAD business-day calendar plus Canadian bank-account validators (DPRN, institution, transit, account).
2. ISO 20022 camt.053/camt.054 parsing for custodian/trust reconciliation, and pain.001 generation with pain.002 parsing for payout instructions. Banks and administrators speak these formats now; Lynx has been ISO-only since Nov 2025.
3. Sanctions screening against the actual Canadian consolidated list (SEMA/JVCFOA XML), the UN list and OFAC (optional), with fuzzy matching and a review queue, as defence in depth on top of the administrator's screening.
4. A FINTRAC record-keeping module (records only, nothing filed) plus a 5-year retention policy.
5. Structured name and address capture (ISO 20022 hybrid or structured address) and a Law 25 transfer-impact register.
6. CPA-005 export (simulation) for EFT payouts by a bank partner.

---

## Summary table

| # | Standard / regime | Applies to us? | Current state in code | Gap → what to add | Priority |
|---|---|---|---|---|---|
| 1 | Payments Canada **Lynx** (RTGS, ISO 20022 only since 22 Nov 2025) | Via partner (bank / administrator sends wires) | `providers.RAILS["LYNX"]` placeholder; wallet payouts say "administrator EFT/wire" | Generate **pain.001** wire instructions with a full ISO party block (structured or hybrid address). Parse **pain.002** status and **camt.054** notifications | P1 |
| 2 | **ACSS / AFT, CPA Standard 005** (1464-byte A/C/D/Z records) | Via partner (bank AFT service); only if we hand the bank a payout file | None | **CPA-005 exporter** (C credit records, Z control totals, file-creation-number sequencing) plus a validator. Simulation, no transmission | P2 |
| 3 | **ISO 20022 AFT** (pacs.008/003/004/007) | Via partner (bank-to-bank) | None | Nothing for us; we map from pain.001 | — |
| 4 | **Real-Time Rail (RTR)** (launch Q4 2026, phased; Interac e-Transfer migration in 2027) | Via partner (Zum Rails/VoPay or a bank) | `RAILS["RTR"]` placeholder, "not yet generally available" | Keep as a disabled rail. Plan for ISO 20022 pacs.008-based instant payouts via a partner in 2027. Don't build now | P3 |
| 5 | **ISO 20022 corporate messages**: pain.001 (initiation), pain.002 (status), camt.053 (statement), camt.054 (debit/credit notification), camt.052 (intraday) | **Yes**: this is how our software talks to banks, custodians and administrators | Custodian adapter docstring mentions "BAI2 / CAMT.053"; the fake custodian returns JSON; payments `recon.py` takes CSV | **camt.053/054 parser** feeding the three-way recon. **pain.001 generator** and **pain.002 parser**. Fixtures and XSD-shape tests | **P1** |
| 6 | **Interac e-Transfer for Business** (bulk up to 10,000 payments per file, up to $25k each; Request Money; Autodeposit) | Via partner (Zum Rails/VoPay/bank) | `RAILS["INTERAC"]` cap of $3,000 (placeholder); fake rails only | Add a rail profile with partner-configurable limits. Keep the payee name match. Only to Autodeposit-registered addresses tied to the verified own-name account | P3 |
| 7 | **PAD, Payments Canada Rule H1** | Only if we **pull** subscriptions by PAD (we don't; investors push to trust) | None (push model) | If PAD is ever added: a PAD Agreement record with the Appendix II mandatory elements, 10-day pre-notification, recourse statement, confirmation. **Recommend keeping push-only** | P3 (avoid) |
| 8 | **SWIFT CBPR+ / ISO 20022** (MT/MX coexistence ended 22 Nov 2025; SR2026 payment changes incl. structured-address mandate **deferred**, update due by Dec 2026) | Via partner (bank) for non-CAD and foreign investors | Foreign investors are not modelled beyond `nonresident_withholding` | Capture **BIC** and **structured address** (town and country mandatory, the hybrid model). Validate BIC format | P2 |
| 9 | **SEPA** (SCT / SCT Inst; Verification of Payee mandatory from 9 Oct 2025) | Only for EUR payouts via a partner | None | IBAN validator (ISO 13616 mod-97). Keep VoP-style name-match result codes (Match / Close match / No match) in our own bank verification | P3 |
| 10 | **FedACH / Nacha** (2026 fraud-monitoring rules: phase 1 20 Mar 2026, phase 2 19 Jun 2026); Fedwire ISO 20022 since 14 Jul 2025 | Only for USD payouts to US accounts via a partner | USD exists in `RAILS["WIRE"]`; no ACH | ABA routing checksum validator. Rely on the partner. Nacha fraud-monitoring duties fall on originators/ODFIs | P3 |
| 11 | **Consumer-Driven Banking Act** (open banking; Royal Assent 26 Mar 2026; **Bank of Canada** oversees, not FCAC; draft regs Jun 2026, consultation to 26 Aug 2026; read access first, write access targeted mid-2027) | Possibly, as a *user* of accredited data providers (Plaid/Flinks) for bank verification | `BankVerification` protocol (Plaid/Flinks) disabled, plus a fake | Record consent (scope, purpose, expiry, revocation) for bank-data access. Prefer CDBA-accredited providers once the registry exists. No change to architecture | P2 |
| 12 | **FINTRAC / PCMLTFA**: KYC methods, LCTR ($10k cash, 15 days), EFTR (international EFT ≥ $10k, 5 working days), travel rule, Listed Person or Entity Property Report (SEMA/JVCFOA from 1 Oct 2025); Mar 2026 amendments (bigger penalties, "effective" compliance programs, universal enrolment coming) | **Via partner** (EMD/dealer and administrator are reporting entities). We must keep records good enough for them to rely on, and must never take cash | Wallet records administrator KYC/sanctions decisions (append-only). `fund.py` flags cash ≥ $10k as records only. No EFTR/LCTR templates; no retention policy; ID method not recorded | Record the **ID verification method** (photo ID+liveness / credit file / dual process / reliance) and its source. **FINTRAC record module** (receipt-of-funds, LCTR/EFTR candidate records, 24 h aggregation, deadlines), records only. **Retention ≥ 5 years**. Refuse cash outright | **P1** |
| 13 | **RPAA**: PSP supervision; safeguarding and operational-risk requirements in force since **8 Sep 2025** | **No**, while we never hold or transfer end-user funds. **Yes** for Zum Rails/VoPay (their trust accounts) | Architecture enforces no stored value, no P2P, no pooled operating account | Keep the boundary: tests already assert no money-moving routes. Add a **partner due-diligence record** (PSP registration status, safeguarding method) | P2 |
| 14 | **PIPEDA** (breach records kept 24 months; report real risk of significant harm) | **Yes** | AES-GCM vault for PII and bank data; masked display; minimal ID (last 4); audit log | **Breach register** (24 months under PIPEDA). Retention/destruction schedule. Access log for PII decrypts. DSAR export | **P1** |
| 15 | **Quebec Law 25** (PIA before transfers outside Québec; incident register ≥ 5 years; privacy by default) | **Yes**, if any investor is a Québec resident | `province` collected; no residency logic | **Transfer-impact register** (where each partner stores data). Privacy-by-default settings. Incident register 5 years. French-language notices | P1 (if QC investors) |
| 16 | **OSFI B-13** (tech and cyber, effective 1 Jan 2024) / **B-10** (third-party risk) | Not directly (we're not an FRFI). **Flows down** contractually from bank partners | Loopback-only console, step-up, CSRF, audit chain, kill switch, vault | Prepare a **controls matrix** mapped to B-13 domains (asset inventory, change management, IAM, crypto key management, incident response, resilience testing) for partner due diligence | P2 |
| 17 | **PCI DSS v4.0.1** (future-dated requirements mandatory since 31 Mar 2025) | **No**: no cards. Keep it that way (out of scope) | No card fields | Add a test that rejects PAN-like input in intake (Luhn 13–19 digits). If cards are ever needed, use hosted fields (SAQ A) | P3 |
| 18 | **SOC 2 Type II / ISO 27001** | Partners have them and will ask about ours | Partner `info()` lists names/docs only | Partner record: SOC 2/ISO certs, report dates, bridge letters. Our own control evidence (audit logs, access reviews) | P2 |
| 19 | **Account identifiers**: Canadian DPRN `0YYYXXXXX` (institution 3 digits + transit 5 digits); account 7–12 digits; IBAN (mod-97); BIC (8/11); ABA (checksum) | **Yes** (data quality before anything goes to a partner) | Fake bank verification returns institution/transit/account; no validation; institution names hard-coded for 6 banks | **Validators module**, plus the Payments Canada **financial institution numeric list** as a data file | **P1** |
| 20 | **CAD holiday calendar** (Payments Canada closure schedule; ACSS/Lynx closed on statutory holidays) | **Yes**: dealing dates, cut-offs, notice periods, settlement estimates, EFTR "working days" | `month_end()` = calendar month end (NAV dated **2026-09-30**, a system closure; 2025-08-31 was a Sunday). `manual.py` skips weekends only ("holidays NOT modelled") | **Business-day calendar** (Payments Canada closures, provincial overlays, US Fed calendar for USD). Dealing date = last business day. Payout value dates roll forward | **P1** |
| 21 | **Sanctions**: Canadian SEMA/JVCFOA consolidated list (XML), UN SC Consolidated List (XML), Criminal Code listed terrorist entities; OFAC SDN (XML) for USD/US nexus | **Yes, directly** (dealing prohibitions apply to everyone in Canada). The administrator screens too | Administrator decision recorded; fake uses a 1-name demo set | **Screening stub**: list loaders from **local fixture files** (no network in this build), name normalisation and fuzzy match, daily rescreen of investors and payees, hit review queue, block payouts on an open hit, Listed Person Property Report record | **P1** |

---

## Details by area

### 1. Payments Canada systems
- **Lynx** (high-value RTGS) fully moved to ISO 20022 MX on **22 Nov 2025** and introduced the PMPG **hybrid postal address** (town and country structured, the rest as lines). Its interbank portfolio is head.001, pacs.008, pacs.009 and pacs.004. Payments Canada publishes **corporate-to-bank guidelines** for pain.001.001.09, pain.002.001.10, camt.052/053/054.001.08.
  - https://www.payments.ca/lynx-achieves-full-adoption-iso-20022-messaging-standard-mx-and-implementation-hybrid-postal
  - https://www.payments.ca/bringing-data-rich-high-value-payments-canada-lynx-fully-adopts-iso-20022-standard
  - https://www.payments.ca/payment-resources/iso-20022
  - https://www.payments.ca/payment-resources/iso-20022/high-value-payment-system-lynx
- **ACSS/AFT** stays in place for batch EFT, payroll and PAD. CPA **Standard 005** files use fixed **1464-character** records:
  - A is the header and Z the trailer with control totals;
  - C (credit) and D (debit) records each pack up to six 240-character segments;
  - E/F are error corrections and I/J are returns;
  - the header carries the originator ID, a 4-digit file creation number, the creation date (0YYDDD) and the processing centre.
  - The ISO AFT mapping is C→pacs.008, D→pacs.003, E/F→pacs.007, I/J→pacs.004 and S→acmt.022, and adoption is market-driven (no mandated end date).
  - https://www.payments.ca/sites/default/files/standard005eng.pdf
  - https://help.treasurysoftware.com/hc/en-us/articles/360043085973-CPA-005-1464-Byte-Description-of-EFT-Record-Formats
  - https://x9ware.com/cpa005-file-format/
  - https://www.payments.ca/sites/default/files/2022-08/introduction_to_the_iso_aft_usage_guidelines_0.pdf
- **Real-Time Rail**: launch **Q4 2026** with initial direct-to-exchange participants. Interac e-Transfer clearing and settlement migration follows in Q1–Q2 2027. It is ISO 20022 with mandatory centralized fraud services. RTR rules and by-law took effect Q3 2026, and industry solution assurance testing began Q3 2026.
  - https://www.payments.ca/systems-services/payment-systems/real-time-rail-payment-system/testing-and-launch
  - https://www.payments.ca/canadas-real-time-rail-quarterly-update-jude-pinto-2026-q3
- **Applies to us:** via partner only. We are not a Payments Canada member and should not become one. **Code state:** RAILS placeholders (`providers.py`); no file formats. **Add:** pain.001/pain.002/camt.053/camt.054 (P1) and a CPA-005 export (P2), both simulation-only and file-based.

### 2. Interac e-Transfer for Business
Bulk disbursement takes up to 10,000 payments per file, with single payments up to **$25,000** subject to bank limits. Request Money and Autodeposit are available, and the e-Transfer API (v3.4) supports Money Request and Autodeposit with account-number routing.
- https://www.interac.ca/en/payments/business/send-receive-money-with-interac-e-transfer-for-business/
- https://innovation.interac.ca/interac-e-transfer-api-3-4/

**Applies:** via partner (Zum Rails/VoPay or a bank).

**Code:** an `INTERAC` rail with a placeholder $3,000 cap.

**Add:** partner-specific limit config. Allow payouts only to an Autodeposit recipient whose registered account matches the verified own-name account. P3.

### 3. Pre-authorized debits (Rule H1)
A PAD needs:
- a **Payor's PAD Agreement** with the Appendix II mandatory elements (account, category, fixed/variable amount, timing, cancellation, contact details, and the mandatory recourse statement);
- a confirmation, and **10 calendar days' pre-notification** for set-interval PADs;
- for sporadic PADs, authorization per debit.

Rule H1 amendments took effect 28 Apr 2025.
- https://www.payments.ca/sites/default/files/h1eng.pdf
- https://www.payments.ca/payment-resources/support-guides/business-guides/pre-authorized-debit
- https://www.payments.ca/rules-updates-2025

**Applies:** no. Our model is push-to-trust. **Recommendation:** keep it that way. PAD makes us, or the partner on our behalf, a payee with recourse exposure. If ever needed, the partner should be the PAD payee and we only store the agreement record.

### 4. Cross-border: SWIFT CBPR+, SEPA, US rails
- **SWIFT CBPR+:**
  - MT/MX coexistence for payment instructions **ended 22 Nov 2025**, and contingency or translation charges started 1 Jan 2026.
  - On **27 Aug 2026** Swift deferred all SR2026 payment changes, including the mandatory retirement of unstructured addresses. A new timeline is due **by December 2026**.
  - Non-payment parts of SR2026 move to 12 Jun 2027.
  - https://www.swift.com/standards/iso-20022/iso-20022-faqs/implementation
  - https://www.swift.com/insights/news/swift-accepts-community-request-extend-structured-address-migration-iso-20022-payment-messages
  - https://www.ingwb.com/en/service/payments-and-collections/swift-iso20022/faq-swift-iso-20022
- **SEPA:** the EPC Verification of Payee rulebook has been in force since 5 Oct 2025, and VoP has been mandatory for euro PSPs since **9 Oct 2025**. Name-match responses are Match / Close Match / No Match / Not possible.
  - https://www.europeanpaymentscouncil.eu/document-library/press-releases/verification-payee-scheme-rulebook-now-force
  - https://www.ecb.europa.eu/paym/retail/instant_payments/html/instant_payments_regulation.en.html
- **US:**
  - Fedwire moved to ISO 20022 on **14 Jul 2025**; FedNow uses pacs.008.
    - https://www.frbservices.org/resources/financial-services/wires/iso-20022-implementation-center/on-the-wire-iso-20022-newsletter/august-2025-iso-20022-newsletter
  - Nacha fraud-monitoring rules: phase 1 on **20 Mar 2026** and phase 2 on **19 Jun 2026**. New company entry descriptions (PAYROLL/PURCHASE) apply.
    - https://www.nacha.org/rules/risk-management-topics-fraud-monitoring-phase-1
    - https://www.nacha.org/rules/risk-management-topics-fraud-monitoring-phase-2
- **Applies:** via partner, and only if we pay out in EUR or USD or to foreign accounts.
- **Code state:** only CAD in the wallet; there's a `nonresident_withholding` term.
- **Add (P2/P3):**
  - BIC, IBAN and ABA validators;
  - structured or hybrid address capture now, so we're ready whatever Swift's new date is;
  - VoP-style three-level name-match results in place of today's binary `norm_name` equality, so close matches go to manual review instead of being hard-rejected.

### 5. Consumer-driven banking (open banking)
- The new **Consumer-Driven Banking Act** came via Bill C-15 (Budget 2025 Implementation Act, No. 1), with **Royal Assent on 26 Mar 2026**. It replaced the 2024 version (which came via C-69) and **moved oversight from FCAC to the Bank of Canada**.
- Proposed regulations were published 27 Jun 2026, with consultation to 26 Aug 2026. Accreditation provisions come into force first, and full implementation is within a year of final publication. Read access comes first; **write access (payment initiation) is targeted for mid-2027**.
  - https://laws-lois.justice.gc.ca/eng/acts/C-36.78/FullText.html
  - https://gazette.gc.ca/rp-pr/p1/2026/2026-06-27/html/reg3-eng.html
  - https://www.dlapiper.com/en-us/insights/publications/2026/04/the-new-consumer-driven-banking-act-explained
  - https://www.nortonrosefulbright.com/en-ca/knowledge/publications/83263b6e/open-banking-in-canada-key-insights-into-the-proposed-regulations
- **Applies:** indirectly. Bank verification through Plaid/Flinks would migrate to accredited channels.
- **Code:** disabled Plaid/Flinks adapters and a fake.
- **Add:** a consent ledger (scope, purpose, granted/expires/revoked, provider, accreditation ID placeholder). Prefer accredited providers once the Bank of Canada registry is published. P2.

### 6. FINTRAC / PCMLTFA
- **Reports:**
  - **EFTR** for international EFTs of $10,000 or more (24 h aggregation), within **5 working days**. Domestic direct deposit and PAD are excluded from the EFT definition.
  - **LCTR** for $10,000 or more in cash (24 h rule), within **15 calendar days**.
  - **Travel rule:** originator and beneficiary name, address and account number travel with EFTs.
  - A **Listed Person or Entity Property Report** covers property of persons listed under the UN Act, the Criminal Code and (from **1 Oct 2025**) SEMA/JVCFOA, reported *immediately*.
  - https://fintrac-canafe.canada.ca/guidance-directives/transaction-operation/eft-dt/eft-dt-eng
  - https://fintrac-canafe.canada.ca/guidance-directives/transaction-operation/lctr-doie/lctr-doie-eng
  - https://fintrac-canafe.canada.ca/guidance-directives/transaction-operation/travel-acheminement/1-eng
- **KYC methods:**
  - government-issued photo ID (authenticated, e.g. with document and liveness);
  - credit file (at least 3 years old);
  - dual process;
  - affiliate/member;
  - reliance (written agreement with another reporting entity).
  - https://fintrac-canafe.canada.ca/guidance-directives/client-clientele/guide11/11-eng
- **2026 changes:** the Strengthening Canada's Immigration System and Borders Act (Royal Assent 26 Mar 2026):
  - higher administrative penalties and compliance orders;
  - compliance programs must be "reasonably designed, risk-based and effective";
  - an anonymous-client prohibition;
  - **universal enrolment** for all reporting entities, pending regulations.
  - Beneficial-ownership discrepancy reporting has applied since 1 Oct 2025.
  - https://fintrac-canafe.canada.ca/businesses-entreprises/changes-changements-eng
- **Who carries the duty:** securities dealers, including EMDs, are reporting entities.
  - https://fintrac-canafe.canada.ca/re-ed/sec-eng
- **Applies:** via partner (EMD/dealer and administrator). We are not an MSB **as long as we never transmit funds**.
- **Code:**
  - administrator decisions recorded in an append-only table;
  - `fund.py` flags cash ≥ $10k (records only);
  - wallet subscriptions are EFT/wire into trust; there is no cash path;
  - no EFTR/LCTR or property-report records;
  - no retention rule;
  - the ID method is free text from the administrator ("passport document + liveness (SIMULATED)").
- **Add (P1):**
  - a structured `kyc_method` enum plus source/reliance fields;
  - a record-only `fintrac.py` with receipt-of-funds records, an EFTR-candidate detector (international, ≥ $10k, 24 h aggregation, working-day deadline from the holiday calendar), LCTR-candidate detection (cash is refused anyway), and Listed Person Property Report drafts on a confirmed sanctions hit;
  - 5-year retention, with deletion blocked while a hold applies.

### 7. RPAA (retail payments)
PSP supervision is live. **Safeguarding and operational-risk/incident requirements have been in force since 8 Sep 2025**. End-user funds held must be in a trust account, or a segregated account plus insurance or a guarantee.
- https://www.bankofcanada.ca/2025/09/payment-service-providers-are-now-under-supervision-registry-to-follow/
- https://www.bankofcanada.ca/regulatory-oversight/retail-payments/supervisory-framework/

**Applies:** not to us, while the platform holds no funds and only gives instructions to regulated partners (confirm with counsel). It does apply to Zum Rails/VoPay.

**Code:** the boundary is enforced (no stored value, no P2P, no pooled account; tested).

**Add:** a partner due-diligence register with RPAA registration status and safeguarding model, reviewed annually. P2.

### 8. Privacy: PIPEDA and Quebec Law 25
- **PIPEDA:** record **every** breach of security safeguards and keep the record **24 months**; report breaches with a real risk of significant harm.
  - https://www.priv.gc.ca/en/privacy-topics/privacy-for-businesses/privacy-breaches-at-your-business/gd_pb_201810/
- **Law 25:**
  - a privacy impact assessment and written agreement before transferring personal information **outside Québec** (s. 17);
  - a confidentiality-incident register kept **≥ 5 years**;
  - privacy by default.
  - https://www.legisquebec.gouv.qc.ca/fr/version/lc/P-39.1?code=se%3A17&langCont=en
- **Applies:** yes.
- **Code:** AES-GCM vault (row- and purpose-bound AAD) with the key from env, masked display, minimal ID data (last 4), audit log. There is no breach or incident register, retention schedule, PII-access log, DSAR export, residency map or key rotation (`key_id` exists, but no rotate command).
- **Add (P1):** an incident register (5 years, which satisfies both laws), a retention schedule that reconciles FINTRAC's 5-year minimum with Law 25 destruction, a PII decrypt access log, a DSAR export, a data-location register per partner, and vault key rotation.

### 9. Security frameworks: OSFI B-13 / B-10, SOC 2, ISO 27001, PCI DSS
- **OSFI B-13** (effective 1 Jan 2024) and **B-10** apply to FRFIs, but banks and trust companies push them down onto vendors.
  - https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/technology-cyber-risk-management
  - https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/third-party-risk-management-guideline
- **PCI DSS v4.0.1:** the future-dated requirements became mandatory 31 Mar 2025.
  - https://blog.pcisecuritystandards.org/important-updates-announced-for-merchants-validating-to-self-assessment-questionnaire-a
- **Applies:** B-13/B-10 and SOC 2/ISO 27001 apply contractually via partners. PCI does **not** apply (no cards).
- **Code:** strong local controls already exist (loopback-only, step-up TOTP, CSRF/origin checks, append-only audit, two-person approval, kill switch, vault).
- **Add:**
  - a controls matrix mapping our controls to B-13 domains and SOC 2 trust criteria, for partner questionnaires (P2);
  - a partner certification register (P2);
  - a PAN-detection guard (Luhn) at intake, so card data can't enter by accident (P3).

### 10. Identifiers and calendars
- **Canadian routing:**
  - the electronic DPRN is **`0YYYXXXXX`** (leading 0, 3-digit institution, 5-digit transit);
  - MICR is `XXXXX-YYY`;
  - Payments Canada publishes the financial-institution numeric list;
  - account numbers are institution-specific (typically 7–12 digits).
  - https://www.payments.ca/sites/default/files/f8eng.pdf
  - https://www.payments.ca/sites/default/files/2025-06-27-Banks_Numeric_List.pdf
- **CAD calendar:** Payments Canada systems close on weekends and statutory holidays. **2026 closures:** Jan 1, Apr 3, May 18, Jul 1, Sep 7, **Sep 30**, Oct 12, Nov 11, Dec 25, Dec 28 (Boxing Day observed).
  - https://www.payments.ca/system-closure-schedule
- **Code gaps:**
  - `partners.month_end()` uses the calendar month end, so the demo's latest NAV is dated a system-closure day (2026-09-30);
  - `manual.next_business_day` ignores holidays;
  - there is no institution, transit or account validation, and only 6 hard-coded bank names.
- **Add (P1):** `calendars.py` (Payments Canada closures as data, yearly update, US Fed holidays for USD) and `bankids.py` (DPRN/MICR conversion, institution list, IBAN mod-97, BIC regex, ABA checksum).

### 11. Sanctions
- **Lists:**
  - **Canadian:** the Consolidated Canadian Autonomous Sanctions List (SEMA and JVCFOA) in XML; UN Act listings via the UN Security Council Consolidated List (XML); the Criminal Code listed terrorist entities.
  - **US:** OFAC SDN and consolidated lists in XML, relevant for USD and US-person nexus.
  - FINTRAC's listed-person definition expanded to SEMA/JVCFOA on 1 Oct 2025.
  - https://www.international.gc.ca/world-monde/international_relations-relations_internationales/sanctions/consolidated-consolide.aspx?lang=eng
  - https://open.canada.ca/data/en/dataset/ab076f2e-94b1-4039-bb3d-58002deb826d
  - https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
  - https://sanctionslist.ofac.treas.gov/Home/SdnList
- **Applies:** **yes, directly**, in addition to the administrator's screening.
- **Code:** only the administrator's decision, with a single demo name.
- **Add (P1):**
  - a `screening.py` that loads list files from a local directory. There is no download in this build; fixtures go under `tests/fixtures/sanctions/`, and in production an operator drops the files in.
  - name normalisation (diacritics, ordering, aliases) with token and Jaro-Winkler fuzzy scoring;
  - DOB and country as secondary keys;
  - a list-version hash in each result;
  - screening of investors at onboarding and payees/beneficial owners at every payout, plus a daily rescreen;
  - a hit queue with two-person disposition;
  - payouts and subscriptions blocked on an open hit;
  - a property-report draft record on a confirmed hit.

---

## Concrete build plan (simulation-safe, offline, no network, no secrets)

All items are pure functions or local files with fixture tests. They do not change the "never holds money" boundary and add no transmission code. Each piece is one commit with explicit paths.

| Step | Module (payments/src/tradingbot_payments/…) | What | Tests |
|---|---|---|---|
| 1 | `banking/calendars.py` + `data/cad_holidays.json` | Payments Canada closure dates for 2025–2027 (as data, with source URL and as-of date). `is_business_day`, `add_business_days`, `last_business_day_of_month`. US Fed holidays for USD | NAV/dealing dates never fall on closures; 2026-09-30 → 2026-09-29; Boxing Day observed |
| 2 | Wire it in: `wallet/partners.month_end` → business-day month-end; `manual.next_business_day`; recon "as of" dates | Dealing, cut-off, notice and value dates use the calendar | Existing wallet tests updated; notice/lockup on business days |
| 3 | `banking/bankids.py` + `data/fi_numeric_list.csv` | DPRN `0YYYXXXXX` ↔ MICR `XXXXX-YYY`; institution lookup; account-length rules; IBAN mod-97; BIC; ABA checksum; Luhn PAN detector (reject at intake) | Valid/invalid vectors; bank verification rejects malformed accounts; PAN refused |
| 4 | `banking/iso20022/camt.py` | Parse **camt.053.001.08** (statement) and **camt.054.001.08** (notification) into normalised lines (booking/value date, amount, CdtDbtInd, EndToEndId, remittance `Ustrd`/`Strd` reference) | Fixture XML (synthetic). The SUB- reference is extracted; wallet recon consumes the camt lines instead of fake JSON |
| 5 | `banking/iso20022/pain.py` | Generate **pain.001.001.09** for redemption and non-fund payouts (group header, PmtInf, CdtTrfTxInf, EndToEndId = payout idem key, hybrid/structured addresses, Canadian clearing system member ID `CACPA` + DPRN). Parse **pain.002.001.10** status (ACCP/ACSC/RJCT + reason codes) | Well-formedness and namespace checks; optional XSD validation if schemas are provided locally; reject statuses map to `release_error` |
| 6 | `banking/cpa005.py` | **CPA-005** credit-file writer (A/C/Z, 1464-char records, ≤ 6 segments per record, file creation number sequence, 0YYDDD dates, control totals) plus a reader/validator. Output marked SIMULATION, written to `var/`, never transmitted | Record lengths, totals, round-trip parse, sequence monotonicity |
| 7 | `compliance/screening.py` + fixtures | Load Canadian consolidated (SEMA/JVCFOA) XML, UN XML and OFAC SDN XML **from local files**. Normalise and fuzzy-match. Hit queue with two-person disposition. Block payout/subscription on an open hit. Daily rescreen job. Record list version and hash | True/false-positive vectors; alias and diacritics; payout blocked; disposition audited |
| 8 | `compliance/fintrac.py` | Record-only: receipt-of-funds records, EFTR candidates (international ≥ $10k, 24 h aggregation, due = +5 working days via the calendar), LCTR candidates (and refuse cash), Listed Person Property Report draft, travel-rule completeness check (name/address/account for both parties) | Aggregation windows, deadlines over holidays, nothing filed (no network), completeness errors |
| 9 | `wallet/service.py` additions | Structured address (street, town, province, postcode, country); `kyc_method` enum + reliance source; VoP-style name-match result (match/close/no) with close → manual review; consent ledger for bank-data access (CDBA-ready) | Migrations; close-match review path; consent revoke blocks re-fetch |
| 10 | `compliance/privacy.py` | Retention schedule (FINTRAC 5 y vs Law 25 destruction), legal hold, PII decrypt access log, DSAR export (JSON/PDF), incident register (5 y), data-location/transfer register per partner, vault key rotation command | Retention dry-run report; rotation re-encrypts and old key refused; DSAR includes only the subject's data |
| 11 | Console | Wallet tabs for "Compliance" (screening queue, FINTRAC records, incidents) and "Files" (download pain.001 / CPA-005 SIM files, upload camt.053 for recon); step-up on dispositions | API tests (roles, step-up, no transmission route) |
| 12 | Docs | Controls matrix (B-13 / SOC 2), partner due-diligence register (RPAA status, SOC 2/ISO dates, safeguarding model), README updates | — |

**Out of scope on purpose:**
- live connectivity to banks, Payments Canada, SWIFT, Interac, Plaid/Flinks or sanctions-list URLs;
- PAD origination;
- card acceptance;
- Payments Canada membership or RPAA registration. These are avoided by the architecture, so confirm with counsel before changing it.

## Open questions for counsel and partners
1. Confirm that instructing the administrator or a PSP (without touching funds) keeps us outside RPAA and MSB scope.
2. Which entity is the FINTRAC reporting entity for these investors (EMD vs administrator)? What reliance agreement is needed, and what records must we keep for it?
3. Which formats do the chosen custodian, administrator and bank accept: camt.053 v08 vs BAI2; pain.001 v09 vs CPA-005 vs a portal upload?
4. Do we have, or expect, Québec-resident investors (French documents, Law 25 PIA)?
5. Should we screen against OFAC as well as the Canadian and UN lists? This depends on US-person staff, USD flows and the partners' requirements.
