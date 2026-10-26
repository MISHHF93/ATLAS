# Bank of Canada Valet (`boc_valet`)

- **Adapter:** `src/atlas/feeds/providers/boc.py` (`BankOfCanadaFXAdapter`)
- **Cost & Terms:** Free, keyless official API (`https://www.bankofcanada.ca/terms/`).
- **Endpoint:** `https://www.bankofcanada.ca/valet/observations/{series}/json?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`
- **Coverage:** Daily (`1d`) FX reference rates published around 16:30 ET (`FXUSDCAD` wired to `USD_CAD` and inverted for `CAD_USD`; `FXEURCAD` for `EUR_CAD`).
- **Rate limit:** No published hard cap; ATLAS rate-limits to `1 req/s`.

