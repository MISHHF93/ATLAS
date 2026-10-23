# ATLAS API keys and the localhost MCP endpoint

Paper/simulation only. No route or tool here can place a live order, move money, approve the autopilot or reset
the Safe stop. MCP tools are read-only and return `execution_permission: "none"`.

## API keys

- Format `atk_<key_id>_<secret>`. The plaintext is printed **once** at creation. The store keeps only
  `sha256(salt || secret)` with a random per-key salt (constant-time compare). File: `ATLAS_API_KEYS_PATH`
  (default `var/api_keys.json`, mode 0600, never committed).
- Scopes (each includes the ones before it):
  - `read`: zones, setups, predict, Safe stop status, autopilot status, shadow summary, autopilot **off**.
  - `research`: adds replay and evidence.
  - `paper-trade`: adds autopilot on-request and manual tick. It still cannot switch the autopilot on.
- Per-key token-bucket rate limit (`--rate` requests/minute, default 60). Over the limit you get HTTP 429.
- Revocation is immediate. Keys are managed only from the local owner CLI, never over HTTP:

```bash
python -m atlas.keys.cli create --name claude-desktop --scope read --rate 60
python -m atlas.keys.cli list
python -m atlas.keys.cli revoke <key_id>
```

Send the key as `Authorization: Bearer atk_...` (or `X-Atlas-Key: atk_...`). Errors: 401 missing/invalid/revoked,
403 insufficient scope or non-local request, 429 rate limited.

## Paper setup autopilot routes

| Method | Path | Scope | Notes |
|---|---|---|---|
| GET | `/api/quant/autopilot` | read | Status, risk room, pending requests, recent decisions (starts the loop if switched on). |
| POST | `/api/quant/autopilot/request-on` | paper-trade | Files a 15-minute request; returns the approve command. |
| POST | `/api/quant/autopilot/off` | read | Instant stop. |
| POST | `/api/quant/autopilot/tick` | paper-trade | Runs one loop step now. |
| GET | `/api/quant/shadow` | read | Shadow-week summaries. |

Approve on the owner's terminal: `atlas-owner setup-autopilot-approve <request_id>` (passphrase + TOTP).
Env names: `ATLAS_SETUP_AUTOPILOT_STREAMS` (`SYMBOL:minutes[:session],…`), `ATLAS_SETUP_AUTOPILOT_INTERVAL_S`,
`ATLAS_STATE_DB`, `ATLAS_AUDIT_DB`, `ATLAS_SHADOW_PATH`.

## MCP endpoint

`POST http://127.0.0.1:<PORT>/api/mcp`. This is MCP over HTTP: JSON-RPC 2.0 with single JSON responses, supporting
`initialize`, `ping`, `tools/list` and `tools/call`; notifications get 202. Requests are refused unless the Host is
localhost, the Origin is absent or localhost, and a valid key is present. The Node server already binds
`127.0.0.1` only.

| Tool | Scope | Arguments |
|---|---|---|
| `zones` | read | `symbol`, `resolution` (minutes, default `60`), `session` |
| `setups` | read | same |
| `predict` | read | same; predict() + EV-gate evaluations with abstention reasons |
| `safe_stop_status` | read | none |
| `replay` | research | `symbol`, `resolution`, `session`, `cost_per_unit`, `max_hold_bars` |
| `evidence` | research | `name` (optional; omit to list files in `docs/spec/evidence/`) |

`tools/list` only shows tools the key's scope allows.

### Register in Claude (Claude Code)

```bash
claude mcp add --transport http atlas http://127.0.0.1:3000/api/mcp \
  --header "Authorization: Bearer $ATLAS_MCP_KEY"
```

Claude Desktop: add a custom connector with the same URL and header, or bridge via `npx mcp-remote
http://127.0.0.1:3000/api/mcp --header "Authorization: Bearer ${ATLAS_MCP_KEY}"` in `claude_desktop_config.json`.

### Register in Grok / other MCP clients

Any client that supports remote MCP over HTTP: server URL `http://127.0.0.1:3000/api/mcp`, header
`Authorization: Bearer <key>`. The endpoint is localhost-only, so the client must run on the same machine. Cloud
connectors cannot reach it, and it is deliberately not exposed publicly.

Replace `3000` with your `PORT`. Keep the key in an env variable, never in committed files.

### Smoke test

```bash
curl -s http://127.0.0.1:3000/api/mcp -H "Authorization: Bearer $ATLAS_MCP_KEY" \
  -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
