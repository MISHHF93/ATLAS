"use client";
import Link from "next/link";
import { NavLink } from "../../nav/NavLink";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { PnlTiles } from "../PnlTiles";
import { Async, Badge, Card, DataTable, EmptyState, Grid, money, num, useApi } from "../primitives";

type InboxItem = { area?: string; severity?: string; title?: string; detail?: string; href?: string };
type Position = { position_id?: string; instrument_id?: string; side?: string; notional_usd?: string | number; stop_kind?: string; stop_distance_bps?: string | number; opened_at?: string };
type Control = { open_positions?: Position[]; account?: { current_equity_usd?: string; total_cumulative_profit_usd?: string } };

export function Overview() {
  const inbox = useApi<{ items?: InboxItem[]; count?: number }>("/api/founder/inbox", 30000);
  const control = useApi<Control>("/api/control/state", 15000);

  return (
    <div className="ux-page">
      <PnlTiles />

      <div className="ux-grid" data-cols={3}>
        <Card span={2} title="Open paper positions" subtitle="From the control plane. Nothing here reaches a broker." actions={<NavLink className="ux-link" to="markets">Markets</NavLink>}>
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

        <Card title="Needs attention" subtitle="Inbox" actions={<NavLink className="ux-link" to="home.inbox">All</NavLink>}>
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
        <NavLink className="ux-tile-link" to="money"><strong>Money</strong><span>P&amp;L, payments, partner wallet and tax.</span></NavLink>
        <NavLink className="ux-tile-link" to="predictions"><strong>Predictions</strong><span>Forecasts, back-tests and model evidence.</span></NavLink>
        <NavLink className="ux-tile-link" to="money.regulatory"><strong>Compliance, Privacy &amp; ISO Standards</strong><span>Venue checks, PIPEDA &amp; Law 25 privacy, ISO 10383/6166/27001/42001, FINTRAC &amp; 3rd-party links.</span></NavLink>
      </Grid>
    </div>
  );
}
