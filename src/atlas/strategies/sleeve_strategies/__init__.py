"""Strategy research round 2 (trading-bot-review/strategy-research-2.md), implemented in its
suggested order. Every item is a CHALLENGER only: it logs each experiment to the global trial log,
is scored with the Deflated Sharpe Ratio over ALL trials, and is registered in the model registry
(stage challenger). Nothing here can promote itself, place orders, or bypass the risk engine.

  1 cash_yield       idle cash -> cash-equivalent ETFs (policy-allowed instruments only)
  2 fx_cost          CAD<->USD route planner: IBKR spot vs Norbert's gambit (DLR/DLR.U)
  3 overlays         vol-managed exposure (down-only) + cash/risk trend switch
  4 timing           turn-of-month deployment window + open/close auction execution policy
  5 screens          SEDI insider-buying clusters, CIRO short-interest screen
  6 pead             PEAD / revisions (provider interface; paid data; fixture-tested)
  7 index_add        S&P/TSX Composite addition predictor
  8 crypto_factors   crypto TS/XS momentum + on-chain factors, vol-targeted, maker-only orders
  9 pairs            long-only pair switching (hold the cheaper leg)
 10 interlisted      TSX vs US line venue selection after FX + spread
 11 tlh              tax-loss harvesting, taxable accounts only, superficial-loss aware
 12 tax_location     account-location advice for dividends (report only)
"""
