# Platform audit: trading-bot-app (+ payments/), 2026-10-16

Scope: architecture, logic, security, dashboard UX. Paper-only and offline rules were kept: nothing was pushed, the specs are unchanged, and no secrets were added.
Severity: **High** = can cause wrong money/position state or a stuck or bypassed safety control. **Med** = wrong under edge conditions or weakens defense in depth. **Low** = hygiene or UX.

## Findings and fixes

| # | Sev | Area | Finding | Fix (commit) |
|---|---|---|---|---|
| 1 | High | Runner / risk | The long-running loop (`tradingbot-run`) **never rolled the session**. `roll_session` only ran in the backtester. In the live paper service, the daily-loss latch and start-of-day/week anchors therefore never reset, so one daily halt blocked buys forever. | `TradingService.ensure_session(now)` rolls on an **America/Toronto** date change and is called every loop tick (ececfb5) |
| 2 | High | Approvals concurrency | `process_owner_approved` did read, then execute, then write with no claim. The dashboard heartbeat *and* the core loop both call `process_owner_actions` against the same state DB, so an owner-approved order could execute **twice**. | Atomic `owner_approved → executing` claim via new `StateStore.update` (`BEGIN IMMEDIATE`, cross-process). An execute exception now marks the item rejected instead of leaving it stranded. Multiprocess test: 4 processes, exactly 1 execution (ececfb5) |
| 3 | High | Payments | `mark_executed` and adapter `execute` checked status, then posted to the ledger, in separate autocommit statements. Two CLI processes could double-post or double-submit a transfer. The ledger post and the status update were also not atomic. | `db.tx()` (re-entrant `BEGIN IMMEDIATE`). Conditional claims `instructed→marking` and `approved→submitting`. Ledger post plus status change run in one transaction. An unknown submit outcome goes to `submit_error` with no auto-retry; pre-flight failures (adapter disabled or wrong rail) leave the transfer approved (856462b) |
| 4 | High | Payments / fund | `redeem` ignored **pending** redemptions, so two orders could redeem more than the units held (negative units at dealing). | Pending redemption units are now counted (856462b) |
| 5 | Med | Payments / fund | Management and performance fees could be charged twice for the same period. NAV ≤ 0 or NaN caused divide errors or garbage units. Fee, unit and HWM updates were not atomic. | Per-(investor, kind, period) dedupe, NAV guard, transactions (856462b) |
| 6 | Med | Payments | A rejected transfer could be flipped back to `approved` by a late second approval under dual control. | Conditional `UPDATE … WHERE status='pending_approval'` (856462b) |
| 7 | Med | Risk engine | `loss_metrics` divided by start/peak equity with no guard. A 0 anchor raised inside `check_breaches`, which runs outside the fail-closed wrapper and crashed the mark-to-market. NaN slipped through. FX check divided by a provider rate that could be 0. | `_loss_pct`: non-finite → 100% (fail closed); anchor ≤ 0 → 0. FX rate ≤ 0 or non-finite → reject (ececfb5) |
| 8 | Med | Time zones | The risk session default used `date.today()`, which is the box zone and is UTC in containers. The weekly anchor compared the ISO week number without the year. Toronto tz was defined in 9 places. | ET session date. `(iso_year, week)` anchor. Single `tradingbot.timez.TORONTO` (ececfb5, a6c4a75) |
| 9 | Med | Kill switch | Engage was a read-modify-write guarded only by a per-process lock, so a concurrent engage could overwrite the reason/ts. | Atomic `update`: the first engage wins and nothing can un-engage except an owner reset (ececfb5) |
| 10 | Med | State store | One sqlite connection was shared across threads, but reads ran without the lock. `items()` treated `_` in prefixes as a LIKE wildcard. | All ops locked; LIKE escaped (ececfb5) |
| 11 | Med | Least privilege | `ApprovalQueue.reject` ignored the approver argument. The state and treasury SQLite files were created 0644. | Owner-only reject (audited denial). DB files chmod 0600 (ececfb5, 9ca1221) |
| 12 | Med | Payments secrets file | Approver secrets were written truncate-then-write, so a crash could corrupt or lose all approver credentials. | Temp file + fsync + `os.replace`, 0600 (856462b) |
| 13 | Med | Decision trail | The same candidate was re-proposed every cycle, so the trail and dashboard filled with identical "dropped at cost" rows (983 of 1000 entries in the sim). | `tradingbot/trail.py`: collapse into the latest entry for the same symbol/side/sleeve when outcome **and** the stage/effect sequence match (`repeat`, `first_ts`). Applied on write (pipeline, sim) and on read (legacy stores). Outcome counts stay exact (e4a834f) |
| 14 | Low | Dashboard server | A malformed `Content-Length` crashed the POST handler. No `__main__` guard, so `python -m tradingbot.dashboard.server` exited silently. | 400 on a bad header; guard added (e4a834f) |
| 15 | Low | Code hygiene | Unused imports in 7 modules; a duplicate import in payments/manual.py. | Removed (a6c4a75) |
| 16 | Low | Dashboard UX | The decision wall was unreadable. The equity canvas was a fixed 900px bitmap (blurry and tiny on mobile) and drew a big empty box with no data. There were 12 identical "not trained" model rows. Muted text was #6b7280 with 10–11px labels. The market strip wrapped into 10 rows on mobile. There was no skip link, focus ring, select label or live region. | Collapsed rows show ×N and first→last seen, with outcome pill, 25 rows plus "Show more". DPR-aware responsive chart with an empty state. One summary row for untrained models. Muted text #4b5563 (7.6:1), labels ≥12px. Horizontally scrollable strip. Full-width kill button on mobile. Skip link, `:focus-visible`, `aria-live` status, labelled filter, "No open positions" row (92acd06) |

