# European Central Bank Data Portal (`ecb_fx`)

- **Adapter:** `src/atlas/feeds/providers/ecb.py` (`ECBFXAdapter`)
- **Cost & Terms:** Free, keyless official API (`https://data.ecb.europa.eu/help/api/data`).
- **Primary Endpoint:** `https://data-api.ecb.europa.eu/service/data/EXR/D.{ccy}.EUR.SP00.A?format=jsondata&startPeriod=YYYY-MM-DD&endPeriod=YYYY-MM-DD`
- **Fallback Endpoint:** `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml`
- **TLS Handling:** Uses `data-api.ecb.europa.eu` (replacing the retired `sdw-wsrest.ecb.europa.eu` host that previously failed TLS), with automatic `certifi` CA bundle fallback in `ecb_transport` on `ssl.SSLError` and static XML failover.
- **Coverage:** Daily (`1d`) euro reference rates (`EUR_USD`, `EUR_CAD`, `EUR_GBP`, `EUR_JPY`, `EUR_CHF`, plus cross-rate `USD_CAD = CAD / USD`).
- **Rate limit:** No published hard cap; ATLAS rate-limits to `1 req/s`.

