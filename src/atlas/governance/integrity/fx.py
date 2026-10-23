"""Single offline indicative FX table (CAD per 1 unit). Both services previously kept their own
copies (USD 1.37 in both, but drift-prone). Live FX (Bank of Canada Valet) stays PROPOSED."""
STATIC_RATES_TO_CAD: dict[str, str] = {
    "CAD": "1", "USD": "1.37", "EUR": "1.49", "GBP": "1.74", "JPY": "0.0091", "HKD": "0.176", "AUD": "0.90",
    "BTC": "90000", "ETH": "3500", "USDC": "1.37",
}
