"use client";
import { useSafeStop } from "./AppShell";
import { Async, Grid, StatTile, money, num, pct, useApi } from "./primitives";

export type Pnl = {
  currency?: string; day_pnl_usd?: number; day_pnl_pct?: number; total_pnl_usd?: number; total_pnl_pct?: number;
  remaining_room?: { current_equity_usd?: number; daily_loss_room_usd?: number; daily_loss_room_pct?: number; daily_loss_limit_pct?: number; daily_drawdown_fraction?: number; trailing_dd_room_usd?: number; trailing_dd_room_pct?: number; drawdown_limit_pct?: number };
};

const tone = (v: unknown) => { const n = num(v); return n === null || n === 0 ? "neutral" : n > 0 ? "good" : "bad"; };

/** The one paper P&L strip (equity, today, since start, room before Safe stop). Shared by Overview and Money › Summary. */
export function PnlTiles() {
  const pnl = useApi<Pnl>("/api/founder/pnl", 15000);
  const safe = useSafeStop();
  return (
    <Async state={pnl} label="Loading P&L">
      {(d) => {
        const room = d.remaining_room ?? {};
        const limit = num(room.daily_loss_limit_pct) ?? 2;
        const used = Math.min(1, Math.max(0, ((num(room.daily_drawdown_fraction) ?? 0) * 100) / limit));
        return (
          <Grid cols={4}>
            <StatTile label="Equity (paper)" value={money(room.current_equity_usd, d.currency)} hint="Simulated account, no real orders" />
            <StatTile label="Today" value={money(d.day_pnl_usd, d.currency)} delta={pct(d.day_pnl_pct, 2, true)} deltaTone={tone(d.day_pnl_usd)} />
            <StatTile label="Since start" value={money(d.total_pnl_usd, d.currency)} delta={pct(d.total_pnl_pct, 2, true)} deltaTone={tone(d.total_pnl_usd)} />
            <StatTile
              label={`Room before Safe stop (${limit}% daily)`}
              value={safe.engaged ? "Safe stop active" : money(room.daily_loss_room_usd, d.currency)}
              hint={safe.engaged ? "New paper orders are blocked" : `${pct(room.daily_loss_room_pct)} of equity left today · trailing drawdown room ${money(room.trailing_dd_room_usd, d.currency)}`}
              meter={{ used, label: `${Math.round(used * 100)}% of today’s ${limit}% loss limit used`, tone: used > 0.75 ? "bad" : used > 0.5 ? "warn" : "good" }}
            />
          </Grid>
        );
      }}
    </Async>
  );
}