New tests: `tests/test_audit_fixes.py` (16) and `payments/tests/test_audit_fixes.py` (8).

## Screenshots (headless Chrome)
- Before: `/workspace/shots/before_desktop.png` (1400w), `/workspace/shots/before_mobile.png` (390w)
- After: `/workspace/shots/after_desktop.png`, `/workspace/shots/after_mobile.png`, `/workspace/shots/after_mobile_viewport.png` (390×844 @2x)

## Reviewed, no change needed
- Risk pipeline order is fail closed: halts → venue/paper → sleeve → no-short → quote/collar → FX → loss limits → rate → sizing → hooks. Sells bypass sizing and loss limits (risk reducing).
- The pipeline's only-shrinks invariant and exits bypassing models are covered by existing tests. The crypto floor rounding was fixed earlier.
- Live trading is impossible (`assert_paper_only`; payments `_live_submit` raises). The dashboard binds to loopback, checks Host and Origin, and compares tokens in constant time. MCP tokens are sha256-hashed with `compare_digest`. No approve or reset path exists over MCP. `.env` and `var/` are gitignored. No secrets are tracked.

## Remaining issues (not fixed)
1. **Med** The order rate limiter (`SlidingWindowLimiter`) is per process. Core and owner-CLI executions don't share the budget. It should move into the StateStore.
2. **Med** The broker and ledger state of the paper service live in memory. After a restart, `roll_day` sets start-of-day equity to *current* equity, which understates that day's loss. Anchors should be persisted.
3. **Med** The sell-side no-short check uses `held` but ignores pending open sell orders, so two concurrent sells could exceed the position. The broker still refuses to go short, so the impact is a rejected fill.
4. **Med** The sector concentration check is skipped when an instrument has no sector. Treating that as an "unknown" bucket would be stricter.
5. **Low** `FullPipeline.trail` (in memory) grows without limit in a very long-running process. Only the stored trail is capped at 1000.
6. **Low** SQLite WAL `-wal`/`-shm` side files follow the umask (0644). Run under `umask 077` or a dedicated OS user. Payments `reject_transfer` and trading-bot `owner_cli reject` need no step-up (risk reducing, by design).
7. **Low** Architecture: `pipeline_full.py` (552 lines) mixes stage logic, `ServiceContext` and service glue. It should be split into `pipeline/stages.py` and `pipeline/service.py`. Payments has its own audit, FX and step-up implementations that duplicate the trading bot's (intentional isolation, but double maintenance). The payments dashboard also defaults to port 8765, which clashes with the trading dashboard.
8. **Low** The dashboard GET API is unauthenticated (loopback only). Add the token to GETs if it is ever exposed beyond loopback or a container.

## Follow-up (2026-10-16): previously remaining items, now fixed
- Rate-limit budget is now shared across processes: `SharedWindowLimiter` on the SQLite StateStore (`BEGIN IMMEDIATE`), key `rate:orders`.
- Paper broker and ledger state now persist across restarts (`paper_state`). State is saved on fill, session roll and each tick, and restored on start.
- The no-short check now counts open sell orders (`pending_sell_qty`).
- A missing sector now counts in its own capped "unknown" bucket. Index/cash/FX/crypto asset classes are exempt.
- The in-memory decision trail is bounded (`trail_max`, with a `n_decisions` counter).
- The db, -wal, -shm and -journal files are now mode 0600.
- `pipeline_full.py` is split into `pipeline_models.py`, `pipeline_service.py` and the core; it re-exports for compatibility.
- `common/` (`tradingbot_common`) holds the shared TOTP/scrypt, hash-chain and static-FX code; the bot and payments both use it.
- The payments dashboard now defaults to port 8766.
- The dashboard is now a one-pager, with a read-only payments panel via `BalanceView`. It is viewer-only on a shared state DB.
