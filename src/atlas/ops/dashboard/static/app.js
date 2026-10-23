"use strict";
// One-page dashboard. All untrusted values are written with textContent (never innerHTML).
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 0) => (n == null || isNaN(n)) ? "–" : Number(n).toLocaleString("en-CA", {minimumFractionDigits: d, maximumFractionDigits: d});
const ET = {timeZone: "America/Toronto", hour12: false};
const et = (x, o = {dateStyle: "short", timeStyle: "short"}) => x ? new Date(x).toLocaleString("en-CA", {...ET, ...o}) : "–";
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function row(tb, cells, cls) { const tr = el("tr", cls); cells.forEach(([v, c]) => tr.append(el("td", c || null, String(v)))); tb.append(tr); return tr; }
function emptyRow(tb, text, span) { const tr = el("tr", "idle"), td = el("td", null, text); td.colSpan = span; tr.append(td); tb.append(tr); }

function limitBar(label, used, limit) {
  const wrap = el("div", "lb");
  const l = el("div", "lim"); l.append(el("span", null, label), el("span", null, `${fmt(used, 2)} / ${fmt(limit, 1)}%`));
  const bar = el("div", "bar"); bar.setAttribute("role", "meter"); bar.setAttribute("aria-label", `${label} loss limit used`);
  bar.setAttribute("aria-valuemin", "0"); bar.setAttribute("aria-valuemax", String(limit)); bar.setAttribute("aria-valuenow", String(used));
  const s = el("span"); const pct = Math.min(100, used / limit * 100); s.style.width = pct + "%"; if (pct > 75) s.className = "hot"; bar.append(s);
  wrap.append(l, bar); return wrap;
}

function render(st) {
  const s = st.status, halted = s.halted;
  $("wd").textContent = (s.watchdog_healthy ? "Watchdog OK" : "Watchdog STALE") + (halted ? ` · HALTED: ${s.kill_reason || ""}` : "");
  document.querySelector("#hdrStatus .dot").style.background = (s.watchdog_healthy && !halted) ? "var(--pos)" : "var(--neg)";
  $("kill").className = halted ? "kill engaged" : "kill"; $("kill").textContent = halted ? "■ HALTED" : "■ KILL SWITCH";
  $("autonomy").textContent = `L${st.limits.autonomy_level} · ${st.limits.approval_required ? "approval required" : "auto"}`;
  $("botcap").textContent = "$" + fmt(s.bot_capital); $("botcap_s").textContent = `eq $${fmt(s.bot_equity)} · cash $${fmt(s.cash)}`;
  const pnl = st.pnl_today; $("pnl").textContent = (pnl >= 0 ? "+$" : "−$") + fmt(Math.abs(pnl), 2); $("pnl").className = "v " + (pnl >= 0 ? "pos" : "neg");
  $("pnl_s").textContent = `session ${s.session}` + (s.daily_halted ? " · DAILY HALT" : "");
  $("npos").textContent = st.positions.length; $("npos_s").textContent = `gross ${fmt(s.gross_exposure_pct, 1)}% · ${s.open_orders} open orders`;
  const lu = $("limits_used"); clear(lu);
  lu.append(limitBar("Day", s.daily_loss_pct, st.limits.loss_limits.daily_pct), limitBar("Week", s.weekly_loss_pct, st.limits.loss_limits.weekly_pct),
            limitBar("DD", s.drawdown_pct, st.limits.loss_limits.max_drawdown_pct));
  const sl = $("sleeves"); clear(sl); let maxDrift = 0;
  for (const x of st.sleeves) {
    const r = el("div"); const sw = el("span", "sw"); sw.style.background = x.locked ? "#e5e7eb" : x.color;
    r.append(sw, el("span", null, x.name + (x.locked ? " (locked)" : "")), el("b", null, `${fmt(x.actual_pct, 1)}% / ${fmt(x.target_pct, 0)}%`));
    sl.append(r); if (!x.locked) maxDrift = Math.max(maxDrift, Math.abs(x.drift_pp));
  }
  const over = maxDrift > st.limits.drift_band_pp;
  $("driftpill").textContent = over ? `drift ${fmt(maxDrift, 1)}pp > band` : "drift OK"; $("driftpill").className = "pill " + (over ? "x" : "f");
  const lim = $("limits"); clear(lim); $("polver").textContent = `v${st.limits.policy_version} · read-only`;
  for (const [k, v] of st.limit_rows) { const r = el("div"); r.append(el("span", null, k), el("b", null, v)); lim.append(r); }
  const q = $("queue"); clear(q); $("qcount").textContent = `${st.approvals.length} pending`;
  if (!st.approvals.length) q.append(el("p", "empty", "No pending approvals."));
  for (const a of st.approvals) {
    const i = a.intent, box = el("div", "appr");
    box.append(el("b", null, `${i.side.toUpperCase()} ${i.qty} ${i.symbol}`), el("span", "muted", ` ${i.sleeve} · expires ${fmt(a.expires_in_s)}s`),
               el("code", null, `tradingbot-owner approve ${a.approval_id}`));
    q.append(box);
  }
  const tb = $("positions"); clear(tb);
  for (const p of st.positions) row(tb, [[p.symbol], [p.sleeve], [p.currency], [fmt(p.qty, 4), "r"], [fmt(p.avg_price, 2), "r"], [fmt(p.last_price, 2), "r"], [fmt(p.market_value_base, 2), "r"]]);
  if (!st.positions.length) emptyRow(tb, "No open positions.", 7);
  $("footer").textContent = `Updated ${new Date().toLocaleTimeString("en-CA", ET)} ET · refreshes every 5 s · read-only except the kill switch · approvals/reset via tradingbot-owner (step-up)`;
}

