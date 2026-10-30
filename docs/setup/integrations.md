# Setting up ATLAS integrations

ATLAS is **paper trading only**. Alpaca is now optional: it does not serve Canadian residents, so the default stock/ETF source is Massive (free, email signup;
see `docs/data/canada-sources.md`). Pick the primary with `ATLAS_STOCK_PROVIDER` (`polygon` default, `alphavantage`, `questrade`, `alpaca`). The Alpaca adapter talks only to `https://paper-api.alpaca.markets`, refuses the live
endpoint, and refuses any account whose number does not start with `PA`. Every order goes through the control plane
first (`ActionableControlPlaneEngine.submit_order`), and research/ML output keeps `execution_permission: none`.

## How it works

1. Copy `.env.example` to `.env` in the repo root (`.env` is gitignored). Every key starts blank.
2. Add a key and save (Settings → Setup). A blank key means that service reads **Needs verification** and stays off; nothing else breaks. No key is ever set for you.
   Press **Verify** next to a service (Settings → Setup, Broker & alerts, Data coverage, or `POST /api/integrations/verify {"service": id}`) to make one read-only check with the key you entered. The result (Verified / failed / format checked only) is stored without the key; changing the key returns it to Needs verification. Stripe accepts test keys only.
3. Check it:
   - `python scripts/check_integrations.py` runs read-only tests (Alpaca paper account + clock, SEC EDGAR, FRED) and prints
     a checklist of what is still missing. It places no orders and sends no alerts. `--json` gives machine output.
   - In the app: **Settings → Broker & alerts → Integrations** shows each service as configured or not, reachable or not
     (press *Test connections*), and its mode (paper / practice / sandbox / live refused / data only).
     The API is `GET /api/integrations/status` (`?probe=true` to test). Secret values are never returned.
   - **Trade → Paper account** shows Alpaca paper equity, cash, positions, orders and fills, with reconciliation checks.

## Services

| Service | Variables | Cost | Where to get it | How to test |
|---|---|---|---|---|
| Alpaca paper trading + data | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (`ALPACA_BASE_URL` stays the paper URL, `ALPACA_DATA_FEED=iex`) | Free (SIP data is paid) | app.alpaca.markets → switch to **Paper** → API Keys → Generate | check script (account + clock); Trade → Paper account |
| SEC EDGAR | `ATLAS_SEC_USER_AGENT` = `AppName your-email@domain` | Free, no key | No signup. SEC requires a contact e-mail in the User-Agent | check script (Apple submissions file) |
| FRED / ALFRED | `FRED_API_KEY` | Free | fredaccount.stlouisfed.org → API Keys | check script (GDP series) |
| **Massive (Polygon), recommended stock source** | `POLYGON_API_KEY` (`MASSIVE_API_KEY` = same key, for the MCP) | Free Stocks Basic (5/min, daily bars) | https://massive.com/dashboard/signup → Keys | Verify; Settings → Connectors feed health |
| Finnhub | `FINNHUB_API_KEY` | Free tier | finnhub.io/dashboard | feed health |
| Tiingo | `TIINGO_API_KEY` | Free tier | tiingo.com → Account → API | feed health |
| Twelve Data | `TWELVEDATA_API_KEY` | Free tier | twelvedata.com → API keys | feed health |
| Alpha Vantage | `ALPHAVANTAGE_API_KEY` | Free tier (25/day) | alphavantage.co/support/#api-key | feed health |
| Financial Modeling Prep | `FMP_API_KEY` | Free tier | financialmodelingprep.com dashboard | autopilot feeds |
| EODHD | `EODHD_API_KEY` | Paid (free = 20 calls/day) | eodhd.com → Settings | autopilot feeds / MCP |
| Databento | `DATABENTO_API_KEY`, `ATLAS_DATABENTO_DATASET` | **Paid, billed per use** | databento.com/portal/keys | feed health |
| OANDA | `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`, `OANDA_ENV=practice` | Free practice account | oanda.com demo → Manage API access | feed health |
| Questrade | `QUESTRADE_REFRESH_TOKEN` | Free with account | Questrade → App Hub → API access (token single-use, 7 days) | feed health |
| IBKR Client Portal | `IBKR_CP_GATEWAY_URL` | Free with account | Run the local gateway, log in with a paper (DU…) user | feed health |
| Coinbase/Kraken, Yahoo | none | Free, keyless | — | feed health |
| Telegram alerts | `ATLAS_ALERTS_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Free | @BotFather | `/api/ext/alerts/preview` (does not send) |
| Discord alerts | `ATLAS_ALERTS_ENABLED=true`, `DISCORD_WEBHOOK_URL` | Free | Channel → Integrations → Webhooks | alerts preview |
| Slack alerts | `ATLAS_ALERTS_ENABLED=true`, `SLACK_WEBHOOK_URL` | Free | api.slack.com/messaging/webhooks | alerts preview |
| External data MCP servers | `ATLAS_EXTERNAL_MCP=on`, plus each server's key (`TRADINGVIEW_TOKEN`, `QUANTCONNECT_API_TOKEN`, …) | Mixed | each vendor | off by default; read-only allowlists |
| Gemini / OpenAI / Anthropic / xAI (assistant) | `GEMINI_API_KEY` (`ATLAS_GEMINI_TIER=paid`), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY` | Paid | each vendor console | assistant page |

Alerts stay off until `ATLAS_ALERTS_ENABLED=true` **and** a channel is set. OANDA `live` is
reported as *live refused*.

## Minimum to link end to end

`POLYGON_API_KEY` (Massive), `ATLAS_SEC_USER_AGENT`, `FRED_API_KEY`, then press Verify on each. Alpaca keys are optional.


## evo-12: monitoring and alerts (all optional, off by default)
| Service | Env | Effect |
|---|---|---|
| Healthchecks.io dead-man ping | `HEALTHCHECKS_PING_URL`, optional `HEALTHCHECKS_INTERVAL_S` | The API pings on a timer and the ingest daemon pings after each cycle; no URL, no calls. Free tier is enough. |
| Sentry | `SENTRY_DSN`, optional `SENTRY_TRACES_SAMPLE_RATE` | Python errors only, with PII, cookies and secrets scrubbed. No DSN, no SDK init. |
| ntfy | `NTFY_TOPIC` (+ optional `NTFY_URL`, `NTFY_TOKEN`) | Alert backend; only used when `ATLAS_ALERTS_ENABLED=true`. |
| Mail | `ATLAS_MAIL_BACKEND=console\|smtp\|file\|memory`, `ATLAS_SMTP_HOST/PORT/USER/PASSWORD/FROM/SECURITY` | Verification, reset, invite mail. Default console: logs the message, sends nothing. |
| Alpaca | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | Canonical names. `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` are accepted. |
