"use client";
import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { useSafeStop } from "../AppShell";
import { Async, Badge, Card, DataTable, EmptyState, Grid, PageHeader, StatTile, money, num, pct, useApi } from "../primitives";

type Pnl = {
  currency?: string; day_pnl_usd?: number; day_pnl_pct?: number; total_pnl_usd?: number; total_pnl_pct?: number;
  remaining_room?: { current_equity_usd?: number; daily_loss_room_usd?: number; daily_loss_room_pct?: number; daily_loss_limit_pct?: number; daily_drawdown_fraction?: number; trailing_dd_room_usd?: number; trailing_dd_room_pct?: number; drawdown_limit_pct?: number };
};
type InboxItem = { area?: string; severity?: string; title?: string; detail?: string; href?: string };
type Position = { position_id?: string; instrument_id?: string; side?: string; notional_usd?: string | number; stop_kind?: string; stop_distance_bps?: string | number; opened_at?: string };
type Control = { open_positions?: Position[]; account?: { current_equity_usd?: string; total_cumulative_profit_usd?: string } };

const tone = (v: unknown) => { const n = num(v); return n === null || n === 0 ? "neutral" : n > 0 ? "good" : "bad"; };

export function Overview() {
  const pnl = useApi<Pnl>("/api/founder/pnl", 15000);
  const inbox = useApi<{ items?: InboxItem[]; count?: number }>("/api/founder/inbox", 30000);
  const control = useApi<Control>("/api/control/state", 15000);
  const safe = useSafeStop();
  const room = pnl.data?.remaining_room;
  const limit = num(room?.daily_loss_limit_pct) ?? 2;
  const usedFrac = ((num(room?.daily_drawdown_fraction) ?? 0) * 100 / limit) * 100; // % of the daily limit used

  return (
    <div className="ux-page">
      <PageHeader
        eyebrow="Home"
        title="Overview"
        summary="Today’s paper results, how much room is left before Safe stop, and what needs your attention."
        actions={<Link className="ux-btn" href="/trade">Open trading desk <ArrowRight size={14} aria-hidden /></Link>}
      />

      <Async state={pnl} label="Loading P&L">
        {(d) => (
          <Grid cols={4}>
            <StatTile label="Equity (paper)" value={money(room?.current_equity_usd, d.currency)} hint="Simulated account, no real orders" />
            <StatTile label="Today" value={money(d.day_pnl_usd, d.currency)} delta={pct(d.day_pnl_pct, 2, true)} deltaTone={tone(d.day_pnl_usd)} />
            <StatTile label="Since start" value={money(d.total_pnl_usd, d.currency)} delta={pct(d.total_pnl_pct, 2, true)} deltaTone={tone(d.total_pnl_usd)} />
            <StatTile
              label={`Room before Safe stop (${limit}% daily)`}
              value={safe.engaged ? "Safe stop active" : money(room?.daily_loss_room_usd, d.currency)}
              hint={safe.engaged ? "New paper orders are blocked" : `${pct(room?.daily_loss_room_pct)} of equity left today`}
              meter={{ used: Math.min(1, Math.max(0, usedFrac / 100)), label: `${Math.round(usedFrac)}% of today’s ${limit}% loss limit used`, tone: usedFrac > 75 ? "bad" : usedFrac > 50 ? "warn" : "good" }}
            />
          </Grid>
        )}
      </Async>

      <div className="ux-grid" data-cols={3}>
        <Card span={2} title="Open paper positions" subtitle="From the control plane. Nothing here reaches a broker." actions={<Link className="ux-link" href="/trade">Desk</Link>}>
          <Async state={control} label="Loading positions">
            {(c) => (
              <DataTable<Position>
                caption="Open paper positions"
                rows={c.open_positions ?? []}
                empty={<EmptyState title="No open positions">Positions opened on the trading desk show up here.</EmptyState>}
                columns={[
                  { key: "instrument_id", label: "Instrument", render: (r) => String(r.instrument_id ?? "").replace(/^comp:|:v\d+$/g, "").toUpperCase() },
                  { key: "side", label: "Side", render: (r) => <Badge tone={r.side === "buy" ? "good" : "bad"}>{r.side === "buy" ? "Long" : "Short"}</Badge> },
                  { key: "notional_usd", label: "Notional", align: "right", render: (r) => money(r.notional_usd) },
                  { key: "stop", label: "Stop", align: "right", render: (r) => `${num(r.stop_distance_bps) ?? "—"} bps ${r.stop_kind ?? ""}` },
                ]}
              />
            )}
          </Async>
        </Card>

        <Card title="Needs attention" subtitle="Inbox" actions={<Link className="ux-link" href="/inbox">All</Link>}>
          <Async state={inbox} label="Loading inbox"
            isEmpty={(d) => !(d.items ?? []).length}
            empty={<EmptyState title="All clear" icon={<ShieldCheck size={20} />}>Nothing needs you right now.</EmptyState>}>
            {(d) => (
              <ul className="ux-list">
                {(d.items ?? []).slice(0, 5).map((it, i) => (
                  <li key={i} className="ux-list__item">
                    <Badge tone={it.severity === "high" || it.severity === "urgent" ? "bad" : "warn"}>{it.area ?? "item"}</Badge>
                    <div>
                      {it.href ? <Link className="ux-link" href={it.href}>{it.title}</Link> : <strong>{it.title}</strong>}
                      {it.detail ? <div className="ux-muted ux-small">{it.detail}</div> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Async>
        </Card>
      </div>

      <Grid cols={3}>
        <Link className="ux-tile-link" href="/money"><strong>Money</strong><span>P&amp;L, payments, partner wallet and tax.</span></Link>
        <Link className="ux-tile-link" href="/research"><strong>Research</strong><span>Signals, chart read and model evidence.</span></Link>
        <Link className="ux-tile-link" href="/compliance"><strong>Compliance</strong><span>Venue checks, FINTRAC timeline, rulebook.</span></Link>
      </Grid>
    </div>
  );
}