async function refresh() {
  try { const r = await fetch("/api/state", {cache: "no-store"}); if (r.ok) render(await r.json()); }
  catch (e) { $("wd").textContent = "dashboard disconnected"; }
}

$("kill").addEventListener("click", async () => {
  const reason = prompt("Kill switch: reason (halts and cancels all orders)");
  if (!reason) return;
  const token = prompt("Dashboard token (DASHBOARD_TOKEN)");
  if (!token) return;
  const r = await fetch("/api/kill", {method: "POST", headers: {"Content-Type": "application/json", "X-Dashboard-Token": token}, body: JSON.stringify({reason})});
  alert(r.ok ? "Kill switch engaged." : `Failed: ${r.status}`); refresh();
});

function drawEquity(series) {
  const c = $("eqchart"), empty = series.length < 2;
  c.hidden = empty; $("eqempty").hidden = !empty;
  if (empty) { $("eqpill").textContent = series.length ? "1 pt" : "no data"; return; }
  const dpr = window.devicePixelRatio || 1, W = c.clientWidth || 200, H = 44;
  c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  const ctx = c.getContext("2d"); ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const v = series.map(p => p[1]); const lo = Math.min(...v), hi = Math.max(...v), span = (hi - lo) || 1;
  ctx.strokeStyle = "#1f2937"; ctx.lineWidth = 1.5; ctx.beginPath();
  v.forEach((y, i) => { const x = 2 + i * (W - 4) / (v.length - 1), yy = H - 3 - (y - lo) / span * (H - 6); i ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy); });
  ctx.stroke();
  const chg = v[v.length - 1] - v[0]; $("eqpill").textContent = `${chg >= 0 ? "+" : "−"}$${fmt(Math.abs(chg), 0)} · ${v.length} pts`;
  c.setAttribute("aria-label", `Paper equity sparkline: from $${fmt(v[0])} to $${fmt(v[v.length - 1])}`);
}

function renderMarkets(m) {
  const s = $("markets"); clear(s);
  if (m.weekend_mode) s.append(el("span", "mk", "Weekend: crypto only"));
  for (const r of m.venues) {
    const b = el("span", "mk" + (r.open ? (r.size_mult < 1 ? " reduced" : " open") : ""), `${r.venue} ${r.open ? r.phase : "closed"}`);
    b.title = `${r.next_change_et ? (r.open ? "closes " : "opens ") + r.next_change_et.slice(5, 16).replace("T", " ") + " ET · " : ""}local ${r.local_time}`;
    s.append(b);
  }
}

