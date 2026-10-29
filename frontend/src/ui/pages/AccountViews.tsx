"use client";
/** Accounts UI (Settings): sign in / register, the visual connector setup, profile and plan. Server-side everything is scoped to the signed-in
 *  user. Secret fields are write-only: after saving you see only the last 4 characters. ATLAS connects paper and practice accounts only. */
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Badge, Card, DataTable, EmptyState, LoadingSkeleton, type Tone } from "../primitives";
import { api, setCsrf, why, type Me, type User } from "./acct";
import { AuthPortal } from "./AuthPortal";
import { InvitesCard, TeamCard } from "./InviteTeam";

type R = Record<string, unknown>;

/* ------------------------------------------------------------- gate */
export function AccountGate({ children }: { children: (me: { user: User; reload: () => void; signOut: () => void }) => ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const load = useCallback(async () => {
    const r = await api<Me>("/api/account/me");
    setCsrf(r.data.csrf_token);
    setMe(r.ok ? r.data : { authenticated: false, require_auth: false });
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (!me) return <LoadingSkeleton label="Checking your session" />;
  if (!me.authenticated || !me.user) return <AuthPortal registration={me.registration} onDone={load} />;
  const signOut = async () => { await api("/api/account/logout", {}); setCsrf(""); void load(); };
  return <>{children({ user: me.user, reload: load, signOut })}</>;
}

/* ------------------------------------------------------------- setup wizard */
type Field = { name: string; label: string; env: string; secret: boolean; required: boolean; placeholder: string; help: string; default: string; choices: string[] };
type SecretState = { set: boolean; last4: string; version: number; updated_at: number };
type CState = { status: string; config: Record<string, string>; secrets: Record<string, SecretState>; last_tested_at: number | null; last_test_ok: boolean | null; last_test_detail: string | null } | null;
type Conn = { id: string; name: string; category: string; stage: string; docs_url: string; signup_url: string; free_tier: string; mode: string; safety_note: string; loop_use: string;
  fields: Field[]; env_names: string[]; light: "gray" | "amber" | "green" | "red"; state: CState };
type Library = { categories: { id: string; title: string; stage: string }[]; connectors: Conn[]; master_key_configured: boolean; entitlements: { plan: string; plan_name: string } & R };

const LIGHT: Record<Conn["light"], { tone: Tone; text: string }> = {
  gray: { tone: "warn", text: "Needs verification" }, amber: { tone: "warn", text: "Needs verification" }, green: { tone: "good", text: "Verified" }, red: { tone: "bad", text: "Verification failed" },
};
const SHAPE: Record<Conn["light"], string> = { gray: "○", amber: "◐", green: "●", red: "■" };

export function SetupWizard() {
  return <AccountGate>{({ user }) => <WizardInner user={user} />}</AccountGate>;
}

function WizardInner({ user }: { user: User }) {
  const [lib, setLib] = useState<Library | null>(null);
  const [err, setErr] = useState("");
  const [step, setStep] = useState(0);
  const load = useCallback(async () => {
    const r = await api<Library>("/api/account/connectors");
    if (r.ok) { setLib(r.data); setErr(""); } else setErr(why(r));
  }, []);
  useEffect(() => { void load(); }, [load]);
  if (err && !lib) return <EmptyState title="Could not load connectors">{err}</EmptyState>;
  if (!lib) return <LoadingSkeleton label="Loading the connector library" />;
  const cats = lib.categories;
  const total = lib.connectors.length;
  const saved = lib.connectors.filter((c) => c.state).length;
  const working = lib.connectors.filter((c) => c.light === "green").length;
  const cat = cats[step];
  const items = lib.connectors.filter((c) => c.category === cat.id);
  return (
    <>
      <Card title="Set up your data and alerts" span="full"
        subtitle={`Signed in as ${user.email}. Go step by step: each service has a free tier, a link to get its key, a save button and a Verify button (one read-only check). Nothing is set up for you: every key reads Needs verification until you enter it and press Verify. Paper and practice accounts only.`}
        actions={<Badge tone="info">{lib.entitlements.plan_name} plan</Badge>}>
        {!lib.master_key_configured ? (
          <p className="ux-action-msg" data-tone="warn" role="status">Secrets cannot be saved yet: the server has no ATLAS_MASTER_KEY. Generate one with
            {" "}<code>python -c &quot;import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())&quot;</code>{" "}and put it in your .env.</p>
        ) : null}
        <p aria-live="polite"><strong>{working}</strong> working · <strong>{saved}</strong> saved · {total} available</p>
        <ol className="ux-wiz-steps" aria-label="Setup steps">
          {cats.map((c, i) => {
            const ci = lib.connectors.filter((x) => x.category === c.id);
            const done = ci.some((x) => x.light === "green");
            return (
              <li key={c.id}>
                <button type="button" className="ux-wiz-step" aria-current={i === step ? "step" : undefined} data-done={done ? "true" : undefined} onClick={() => setStep(i)}>
                  <span className="ux-wiz-step__n" aria-hidden>{done ? "✓" : i + 1}</span>
                  <span>{c.title}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </Card>
      <Card title={`Step ${step + 1} of ${cats.length}: ${cat.title}`} subtitle={cat.stage} span="full"
        actions={<span className="ux-form-row" data-tight>
          <button type="button" className="ux-btn" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</button>
          <button type="button" className="ux-btn" data-variant="primary" disabled={step === cats.length - 1} onClick={() => setStep(step + 1)}>Next</button>
        </span>}>
        <div className="ux-wiz-grid">{items.map((c) => <ConnectorCard key={c.id} c={c} reload={load} />)}</div>
      </Card>
    </>
  );
}

function ConnectorCard({ c, reload }: { c: Conn; reload: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [replacing, setReplacing] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "bad" | "warn"; text: string } | null>(null);
  const L = LIGHT[c.light];
  const set = (k: string, v: string) => setVals((p) => ({ ...p, [k]: v }));
  const run = async (what: string, path: string, body: unknown, okText: string) => {
    setBusy(what); setMsg(null);
    const r = await api<{ state?: { status?: string; last_test_detail?: string | null; light?: string } }>(path, body);
    setBusy("");
    if (r.ok) {
      const st = r.data.state;
      setMsg(what === "test" ? { tone: st?.status === "ok" ? (st.light === "amber" ? "warn" : "good") : "bad", text: st?.last_test_detail || okText } : { tone: "good", text: okText });
      if (what !== "test") { setVals({}); setReplacing({}); }
      await reload();
    } else setMsg({ tone: "bad", text: why(r) });
  };
  const save = (e: FormEvent) => {
    e.preventDefault();
    const send: Record<string, string> = {};
    for (const f of c.fields) { const v = vals[f.name]; if (v !== undefined && v !== "") send[f.name] = v; }
    void run("save", `/api/account/connectors/${c.id}/save`, { values: send }, "Saved. Secret values are encrypted and will not be shown again.");
  };
  return (
    <article className="ux-wiz-card" data-light={c.light} aria-label={c.name}>
      <header className="ux-wiz-card__head">
        <h3 className="ux-h3">{c.name}</h3>
        <span className="ux-light" data-light={c.light} role="status" aria-label={`${c.name}: ${L.text}`}><span aria-hidden>{SHAPE[c.light]}</span> {L.text}</span>
      </header>
      <p className="ux-small">{c.loop_use}</p>
      <p className="ux-small"><strong>Free tier:</strong> {c.free_tier}</p>
      {c.safety_note ? <p className="ux-small ux-wiz-safe">{c.safety_note}</p> : null}
      <p className="ux-small">
        <a className="ux-link" href={c.signup_url} target="_blank" rel="noopener noreferrer">Get a key ↗</a>{" · "}
        <a className="ux-link" href={c.docs_url} target="_blank" rel="noopener noreferrer">Docs ↗</a>
      </p>
      {!c.state ? <p className="ux-small">No key entered yet. Get a free key, paste it under Set up, Save, then press Verify.</p> : c.light === "amber" ? <p className="ux-small">Saved but not verified yet. Press Verify.</p> : null}
      {c.state?.last_test_detail ? <p className="ux-small">Last check: {c.state.last_test_detail}</p> : null}
      <div className="ux-form-row" data-tight>
        <button type="button" className="ux-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{c.state ? "Edit" : "Set up"}</button>
        <button type="button" className="ux-btn" disabled={!c.state || busy !== ""} onClick={() => void run("test", `/api/account/connectors/${c.id}/test`, {}, "Verification finished.")}>{busy === "test" ? "Verifying…" : "Verify"}</button>
      </div>
      {open ? (
        <form onSubmit={save} className="ux-wiz-form" aria-label={`${c.name} settings`}>
          {c.fields.map((f) => {
            const s = c.state?.secrets[f.name];
            const cur = c.state?.config[f.name];
            if (f.secret && s?.set && !replacing[f.name]) {
              return (
                <div className="ux-field" key={f.name}>{f.label}
                  <span className="ux-form-row" data-tight>
                    <code>•••• {s.last4}</code><span className="ux-small">version {s.version}</span>
                    <button type="button" className="ux-btn" onClick={() => setReplacing((p) => ({ ...p, [f.name]: true }))}>Replace</button>
                  </span>
                </div>
              );
            }
            return (
              <label className="ux-field" key={f.name}>{f.label}{f.required ? "" : " (optional)"}
                <input type={f.secret ? "password" : "text"} value={vals[f.name] ?? ""} placeholder={f.secret ? f.placeholder || "paste the key" : cur ?? (f.default || f.placeholder)}
                  onChange={(e) => set(f.name, e.target.value)} autoComplete="off" spellCheck={false} maxLength={600}
                  {...(f.choices.length ? { list: `${c.id}-${f.name}` } : {})} />
                {f.choices.length ? <datalist id={`${c.id}-${f.name}`}>{f.choices.map((o) => <option key={o} value={o} />)}</datalist> : null}
                {f.help ? <span className="ux-small">{f.help}</span> : null}
              </label>
            );
          })}
          <div className="ux-form-row" data-tight>
            <button type="submit" className="ux-btn" data-variant="primary" disabled={busy !== ""}>{busy === "save" ? "Saving…" : "Save"}</button>
            {Object.entries(replacing).some(([, v]) => v) ? (
              <button type="button" className="ux-btn" disabled={busy !== ""} onClick={() => {
                const f = Object.keys(replacing).find((k) => replacing[k]);
                if (f && vals[f]) void run("rotate", `/api/account/connectors/${c.id}/rotate`, { field: f, value: vals[f] }, "Replaced. The old value was destroyed.");
              }}>Replace secret now</button>
            ) : null}
            {c.state ? <button type="button" className="ux-btn" data-variant="danger" disabled={busy !== ""} onClick={() => { if (window.confirm(`Delete ${c.name} and its saved secrets?`)) void run("delete", `/api/account/connectors/${c.id}/delete`, {}, "Deleted."); }}>Delete</button> : null}
          </div>
        </form>
      ) : null}
      {msg ? <p className="ux-action-msg" data-tone={msg.tone} role="status">{msg.text}</p> : null}
    </article>
  );
}

/* ------------------------------------------------------------- profile */
type Sess = { id: string; created_at: number; last_seen_at: number; user_agent: string; current: boolean };
type Ev = { seq: number; ts: number; action: string; target_id: string; outcome: string };
const when = (t: number | null | undefined) => (t ? new Date(t * 1000).toLocaleString("en-CA") : "never");

export function ProfilePanel() {
  return <AccountGate>{({ user, reload, signOut }) => <ProfileInner user={user} reload={reload} signOut={signOut} />}</AccountGate>;
}

function ProfileInner({ user, reload, signOut }: { user: User; reload: () => void; signOut: () => void }) {
  const [name, setName] = useState(user.display_name); const [tz, setTz] = useState(user.timezone);
  const [cur, setCur] = useState(""); const [next, setNext] = useState(""); const [delpw, setDelpw] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [sessions, setSessions] = useState<Sess[]>([]); const [events, setEvents] = useState<Ev[]>([]);
  const [refs, setRefs] = useState<{ code: string | null; counts: Record<string, number>; note: string } | null>(null);
  const refresh = useCallback(async () => {
    const [s, a, rf] = await Promise.all([api<{ sessions: Sess[] }>("/api/account/sessions"), api<{ events: Ev[] }>("/api/account/audit"), api<{ code: string | null; counts: Record<string, number>; note: string }>("/api/account/referrals")]);
    if (s.ok) setSessions(s.data.sessions); if (a.ok) setEvents(a.data.events); if (rf.ok) setRefs(rf.data);
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const done = async (p: Promise<{ ok: boolean; error: string; message: string; status: number }>, ok: string) => {
    const r = await p; setMsg(r.ok ? { tone: "good", text: ok } : { tone: "bad", text: why(r) }); if (r.ok) { void refresh(); reload(); } return r.ok;
  };
  return (
    <>
      <Card title="Your profile" span="full" subtitle={`${user.email} · role: ${user.role} · member since ${when(user.created_at)}`}
        actions={<button type="button" className="ux-btn" onClick={signOut}>Sign out</button>}>
        <form className="ux-form-row" onSubmit={(e) => { e.preventDefault(); void done(api("/api/account/profile", { display_name: name, timezone: tz }), "Profile saved."); }}>
          <label className="ux-field">Display name<input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></label>
          <label className="ux-field">Time zone<input value={tz} maxLength={64} onChange={(e) => setTz(e.target.value)} /></label>
          <button type="submit" className="ux-btn" data-variant="primary">Save profile</button>
        </form>
        {msg ? <p className="ux-action-msg" data-tone={msg.tone} role="status">{msg.text}</p> : null}
      </Card>
      <Card title="Password" subtitle="Changing it signs out every other device." span="full">
        <form className="ux-form-row" onSubmit={async (e) => { e.preventDefault(); if (await done(api("/api/account/password", { current: cur, new: next }), "Password changed. Other devices were signed out.")) { setCur(""); setNext(""); } }}>
          <label className="ux-field">Current password<input type="password" required value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></label>
          <label className="ux-field">New password (12+ characters)<input type="password" required minLength={12} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></label>
          <button type="submit" className="ux-btn">Change password</button>
        </form>
      </Card>
      <Card title="Signed-in devices" span="full" actions={<button type="button" className="ux-btn" onClick={() => void done(api("/api/account/sessions/revoke", { all_others: true }), "Other devices signed out.")}>Sign out all others</button>}>
        <DataTable rows={sessions as unknown as R[]} columns={[
          { key: "created_at", label: "Signed in", render: (r) => when(r.created_at as number) },
          { key: "last_seen_at", label: "Last seen", render: (r) => when(r.last_seen_at as number) },
          { key: "user_agent", label: "Browser", render: (r) => String(r.user_agent ?? "").slice(0, 60) || "unknown" },
          { key: "current", label: "", render: (r) => (r.current ? <Badge tone="good">this device</Badge> : <button type="button" className="ux-btn" onClick={() => void done(api("/api/account/sessions/revoke", { id: r.id }), "Device signed out.")}>Sign out</button>) },
        ]} />
      </Card>
      <Card title="Referral link" span="full" subtitle="Share this code. ATLAS only counts sign-ups; no payout is set up.">
        {refs?.code ? <p><code>?ref={refs.code}</code> · {Object.entries(refs.counts).map(([k, v]) => `${v} ${k}`).join(", ") || "no referrals yet"}</p> : <p>No code yet.</p>}
      </Card>
      <Card title="Recent account activity" span="full" subtitle="Every change to your connectors and account is logged. The log never contains secret values.">
        <DataTable rows={events as unknown as R[]} columns={[
          { key: "ts", label: "When", render: (r) => when(r.ts as number) },
          { key: "action", label: "Action" }, { key: "target_id", label: "Target" }, { key: "outcome", label: "Result" },
        ]} empty="No activity yet" />
      </Card>
      <TeamCard reload={reload} />
      {user.role !== "user" ? <><InvitesCard /><AdminCard /></> : null}
      <Card title="Delete account" subtitle="Removes your profile, sessions and every saved connector secret. This cannot be undone." span="full">
        <form className="ux-form-row" onSubmit={(e) => { e.preventDefault(); if (window.confirm("Delete your account and all saved secrets?")) void done(api("/api/account/delete", { password: delpw }), "Account deleted.").then(() => reload()); }}>
          <label className="ux-field">Confirm with your password<input type="password" required value={delpw} onChange={(e) => setDelpw(e.target.value)} autoComplete="current-password" /></label>
          <button type="submit" className="ux-btn" data-variant="danger">Delete my account</button>
        </form>
      </Card>
    </>
  );
}

function AdminCard() {
  const [users, setUsers] = useState<R[]>([]); const [chain, setChain] = useState<string>("");
  useEffect(() => { void (async () => {
    const u = await api<{ users: R[] }>("/api/admin/users"); if (u.ok) setUsers(u.data.users);
    const a = await api<{ chain: { ok: boolean; rows?: number } }>("/api/admin/audit"); if (a.ok) setChain(a.data.chain.ok ? `intact (${a.data.chain.rows ?? "?"} entries)` : "BROKEN: investigate");
  })(); }, []);
  return (
    <Card title="Users (admin)" span="full" subtitle={`Audit chain: ${chain || "checking"}`}>
      <DataTable rows={users} columns={[{ key: "email", label: "Email" }, { key: "role", label: "Role" }, { key: "status", label: "Status" },
        { key: "created_at", label: "Joined", render: (r) => when(r.created_at as number) }, { key: "last_login_at", label: "Last sign-in", render: (r) => when(r.last_login_at as number) }]} />
    </Card>
  );
}

/* ------------------------------------------------------------- billing */
type Plan = { code: string; tier: string; name: string; description: string; price_cents: number; currency: string; interval: string; seats_included: number; extra_seat_cents: number; is_placeholder: boolean; entitlements?: R };
type Ent = { kind: string; limit?: number | null; used?: number; allowed?: boolean; unlimited?: boolean; period?: string };
type Addon = { code: string; name: string; usd: number; cad: number };

export function BillingPanel() {
  return <AccountGate>{() => <BillingInner />}</AccountGate>;
}

const money = (cents: number, cur: string) => `${cur.toUpperCase() === "CAD" ? "CA$" : "US$"}${(cents / 100).toFixed(cents % 100 ? 2 : 0)}`;

function BillingInner() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [addons, setAddons] = useState<Addon[]>([]);
  const [interval, setInterval_] = useState<"month" | "year">("month");
  const [currency, setCurrency] = useState<"usd" | "cad">("usd");
  const [seats, setSeats] = useState(5);
  const [sub, setSub] = useState<{ plan: string; tier?: string; plan_name: string; status?: string; seats?: number; entitlements: { entitlements: Record<string, Ent> }; stripe_test_mode: { secret_key: boolean; webhook_secret: boolean } } | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { void (async () => {
    const p = await api<{ plans: Plan[]; addons?: Addon[] }>("/api/billing/plans"); if (p.ok) { setPlans(p.data.plans); setAddons(p.data.addons ?? []); }
    const s = await api<NonNullable<typeof sub>>("/api/billing/subscription"); if (s.ok) setSub(s.data);
  })(); }, []);
  const checkout = async (p: Plan) => {
    setMsg("");
    const body: R = { plan: p.tier, interval, currency };
    if (p.tier === "team") body.seats = seats;
    const r = await api<{ url?: string }>("/api/billing/checkout", body);
    if (r.ok && r.data.url && r.data.url.startsWith("https://checkout.stripe.com/")) window.location.assign(r.data.url); else setMsg(why(r));
  };
  const shown = plans.filter((p) => p.tier === "free" || (p.interval === interval && p.currency === currency));
  const ents = sub?.entitlements?.entitlements ?? {};
  return (
    <>
      <Card title="Plan and billing" span="full" subtitle="Test mode only. Prices below are placeholders, not an offer.">
        <p className="ux-action-msg" data-tone="good" role="note"><strong>$0 per-trade fees. No performance fee.</strong> ATLAS earns only from the subscription you choose below. Your broker sets your trading costs.</p>
        <p className="ux-action-msg" data-tone="warn" role="note">Placeholder plans: names, prices and limits are not final, and a legal review is required before real billing is switched on. Prices exclude tax; tax is added at checkout.</p>
        <p>Current plan: <strong>{sub?.plan_name ?? "…"}</strong>{sub?.status && sub.status !== "free" ? ` (${sub.status})` : ""}{sub?.tier === "team" && sub.seats ? `, ${sub.seats} seats` : ""}</p>
        {sub && !sub.stripe_test_mode.secret_key ? <p className="ux-small">Stripe test keys are not set on this server, so checkout is unavailable.</p> : null}
        <div className="atlas-chart-seg" role="group" aria-label="Billing options">
          <button type="button" aria-pressed={interval === "month"} onClick={() => setInterval_("month")}>Monthly</button>
          <button type="button" aria-pressed={interval === "year"} onClick={() => setInterval_("year")}>Yearly (about 2 months free)</button>
          <button type="button" aria-pressed={currency === "usd"} onClick={() => setCurrency("usd")}>USD</button>
          <button type="button" aria-pressed={currency === "cad"} onClick={() => setCurrency("cad")}>CAD</button>
        </div>
        {msg ? <p className="ux-action-msg" data-tone="bad" role="alert">{msg}</p> : null}
        <div className="ux-wiz-grid">
          {shown.map((p) => (
            <article className="ux-wiz-card" key={p.code} data-light={sub?.plan === p.code ? "green" : "gray"} aria-label={`${p.name} plan`}>
              <header className="ux-wiz-card__head"><h3 className="ux-h3">{p.name}</h3>{p.is_placeholder ? <Badge tone="warn">placeholder</Badge> : null}</header>
              <p><strong>{p.price_cents ? `${money(p.price_cents, p.currency)} / ${p.interval}` : "$0"}</strong> <span className="ux-small">(example price, excl. tax)</span></p>
              {p.tier === "team" ? <p className="ux-small">{p.seats_included} seats included, extra seats {money(p.extra_seat_cents, p.currency)} each per {p.interval}.</p> : null}
              <p className="ux-small">{p.description}</p>
              {p.tier === "team" ? <label className="ux-small">Seats <input type="number" min={p.seats_included} max={100} value={seats} onChange={(e) => setSeats(Math.max(p.seats_included, Math.min(100, Number(e.target.value) || p.seats_included)))} aria-label="Number of seats" /></label> : null}
              {sub?.plan === p.code ? <Badge tone="good">your plan</Badge> : p.price_cents > 0 ? <button type="button" className="ux-btn" disabled={!sub?.stripe_test_mode.secret_key} onClick={() => void checkout(p)}>Try in test mode</button> : null}
            </article>
          ))}
        </div>
      </Card>
      {addons.length ? (
        <Card title="Add-ons (planned)" span="full" subtitle="Not purchasable yet. Listed so you can see what may come.">
          <ul className="ux-small">{addons.map((a) => <li key={a.code}><strong>{a.name}</strong>{`: ${money(a[currency], currency)}`}</li>)}</ul>
        </Card>
      ) : null}
      <Card title="What your plan includes" span="full">
        <DataTable rows={Object.entries(ents).map(([k, v]) => ({ key: k, ...v })) as unknown as R[]} columns={[
          { key: "key", label: "Feature" },
          { key: "kind", label: "Limit", render: (r) => (r.kind === "flag" ? (r.allowed ? "included" : "not in plan") : r.unlimited ? "unlimited" : `${r.used ?? 0} of ${r.limit}${r.period && r.period !== "none" ? ` per ${r.period}` : ""}`) },
        ]} />
      </Card>
    </>
  );
}
