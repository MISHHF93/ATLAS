"""Investor wallet: SIMULATION ONLY (see wallet-research.md, "Recommended architecture").

The platform NEVER holds investor money. The "wallet" is a read-only view of balances held by regulated
partners: the fund administrator / custodian (subscription trust account, fund custody and broker accounts in
the fund's name) and, optionally, a payments partner's trust account (Zum Rails / VoPay) for non-fund payouts.

* partners.py: adapter interfaces (FundAdministrator, Custodian, PayoutRail, BankVerification). The real adapters
  are DISABLED and have no network code. Offline fakes simulate the partners' systems in their own SQLite file.
* service.py: onboarding (the app collects data; KYC / eligibility / suitability / sanctions decisions come FROM
  the administrator or dealer and are only recorded), bank verification (payouts only to a verified account in
  the investor's own name), subscriptions (pay the administrator's trust account directly, using a reference ID;
  units are issued at the administrator's next NAV), redemptions (notice / lockup / gate terms; the administrator
  processes them), and payout requests (two-person approval).
* recon.py: daily three-way reconciliation (internal unit ledger <-> administrator register/NAV <-> custodian
  statements) producing a breaks report.
* vault.py: AES-GCM vault for bank details. The key comes from the environment; values are displayed masked.
* portal_auth.py: investor portal logins (a separate role: passphrase + TOTP step-up).
There are no stored-value balances, no P2P transfers, no pooled operating-company account and no crypto custody.
"""