function renderAudit(rows) {
  const tb = $("audit"); clear(tb);
  for (const r of rows) row(tb, [[r.seq], [et(r.ts, {dateStyle: "short", timeStyle: "medium"})], [r.event], [r.actor], [r.payload, "p"]]);
  if (!rows.length) emptyRow(tb, "No audit entries.", 5);
}

function renderModels(d) {
  const box = $("models"); clear(box);
  const idle = d.models.filter(m => m.status === "not trained"), live = d.models.filter(m => m.status !== "not trained");
  const champs = live.filter(m => m.champion).length, chall = live.filter(m => m.challenger).length, drift = live.filter(m => m.drift === "drift").length;
  const sum = el("div", "chips");
  [[`${champs} champion`, champs ? "f" : ""], [`${chall} challenger`, chall ? "p" : ""], [`${idle.length} untrained`, ""], [`${drift} drifting`, drift ? "x" : ""]]
    .forEach(([t, c]) => sum.append(el("span", "pill " + c, t)));
  box.append(sum);
  for (const m of live) {
    const r = el("div", "mrow");
    r.append(el("b", null, m.kind), el("span", "muted", `${m.status}${m.challenger ? ` · ch ${m.shadow_weeks || 0}w` : ""}`),
             el("span", "drift-" + (m.drift || "none"), m.drift || ""));
    box.append(r);
  }
  if (idle.length) box.append(el("p", "empty", "Untrained: " + idle.map(m => m.kind).join(", ")));
  const a = d.autonomy;
  $("ladder").textContent = a ? `L${a.current_level}→L${a.target_level} ${a.evidence_ready ? "ready" : "not ready"}` : "autonomy: n/a";
  const lc = $("ladderchecks"); clear(lc);
  if (a) for (const c of a.checks) lc.append(el("span", "pill " + (c.passed ? "f" : "x"), `${c.name}: ${c.value ?? "–"}/${c.threshold}`));
}

function renderPayments(p) {
  const pend = $("paypending"), bal = $("paybal"), tx = $("paytx"); [pend, bal, tx].forEach(clear);
  if (!p.available) {
    $("paystate").textContent = "not connected"; $("paycash").textContent = "–"; $("paycash_s").textContent = p.reason || "";
    pend.append(el("p", "empty", "Payments service not connected (read-only view).")); emptyRow(bal, "–", 3); emptyRow(tx, "–", 6); return;
  }
  $("paystate").textContent = p.kill_switch ? "KILL ON" : `${p.pending_manual.length} open`; $("paystate").className = "pill " + (p.kill_switch ? "x" : p.pending_manual.length ? "p" : "f");
  let cad = 0; const ccys = new Set();
  for (const [acct, d] of Object.entries(p.balances)) for (const [ccy, amt] of Object.entries(d)) {
    row(bal, [[acct], [ccy], [fmt(Number(amt), 2), "r"]]); ccys.add(ccy); if (ccy === "CAD") cad += Number(amt);
  }
  if (!Object.keys(p.balances).length) emptyRow(bal, "No balances.", 3);
  $("paycash").textContent = "$" + fmt(cad); $("paycash_s").textContent = `CAD across asset accounts${ccys.size > 1 ? ` · +${ccys.size - 1} other ccy` : ""}`;
  for (const t of p.pending_manual) {
    const r = el("div", "appr");
    r.append(el("b", null, `#${t.id} ${fmt(Number(t.amount), 2)} ${t.currency}`), el("span", "muted", ` ${t.rail} · ${t.status} · value ${t.value_date || "–"}`));
    if (t.flag) r.append(el("span", "pill x", t.flag));
    pend.append(r);
  }
  if (!p.pending_manual.length) pend.append(el("p", "empty", "No pending manual transfers."));
  for (const t of p.transfers) row(tx, [[t.id], [t.status], [fmt(Number(t.amount), 2), "r"], [t.currency], [t.rail], [t.purpose || ""]]);
  if (!p.transfers.length) emptyRow(tx, "No transfers.", 6);
}

