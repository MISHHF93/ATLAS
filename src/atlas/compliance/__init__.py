"""Compliance tooling (SIMULATION / OFFLINE, records only):
* lists.py / matching.py / screening.py: sanctions screening against the Canadian Consolidated Autonomous Sanctions
  List (SEMA / JVCFOA), the UN Security Council Consolidated List and OFAC SDN, loaded from LOCAL files (the owner
  downloads them with tools/fetch_sanctions_lists.py); fuzzy name matching; two-person hit review; payouts and other
  money movement blocked while a hit is open or confirmed.
* fintrac.py: FINTRAC record-keeping (LCTR / EFTR / LVCTR / listed-person property records, travel-rule fields,
  ID-verification method records), deadlines on the business-day calendar, 5-year retention. Nothing is filed.
No network I/O anywhere in this package."""