function renderDecisions(d) {
  const box = $("decisions"); clear(box);
  $("decsum").textContent = Object.entries(d.outcomes || {}).map(([k, v]) => `${k.replace("dropped at ", "drop:")} ${v}`).join(" · ") || "none";
  for (const t of d.decisions) {
    const det = el("details", "dec " + (t.final === "submitted" ? "ok" : "drop"));
    const sm = el("summary");
    const rep = (t.repeat || 1) > 1 ? ` ×${t.repeat} (${et(t.first_ts)} → ${et(t.ts)})` : ` ${et(t.ts)}`;
    sm.append(el("span", "pill " + (t.final === "submitted" ? "f" : "x"), t.final === "submitted" ? "submitted" : "dropped"),
              el("b", null, ` ${t.side} ${t.symbol}`), el("span", "muted", ` ${t.sleeve} · ${t.final}${t.routing ? " · " + t.routing : ""} ·${rep}`));
    det.append(sm);
    const tbl = el("table"); const tb = el("tbody");
    for (const s of t.stages) row(tb, [[s.stage], [s.effect], [s.qty != null ? fmt(s.qty, 4) : ""], [s.detail]], "eff-" + String(s.effect).replace(/[^a-z]/g, ""));
    tbl.append(tb); det.append(tbl);
    if (t.shadow && Object.keys(t.shadow).length)
      det.append(el("div", "muted", "shadow (challengers, not applied): " + Object.entries(t.shadow).map(([k, v]) => `${k}=${v}`).join(", ")));
    box.append(det);
  }
  if (!d.decisions.length) box.append(el("p", "empty", "No decisions yet."));
}

let decLimit = 25;
async function refreshDecisions() {
  const f = $("decfilter").value;
  const r = await fetch(`/api/decisions?limit=${decLimit + 1}` + (f ? "&final=" + f : ""), {cache: "no-store"});
  if (!r.ok) return;
  const d = await r.json(); const more = d.decisions.length > decLimit;
  d.decisions = d.decisions.slice(0, decLimit); renderDecisions(d); $("decmore").hidden = !more;
}
$("decmore").addEventListener("click", () => { decLimit += 50; refreshDecisions(); });
$("decfilter").addEventListener("change", () => { decLimit = 25; refreshDecisions(); });

// WAI-ARIA tabs: click + arrow keys; panels stay in the page (no navigation)
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(t) {
  for (const x of tabs) { const on = x === t; x.setAttribute("aria-selected", String(on)); x.tabIndex = on ? 0 : -1; $(x.getAttribute("aria-controls")).hidden = !on; }
  t.focus();
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => selectTab(t));
  t.addEventListener("keydown", e => {
    const k = {ArrowRight: 1, ArrowLeft: -1}[e.key]; if (k) { e.preventDefault(); selectTab(tabs[(i + k + tabs.length) % tabs.length]); }
    if (e.key === "Home") { e.preventDefault(); selectTab(tabs[0]); } if (e.key === "End") { e.preventDefault(); selectTab(tabs[tabs.length - 1]); }
  });
});

async function refreshSlow() {
  try {
    const urls = ["/api/equity", "/api/audit?limit=40", "/api/markets", "/api/models", "/api/payments"];
    const [e, a, m, mo, p] = await Promise.all(urls.map(u => fetch(u, {cache: "no-store"})));
    if (e.ok) drawEquity(await e.json()); if (a.ok) renderAudit(await a.json()); if (m.ok) renderMarkets(await m.json());
    if (mo.ok) renderModels(await mo.json()); if (p.ok) renderPayments(await p.json());
    await refreshDecisions();
  } catch (err) { /* shown by refresh() */ }
}
refresh(); setInterval(refresh, 5000); refreshSlow(); setInterval(refreshSlow, 30000);
